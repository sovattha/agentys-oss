# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests — log redactor + magic-link plaintext (CASA V7.1, GitHub #210).

Avant cette PR :
  - app/api/auth.py:430 logguait le magic_url en plaintext (token = session
    takeover si fuite vers Sentry/Railway logs)
  - Aucun filtre global ne scrubbait les tokens / passwords / Bearer

Cette PR ajoute :
  - _SecretRedactingFilter sur root logger (defense-in-depth)
  - auth.py log redacted token_id only + dev guard fail-closed
    (FLASK_ENV == "development" au lieu de != "production")
"""

import logging

import pytest


@pytest.fixture
def app_with_redactor(monkeypatch):
    """create_app() pour s'assurer que le filter root est attaché."""
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    create_app()  # Side effect: attach _SecretRedactingFilter on root logger
    return logging.getLogger("test_redactor_target")


class TestSecretRedactingFilter:
    """Le filter root doit scrubber les patterns sensibles avant émission."""

    def test_redacts_magic_link_token_in_url(self, app_with_redactor, caplog):
        with caplog.at_level(logging.INFO):
            app_with_redactor.info("Magic link http://localhost:1420/?token=abc123def456ghi789")
        assert "abc123def456ghi789" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_redacts_bearer_token(self, app_with_redactor, caplog):
        with caplog.at_level(logging.WARNING):
            app_with_redactor.warning("Auth Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_redacts_oauth_access_token(self, app_with_redactor, caplog):
        with caplog.at_level(logging.INFO):
            app_with_redactor.info('Got response: {"access_token": "ya29.realtoken-xyz", "expires_in": 3600}')
        assert "ya29.realtoken-xyz" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_redacts_refresh_token(self, app_with_redactor, caplog):
        with caplog.at_level(logging.INFO):
            app_with_redactor.info('refresh_token=1//0gabcdef-secret-payload')
        assert "1//0gabcdef-secret-payload" not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_redacts_password_assignment(self, app_with_redactor, caplog):
        with caplog.at_level(logging.WARNING):
            app_with_redactor.warning("Connection failed: password=hunter2-real")
        assert "hunter2-real" not in caplog.text

    def test_redacts_anthropic_style_api_key(self, app_with_redactor, caplog):
        with caplog.at_level(logging.INFO):
            app_with_redactor.info("Using key sk-ant-api03-realsecretvalue1234567890abcdef")
        assert "realsecretvalue1234567890abcdef" not in caplog.text

    def test_redacts_github_pat(self, app_with_redactor, caplog):
        with caplog.at_level(logging.INFO):
            app_with_redactor.info("token=ghp_abcdef0123456789abcdef0123456789abcd")
        assert "ghp_abcdef0123456789abcdef0123456789abcd" not in caplog.text

    def test_does_not_corrupt_clean_messages(self, app_with_redactor, caplog):
        """Une ligne sans secret doit passer inchangée."""
        with caplog.at_level(logging.INFO):
            app_with_redactor.info("User u-42 connected to room=lobby with 3 friends")
        assert "User u-42 connected to room=lobby with 3 friends" in caplog.text

    def test_redacts_email_body_fields(self, app_with_redactor, caplog):
        """Les champs de contenu email connus ne doivent jamais sortir en clair."""
        raw_body = "Bonjour Alice, le contrat secret ACME est prêt pour demain"
        with caplog.at_level(logging.INFO):
            app_with_redactor.info('Provider payload: {"body_text": "%s"}', raw_body)
        assert raw_body not in caplog.text
        assert "[EMAIL_CONTENT_REDACTED]" in caplog.text

    def test_redacts_inline_email_snippet_fields(self, app_with_redactor, caplog):
        raw_snippet = "Voici un extrait sensible assez long pour être masqué"
        with caplog.at_level(logging.INFO):
            app_with_redactor.info("Persisted snippet=%s", raw_snippet)
        assert raw_snippet not in caplog.text
        assert "snippet=[EMAIL_CONTENT_REDACTED]" in caplog.text

    def test_factory_idempotent_across_create_app_calls(self):
        """create_app() appelé N fois ne doit pas empiler N factories — sinon
        la chaîne de regex est appliquée N fois, perf dégrade linéairement."""
        from app.api.app import create_app
        for _ in range(3):
            create_app()
        # The flag _agentys_redactor_installed must be True after first call,
        # and the factory must still be our wrapper (not stacked).
        assert getattr(logging, "_agentys_redactor_installed", False) is True
        factory = logging.getLogRecordFactory()
        # Walking the closure chain: if the factory is wrapped 3 times,
        # the underlying name should still be _agentys_redacting_factory once.
        assert factory.__name__ == "_agentys_redacting_factory"


class TestMagicLinkLeakRegression:
    """Regression : auth.py:430 ne doit plus logger le magic_url en clair."""

    def test_request_login_logs_only_token_id(self, monkeypatch, caplog):
        # Mode dev pour exercer la branche de log
        monkeypatch.setenv("FLASK_ENV", "development")
        # Disable real email send
        from app.api import auth as auth_module
        monkeypatch.setattr(auth_module, "_send_magic_link_email", lambda *a, **kw: True)
        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

        from app.api.app import create_app
        app = create_app()
        client = app.test_client()

        with caplog.at_level(logging.INFO):
            resp = client.post("/api/auth/request-magic-link", json={"email": "alice@test.local"})

        assert resp.status_code == 200
        # The magic_url contains "?token=<full-token>". After fix, the log
        # must contain neither the URL nor the full token. Only token_id=8chars
        # is allowed.
        all_log_text = caplog.text
        assert "?token=" not in all_log_text, (
            f"MAGIC LINK LEAK: full ?token= appeared in logs.\n{all_log_text}"
        )
        # Sanity check: we DID emit the redacted info line
        assert "Magic link issued" in all_log_text
        # CASA V7.1 (#210): email PII is masked at LogRecord time —
        # `alice@test.local` → `a***@test.local`. The full local-part must NOT
        # appear; the masked prefix + domain MUST appear (so log-based triage
        # by domain still works).
        assert "alice@test.local" not in all_log_text, (
            f"PII LEAK: full email local-part appeared unmasked.\n{all_log_text}"
        )
        assert "a***@test.local" in all_log_text, (
            f"REDACTOR REGRESSION: masked email shape missing.\n{all_log_text}"
        )

    def test_dev_guard_is_fail_closed(self, monkeypatch, caplog):
        """Sans FLASK_ENV explicit (= prod-like), aucun log dev ne doit fuir."""
        monkeypatch.delenv("FLASK_ENV", raising=False)  # neither prod nor dev
        from app.api import auth as auth_module
        monkeypatch.setattr(auth_module, "_send_magic_link_email", lambda *a, **kw: True)
        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

        from app.api.app import create_app
        app = create_app()
        client = app.test_client()

        with caplog.at_level(logging.INFO):
            resp = client.post("/api/auth/request-magic-link", json={"email": "bob@test.local"})

        assert resp.status_code == 200
        # No "Magic link issued" line should appear when FLASK_ENV is unset.
        # (The auth log is gated on FLASK_ENV == "development".)
        assert "Magic link issued" not in caplog.text, (
            f"FAIL-CLOSED REGRESSION: dev log fired without explicit FLASK_ENV=development\n{caplog.text}"
        )
