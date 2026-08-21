# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests for the onboarding API endpoints."""

from unittest.mock import MagicMock, patch

import pytest

from app.api import onboarding as onboarding_api
from app.api.app import create_app
from app.billing.entitlements import BillingEntitlement, EntitlementRequiredError


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def allow_paid_onboarding(monkeypatch):
    """Keep legacy route tests focused unless they opt into billing denial."""
    monkeypatch.setattr(onboarding_api, "_assert_paid_onboarding", lambda _account_id: None)


def _deny_paid_onboarding(_account_id):
    entitlement = BillingEntitlement(
        plan="free",
        subscription_status="none",
        ai_enabled=False,
        reason="no_active_subscription",
        user_id=42,
    )
    raise EntitlementRequiredError(entitlement)


class TestOnboardingStartEndpoint:
    """Tests for POST /api/onboarding/start."""

    def test_start_requires_json_body(self, client):
        resp = client.post("/api/onboarding/start")
        assert resp.status_code == 400

    def test_start_requires_account_id(self, client):
        resp = client.post(
            "/api/onboarding/start",
            json={"user_email": "test@test.com"},
        )
        assert resp.status_code == 400
        assert "account_id" in resp.get_json()["error"]

    def test_start_requires_user_email(self, client):
        resp = client.post(
            "/api/onboarding/start",
            json={"account_id": 1},
        )
        assert resp.status_code == 400

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_start_success(self, mock_get_mgr, _mock_resolve, client):
        mock_mgr = MagicMock()
        mock_mgr.start.return_value = {
            "status": "started",
            "onboarding_id": 42,
            "account_id": 1,
        }
        mock_get_mgr.return_value = mock_mgr

        resp = client.post(
            "/api/onboarding/start",
            json={"account_id": 1, "user_email": "test@test.com"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "started"
        assert data["onboarding_id"] == 42

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_start_requires_paid_onboarding(self, mock_get_mgr, _mock_resolve, client, monkeypatch):
        monkeypatch.setattr(onboarding_api, "_assert_paid_onboarding", _deny_paid_onboarding)

        resp = client.post(
            "/api/onboarding/start",
            json={"account_id": 1, "user_email": "test@test.com"},
        )

        assert resp.status_code == 402
        data = resp.get_json()
        assert data["error_code"] == "BILLING_REQUIRED"
        assert data["billing"]["ai_enabled"] is False
        mock_get_mgr.assert_not_called()


class TestOnboardingRefreshEndpoint:
    """Tests for POST /api/onboarding/refresh."""

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_refresh_requires_paid_onboarding(self, mock_get_mgr, _mock_resolve, client, monkeypatch):
        monkeypatch.setattr(onboarding_api, "_assert_paid_onboarding", _deny_paid_onboarding)

        resp = client.post(
            "/api/onboarding/refresh",
            json={"account_id": 1, "user_email": "test@test.com"},
        )

        assert resp.status_code == 402
        assert resp.get_json()["error_code"] == "BILLING_REQUIRED"
        mock_get_mgr.assert_not_called()


class TestOnboardingStatusEndpoint:
    """Tests for GET /api/onboarding/status."""

    def test_status_requires_account_id(self, client):
        resp = client.get("/api/onboarding/status")
        assert resp.status_code == 400

    @patch("app.api.onboarding._resolve_db_account_id", return_value=999)
    @patch("app.api.onboarding._get_manager")
    def test_status_not_started(self, mock_get_mgr, _mock_resolve, client):
        # When the account exists but no onboarding row is present, the
        # endpoint now returns 200 {status: 'not_started'} instead of 404.
        # Rationale: the account IS the primary resource; its onboarding is
        # a derived state. 404 caused the frontend polling circuit-breaker
        # to treat "not started yet" as "account disappeared" (cf. commit
        # 02c4b197).
        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = None
        mock_get_mgr.return_value = mock_mgr

        resp = client.get("/api/onboarding/status?account_id=999")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "not_started"
        assert body["account_id"] == 999

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_status_found(self, mock_get_mgr, _mock_resolve, client):
        mock_mgr = MagicMock()
        mock_mgr.get_status.return_value = {
            "id": 1,
            "account_id": 1,
            "status": "completed",
            "emails_analysed": 100,
        }
        mock_get_mgr.return_value = mock_mgr

        resp = client.get("/api/onboarding/status?account_id=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "completed"

    @patch(
        "app.api.onboarding._resolve_db_account_id",
        side_effect=PermissionError("Account id=6 does not belong to bob@x.com"),
    )
    def test_status_permission_denied_returns_403_not_500(self, _mock_resolve, client):
        # Regression for the May 1 2026 incident: a `PermissionError` from
        # `_resolve_db_account_id` (cross-account enumeration attempt) used
        # to bubble into the generic `except Exception` branch and surface
        # as 500. The frontend polling treated 500 as transient and kept
        # hammering the endpoint, swamping devtools with red noise. Must
        # be 403 — the call is well-formed, the caller just doesn't own
        # the resource.
        resp = client.get("/api/onboarding/status?account_id=6")
        assert resp.status_code == 403, (
            f"PermissionError should map to 403, got {resp.status_code}: "
            f"{resp.get_json()}"
        )


class TestOnboardingInsightsEndpoint:
    """Tests for GET /api/onboarding/insights."""

    def test_insights_requires_account_id(self, client):
        resp = client.get("/api/onboarding/insights")
        assert resp.status_code == 400

    @patch("app.api.onboarding._resolve_db_account_id", return_value=999)
    @patch("app.api.onboarding._get_manager")
    def test_insights_not_found(self, mock_get_mgr, _mock_resolve, client):
        mock_mgr = MagicMock()
        mock_mgr.get_insights.return_value = None
        mock_get_mgr.return_value = mock_mgr

        resp = client.get("/api/onboarding/insights?account_id=999")
        assert resp.status_code == 404

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_insights_returns_data(self, mock_get_mgr, _mock_resolve, client):
        mock_mgr = MagicMock()
        mock_mgr.get_insights.return_value = {
            "id": 1,
            "status": "completed",
            "profile": {"user_name": "Sophie"},
            "knowledge": {"contacts": []},
            "rules": {"contact_rules": []},
        }
        mock_get_mgr.return_value = mock_mgr

        resp = client.get("/api/onboarding/insights?account_id=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profile"]["user_name"] == "Sophie"

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_insights_are_masked_for_free_users(self, mock_get_mgr, _mock_resolve, client, monkeypatch):
        monkeypatch.setattr(onboarding_api, "_assert_paid_onboarding", _deny_paid_onboarding)

        resp = client.get("/api/onboarding/insights?account_id=1")

        assert resp.status_code == 402
        assert resp.get_json()["error_code"] == "BILLING_REQUIRED"
        mock_get_mgr.assert_not_called()


class TestOnboardingFeedbackEndpoint:
    """Tests for POST /api/onboarding/feedback."""

    def test_feedback_requires_json(self, client):
        resp = client.post("/api/onboarding/feedback")
        assert resp.status_code == 400

    def test_feedback_requires_account_id(self, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={"approved": True},
        )
        assert resp.status_code == 400

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    def test_feedback_success(self, _mock_resolve, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={"account_id": 1, "approved": True, "corrections": {}},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "recorded"
        assert data["approved"] is True

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_feedback_requires_paid_onboarding(self, mock_get_mgr, _mock_resolve, client, monkeypatch):
        monkeypatch.setattr(onboarding_api, "_assert_paid_onboarding", _deny_paid_onboarding)

        resp = client.post(
            "/api/onboarding/feedback",
            json={"account_id": 1, "approved": True},
        )

        assert resp.status_code == 402
        assert resp.get_json()["error_code"] == "BILLING_REQUIRED"
        mock_get_mgr.assert_not_called()

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_feedback_persists_profile_profession(self, mock_get_mgr, _mock_resolve, client):
        mock_mgr = MagicMock()
        mock_mgr.confirm_profession.return_value = {
            "profession": "courtier immobilier",
            "profession_confirmed": True,
        }
        mock_get_mgr.return_value = mock_mgr

        resp = client.post(
            "/api/onboarding/feedback",
            json={
                "account_id": 1,
                "approved": True,
                "corrections": {"profile": {"profession": " courtier immobilier "}},
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profile"] == {
            "profession": "courtier immobilier",
            "profession_confirmed": True,
        }
        mock_mgr.confirm_profession.assert_called_once_with(1, "courtier immobilier")

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_feedback_rejects_empty_profession(self, mock_get_mgr, _mock_resolve, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={
                "account_id": 1,
                "approved": True,
                "corrections": {"profile": {"profession": "   "}},
            },
        )

        assert resp.status_code == 400
        assert "profession" in resp.get_json()["error"]
        mock_get_mgr.assert_not_called()

    @patch("app.api.onboarding._resolve_db_account_id", return_value=1)
    @patch("app.api.onboarding._get_manager")
    def test_feedback_rejects_too_long_profession(self, mock_get_mgr, _mock_resolve, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={
                "account_id": 1,
                "approved": True,
                "corrections": {"profile": {"profession": "x" * 121}},
            },
        )

        assert resp.status_code == 400
        assert "120" in resp.get_json()["error"]
        mock_get_mgr.assert_not_called()

    @patch(
        "app.api.onboarding._resolve_db_account_id",
        side_effect=PermissionError("blocked"),
    )
    def test_feedback_ownership_error_remains_403(self, _mock_resolve, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={
                "account_id": 1,
                "approved": True,
                "corrections": {"profile": {"profession": "avocat"}},
            },
        )

        assert resp.status_code == 403

    @patch(
        "app.api.onboarding._resolve_db_account_id",
        side_effect=ValueError("missing"),
    )
    def test_feedback_missing_account_remains_404(self, _mock_resolve, client):
        resp = client.post(
            "/api/onboarding/feedback",
            json={
                "account_id": 1,
                "approved": True,
                "corrections": {"profile": {"profession": "avocat"}},
            },
        )

        assert resp.status_code == 404
