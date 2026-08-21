# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix M-3 (issue #537) — `/api/wizard/test-*` SSRF + LLM-budget burn.

Bug : `POST /api/wizard/test-connection` (`app/api/wizard.py:933`) et
`POST /api/wizard/test-llm` (`:1128`) étaient auth-gated mais sans
`@require_admin` — incohérent avec leurs sibling write endpoints du wizard
(`config` POST/DELETE, `import`, `export`, `import-env`, tous admin-only).

Conséquences :
  * **SSRF** : `test-connection` ouvre une connexion sortante IMAP/SMTP
    vers un `host:port` fourni dans le body. Tout user authentifié pouvait
    scanner le réseau interne via les retours (`169.254.169.254` AWS
    metadata, `127.0.0.1:5050` API admin, etc.).
  * **LLM-budget burn** : `test-llm` hit le provider configuré avec un
    prompt de test. En multi-tenant, un user non-admin pouvait drainer
    le quota Anthropic / OpenAI du compte.

Fix : `@require_admin` ajouté sur les deux endpoints, aligné avec le reste
du wizard. Pattern mirror de `c_03_push_broadcast_admin_only` et
`/api/sync/trigger` (#535).

Run: `pytest tests/audit_fixes/test_m_03_wizard_test_endpoints_admin.py -v`
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

pytest.importorskip("flask_cors")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def client():
    from app.api.app import create_app
    app = create_app(config={"TESTING": True})
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


REMOTE_ATTACKER = {"REMOTE_ADDR": "203.0.113.10"}

# Body that would have triggered an outbound IMAP connection to AWS metadata.
SSRF_CONN_BODY = {
    "imap_host": "169.254.169.254",
    "imap_port": 80,
    "imap_username": "x",
    "imap_password": "x",
    "smtp_host": "169.254.169.254",
    "smtp_port": 80,
    "smtp_username": "x",
    "smtp_password": "x",
}

# Body that would have burned Anthropic credit.
TEST_LLM_BODY = {
    "provider": "claude",
    "api_key": "sk-attacker-key",
    "model": "claude-haiku-4-5-20251001",
}


# --------------------------------------------------------------------------- #
# Reproduction: a non-admin authenticated user MUST NOT trigger.
# --------------------------------------------------------------------------- #


def test_test_connection_non_admin_jwt_must_be_rejected(client):
    """A magic-link JWT for a normal user MUST be 403."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False), \
         patch("app.api.wizard._test_imap_connection") as mock_imap, \
         patch("app.api.wizard._test_smtp_connection") as mock_smtp:
        resp = client.post(
            "/api/wizard/test-connection",
            json=SSRF_CONN_BODY,
            content_type="application/json",
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403, resp.get_data(as_text=True)
    # No outbound IMAP/SMTP probe — the gate must abort before any I/O.
    mock_imap.assert_not_called()
    mock_smtp.assert_not_called()


def test_test_llm_non_admin_jwt_must_be_rejected(client):
    """LLM-budget burn must be blocked: the gate aborts before the LLM call."""
    fake_payload = {"sub": "42", "email": "victim@example.com"}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=False), \
         patch("app.api.wizard._test_claude_connection") as mock_claude:
        resp = client.post(
            "/api/wizard/test-llm",
            json=TEST_LLM_BODY,
            content_type="application/json",
            headers={"Authorization": "Bearer normal-user-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code == 403
    # No Anthropic call — the gate must reject before the adapter is built.
    mock_claude.assert_not_called()


def test_test_connection_no_jwt_remote_must_be_rejected(client):
    with patch("app.api.wizard._test_imap_connection") as mock_imap:
        resp = client.post(
            "/api/wizard/test-connection",
            json=SSRF_CONN_BODY,
            content_type="application/json",
            environ_base=REMOTE_ATTACKER,
        )
    assert resp.status_code in (401, 403)
    mock_imap.assert_not_called()


def test_test_llm_no_jwt_remote_must_be_rejected(client):
    with patch("app.api.wizard._test_claude_connection") as mock_claude:
        resp = client.post(
            "/api/wizard/test-llm",
            json=TEST_LLM_BODY,
            content_type="application/json",
            environ_base=REMOTE_ATTACKER,
        )
    assert resp.status_code in (401, 403)
    mock_claude.assert_not_called()


# --------------------------------------------------------------------------- #
# Sanity: admin still works (Tauri wizard flow legitimately uses these).
# --------------------------------------------------------------------------- #


def test_test_connection_admin_jwt_passes_gate(client):
    """An admin JWT must clear the gate and reach the IMAP/SMTP test logic."""
    fake_payload = {"sub": "1", "email": "admin@test.com"}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True), \
         patch(
             "app.api.wizard._test_imap_connection",
             return_value={"success": True, "response_time_ms": 10},
         ), \
         patch(
             "app.api.wizard._test_smtp_connection",
             return_value={"success": True, "response_time_ms": 10},
         ):
        resp = client.post(
            "/api/wizard/test-connection",
            json=SSRF_CONN_BODY,
            content_type="application/json",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code != 403, resp.get_data(as_text=True)


def test_test_llm_admin_jwt_passes_gate(client):
    fake_payload = {"sub": "1", "email": "admin@test.com"}

    with patch("app.api.auth._decode_jwt", return_value=fake_payload), \
         patch("app.api.admin._is_admin", return_value=True), \
         patch(
             "app.api.wizard._test_claude_connection",
             return_value={"success": True, "response_time_ms": 10},
         ):
        resp = client.post(
            "/api/wizard/test-llm",
            json=TEST_LLM_BODY,
            content_type="application/json",
            headers={"Authorization": "Bearer admin-jwt"},
            environ_base=REMOTE_ATTACKER,
        )

    assert resp.status_code != 403


# --------------------------------------------------------------------------- #
# Static check: the decorator stack is actually present.
# --------------------------------------------------------------------------- #


def test_source_has_require_admin_on_both_test_endpoints():
    """Source-level lock — un futur refactor qui retire le décorateur
    régresserait la fix. Pattern mirror de
    test_c_03_push_broadcast_admin_only."""
    from app.api import wizard

    src = inspect.getsource(wizard)

    for view_name in ("test_connection", "test_llm_connection"):
        idx = src.find(f"def {view_name}(")
        assert idx > 0, f"{view_name} not found in source"
        preamble = src[max(0, idx - 400) : idx]
        assert "@require_admin" in preamble, (
            f"@require_admin missing immediately above {view_name} — "
            f"the M-3 fix has been regressed.\nPreamble:\n{preamble}"
        )
