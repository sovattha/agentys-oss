# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_record_pending_draft_history_adds_account_scoped_record(monkeypatch):
    from app.api import routes_emails

    history = MagicMock()
    container = MagicMock()
    container.get_draft_history.return_value = history
    monkeypatch.setattr(routes_emails._rh, "_get_container", lambda: container)

    email = SimpleNamespace(
        sender="client@example.com",
        subject="Besoin d'aide",
        body="Bonjour, pouvez-vous m'aider avec mon compte ?",
    )

    routes_emails._record_pending_draft_history(
        email=email,
        email_id="email-123",
        account_id=42,
        draft_id="draft-123",
        draft_v1="Bonjour, je regarde.",
        critique_text="Clarifier la prochaine étape.",
        final_draft="Bonjour, je regarde et je reviens vers vous.",
        status="STANDARD_V2",
        details={"was_corrected": True},
        priority=80,
        classification="Action",
        processing_time_ms=1234,
    )

    history.add.assert_called_once()
    record = history.add.call_args.args[0]
    assert record.account_id == 42
    assert record.email_id == "email-123"
    assert record.draft_id == "draft-123"
    assert record.status == "V2"
    assert record.priority_score == 80
    assert record.category == "Action"
    assert record.processing_time_ms == 1234
    assert record.draft_final == "Bonjour, je regarde et je reviens vers vous."


def test_record_pending_draft_history_skips_unresolved_account(monkeypatch):
    from app.api import routes_emails

    history = MagicMock()
    container = MagicMock()
    container.get_draft_history.return_value = history
    monkeypatch.setattr(routes_emails._rh, "_get_container", lambda: container)

    email = SimpleNamespace(sender="client@example.com", subject="Sujet", body="Body")

    routes_emails._record_pending_draft_history(
        email=email,
        email_id="email-123",
        account_id=-1,
        draft_id="draft-123",
        draft_v1="V1",
        critique_text="",
        final_draft="Final",
        status="STANDARD_HAIKU",
        details={"was_corrected": False},
        priority=50,
        classification="Action",
        processing_time_ms=12,
    )

    history.add.assert_not_called()
