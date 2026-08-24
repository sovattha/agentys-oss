# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Regression: the admin dashboard must list real connected accounts.

Bug: ``/api/admin/users`` and ``/api/admin/aggregate`` derived the user list
and ``total_users`` from ``data/known_users.json`` alone. That side-file ignores
``AGENTYS_DATA_DIR`` (unlike the DB), so on any environment where it was empty
or wiped — e.g. a container redeploy — the dashboard showed "no users" even
though the ``accounts`` table was full. The fix sources the user universe from
``accounts`` (canonical store), merged with known_users.json for metadata.

The fixture wires both DB stacks on temp SQLite, with known_users.json pointed
at an empty temp path, so these tests reproduce the "wiped registry" condition.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.api import admin as admin_module
from app.api.auth import user_id_from_email


def _seed_account(email: str, user_id: int | None) -> None:
    from app.db.database import get_db_session
    from app.db.models.account import Account

    with get_db_session() as session:
        session.add(Account(email=email, provider="gmail", user_id=user_id))


def _utc_naive(offset_days: int) -> datetime:
    """A naive-UTC datetime offset from now (matches the DateTime column)."""
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).replace(tzinfo=None)


def _seed_subscription(user_id: int, plan: str, status: str, *, period_offset_days: int | None = None) -> None:
    from app.db.database import get_db_session
    from app.db.models import BillingSubscription

    with get_db_session() as session:
        session.add(
            BillingSubscription(
                user_id=user_id,
                plan=plan,
                status=status,
                stripe_subscription_id=f"sub_{user_id}_{status}",
                stripe_customer_id=f"cus_{user_id}",
                current_period_end=None if period_offset_days is None else _utc_naive(period_offset_days),
            )
        )


def _write_known_users(entries: list[dict]) -> None:
    with open(admin_module._known_users_file_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f)


def test_registry_lists_accounts_when_known_users_empty(admin_client):
    """The core regression: empty registry + populated accounts → users appear."""
    _seed_account("alice@example.com", user_id_from_email("alice@example.com"))
    _seed_account("bob@example.com", user_id_from_email("bob@example.com"))

    registry = admin_module._dashboard_user_registry()
    emails = {u["email"] for u in registry}

    assert emails == {"alice@example.com", "bob@example.com"}


def test_registry_merges_known_users_metadata(admin_client):
    """registered_at / last_seen from known_users.json survive the merge."""
    _write_known_users([
        {
            "email": "alice@example.com",
            "registered_at": "2026-01-01T00:00:00+00:00",
            "last_seen": "2026-02-01T00:00:00+00:00",
        }
    ])
    _seed_account("alice@example.com", user_id_from_email("alice@example.com"))

    registry = {u["email"]: u for u in admin_module._dashboard_user_registry()}

    assert registry["alice@example.com"]["registered_at"] == "2026-01-01T00:00:00+00:00"
    assert registry["alice@example.com"]["last_seen"] == "2026-02-01T00:00:00+00:00"


def test_multi_account_user_collapses_to_one_entry(admin_client):
    """Two accounts owned by the same JWT user_id → a single dashboard row."""
    uid = user_id_from_email("alice@example.com")
    _seed_account("alice@example.com", uid)
    _seed_account("alice.work@example.com", uid)

    registry = admin_module._dashboard_user_registry()
    emails = [u["email"] for u in registry]

    assert len(registry) == 1
    assert emails == ["alice@example.com"]


def test_null_user_id_accounts_listed_individually(admin_client):
    """Legacy/Tauri desktop accounts (user_id NULL) still surface as users."""
    _seed_account("desktop@example.com", None)

    emails = {u["email"] for u in admin_module._dashboard_user_registry()}

    assert "desktop@example.com" in emails


def test_fallback_to_known_users_without_accounts(admin_client):
    """No accounts reachable → behaviour falls back to known_users.json."""
    _write_known_users([
        {"email": "legacy@example.com", "registered_at": "2026-01-01T00:00:00+00:00"}
    ])

    registry = admin_module._dashboard_user_registry()

    assert [u["email"] for u in registry] == ["legacy@example.com"]


