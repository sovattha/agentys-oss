# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-29 — POST /api/labels/learn trusted client-supplied identity.

Bug: the learning-coordinator notification forwarded ``data["account_id"]`` and
``data["user_email"]`` straight from the request body, letting an authenticated
tenant inject a label-corrected event into ANOTHER tenant's private WebSocket
room and trigger a knowledge-base rebuild on their account.

Fix: the notification uses the JWT-resolved account_id + g.auth_user email; the
body fields are ignored entirely.

Run: pytest tests/audit_fixes/test_isolation_2026_05_29_labels_learn_identity.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "5", "email": "caller@corp.com"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def _container():
    container = MagicMock()
    store = MagicMock()
    store.get_assignment.return_value = None
    store.get_rules.return_value = []
    store.add_rule.return_value = False
    container.get_label_store.return_value = store
    container.get_learn_labeling_rule_use_case.return_value.execute.return_value = []
    tpl = MagicMock()
    tpl.fingerprint.return_value = "fp"
    container.get_template_label_cache.return_value = tpl
    return container


def test_learn_notify_ignores_body_identity_uses_jwt(client):
    """Body carries a FOREIGN account_id/user_email; the coordinator must be
    called with the JWT identity (5 / caller@corp.com), never the body's."""
    coordinator = MagicMock()
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=5), \
         patch("app.api.labels._get_labels_cached", return_value=[SimpleNamespace(name="ProjetX")]), \
         patch("app.api.labels.get_container", return_value=_container()), \
         patch("app.api.labels._maybe_aggregate_domain_rule"), \
         patch("app.api.labels._persist_label_correction_for_eval"), \
         patch("app.infrastructure.sender_reputation_store.get_reputation_store", return_value=MagicMock()), \
         patch("app.learning_refresh.get_refresh_coordinator", return_value=coordinator):
        resp = client.post(
            "/api/labels/learn",
            headers=AUTH, environ_base=REMOTE,
            json={
                "email_id": "e1",
                "sender": "x@y.com",
                "subject": "s",
                "body": "b",
                "old_labels": ["Info"],
                "new_labels": ["ProjetX"],
                # Attacker-injected identity — must be IGNORED:
                "account_id": 99,
                "user_email": "victim@evil.com",
            },
        )
    assert resp.status_code == 200
    coordinator.on_label_corrected.assert_called_once()
    kwargs = coordinator.on_label_corrected.call_args.kwargs
    assert kwargs["account_id"] == 5, "must use JWT account_id, not body 99"
    assert kwargs["user_email"] == "caller@corp.com", "must use JWT email, not body victim"
