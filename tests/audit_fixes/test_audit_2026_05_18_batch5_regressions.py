# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression tests for audit-regressions batch5 fixes (2026-05-18).

Each test pins a specific finding from
`tasks/audit-reports/2026-05-18_0844_regressions/pass-2-final.md`. The
batch5 PR closes 5 blockers (F-01/F-02/F-04/F-05/F-07/F-10). Tests that
naturally live in a co-located file (accountIdMap.test.ts, dedup_race,
writing_style_store) are added there; this file covers F-10's backend-
side error_code migration that has no obvious sibling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest


# ============================================================================
# F-10 — scheduled_emails error_code migration (5 hardcoded French strings)
# ============================================================================

@pytest.fixture()
def app():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def store(tmp_path):
    from app.services.scheduled_email_store import (
        ScheduledEmailStore,
        reset_default_store,
    )
    s = ScheduledEmailStore(db_path=str(tmp_path / "sched.db"))
    reset_default_store(s)
    yield s
    reset_default_store(None)


@pytest.fixture(autouse=True)
def _mock_account():
    mock = Mock()
    mock.id = "test-account"
    mock.email = "test@example.com"
    with patch(
        "app.api.scheduled_emails._get_current_account_for_user",
        return_value=mock,
    ), patch(
        "app.api.scheduled_emails._resolve_account_id_cached",
        return_value=42,
    ):
        yield mock


def _future_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_f10_post_missing_to_returns_error_code(client, store):
    """POST /scheduled with no `to` field must return error_code TO_INVALID_OR_MISSING.

    Pre-batch5: backend returned ``{"error": "Adresse de destinataire invalide ou manquante"}``
    — the French string leaked into en/es/de UIs because the FE surfaced ``data.error``
    verbatim. Post-batch5: the FE looks up the i18n template via ``data.error_code``.
    """
    resp = client.post(
        "/api/emails/schedule",
        json={"subject": "Test", "body": "Body", "send_at": _future_iso()},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error_code"] == "TO_INVALID_OR_MISSING"
    assert "error" in body  # English fallback present for old FE deploys


def test_f10_post_missing_body_returns_error_code(client, store):
    """POST /scheduled with empty body must return error_code BODY_REQUIRED."""
    resp = client.post(
        "/api/emails/schedule",
        json={
            "to": "alice@example.com",
            "subject": "Test",
            "body": "",
            "send_at": _future_iso(),
        },
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error_code"] == "BODY_REQUIRED"


def test_f10_post_invalid_cc_returns_error_code_with_context(client, store):
    """POST /scheduled with a malformed cc must return RECIPIENT_INVALID + address context."""
    resp = client.post(
        "/api/emails/schedule",
        json={
            "to": "alice@example.com",
            "cc": "not-an-email",
            "subject": "Test",
            "body": "Body",
            "send_at": _future_iso(),
        },
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error_code"] == "RECIPIENT_INVALID"
    # Context must carry the address so the i18n template `Invalid address:
    # {{address}}` can render it in the user's locale.
    assert body["error_context"] == {"address": "not-an-email"}


def test_f10_cancel_non_pending_returns_scheduled_status_not_cancelable(client, store):
    """DELETE /scheduled/<id> on a row with status!=pending must surface
    error_code SCHEDULED_STATUS_NOT_CANCELABLE + status context."""
    # Seed a scheduled row, then transition it to "sent" so cancel fails the gate.
    sched_id = store.insert(
        account_id=42,
        payload={"to": ["alice@example.com"], "subject": "S", "body": "B"},
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.mark_sent(sched_id, message_id="msg-1")

    resp = client.delete(f"/api/emails/scheduled/{sched_id}")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error_code"] == "SCHEDULED_STATUS_NOT_CANCELABLE"
    assert body["error_context"] == {"status": "sent"}


def test_f10_patch_invalid_to_returns_error_code(client, store):
    """PATCH /scheduled/<id> with malformed `to` must return TO_INVALID."""
    sched_id = store.insert(
        account_id=42,
        payload={"to": ["alice@example.com"], "subject": "S", "body": "B"},
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    resp = client.patch(
        f"/api/emails/scheduled/{sched_id}",
        json={"to": ""},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error_code"] == "TO_INVALID"


def test_f10_patch_empty_body_returns_error_code(client, store):
    """PATCH /scheduled/<id> with empty body must return BODY_REQUIRED."""
    sched_id = store.insert(
        account_id=42,
        payload={"to": ["alice@example.com"], "subject": "S", "body": "B"},
        send_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    resp = client.patch(
        f"/api/emails/scheduled/{sched_id}",
        json={"body": "   "},  # whitespace-only — stripped to empty
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error_code"] == "BODY_REQUIRED"


def test_f10_no_hardcoded_french_jsonify_in_scheduled_emails():
    """Static guard: re-introducing a hardcoded French jsonify in this file
    should visibly fail. Captures the audit's regret about commit 3850dea9
    claiming a "full sweep" while leaving 5 sites unmigrated."""
    import re
    from pathlib import Path
    src = Path("app/api/scheduled_emails.py").read_text(encoding="utf-8")
    # Match `jsonify({"error": "<uppercase-Latin-1>...` — flags French strings.
    # The remaining `jsonify({"error": err})` / `jsonify({"error": str(e)})`
    # pass through already-translated user-facing messages from helpers, which
    # are out-of-scope for F-10.
    hits = re.findall(r'jsonify\(\{"error":\s*"[A-ZÀ-Ÿ]', src)
    interpolated = re.findall(r'jsonify\(\{"error":\s*f"', src)
    assert hits == [], f"Hardcoded jsonify error strings re-introduced: {hits}"
    assert interpolated == [], (
        f"Hardcoded f-string jsonify error re-introduced: {interpolated} — "
        f"use error_response(..., context={{...}}) instead"
    )
