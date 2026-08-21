# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Stripe checkout price selection — annual-checkout regression (2026-06-23).

Reported bug: "Le paiement annuel ne fonctionne pas" — with the Annual toggle
selected, clicking upgrade showed "Impossible d'ouvrir le paiement Stripe".

The entire checkout path is interval-agnostic EXCEPT ``_select_price_id``: a
missing ``STRIPE_PRICE_<PLAN>_YEARLY`` env var raises ``BillingConfigError`` →
``POST /api/billing/checkout`` returns ``503 BILLING_NOT_CONFIGURED`` → the FE
renders that banner. Monthly keeps working because its price var is set, which is
exactly why the failure looks "annual-only".

These tests pin the env-var contract so the (deployment-config) root cause is
unambiguous and documented in code, and guard the legacy-alias behaviour.
"""
from __future__ import annotations

import pytest

from app.api.billing import (
    BillingConfigError,
    _normalize_interval,
    _select_price_id,
)


_PRICE_ENV_VARS = (
    "STRIPE_PRICE_STARTER_MONTHLY",
    "STRIPE_PRICE_STARTER_YEARLY",
    "STRIPE_PRICE_PROFESSIONAL_MONTHLY",
    "STRIPE_PRICE_PROFESSIONAL_YEARLY",
    "STRIPE_PRICE_PRO_MONTHLY",
    "STRIPE_PRICE_PRO_YEARLY",
)


@pytest.fixture(autouse=True)
def _clear_price_env(monkeypatch):
    """Start every test from a clean slate so prior env/config can't leak in."""
    for var in _PRICE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("value", ["yearly", "annual", "annually", "year", "YEARLY", "Annual"])
def test_normalize_interval_accepts_annual_synonyms(value):
    assert _normalize_interval(value) == "yearly"


def test_yearly_price_resolved_when_env_set(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_PROFESSIONAL_YEARLY", "price_pro_year")
    assert _select_price_id("professional", "yearly") == "price_pro_year"


def test_yearly_missing_is_the_reported_bug(monkeypatch):
    """Monthly configured + yearly missing == "le paiement annuel ne marche pas"."""
    # Monthly IS configured → monthly checkout works.
    monkeypatch.setenv("STRIPE_PRICE_PROFESSIONAL_MONTHLY", "price_pro_month")
    assert _select_price_id("professional", "monthly") == "price_pro_month"
    # Yearly is NOT configured → the exact symptom the user reported.
    with pytest.raises(BillingConfigError) as exc:
        _select_price_id("professional", "yearly")
    assert "STRIPE_PRICE_PROFESSIONAL_YEARLY" in str(exc.value)


def test_professional_yearly_falls_back_to_legacy_pro_alias(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_legacy_pro_year")
    assert _select_price_id("professional", "yearly") == "price_legacy_pro_year"


def test_starter_yearly_has_no_legacy_alias(monkeypatch):
    """Gotcha: the legacy PRO alias does NOT cover starter — starter yearly
    REQUIRES its own STRIPE_PRICE_STARTER_YEARLY."""
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEARLY", "price_legacy_pro_year")
    with pytest.raises(BillingConfigError) as exc:
        _select_price_id("starter", "yearly")
    assert "STRIPE_PRICE_STARTER_YEARLY" in str(exc.value)


def test_starter_yearly_resolved_when_env_set(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_STARTER_YEARLY", "price_starter_year")
    assert _select_price_id("starter", "yearly") == "price_starter_year"
