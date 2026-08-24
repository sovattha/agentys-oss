# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Deep audit 2026-06-02 F: EmailRepository.get_by_email_ids batch row fetch.

The inbox-sync loop (_sync_emails_to_cache) did a batch existence check and then,
for EVERY already-cached email, called get_by_email_id() individually — one
SELECT per row, defeating the batch check (an N+1 on a hot per-account sync
tick). get_by_email_ids collapses that into a single IN(...) query. These tests
pin the method's contract (dict keyed by email_id, account-scoped, empty-safe).
"""

from __future__ import annotations

from datetime import datetime

from app.db.models import Email
from app.db.repositories.email_repository import EmailRepository


def _mk(session, account_id: int, email_id: str) -> Email:
    row = Email(
        email_id=email_id,
        account_id=account_id,
        subject="s",
        sender="a@example.com",
        sender_name="A",
        recipients="b@example.com",
        date=datetime.utcnow(),
        body_text="…",
        snippet="…",
        is_read=False,
        is_starred=False,
    )
    session.add(row)
    session.flush()
    return row


def test_get_by_email_ids_returns_dict_keyed_by_email_id(session, sample_account):
    _mk(session, sample_account.id, "id-1")
    _mk(session, sample_account.id, "id-2")
    session.commit()

    out = EmailRepository(session).get_by_email_ids(
        ["id-1", "id-2", "missing"], account_id=sample_account.id
    )

    assert set(out) == {"id-1", "id-2"}  # missing ID simply absent
    assert out["id-1"].email_id == "id-1"
    assert isinstance(out["id-2"], Email)


def test_get_by_email_ids_scopes_by_account(session, sample_account):
    _mk(session, sample_account.id, "id-1")
    session.commit()
    repo = EmailRepository(session)

    # A different account_id must not see this row (multi-tenant isolation).
    assert repo.get_by_email_ids(["id-1"], account_id=sample_account.id + 1) == {}
    # The owning account does.
    assert "id-1" in repo.get_by_email_ids(["id-1"], account_id=sample_account.id)


def test_get_by_email_ids_empty_input_returns_empty_dict(session, sample_account):
    assert EmailRepository(session).get_by_email_ids([], account_id=sample_account.id) == {}
