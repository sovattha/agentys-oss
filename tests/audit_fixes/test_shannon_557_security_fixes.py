# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests for Shannon pentest 2026-05-05 (issue #557).

Each test maps to a vulnerability ID in the report:
- AUTH-VULN-01    OAuth poll JWT theft via state knowledge
- AUTH-VULN-03    JWT revocation + /api/auth/logout
- AUTH-VULN-04    Outlook nOAuth identity verification
- AUTHZ-VULN-04   /api/tasks/{id} IDOR (per-tenant scoping)
- AUTHZ-VULN-05   Reminder cross-user delete
- AUTHZ-VULN-08   /api/wizard/test-llm SSRF
- AUTHZ-VULN-09   /api/wizard/llm-settings persistent SSRF
- AUTHZ-VULN-10   Cross-user agent marketplace config
- SSRF-VULN-01    /api/knowledge/scan-url cloud metadata exfiltration
- SSRF-VULN-02/03/06   Newsletter unsubscribe SSRF (covered by helper test)

The point of these tests is **forensic**: they reproduce the attacker's
witness payload from the Shannon report and assert the new defense
refuses it. A future refactor that breaks the defense fails here loudly.
"""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip("flask_cors")


# ──────────────────────────────────────────────────────────────────────────────
# safe_outbound helper — foundation for every SSRF fix
# ──────────────────────────────────────────────────────────────────────────────


class TestSafeOutbound:
    """Direct unit tests for app.utils.safe_outbound — the SSRF foundation."""

    def test_rejects_file_scheme(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with pytest.raises(SsrfBlocked, match="[Ss]cheme"):
            validate_outbound_url("file:///etc/passwd")

    def test_rejects_gopher_scheme(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with pytest.raises(SsrfBlocked, match="[Ss]cheme"):
            validate_outbound_url("gopher://internal.example.com:11211/")

    def test_rejects_dict_scheme(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with pytest.raises(SsrfBlocked):
            validate_outbound_url("dict://internal.example.com/")

    def test_rejects_aws_metadata(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
        ):
            with pytest.raises(SsrfBlocked, match="interne|169"):
                validate_outbound_url("http://attacker-rebind.example/")

    def test_rejects_localhost_via_dns(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
        ):
            with pytest.raises(SsrfBlocked):
                validate_outbound_url("http://attacker.example/")

    def test_rejects_rfc1918_10_dot(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 0))],
        ):
            with pytest.raises(SsrfBlocked):
                validate_outbound_url("http://attacker.example/")

    def test_rejects_rfc1918_192_168(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.1", 0))],
        ):
            with pytest.raises(SsrfBlocked):
                validate_outbound_url("http://attacker.example/")

    def test_rejects_link_local(self):
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.0.5", 0))],
        ):
            with pytest.raises(SsrfBlocked):
                validate_outbound_url("http://attacker.example/")

    def test_rejects_when_any_resolved_ip_is_private(self):
        """Mixed A/AAAA records: one public, one private. Must refuse."""
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[
                (2, 1, 6, "", ("8.8.8.8", 0)),
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ],
        ):
            with pytest.raises(SsrfBlocked):
                validate_outbound_url("http://mixed.example/")

    def test_accepts_public_https(self):
        from app.utils.safe_outbound import validate_outbound_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
        ):
            target = validate_outbound_url("https://example.com/foo")
        assert target.scheme == "https"
        assert target.host == "example.com"
        assert target.ip == "8.8.8.8"

    def test_safe_request_strips_caller_allow_redirects(self):
        """`allow_redirects=True` from caller is silently overridden."""
        from app.utils.safe_outbound import safe_request
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("8.8.8.8", 0))],
        ), patch("requests.request") as mock_req:
            mock_req.return_value = MagicMock(status_code=200, headers={})
            safe_request("GET", "https://example.com/", allow_redirects=True)
            kwargs = mock_req.call_args.kwargs
            assert kwargs["allow_redirects"] is False, (
                "allow_redirects must be forced to False"
            )

    def test_safe_request_revalidates_redirect_targets(self):
        """A 302 → private IP must NOT be auto-followed."""
        from app.utils.safe_outbound import safe_request, SsrfBlocked
        seen_urls = []

        def fake_request(method, url, **kwargs):
            seen_urls.append(url)
            mock = MagicMock(status_code=302, headers={
                "Location": "http://169.254.169.254/latest/meta-data/"
            })
            return mock

        with patch("socket.getaddrinfo") as mock_dns, \
             patch("requests.request", side_effect=fake_request):
            # First call resolves to public IP, second (redirect target)
            # would resolve to the AWS metadata IP and must be refused.
            def dns_side_effect(host, *a, **kw):
                if "169.254" in host:
                    return [(2, 1, 6, "", ("169.254.169.254", 0))]
                return [(2, 1, 6, "", ("8.8.8.8", 0))]
            mock_dns.side_effect = dns_side_effect

            with pytest.raises(SsrfBlocked):
                safe_request("GET", "https://benign.example/")


# ──────────────────────────────────────────────────────────────────────────────
# AUTHZ-VULN-08, AUTHZ-VULN-09 — wizard LLM endpoints
# ──────────────────────────────────────────────────────────────────────────────


class TestWizardLlmGuards:
    """The two wizard LLM endpoints must be admin-only and SSRF-safe."""

    def test_test_llm_requires_admin(self):
        # Decorator chain: require_admin (outer) → require_json. We grep the
        # wider module source to confirm the decoration sits above the
        # function definition (functools.wraps masks runtime introspection).
        import inspect
        from app.api import wizard
        mod_src = inspect.getsource(wizard)
        # Anchor: the literal pattern `@require_admin\n@require_json\ndef test_llm_connection`
        assert "@require_admin\n@require_json\ndef test_llm_connection" in mod_src, (
            "AUTHZ-VULN-08: /api/wizard/test-llm must be guarded by @require_admin"
        )

    def test_save_llm_settings_requires_admin(self):
        import inspect
        from app.api import wizard
        mod_src = inspect.getsource(wizard)
        assert "@require_admin\n@require_json\ndef save_llm_settings" in mod_src, (
            "AUTHZ-VULN-09: POST /api/wizard/llm-settings must be @require_admin"
        )

    def test_get_llm_settings_requires_admin(self):
        import inspect
        from app.api import wizard
        mod_src = inspect.getsource(wizard)
        assert "@require_admin\ndef get_llm_settings" in mod_src, (
            "AUTHZ-VULN-09: GET /api/wizard/llm-settings must be @require_admin"
        )

    def test_validate_ollama_url_rejects_file_scheme(self):
        from app.api.wizard import _validate_ollama_url
        ok, err = _validate_ollama_url("file:///etc/passwd")
        assert ok is False
        assert "scheme" in err.lower() or "Scheme" in err

    def test_validate_ollama_url_rejects_aws_metadata_in_prod(self):
        from app.api.wizard import _validate_ollama_url
        with patch("app.api._auth_helpers.is_production", return_value=True), \
             patch("socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("169.254.169.254", 0))]):
            ok, err = _validate_ollama_url("http://attacker.example/")
        assert ok is False, f"expected refusal, got ok=True err={err}"

    def test_validate_ollama_url_allows_localhost_in_dev(self):
        """Desktop Ollama lives on localhost — must keep working in dev."""
        from app.api.wizard import _validate_ollama_url
        with patch("app.api._auth_helpers.is_production", return_value=False):
            ok, _ = _validate_ollama_url("http://localhost:11434")
        assert ok is True


# ──────────────────────────────────────────────────────────────────────────────
# SSRF-VULN-01 — /api/knowledge/scan-url cloud metadata exfiltration
# ──────────────────────────────────────────────────────────────────────────────


class TestKnowledgeScanUrlSsrf:
    def test_faq_scanner_uses_safe_outbound(self):
        """The fix imports safe_outbound and uses safe_get."""
        import inspect
        from app.services import faq_scanner
        src = inspect.getsource(faq_scanner)
        assert "from app.utils.safe_outbound import" in src
        assert "safe_get(" in src
        # Defense-in-depth: no raw requests.get usage with allow_redirects=True
        # remains in the scanner.
        assert "allow_redirects=True" not in src

    def test_faq_scanner_refuses_aws_metadata(self):
        from app.services.faq_scanner import scan_url
        with patch(
            "socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
        ):
            result = scan_url("http://attacker-rebind.example/")
        assert result.error is not None
        assert "non autorisée" in result.error.lower() or "url" in result.error.lower()
        assert result.faq == []


# ──────────────────────────────────────────────────────────────────────────────
# AUTH-VULN-01 — OAuth poll JWT theft via state knowledge
# ──────────────────────────────────────────────────────────────────────────────


class TestOAuthPollFingerprint:
    def test_state_fingerprint_is_recorded_at_pkce_store(self):
        import inspect
        from app.api import oauth
        src = inspect.getsource(oauth.store_code_verifier)
        assert "_record_state_fingerprint" in src, (
            "AUTH-VULN-01: /pkce/store must record initiator fingerprint"
        )

    def test_poll_verifies_state_fingerprint(self):
        import inspect
        from app.api import oauth
        src = inspect.getsource(oauth.poll_oauth_session)
        assert "_verify_state_fingerprint" in src, (
            "AUTH-VULN-01: poll must verify caller fingerprint"
        )

    def test_fingerprint_match_returns_ok(self):
        from app.api import oauth
        oauth._state_fingerprints.clear()
        # Seed the binding directly, mirroring what /pkce/store would do.
        fp = "stable-fp-stub"
        with oauth._state_fingerprint_lock:
            oauth._state_fingerprints["xyz"] = {
                "fingerprint": fp,
                "timestamp": time.time(),
            }
        # The verifier compares against `_state_fingerprint_from_request()`
        # — patch it to simulate the legitimate caller (same fingerprint).
        with patch.object(oauth, "_state_fingerprint_from_request",
                          return_value=fp):
            ok, reason = oauth._verify_state_fingerprint("xyz")
        assert ok is True
        assert reason == "match"

    def test_fingerprint_mismatch_returns_false(self):
        from app.api import oauth
        oauth._state_fingerprints.clear()
        with oauth._state_fingerprint_lock:
            oauth._state_fingerprints["xyz"] = {
                "fingerprint": "victim_fp",
                "timestamp": time.time(),
            }
        with patch.object(oauth, "_state_fingerprint_from_request",
                          return_value="attacker_fp"):
            ok, reason = oauth._verify_state_fingerprint("xyz")
        assert ok is False
        assert reason == "mismatch"

    def test_unbound_state_is_lenient(self):
        """Legacy clients that didn't call /pkce/store stay accepted —
        this is the backward-compat lane, NOT a regression of the fix."""
        from app.api import oauth
        oauth._state_fingerprints.clear()
        ok, reason = oauth._verify_state_fingerprint("never-bound")
        assert ok is True
        assert reason == "unbound"


# ──────────────────────────────────────────────────────────────────────────────
# AUTH-VULN-03 — JWT revocation + /api/auth/logout
# ──────────────────────────────────────────────────────────────────────────────


class TestJwtRevocation:
    def test_jwt_payload_includes_jti(self):
        from app.api.auth import _create_jwt, JWT_SECRET, JWT_ALGORITHM
        import jwt
        token = _create_jwt(42, "alice@example.com")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert "jti" in payload
        assert isinstance(payload["jti"], str)
        assert len(payload["jti"]) >= 16

    def test_revoke_jti_blocks_subsequent_decode(self, tmp_path, monkeypatch):
        # Redirect the on-disk persistence to a tmp dir so we don't pollute
        # the dev data folder.
        from app.api import auth
        monkeypatch.setattr(
            auth, "_revoked_jtis_file_path",
            lambda: str(tmp_path / "revoked_jtis.json"),
        )
        # Reset in-memory state for isolation.
        with auth._revoked_jtis_lock:
            auth._revoked_jtis.clear()

        token = auth._create_jwt(42, "alice@example.com")
        # Pre-revoke: token decodes fine
        assert auth._decode_jwt(token) is not None

        # Revoke this token
        import jwt as _jwt
        payload = _jwt.decode(token, auth.JWT_SECRET, algorithms=[auth.JWT_ALGORITHM])
        auth.revoke_jti(payload["jti"], payload["exp"])

        # Post-revoke: token must NOT decode
        assert auth._decode_jwt(token) is None, (
            "AUTH-VULN-03: revoked JWT still decodes — blocklist broken"
        )

    def test_logout_endpoint_revokes_caller_jwt(self, tmp_path, monkeypatch):
        from app.api import auth
        monkeypatch.setattr(
            auth, "_revoked_jtis_file_path",
            lambda: str(tmp_path / "revoked_jtis.json"),
        )
        with auth._revoked_jtis_lock:
            auth._revoked_jtis.clear()

        from app.api.app import create_app
        app = create_app(config={"TESTING": True})
        client = app.test_client()

        token = auth._create_jwt(42, "alice@example.com")
        resp = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"logout failed: {resp.get_data(as_text=True)}"
        body = resp.get_json()
        assert body["success"] is True

        # Now the token must no longer decode.
        assert auth._decode_jwt(token) is None


# ──────────────────────────────────────────────────────────────────────────────
# AUTHZ-VULN-04 — /api/tasks/{id} IDOR (per-tenant scoping)
# ──────────────────────────────────────────────────────────────────────────────


class TestTaskOwnership:
    def test_get_by_id_refuses_foreign_account_id(self):
        from app.infrastructure.database import TaskRepository

        # Build a stub Database that returns a row with account_id=99
        # regardless of query.
        class _Row(dict):
            pass

        class _StubDb:
            def fetchone(self, sql, params):
                if "AND account_id = ?" in sql:
                    # Caller passed account_id — assert it's NOT 99 here.
                    if params[1] == 99:
                        return _Row({
                            "id": params[0], "account_id": 99,
                            "title": "t", "description": "", "priority": "low",
                            "deadline": None, "status": "pending",
                            "email_id": "", "created_at": "", "completed_at": None,
                        })
                    return None
                # Unscoped fallthrough — should NOT happen in our route.
                return _Row({"id": params[0], "account_id": 99})

            def fetchall(self, *a, **k): return []
            def execute(self, *a, **k): return MagicMock(lastrowid=1)
            def commit(self): pass

        repo = TaskRepository(database=_StubDb())
        # Owner can read
        owner_view = repo.get_by_id(123, account_id=99)
        assert owner_view is not None
        # Foreign user cannot
        attacker_view = repo.get_by_id(123, account_id=42)
        assert attacker_view is None, (
            "AUTHZ-VULN-04: foreign account_id leaked task data"
        )


# ──────────────────────────────────────────────────────────────────────────────
# AUTHZ-VULN-05 — Reminder cross-user delete
# ──────────────────────────────────────────────────────────────────────────────


class TestReminderOwnership:
    def test_dismiss_reminder_refuses_foreign_account(self, tmp_path, monkeypatch):
        from app.services import reminder_service as rs
        monkeypatch.setattr(rs, "_REMINDERS_FILE", tmp_path / "reminders.json")

        # Seed: user 7 owns reminder 'rem-1'
        rem_id = rs.add_reminder("email-1", "Subj", "2099-01-01T00:00:00+00:00", account_id=7)

        # User 8 tries to delete it → must fail
        ok = rs.dismiss_reminder(rem_id, account_id=8)
        assert ok is False, "AUTHZ-VULN-05: foreign user deleted another user's reminder"

        # User 7 (legitimate) deletes it → must succeed
        ok = rs.dismiss_reminder(rem_id, account_id=7)
        assert ok is True

    def test_get_all_pending_filters_by_account(self, tmp_path, monkeypatch):
        from app.services import reminder_service as rs
        monkeypatch.setattr(rs, "_REMINDERS_FILE", tmp_path / "reminders.json")

        rs.add_reminder("e1", "S1", "2099-01-01T00:00:00+00:00", account_id=7)
        rs.add_reminder("e2", "S2", "2099-01-01T00:00:00+00:00", account_id=8)

        rems_7 = rs.get_all_pending(account_id=7)
        rems_8 = rs.get_all_pending(account_id=8)

        assert len(rems_7) == 1 and rems_7[0]["account_id"] == 7
        assert len(rems_8) == 1 and rems_8[0]["account_id"] == 8


# ──────────────────────────────────────────────────────────────────────────────
# AUTHZ-VULN-10 — Cross-user agent marketplace config
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentMarketplaceUserScope:
    def test_config_path_namespaced_by_user(self, tmp_path, monkeypatch):
        from app.api import agent_marketplace as am
        monkeypatch.setattr(am, "_DATA_DIR", tmp_path / "agent_configs")
        monkeypatch.setattr(am, "_LEGACY_CONFIG_DIR", tmp_path / "agent_configs")

        path_user_42 = am._config_path("refund", user_id=42)
        path_user_99 = am._config_path("refund", user_id=99)

        assert path_user_42 != path_user_99, (
            "AUTHZ-VULN-10: configs from different users share a path"
        )
        assert "u_42" in str(path_user_42)
        assert "u_99" in str(path_user_99)

    def test_config_path_rejects_traversal(self, tmp_path, monkeypatch):
        from app.api import agent_marketplace as am
        monkeypatch.setattr(am, "_DATA_DIR", tmp_path / "agent_configs")
        with pytest.raises(ValueError):
            am._config_path("../../etc/passwd", user_id=42)
        with pytest.raises(ValueError):
            am._config_path("refund/../escape", user_id=42)

    def test_save_config_refuses_ssrf_base_url_in_prod(self, tmp_path, monkeypatch):
        """The save_config endpoint validates the custom provider base_url
        against the SSRF allowlist before persisting."""
        from app.api.app import create_app
        from app.api import auth as _auth
        from app.api import agent_marketplace as am

        monkeypatch.setattr(am, "_DATA_DIR", tmp_path / "agent_configs")
        monkeypatch.setattr(am, "_LEGACY_CONFIG_DIR", tmp_path / "agent_configs")

        app = create_app(config={"TESTING": True})
        client = app.test_client()

        token = _auth._create_jwt(42, "alice@example.com")

        with patch("app.api._auth_helpers.is_production", return_value=True), \
             patch("socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("169.254.169.254", 0))]):
            resp = client.patch(
                "/api/agent-marketplace/account/config",
                json={"providers": {"custom": {"base_url": "http://attacker.example/"}}},
                headers={"Authorization": f"Bearer {token}"},
            )
        # Must be refused (400 from validation, not 200 success)
        assert resp.status_code == 400, (
            f"AUTHZ-VULN-10: SSRF base_url accepted: {resp.status_code} "
            f"{resp.get_data(as_text=True)[:200]}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# AUTH-VULN-04 — Outlook nOAuth identity verification
# ──────────────────────────────────────────────────────────────────────────────


class TestOutlookNOAuth:
    def test_validate_outlook_identity_allows_oid_userinfo_divergence(self):
        """Regression (2026-05-20): a legitimate Microsoft account whose
        id_token `oid` diverges from the Graph `/me` `id` MUST still sign in.

        The `oid == /me.id` equality is not a valid nOAuth control — in the
        real attack the attacker's own oid and Graph id agree, so the equality
        passes anyway — and it false-positively locked out legitimate accounts
        (personal MSA, B2B guests, v1/v2 token nuances) with
        `oid_userinfo_mismatch` (HTTP 400). The divergence is now logged, not
        fatal.
        """
        from app.api.oauth import _validate_outlook_identity
        # Craft an id_token whose oid differs from the Graph userinfo `id`.
        import base64
        import json as _json
        claims = {"oid": "alice-oid", "tid": "tenant-x", "email": "alice@x.com"}
        payload_b64 = base64.urlsafe_b64encode(_json.dumps(claims).encode()).rstrip(b"=").decode()
        fake_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        tokens = {"id_token": fake_jwt}
        # Graph returns a different `id` than the id_token's `oid` — the exact
        # production lockout scenario.
        userinfo = {"id": "graph-different-id", "mail": "alice@x.com"}

        with patch("app.api.oauth.logger") as mock_logger:
            ok, reason = _validate_outlook_identity(tokens, userinfo)

        assert ok is True, "legitimate oid/userinfo divergence must NOT block sign-in"
        assert reason == "ok"
        # Divergence stays observable in logs even though it no longer blocks.
        assert mock_logger.warning.called
        logged = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "divergence" in logged.lower() and "oid" in logged.lower()

    def test_validate_outlook_identity_passes_when_oid_matches(self):
        from app.api.oauth import _validate_outlook_identity
        import base64
        import json as _json
        claims = {"oid": "alice-oid", "tid": "tenant-x", "email": "alice@x.com"}
        payload_b64 = base64.urlsafe_b64encode(_json.dumps(claims).encode()).rstrip(b"=").decode()
        fake_jwt = f"eyJhbGciOiJIUzI1NiJ9.{payload_b64}.signature"
        tokens = {"id_token": fake_jwt}
        userinfo = {"id": "alice-oid", "mail": "alice@x.com"}

        ok, _ = _validate_outlook_identity(tokens, userinfo)
        assert ok is True

    def test_validate_outlook_identity_refuses_no_id_token_in_prod(self):
        from app.api.oauth import _validate_outlook_identity
        with patch("app.api._auth_helpers.is_production", return_value=True):
            ok, reason = _validate_outlook_identity({}, {"id": "x"})
        assert ok is False
        assert "id_token" in reason

    def test_capture_oauth_identity_rejection_uses_safe_sentry_tags(self):
        from app.api.oauth import _capture_oauth_identity_rejection

        scope = MagicMock()
        scope_cm = MagicMock()
        scope_cm.__enter__.return_value = scope
        scope_cm.__exit__.return_value = False

        with patch("sentry_sdk.new_scope", return_value=scope_cm), \
             patch("sentry_sdk.capture_message") as capture_message:
            _capture_oauth_identity_rejection(
                provider="outlook",
                flow="complete",
                reason="id_token absent — refus nOAuth-defense",
            )

        scope.set_tag.assert_any_call("oauth.provider", "outlook")
        scope.set_tag.assert_any_call("oauth.flow", "complete")
        scope.set_tag.assert_any_call("oauth.error_code", "identity_invalid")
        scope.set_tag.assert_any_call("oauth.identity_reject_reason", "id_token_absent")
        capture_message.assert_called_once_with("OAuth identity rejected", level="warning")
        assert "refus nOAuth-defense" not in str(scope.set_tag.call_args_list)
