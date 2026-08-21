# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix ISO-07 + ISO-08 — public label endpoints leak per-email data.

Bug:
- ISO-07: `GET /api/labels/assignments/<email_id>` was in `_PUBLIC_ENDPOINTS`
  (cf. `app/api/app.py:324`) and the handler called
  `store.get_assignment(email_id)` with no account scoping. Any caller
  could enumerate IMAP / Gmail thread IDs to fetch User A's labels.
- ISO-08: `GET /api/labels/emails/<label_name>` was also public, and the
  underlying LabelStore.get_emails_by_label falls back to a global JSON
  cache when no account context is available — leaking every user's
  tagged email IDs.

Fix: remove both routes from `_PUBLIC_ENDPOINTS`, scope the queries to the
caller's account in the handlers.

Run: `pytest tests/audit_fixes/test_iso_07_08_public_label_endpoints.py -v`
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def test_get_assignment_remote_no_auth_must_be_rejected(client):
    """ISO-07: unauthenticated remote caller MUST NOT receive label
    assignments by guessing email_ids."""
    resp = client.get(
        "/api/labels/assignments/some-email-id-123",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert resp.status_code in (401, 403), (
        f"ISO-07 leak: unauthenticated caller got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )


def test_get_emails_by_label_remote_no_auth_must_be_rejected(client):
    """ISO-08: unauthenticated remote caller MUST NOT receive the list
    of email_ids tagged with a given label."""
    resp = client.get(
        "/api/labels/emails/VIP",
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert resp.status_code in (401, 403), (
        f"ISO-08 leak: unauthenticated caller got {resp.status_code} "
        f"with body {resp.get_data(as_text=True)[:200]}"
    )


def _stub_jwt(user_id: int, email: str):
    return patch(
        "app.api.auth._decode_jwt",
        return_value={"sub": user_id, "email": email},
    )


def test_get_assignment_with_jwt_but_no_db_account_returns_no_data(client):
    """ISO-07: a JWT user whose email isn't in the accounts table must
    not receive someone else's label assignments via fallback."""
    with _stub_jwt(user_id=42, email="stranger@example.com"), \
         patch("app.api.routes_helpers._resolve_account_id_for_user",
               return_value=-1):  # _NO_ACCOUNT_SENTINEL
        resp = client.get(
            "/api/labels/assignments/some-email-id",
            headers={"Authorization": "Bearer stub"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
    # 401 (no scoped account) or 404 (no assignment) — anything but 200
    # with someone else's data.
    assert resp.status_code in (401, 403, 404)
    body = resp.get_json() or {}
    assert "assignment" not in body
