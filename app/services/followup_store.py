# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Store DB des follow-ups — remplace le dict mémoire de calendar.py.

API en RECORDS (dicts au format JSON historique) pour que les routes de
``calendar.py`` gardent leur logique inchangée : un record est ce qui était
stocké sous ``_followups[fid]`` ; les routes composent ``{"id": fid, **rec}``.

L'import legacy reprend les DEUX comportements de robustesse du module
historique : quarantaine ``.corrupt-<ts>`` d'un JSON illisible (audit
2026-05-11 P1 — un fichier corrompu ne doit pas spammer les boots), et
parking ``.imported`` après import réussi (pattern migrations 039/040).
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import json
import logging
import os
import threading
import time

from sqlalchemy import select

from app.db.models.followup import FollowupRow

logger = logging.getLogger(__name__)

# Même résolution que le module calendar historique (volume Railway).
_DATA_DIR = os.environ.get("AGENTYS_DATA_DIR", "").strip() or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
)
FOLLOWUPS_FILE = os.path.join(_DATA_DIR, "followups.json")

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def ensure_legacy_import() -> None:
    """Import one-shot de ``followups.json`` (objet {id: record}) vers la DB.

    Idempotent par PK, thread-safe. JSON corrompu → quarantaine
    ``.corrupt-<ts>`` (comportement historique conservé). DB indisponible →
    retry au prochain accès (fichier intact).
    """
    global _legacy_import_done
    if _legacy_import_done:
        return
    with _legacy_import_lock:
        if _legacy_import_done:
            return
        if not os.path.exists(FOLLOWUPS_FILE):
            _legacy_import_done = True
            return
        try:
            with open(FOLLOWUPS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("followups.json root must be a JSON object")
        except Exception as e:
            logger.error(
                "followups: JSON legacy illisible (%s) — quarantaine", e
            )
            try:
                quarantine = f"{FOLLOWUPS_FILE}.corrupt-{int(time.time())}"
                os.replace(FOLLOWUPS_FILE, quarantine)
                logger.warning("Corrupt followups.json moved to %s", quarantine)
            except Exception as rename_exc:  # noqa: BLE001
                logger.warning(
                    "Could not quarantine corrupt followups.json: %s", rename_exc
                )
            _legacy_import_done = True
            return

        imported = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                for fid, record in data.items():
                    if not isinstance(record, dict):
                        continue
                    fid = str(fid)
                    if session.get(FollowupRow, fid) is not None:
                        continue
                    row = FollowupRow(id=fid)
                    row.apply_record(record)
                    session.add(row)
                    imported += 1
                session.commit()
        except Exception as e:
            logger.error("followups: import legacy échoué: %s", e)
            return

        try:
            os.replace(FOLLOWUPS_FILE, FOLLOWUPS_FILE + ".imported")
        except OSError as e:
            logger.warning("followups: impossible de parquer le JSON importé: %s", e)
        _legacy_import_done = True
        if imported:
            logger.info("followups: %d follow-ups legacy importés", imported)


def get_record(followup_id: str) -> Optional[Dict]:
    """Record d'un follow-up, ou None."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = session.get(FollowupRow, followup_id) if followup_id else None
        return row.to_record() if row else None


def save_record(followup_id: str, record: Dict) -> None:
    """Upsert d'un record (création ou read-modify-write des routes)."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = session.get(FollowupRow, followup_id)
        if row is None:
            row = FollowupRow(id=followup_id)
            session.add(row)
        row.apply_record(record)
        session.commit()


def delete_record(followup_id: str) -> bool:
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = session.get(FollowupRow, followup_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def records_for_account(account_id: str) -> List[Tuple[str, Dict]]:
    """[(id, record)] du compte (string OAuth hash)."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = session.execute(
            select(FollowupRow).where(FollowupRow.account_id == account_id)
        ).scalars()
        return [(row.id, row.to_record()) for row in rows]


def all_records() -> List[Tuple[str, Dict]]:
    """[(id, record)] tous comptes — pour la branche « pas de compte actif »
    de list_followups qui valide l'ownership followup par followup."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = session.execute(select(FollowupRow)).scalars()
        return [(row.id, row.to_record()) for row in rows]


def delete_all_for_account(account_id: str) -> int:
    """Purge RGPD / suppression de compte. Retourne le nombre supprimé."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = list(session.execute(
            select(FollowupRow).where(FollowupRow.account_id == account_id)
        ).scalars())
        for row in rows:
            session.delete(row)
        if rows:
            session.commit()
        return len(rows)


def wake_snoozed(now: Optional[datetime] = None) -> int:
    """Réactive les follow-ups snoozés dont la date est dépassée.

    Même tolérance que l'historique : un ``snoozed_until`` illisible est
    laissé tel quel (pas de crash, pas de réveil).
    """
    ensure_legacy_import()
    now = now or datetime.now(timezone.utc)
    woken = 0
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = session.execute(
            select(FollowupRow).where(FollowupRow.status == "snoozed")
        ).scalars()
        for row in rows:
            snoozed_until_str = row.snoozed_until or ""
            if not snoozed_until_str:
                continue
            try:
                snoozed_until = datetime.fromisoformat(
                    snoozed_until_str.replace("Z", "+00:00")
                )
                if snoozed_until.tzinfo is None:
                    snoozed_until = snoozed_until.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if snoozed_until <= now:
                row.status = "pending"
                row.snoozed_until = None
                woken += 1
        if woken:
            session.commit()
    return woken