def test_fetch_user_metrics_includes_accounts_with_full_shape(admin_client):
    """_fetch_user_metrics surfaces account-derived users with the CSV/UI shape."""
    _seed_account("alice@example.com", user_id_from_email("alice@example.com"))

    start_iso, end_iso = admin_module._get_period_range("30d")
    users = admin_module._fetch_user_metrics(start_iso, end_iso)

    by_email = {u["email"]: u for u in users}
    assert "alice@example.com" in by_email

    expected_keys = {
        "email", "registered_at", "last_active", "active_days", "total_actions",
        "compose_ai", "emails_sent", "cost_usd", "revenue_usd", "margin_usd",
        "churn_risk", "sparkline",
    }
    assert expected_keys <= set(by_email["alice@example.com"].keys())


def test_search_filters_account_users(admin_client):
    _seed_account("alice@example.com", user_id_from_email("alice@example.com"))
    _seed_account("bob@example.com", user_id_from_email("bob@example.com"))

    start_iso, end_iso = admin_module._get_period_range("30d")
    users = admin_module._fetch_user_metrics(start_iso, end_iso, search="alice")

    assert [u["email"] for u in users] == ["alice@example.com"]


# ─── Tier (free / paid) segmentation ─────────────────────────────────────────

def test_classify_tier_rules():
    """_classify_tier is a pure function — paid == entitled active/trialing."""
    future = datetime.now(timezone.utc) + timedelta(days=5)
    past = datetime.now(timezone.utc) - timedelta(days=5)

    assert admin_module._classify_tier("professional", "active", future)["tier"] == "paid"
    assert admin_module._classify_tier("starter", "trialing", future)["tier"] == "paid"
    assert admin_module._classify_tier("professional", "active", None)["tier"] == "paid"  # no end = active
    assert admin_module._classify_tier("professional", "active", past)["tier"] == "free"  # period expired
    assert admin_module._classify_tier("professional", "canceled", future)["tier"] == "free"
    assert admin_module._classify_tier("professional", "past_due", future)["tier"] == "free"
    assert admin_module._classify_tier("free", "active", None)["tier"] == "free"
    assert admin_module._classify_tier(None, None, None) == admin_module._FREE_TIER
    # plan alias normalization
    assert admin_module._classify_tier("pro", "active", None)["plan"] == "professional"


def test_fetch_user_metrics_tags_paid_and_free(admin_client):
    paid_uid = user_id_from_email("paid@example.com")
    free_uid = user_id_from_email("free@example.com")
    _seed_account("paid@example.com", paid_uid)
    _seed_account("free@example.com", free_uid)
    _seed_subscription(paid_uid, "professional", "active", period_offset_days=10)

    start_iso, end_iso = admin_module._get_period_range("30d")
    users = {u["email"]: u for u in admin_module._fetch_user_metrics(start_iso, end_iso)}

    assert users["paid@example.com"]["tier"] == "paid"
    assert users["paid@example.com"]["plan"] == "professional"
    assert users["paid@example.com"]["subscription_status"] == "active"
    assert users["free@example.com"]["tier"] == "free"
    assert users["free@example.com"]["plan"] == "free"
    assert users["free@example.com"]["subscription_status"] == "none"


def test_tier_filter_selects_one_segment(admin_client):
    paid_uid = user_id_from_email("paid@example.com")
    _seed_account("paid@example.com", paid_uid)
    _seed_account("free@example.com", user_id_from_email("free@example.com"))
    _seed_subscription(paid_uid, "starter", "trialing", period_offset_days=5)

    start_iso, end_iso = admin_module._get_period_range("30d")

    paid = admin_module._fetch_user_metrics(start_iso, end_iso, tier="paid")
    free = admin_module._fetch_user_metrics(start_iso, end_iso, tier="free")

    assert [u["email"] for u in paid] == ["paid@example.com"]
    assert [u["email"] for u in free] == ["free@example.com"]


def test_subscription_tier_map_counts(admin_client):
    paid_uid = user_id_from_email("paid@example.com")
    canceled_uid = user_id_from_email("canceled@example.com")
    _seed_account("paid@example.com", paid_uid)
    _seed_account("canceled@example.com", canceled_uid)
    _seed_account("free@example.com", user_id_from_email("free@example.com"))
    _seed_subscription(paid_uid, "professional", "active", period_offset_days=30)
    _seed_subscription(canceled_uid, "professional", "canceled", period_offset_days=30)

    registry = admin_module._dashboard_user_registry()
    tier_map = admin_module._subscription_tier_map()
    paid_users = sum(
        1 for u in registry
        if tier_map.get(u.get("user_id"), admin_module._FREE_TIER)["tier"] == "paid"
    )

    assert paid_users == 1
    assert len(registry) - paid_users == 2  # canceled + free both count as free
