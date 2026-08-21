# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Repository pour les groupes de contacts (table ``contact_groups``).

Source de vérité unique post-migration du store JSON (chantier « web tier
stateless »). Toutes les lectures métier sont scopées par ``account_id`` —
le seul accès non scopé est ``get`` (lookup par PK), dont les appelants
DOIVENT re-vérifier l'appartenance au compte (contrat hérité de
``_get_group_by_id`` + quicksteps forward).
"""

from datetime import datetime
from typing import List, Optional

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.contact_group import ContactGroupRow

logger = logging.getLogger(__name__)


class ContactGroupRepository:
    """CRUD scopé compte pour ``contact_groups``."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, group_id: str) -> Optional[ContactGroupRow]:
        """Lookup par PK — l'appelant doit vérifier ``account_id``."""
        if not group_id:
            return None
        return self.session.get(ContactGroupRow, group_id)

    def get_for_account(self, group_id: str, account_id: int) -> Optional[ContactGroupRow]:
        row = self.get(group_id)
        if row is None or row.account_id != account_id:
            return None
        return row

    def list_for_account(self, account_id: int) -> List[ContactGroupRow]:
        """Groupes du compte, triés use_count desc puis nom asc (contrat API)."""
        stmt = (
            select(ContactGroupRow)
            .where(ContactGroupRow.account_id == account_id)
            .order_by(ContactGroupRow.use_count.desc(), ContactGroupRow.name.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def name_exists(
        self, account_id: int, name: str, exclude_id: Optional[str] = None
    ) -> bool:
        """Unicité du nom par compte, insensible à la casse (contrat legacy).

        Appliquée en code et non en contrainte DB : un index unique
        fonctionnel lower(name) n'est pas portable SQLite/Postgres, et les
        orphelins legacy ``account_id=-1`` issus de tenants différents
        peuvent légitimement porter le même nom.
        """
        stmt = select(ContactGroupRow.id).where(
            ContactGroupRow.account_id == account_id,
            func.lower(ContactGroupRow.name) == (name or "").lower(),
        )
        if exclude_id:
            stmt = stmt.where(ContactGroupRow.id != exclude_id)
        return self.session.execute(stmt.limit(1)).first() is not None

    def add(self, row: ContactGroupRow) -> ContactGroupRow:
        self.session.add(row)
        return row

    def delete(self, row: ContactGroupRow) -> None:
        self.session.delete(row)

    def delete_all_for_account(self, account_id: int) -> int:
        """Purge RGPD / suppression de compte. Retourne le nombre supprimé."""
        rows = self.list_for_account(account_id)
        for row in rows:
            self.session.delete(row)
        return len(rows)

    @staticmethod
    def row_from_legacy_dict(grp: dict, group_id: str) -> ContactGroupRow:
        """Construit une row depuis un enregistrement du JSON legacy.

        Tolérant aux champs manquants (mêmes défauts que ``_load_groups`` :
        ``account_id`` absent → -1, ``virtual_meeting`` absent → False) et
        aux timestamps illisibles (→ now, plutôt que de perdre le groupe).
        """
        def _parse_dt(value) -> datetime:
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    pass
            return datetime.now()

        members = grp.get("members")
        if not isinstance(members, list):
            members = []
        return ContactGroupRow(
            id=group_id,
            account_id=int(grp.get("account_id", -1) or -1),
            name=str(grp.get("name") or "")[:512] or "(sans nom)",
            emoji=grp.get("emoji") or None,
            description=grp.get("description") or None,
            label_name=grp.get("label_name") or None,
            members_json=json.dumps(members, ensure_ascii=False),
            virtual_meeting=bool(grp.get("virtual_meeting", False)),
            use_count=int(grp.get("use_count", 0) or 0),
            created_at=_parse_dt(grp.get("created_at")),
            updated_at=_parse_dt(grp.get("updated_at")),
        )
