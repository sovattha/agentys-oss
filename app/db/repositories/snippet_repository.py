# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Repository pour les snippets et leurs partages.

Source de vérité unique post-migration 040. Le périmètre d'accès est celui
du contrat historique : un snippet appartient à ``owner_email`` ; un
``owner_email`` NULL (legacy) appartient à tout le monde ; les partages
donnent un accès lecture/duplication par email cible.
"""

from typing import List, Optional, Tuple

import json
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.snippet import SnippetRow, SnippetShareRow

logger = logging.getLogger(__name__)


def _norm_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


class SnippetRepository:
    """CRUD snippets + partages, aux règles d'accès du contrat historique."""

    def __init__(self, session: Session):
        self.session = session

    # ── Snippets ──────────────────────────────────────────────────────────

    def get(self, snippet_id: str) -> Optional[SnippetRow]:
        if not snippet_id:
            return None
        return self.session.get(SnippetRow, snippet_id)

    def is_owner(self, row: SnippetRow, email: str) -> bool:
        """Sémantique historique : legacy sans owner = possédé par tous."""
        return row.owner_email is None or _norm_email(row.owner_email) == _norm_email(email)

    def list_visible(
        self, email: str, account_id: Optional[int] = None
    ) -> List[SnippetRow]:
        """Snippets propres + legacy, filtrés par compte, triés use_count desc puis nom.

        ``account_id`` None = pas de filtre (compat legacy / mode local) ;
        un snippet à ``account_id`` NULL est visible dans tous les comptes.
        """
        stmt = select(SnippetRow).where(
            or_(
                SnippetRow.owner_email.is_(None),
                SnippetRow.owner_email == _norm_email(email),
            )
        )
        if account_id is not None:
            stmt = stmt.where(
                or_(
                    SnippetRow.account_id.is_(None),
                    SnippetRow.account_id == account_id,
                )
            )
        stmt = stmt.order_by(SnippetRow.use_count.desc(), SnippetRow.name.asc())
        return list(self.session.execute(stmt).scalars())

    def name_exists_for_owner(
        self, email: str, name: str, exclude_id: Optional[str] = None
    ) -> bool:
        """Unicité du nom dans le périmètre du propriétaire (case-insensitive).

        Le périmètre inclut les snippets legacy sans owner — comme le check
        historique ``_is_owner(s, email)`` qui les considérait possédés.
        """
        stmt = select(SnippetRow.id).where(
            func.lower(SnippetRow.name) == (name or "").lower(),
            or_(
                SnippetRow.owner_email.is_(None),
                SnippetRow.owner_email == _norm_email(email),
            ),
        )
        if exclude_id:
            stmt = stmt.where(SnippetRow.id != exclude_id)
        return self.session.execute(stmt.limit(1)).first() is not None

    def add(self, row: SnippetRow) -> SnippetRow:
        self.session.add(row)
        return row

    def delete(self, row: SnippetRow) -> None:
        self.session.delete(row)

    # ── Shares ────────────────────────────────────────────────────────────

    def get_share(self, snippet_id: str, target_email: str) -> Optional[SnippetShareRow]:
        stmt = select(SnippetShareRow).where(
            SnippetShareRow.snippet_id == snippet_id,
            SnippetShareRow.shared_with == _norm_email(target_email),
        )
        return self.session.execute(stmt.limit(1)).scalars().first()

    def list_shares_for_snippet(self, snippet_id: str) -> List[SnippetShareRow]:
        stmt = select(SnippetShareRow).where(SnippetShareRow.snippet_id == snippet_id)
        return list(self.session.execute(stmt).scalars())

    def list_shares_for_user(self, email: str) -> List[SnippetShareRow]:
        stmt = select(SnippetShareRow).where(
            SnippetShareRow.shared_with == _norm_email(email)
        )
        return list(self.session.execute(stmt).scalars())

    def add_share(self, row: SnippetShareRow) -> SnippetShareRow:
        self.session.add(row)
        return row

    def delete_share(self, row: SnippetShareRow) -> None:
        self.session.delete(row)

    def delete_shares_for_snippet(self, snippet_id: str) -> int:
        """Cascade historique de delete_snippet."""
        rows = self.list_shares_for_snippet(snippet_id)
        for row in rows:
            self.session.delete(row)
        return len(rows)

    # ── Purge compte (RGPD / suppression de compte) ───────────────────────

    def purge_for_account(
        self, db_account_id: int, owner_email: str, owner_has_no_more_accounts: bool
    ) -> Tuple[int, int]:
        """Purge à la sémantique historique de ``_purge_snippets_for_account``.

        - Dernier compte du propriétaire supprimé → TOUS ses snippets partent
          (les legacy sans owner restent).
        - Sinon → seulement ceux explicitement tagués ``account_id``.
        Cascade les shares des snippets supprimés. Retourne (snippets, shares).
        """
        if owner_has_no_more_accounts:
            stmt = select(SnippetRow).where(
                SnippetRow.owner_email == _norm_email(owner_email)
            )
        else:
            stmt = select(SnippetRow).where(SnippetRow.account_id == db_account_id)
        doomed = list(self.session.execute(stmt).scalars())
        shares_removed = 0
        for row in doomed:
            shares_removed += self.delete_shares_for_snippet(row.id)
            self.session.delete(row)
        return len(doomed), shares_removed

    # ── Import legacy ─────────────────────────────────────────────────────

    @staticmethod
    def snippet_from_legacy_dict(s: dict, snippet_id: str) -> SnippetRow:
        """Row depuis un enregistrement de ``snippets.json`` (tolérant)."""
        def _enc(value) -> Optional[str]:
            return None if value is None else json.dumps(value, ensure_ascii=False)

        owner = s.get("owner_email")
        account_id = s.get("account_id")
        try:
            account_id = int(account_id) if account_id is not None else None
        except (TypeError, ValueError):
            account_id = None
        return SnippetRow(
            id=snippet_id,
            owner_email=_norm_email(owner) if owner else None,
            account_id=account_id,
            name=str(s.get("name") or "")[:512] or "(sans nom)",
            content=str(s.get("content") or ""),
            subject=s.get("subject") or None,
            to_json=_enc(s.get("to")),
            cc_json=_enc(s.get("cc")),
            bcc_json=_enc(s.get("bcc")),
            category=s.get("category") or None,
            is_private=bool(s.get("is_private", True)),
            use_count=int(s.get("use_count", 0) or 0),
            created_at=str(s.get("created_at") or ""),
            updated_at=str(s.get("updated_at") or ""),
        )

    @staticmethod
    def share_from_legacy_dict(sh: dict, share_id: str) -> SnippetShareRow:
        """Row depuis un enregistrement de ``snippet_shares.json``."""
        return SnippetShareRow(
            id=share_id,
            snippet_id=str(sh.get("snippet_id") or ""),
            shared_by=_norm_email(sh.get("shared_by")),
            shared_with=_norm_email(sh.get("shared_with")),
            shared_at=str(sh.get("shared_at") or ""),
        )
