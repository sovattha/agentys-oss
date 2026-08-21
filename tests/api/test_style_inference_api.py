# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour POST /api/style/reanalyze (issue #187 / S5)."""

from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import pytest
from flask import Flask

from app.api.style_inference import style_inference_bp


@dataclass
class FakeSentEmail:
    body_text: str
    subject: str = ""
    body_html: Optional[str] = None


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(style_inference_bp, url_prefix="/api/style")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _mock_account_resolution():
    """Par défaut, la résolution d'account depuis la session auth renvoie 1.
    Les tests qui veulent tester le 403 (no-account) peuvent override via patch."""
    with patch(
        "app.api.routes_helpers._resolve_account_id_for_user", return_value=1
    ):
        yield


class TestReanalyzeEndpoint:
    @patch("app.api.style_inference._get_sent_emails")
    def test_returns_400_when_too_few_emails(self, mock_get_sent, client):
        mock_get_sent.return_value = [FakeSentEmail(body_text="hi") for _ in range(5)]
        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 400
        data = response.get_json()
        assert "email" in (data.get("error") or "").lower()

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_returns_200_with_metrics_on_success(
        self, mock_get_sent, mock_persist, client
    ):
        """Happy path: 30+ emails → retour 200 avec métriques et exemples."""
        emails = [
            FakeSentEmail(
                body_text=(
                    "Bonjour Alice,\n\n"
                    "Je vous prie de trouver ci-joint le document. "
                    "Cordialement."
                ),
                subject=f"Sujet formel #{i}",
            )
            for i in range(30)
        ]
        mock_get_sent.return_value = emails

        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "completed"
        assert data["email_count"] == 30
        assert "metrics" in data
        assert "examples_count" in data
        assert data["examples_count"] >= 1

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_metrics_include_expected_fields(
        self, mock_get_sent, mock_persist, client
    ):
        emails = [
            FakeSentEmail(
                body_text="Phrase courte. Autre phrase. Troisième phrase." * 5,
                subject=f"sujet {i}",
            )
            for i in range(30)
        ]
        mock_get_sent.return_value = emails

        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 200
        data = response.get_json()
        metrics = data["metrics"]
        for key in (
            "avg_sentence_length",
            "formality_score",
            "emoji_rate",
            "vocabulary_density",
        ):
            assert key in metrics

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_persist_profile_called_on_success(
        self, mock_get_sent, mock_persist, client
    ):
        emails = [
            FakeSentEmail(body_text="Bonjour, merci. Cordialement." * 3, subject="x")
            for _ in range(30)
        ]
        mock_get_sent.return_value = emails

        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 200
        assert mock_persist.called
        call_args = mock_persist.call_args
        # Premier arg : account_id — doit être celui résolu depuis la session auth (fixture)
        assert call_args[0][0] == 1
        # Deuxième arg : profile enrichi (WritingStyleProfile instance)
        profile_arg = call_args[0][1]
        if isinstance(profile_arg, dict):
            assert "formality_score" in profile_arg
            assert "reference_examples" in profile_arg
        else:
            assert hasattr(profile_arg, "formality_score")
            assert hasattr(profile_arg, "reference_examples")


class TestReanalyzeSecurityF1F7:
    """Tests de sécurité (issue #187 review findings F1+F7)."""

    def test_returns_403_when_session_has_no_account(self, client):
        """Session sans compte associé → 403, aucune donnée exposée."""
        with patch(
            "app.api.routes_helpers._resolve_account_id_for_user", return_value=-1
        ):
            response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 403
        data = response.get_json()
        assert "account" in (data.get("error") or "").lower()

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_ignores_account_id_in_body_uses_session_account(
        self, mock_get_sent, mock_persist, client
    ):
        """Si le client injecte un account_id dans le body, il doit être
        IGNORÉ — seul l'account résolu depuis la session auth est utilisé.
        Prévient le cross-account data leak (F1+F7)."""
        mock_get_sent.return_value = [
            FakeSentEmail(body_text="Cordialement.", subject="x") for _ in range(30)
        ]
        # Le client tente d'accéder à l'account 999 (victime), mais la session
        # authentifiée résout à 1 (autouse fixture).
        response = client.post(
            "/api/style/reanalyze", json={"account_id": 999}
        )
        assert response.status_code == 200
        # _get_sent_emails doit avoir été appelé avec 1 (session), PAS 999 (body)
        call_args = mock_get_sent.call_args
        called_account_id = call_args[0][0] if call_args[0] else call_args[1]["account_id"]
        assert called_account_id == 1, (
            f"SECURITY: endpoint used body-supplied account_id "
            f"{called_account_id} instead of session-resolved 1"
        )


class TestReanalyzeLimitValidationF3:
    """Tests sur la validation de `limit` (issue #187 review finding F3)."""

    def test_returns_400_when_limit_not_integer(self, client):
        response = client.post("/api/style/reanalyze", json={"limit": "abc"})
        assert response.status_code == 400
        data = response.get_json()
        assert "limit" in (data.get("error") or "").lower()

    def test_returns_400_when_limit_is_list(self, client):
        response = client.post("/api/style/reanalyze", json={"limit": [1, 2, 3]})
        assert response.status_code == 400

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_limit_capped_at_default_max(self, mock_get_sent, mock_persist, client):
        """Un limit énorme (attaque DoS) est plafonné à DEFAULT_OUTBOX_LIMIT."""
        mock_get_sent.return_value = [
            FakeSentEmail(body_text="hi.") for _ in range(30)
        ]
        response = client.post(
            "/api/style/reanalyze", json={"limit": 999999}
        )
        assert response.status_code == 200
        call_args = mock_get_sent.call_args
        called_limit = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["limit"]
        assert called_limit <= 500, f"limit not capped: {called_limit}"


class TestReanalyzeErrorLeakageF2:
    """Tests que les exceptions internes ne fuient pas dans les responses (F2)."""

    @patch("app.api.style_inference._get_sent_emails")
    def test_fetch_outbox_exception_returns_generic_error(
        self, mock_get_sent, client
    ):
        mock_get_sent.side_effect = RuntimeError(
            "sensitive: postgresql://user:password@internal.host:5432/db"
        )
        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 500
        data = response.get_json()
        error = data.get("error") or ""
        # Le détail sensible ne doit PAS fuir
        assert "password" not in error
        assert "postgresql" not in error
        assert "internal.host" not in error
        # Le message doit rester générique
        assert "fetch outbox" in error.lower() or "failed" in error.lower()

    @patch("app.api.style_inference._persist_profile")
    @patch("app.api.style_inference._get_sent_emails")
    def test_persist_exception_returns_generic_error(
        self, mock_get_sent, mock_persist, client
    ):
        mock_get_sent.return_value = [
            FakeSentEmail(body_text="Cordialement.") for _ in range(30)
        ]
        mock_persist.side_effect = RuntimeError(
            "sensitive: S3 bucket 'internal-prod-bucket' access denied"
        )
        response = client.post("/api/style/reanalyze", json={})
        assert response.status_code == 500
        data = response.get_json()
        error = data.get("error") or ""
        assert "internal-prod-bucket" not in error
        assert "S3" not in error
