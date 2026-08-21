# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-13 — /api/admin/llm-stats and /api/admin/draft-feedback endpoints.

These endpoints back the "AI Operations" panel of the admin dashboard. The
tests exercise the real Flask route instead of inspecting source text, so they
catch missing auth gates and payload drift.
"""
from __future__ import annotations

pytest_plugins = ("tests.audit_fixes._admin_helpers",)


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "Nat"}


def test_ai_ops_endpoints_reject_anonymous(admin_client):
    client, _ = admin_client

    for path in ("/api/admin/llm-stats", "/api/admin/draft-feedback"):
        response = client.get(path)
        assert response.status_code in {401, 403}


def test_llm_stats_response_contract(admin_client):
    from app.db.database import get_db_session
    from app.db.models.token_usage_log import TokenUsageLogRow

    client, _ = admin_client
    with get_db_session() as session:
        session.add(
            TokenUsageLogRow(
                account_id=42,
                user_id=7,
                agent="DrafterAgent",
                feature="drafting",
                model="claude-haiku-4-5-20251001",
                input_tokens=1000,
                output_tokens=500,
                cache_creation_input_tokens=100,
                cache_read_input_tokens=200,
                cost_usd=0.0123,
            )
        )

    response = client.get("/api/admin/llm-stats?days=7", headers=_admin_headers())

    assert response.status_code == 200
    payload = response.get_json()
    for key in (
        "cache",
        "critic_skip",
        "latency",
        "token_writer",
        "cost_by_agent",
        "cost_by_user",
        "active_accounts",
        "active_users",
        "mau",
        "total_spend_usd",
        "total_tokens",
        "token_calls",
        "cost_per_mau",
        "window_days",
    ):
        assert key in payload
    assert payload["cost_by_agent"]["DrafterAgent"] == 0.0123
    assert payload["cost_by_user"] == [
        {
            "user_id": 7,
            "account_count": 1,
            "cost_usd": 0.0123,
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 200,
            "total_tokens": 1800,
            "calls": 1,
        }
    ]
    assert payload["active_accounts"] == 1
    assert payload["active_users"] == 1
    assert payload["mau"] == 1
    assert payload["total_spend_usd"] == 0.0123
    assert payload["total_tokens"] == 1800
    assert payload["token_calls"] == 1
    assert payload["cost_per_mau"] == 0.0123


def test_draft_feedback_endpoint_aggregates(admin_client):
    from app.db.database import get_db_session
    from app.db.models.account import Account
    from app.db.models.draft_feedback import DraftFeedbackRecord

    client, _ = admin_client
    with get_db_session() as session:
        account = Account(email="nat@example.com", provider="gmail")
        session.add(account)
        session.flush()
        session.add_all(
            [
                DraftFeedbackRecord(
                    account_id=account.id,
                    draft_id="draft-accept",
                    action="accept",
                ),
                DraftFeedbackRecord(
                    account_id=account.id,
                    draft_id="draft-edit",
                    action="edit",
                    edit_distance=0.42,
                ),
                DraftFeedbackRecord(
                    account_id=account.id,
                    draft_id="draft-reject",
                    action="reject",
                ),
            ]
        )

    response = client.get("/api/admin/draft-feedback", headers=_admin_headers())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["counts"] == {"accept": 1, "edit": 1, "reject": 1}
    assert payload["total"] == 3
    assert payload["rates"] == {"accept": 0.3333, "edit": 0.3333, "reject": 0.3333}
    assert payload["avg_edit_distance"] == 0.42
    assert payload["top_rejecters_30d"] == [
        {"account_id": account.id, "rejects": 1}
    ]
