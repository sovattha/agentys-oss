# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests d'isolation multi-compte pour draft_history.

Bug 2026-04-14 : GET /api/drafts retournait les brouillons de TOUS les
comptes confondus car l'adapter n'avait pas de filtre account_id.

Ces tests vérifient que :
  1. Un draft inséré avec account_id=A n'est PAS visible via
     get_all_for_account(B), get_by_id_for_account(draft_id, B), etc.
  2. L'adapter refuse d'insérer un DraftRecord sans account_id (ValueError).
  3. Les méthodes unscoped (get_all, get_by_id) lèvent RuntimeError en prod.
  4. Les rows legacy sans account_id (NULL) sont quarantinés (jamais retournés).
"""

from __future__ import annotations

import sqlite3

import pytest

from app.domain.entities.draft_history import DraftRecord
from app.infrastructure.adapters.sqlite_learning_store import SqliteDraftHistoryAdapter


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class _InMemoryDb:
    """Minimal Database-compatible wrapper for SqliteDraftHistoryAdapter."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE draft_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                email_id TEXT NOT NULL,
                email_sender TEXT,
                email_subject TEXT,
                email_body TEXT,
                draft_v1 TEXT,
                critique TEXT,
                draft_final TEXT,
                status TEXT,
                draft_id TEXT,
                tokens_used INTEGER DEFAULT 0,
                model TEXT,
                processing_time_ms INTEGER,
                priority_score INTEGER DEFAULT 50,
                category TEXT DEFAULT 'NORMAL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                feedback TEXT,
                feedback_score INTEGER
            );
            """
        )

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(query, params)

    def fetchone(self, query: str, params: tuple = ()):
        return self._conn.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple = ()):
        return self._conn.execute(query, params).fetchall()

    def commit(self) -> None:
        self._conn.commit()


@pytest.fixture
def adapter():
    return SqliteDraftHistoryAdapter(_InMemoryDb())


def _make_record(draft_id: str, account_id: int | None = 1) -> DraftRecord:
    # La colonne SQL `id` est AUTOINCREMENT, c'est `draft_id` (TEXT) qui
    # correspond à l'identifiant provider recherché par get_by_id_for_account.
    return DraftRecord(
        id=draft_id,
        timestamp="2026-04-15T10:00:00",
        email_id=f"email-{draft_id}",
        email_sender="sender@example.com",
        email_subject=f"sujet {draft_id}",
        email_preview=f"aperçu {draft_id}",
        draft_v1="v1",
        critique="critique",
        draft_final="final",
        status="V1",
        account_id=account_id,
        draft_id=draft_id,
    )


# --------------------------------------------------------------------------- #
# Test 1 — isolation par compte
# --------------------------------------------------------------------------- #


def test_get_all_for_account_filters_by_account(adapter):
    adapter.add(_make_record("d1", account_id=1))
    adapter.add(_make_record("d2", account_id=2))
    adapter.add(_make_record("d3", account_id=1))

    a1 = adapter.get_all_for_account(1)
    a2 = adapter.get_all_for_account(2)

    emails_a1 = {d.email_id for d in a1}
    emails_a2 = {d.email_id for d in a2}

    assert emails_a1 == {"email-d1", "email-d3"}
    assert emails_a2 == {"email-d2"}
    assert emails_a1.isdisjoint(emails_a2), "cross-account leak détecté"


def test_get_by_id_for_account_blocks_other_accounts(adapter):
    adapter.add(_make_record("shared-id", account_id=1))
    # ID différent pour compte 2
    adapter.add(_make_record("other-id", account_id=2))

    # Compte 1 peut lire son draft
    assert adapter.get_by_id_for_account("shared-id", 1) is not None
    # Compte 2 ne voit PAS le draft du compte 1
    assert adapter.get_by_id_for_account("shared-id", 2) is None


def test_add_metadata_only_drops_persisted_content(adapter, monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")

    adapter.add(_make_record("private", account_id=1))

    row = adapter.db.fetchone(
        """
        SELECT email_body, draft_v1, critique, draft_final
        FROM draft_history
        WHERE draft_id = ?
        """,
        ("private",),
    )
    assert tuple(row) == (None, None, None, None)

    loaded = adapter.get_by_id_for_account("private", 1)
    assert loaded is not None
    assert loaded.email_preview == ""
    assert loaded.draft_v1 == ""
    assert loaded.critique == ""
    assert loaded.draft_final == ""
    assert loaded.status == "V1"


def test_update_feedback_for_account_blocks_other_accounts(adapter):
    adapter.add(_make_record("d1", account_id=1))

    # Compte 2 ne peut pas modifier le feedback d'un draft du compte 1
    ok = adapter.update_feedback_for_account("d1", account_id=2, feedback="spam")
    assert ok is False

    # Compte 1 peut — et le feedback reste isolé
    ok = adapter.update_feedback_for_account("d1", account_id=1, feedback="good")
    assert ok is True

    # Vérification : le feedback existe bien (via email_id pour éviter ambiguïté)
    records = adapter.get_all_for_account(1)
    matching = [r for r in records if r.email_id == "email-d1"]
    assert len(matching) == 1 and matching[0].feedback == "good"


# --------------------------------------------------------------------------- #
# Test 2 — insertion sans account_id refusée
# --------------------------------------------------------------------------- #


def test_add_refuses_record_without_account_id(adapter):
    record = _make_record("d1", account_id=None)
    with pytest.raises(ValueError, match="account_id"):
        adapter.add(record)


def test_add_refuses_record_with_zero_account_id(adapter):
    record = _make_record("d1", account_id=0)
    with pytest.raises(ValueError, match="account_id"):
        adapter.add(record)


# --------------------------------------------------------------------------- #
# Test 3 — legacy rows (account_id NULL) jamais retournés
# --------------------------------------------------------------------------- #


def test_legacy_rows_with_null_account_id_are_quarantined(adapter):
    # Simule un row legacy pré-migration : account_id NULL
    adapter.db.execute(
        """INSERT INTO draft_history
        (account_id, email_id, email_sender, email_subject, email_body,
         draft_v1, critique, draft_final, status)
        VALUES (NULL, 'legacy-email', 'x@y', 'legacy', 'body',
                'v1', 'c', 'f', 'V1')"""
    )
    adapter.db.commit()
    # Plus un row normal
    adapter.add(_make_record("d1", account_id=1))

    results = adapter.get_all_for_account(1)
    assert len(results) == 1
    assert results[0].email_id == "email-d1"
    # Le legacy row n'est jamais retourné à aucun compte
    assert adapter.get_all_for_account(2) == []


# --------------------------------------------------------------------------- #
# Test 4 — les méthodes unscoped lèvent en prod
# --------------------------------------------------------------------------- #


def test_unscoped_get_all_raises_in_prod(adapter, monkeypatch):
    monkeypatch.delenv("ALLOW_UNSCOPED_DRAFT_HISTORY", raising=False)
    with pytest.raises(RuntimeError, match="non scopé"):
        adapter.get_all()


def test_unscoped_get_by_id_raises_in_prod(adapter, monkeypatch):
    monkeypatch.delenv("ALLOW_UNSCOPED_DRAFT_HISTORY", raising=False)
    with pytest.raises(RuntimeError, match="non scopé"):
        adapter.get_by_id("d1")


def test_unscoped_update_feedback_raises_in_prod(adapter, monkeypatch):
    monkeypatch.delenv("ALLOW_UNSCOPED_DRAFT_HISTORY", raising=False)
    with pytest.raises(RuntimeError, match="non scopé"):
        adapter.update_feedback("d1", "good")


def test_unscoped_methods_allowed_with_env_flag(adapter, monkeypatch):
    monkeypatch.setenv("ALLOW_UNSCOPED_DRAFT_HISTORY", "1")
    # Ne lève pas, retourne liste (éventuellement vide)
    assert adapter.get_all() == []
    assert adapter.get_by_id("nonexistent") is None


# --------------------------------------------------------------------------- #
# Test 5 — get_all_for_account avec account_id invalide
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("invalid_id", [0, -1, -42])
def test_get_all_for_account_returns_empty_for_invalid_account(adapter, invalid_id):
    adapter.add(_make_record("d1", account_id=1))
    assert adapter.get_all_for_account(invalid_id) == []


@pytest.mark.parametrize("invalid_id", [0, -1, -42])
def test_get_by_id_for_account_returns_none_for_invalid_account(adapter, invalid_id):
    adapter.add(_make_record("d1", account_id=1))
    assert adapter.get_by_id_for_account("d1", invalid_id) is None
