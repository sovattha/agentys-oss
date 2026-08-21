# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-30 — PATCH /api/settings global-write leak.

When an AUTHENTICATED (JWT) caller has no resolved account yet — just-signed-up,
hasn't run the wizard — `_get_current_account_id()` returns None. The handler
used to fall through to `save_settings(..., account_id=None)` →
`_save_global_settings`, mutating the shared `data/settings.json` and seeding
every other tenant's defaults, while returning `success: true`.

Fix: guard the None case for authenticated callers — return 401
ONBOARDING_REQUIRED instead of writing the global file (mirrors
@account_scoped, account_scope.py:54-58). Loopback/Tauri no-JWT callers keep
the legitimate global write (they have no `g.auth_user`).

Run: pytest tests/audit_fixes/test_audit_fix_settings_global_write.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask_cors")

REMOTE = {"REMOTE_ADDR": "203.0.113.10"}  # non-loopback
AUTH = {"Authorization": "Bearer tok"}
JWT = {"sub": "7", "email": "tenant7@corp.com"}


@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    return app.test_client()


def test_authenticated_unresolved_account_does_not_write_global(client):
    """Authenticated PATCH with no resolved account => 401, no global write."""
    save = MagicMock(return_value=True)
    save_global = MagicMock(return_value=True)
    with patch("app.api.auth._decode_jwt", return_value=JWT), \
         patch("app.api.settings._get_current_account_id", return_value=None), \
         patch("app.api.settings.save_settings", save), \
         patch("app.api.settings._save_global_settings", save_global):
        resp = client.patch(
            "/api/settings",
            json={"notifications_enabled": False},
            headers=AUTH,
            environ_base=REMOTE,
        )

    assert resp.status_code in (401, 409)
    body = resp.get_json()
    assert body.get("code") == "ONBOARDING_REQUIRED"
    # The global settings file must NOT be written for an unresolved tenant.
    save.assert_not_called()
    save_global.assert_not_called()
