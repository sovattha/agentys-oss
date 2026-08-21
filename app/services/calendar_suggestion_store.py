# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Store DB des suggestions d'engagement IA — remplace le dict de calendar.py.

Même contrat-records et même robustesse d'import que ``followup_store``
(migration 041) : quarantaine ``.corrupt-<ts>`` d'un JSON illisible, parking
``.imported`` après import réussi, idempotence par PK.
"""

from typing import Dict, List, Optional, Tuple

import json
import logging
import os
import threading
import time

from sqlalchemy import select

from app.db.models.calendar_suggestion import CalendarSuggestionRow

logger = logging.getLogger(__name__)

_DATA_DIR = os.environ.get("AGENTYS_DATA_DIR", "").strip() or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
)
SUGGESTIONS_FILE = os.path.join(_DATA_DIR, "calendar_suggestions.json")

_legacy_import_done = False
_legacy_import_lock = threading.Lock()


def ensure_legacy_import() -> None:
    """Import one-shot de ``calendar_suggestions.json`` (objet {id: record})."""
    global _legacy_import_done
    if _legacy_import_done:
        return
    with _legacy_import_lock:
        if _legacy_import_done:
            return
        if not os.path.exists(SUGGESTIONS_FILE):
            _legacy_import_done = True
            return
        try:
            with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("calendar_suggestions.json root must be a JSON object")
        except Exception as e:
            logger.error("suggestions: JSON legacy illisible (%s) — quarantaine", e)
            try:
                quarantine = f"{SUGGESTIONS_FILE}.corrupt-{int(time.time())}"
                os.replace(SUGGESTIONS_FILE, quarantine)
                logger.warning("Corrupt calendar_suggestions.json moved to %s", quarantine)
            except Exception as rename_exc:  # noqa: BLE001
                logger.warning(
                    "Could not quarantine corrupt calendar_suggestions.json: %s",
                    rename_exc,
                )
            _legacy_import_done = True
            return

        imported = 0
        try:
            from app.db.database import get_db_session
            with get_db_session() as session:
                for sid, record in data.items():
                    if not isinstance(record, dict):
                        continue
                    sid = str(sid)
                    if session.get(CalendarSuggestionRow, sid) is not None:
                        continue
                    row = CalendarSuggestionRow(id=sid)
                    row.apply_record(record)
                    session.add(row)
                    imported += 1
                session.commit()
        except Exception as e:
            logger.error("suggestions: import legacy échoué: %s", e)
            return

        try:
            os.replace(SUGGESTIONS_FILE, SUGGESTIONS_FILE + ".imported")
        except OSError as e:
            logger.warning("suggestions: impossible de parquer le JSON importé: %s", e)
        _legacy_import_done = True
        if imported:
            logger.info("suggestions: %d suggestions legacy importées", imported)


def get_record(suggestion_id: str) -> Optional[Dict]:
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = session.get(CalendarSuggestionRow, suggestion_id) if suggestion_id else None
        return row.to_record() if row else None


def save_record(suggestion_id: str, record: Dict) -> None:
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        row = session.get(CalendarSuggestionRow, suggestion_id)
        if row is None:
            row = CalendarSuggestionRow(id=suggestion_id)
            session.add(row)
        row.apply_record(record)
        session.commit()


def all_records() -> List[Tuple[str, Dict]]:
    """[(id, record)] tous comptes — list_suggestions valide l'ownership
    suggestion par suggestion (comportement historique)."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = session.execute(select(CalendarSuggestionRow)).scalars()
        return [(row.id, row.to_record()) for row in rows]


def delete_all_for_account(account_id: str) -> int:
    """Purge RGPD / suppression de compte (trou comblé par la migration 042 —
    rien ne purgeait les suggestions d'un compte supprimé avant)."""
    ensure_legacy_import()
    from app.db.database import get_db_session
    with get_db_session() as session:
        rows = list(session.execute(
            select(CalendarSuggestionRow).where(
                CalendarSuggestionRow.account_id == account_id
            )
        ).scalars())
        for row in rows:
            session.delete(row)
        if rows:
            session.commit()
        return len(rows)
