# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Q-15 — Cost enforcer (audit 2026-05-06).

Pre-fix: ``cost_manager.py`` had ``can_proceed()`` and ``enforce_budget``
but they were never invoked. The audit table called this out as the
"single biggest cost-defense gap".

Post-fix:
- ``app/infrastructure/cost_enforcer.py`` reads from the persistent
  ``token_usage_log`` table for both global monthly and per-user daily
  caps.
- ``CostGatedLLM`` wraps any LLMPort and runs ``check_or_raise`` before
  every call. Off by default; enable with COST_ENFORCEMENT_ENABLED=true.
- Container.llm_drafting (and the other categorized LLMs) auto-wrap
  with the gate when enforcement is on.

Pinned by this test:
1. Disabled by default — ``check_or_raise`` is a no-op.
2. Enabled + below cap — no exception.
3. Enabled + global cap exceeded — raises CostBudgetExceededError.
4. Enabled + user cap exceeded — raises with scope='user_daily'.
5. CostGatedLLM proxies the inner LLM's ``model`` and ``name``.
6. Container only wraps when the env is on.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _reset_cache():
    """Clear the 60s TTL cache so tests see fresh values."""
    import app.infrastructure.cost_enforcer as ce
    with ce._cache_lock:
        ce._cache_global = (0.0, 0.0)
        ce._cache_user.clear()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("COST_ENFORCEMENT_ENABLED", raising=False)
    from app.infrastructure.cost_enforcer import check_or_raise
    # Should be a no-op even with no DB available.
    check_or_raise(account_id=42)
    check_or_raise(account_id=None)


def test_enabled_below_cap_no_raise(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "1000")
    monkeypatch.setenv("USER_DAILY_CAP_USD", "5")
    _reset_cache()
    from app.infrastructure import cost_enforcer as ce
    with patch.object(ce, "_read_global_month_total_usd", return_value=42.0), \
         patch.object(ce, "_read_user_day_total_usd", return_value=1.50):
        ce.check_or_raise(account_id=7)


def test_enabled_global_cap_exceeded_raises(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "100")
    _reset_cache()
    import pytest
    from app.infrastructure import cost_enforcer as ce
    with patch.object(ce, "_read_global_month_total_usd", return_value=120.0):
        with pytest.raises(ce.CostBudgetExceededError) as exc:
            ce.check_or_raise(account_id=42)
    assert exc.value.scope == "global_monthly"
    assert exc.value.current_usd == 120.0
    assert exc.value.cap_usd == 100.0


def test_enabled_global_read_error_fails_closed(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "100")
    _reset_cache()
    import pytest
    from app.infrastructure import cost_enforcer as ce
    with patch.object(ce, "_read_global_month_total_usd", side_effect=RuntimeError("db down")):
        with pytest.raises(ce.CostBudgetExceededError) as exc:
            ce.check_or_raise(account_id=42)
    assert exc.value.scope == "global_monthly_unavailable"
    assert exc.value.account_id == 42


def test_enabled_user_cap_exceeded_raises(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "1000")
    monkeypatch.setenv("USER_DAILY_CAP_USD", "5")
    _reset_cache()
    import pytest
    from app.infrastructure import cost_enforcer as ce
    with patch.object(ce, "_read_global_month_total_usd", return_value=10.0), \
         patch.object(ce, "_read_user_day_total_usd", return_value=6.50):
        with pytest.raises(ce.CostBudgetExceededError) as exc:
            ce.check_or_raise(account_id=7)
    assert exc.value.scope == "user_daily"
    assert exc.value.account_id == 7


def test_disabled_does_not_query_db(monkeypatch):
    """When disabled, no DB reads happen — pure short-circuit."""
    monkeypatch.delenv("COST_ENFORCEMENT_ENABLED", raising=False)
    _reset_cache()
    from app.infrastructure import cost_enforcer as ce
    with patch.object(ce, "_read_global_month_total_usd",
                      side_effect=AssertionError("must not be called")):
        ce.check_or_raise(account_id=42)


def test_cost_gated_llm_proxies_model_and_name():
    from app.infrastructure.cost_enforcer import CostGatedLLM
    inner = MagicMock()
    inner.model = "claude-haiku-4-5-20251001"
    inner.name = "claude"
    gated = CostGatedLLM(inner)
    assert gated.model == "claude-haiku-4-5-20251001"
    assert gated.name == "claude"


def test_cost_gated_llm_calls_inner_complete(monkeypatch):
    """When enforcement is OFF the gate must NOT block — inner.complete fires."""
    monkeypatch.delenv("COST_ENFORCEMENT_ENABLED", raising=False)
    from app.infrastructure.cost_enforcer import CostGatedLLM
    inner = MagicMock()
    inner.complete.return_value = "draft"
    gated = CostGatedLLM(inner)
    assert gated.complete(system="x", user="y", max_tokens=10) == "draft"
    inner.complete.assert_called_once()


def test_cost_gated_llm_blocks_when_over_cap(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "10")
    _reset_cache()
    import pytest
    from app.infrastructure import cost_enforcer as ce
    inner = MagicMock()
    gated = ce.CostGatedLLM(inner)
    with patch.object(ce, "_read_global_month_total_usd", return_value=99.0):
        with pytest.raises(ce.CostBudgetExceededError):
            gated.complete(system="x", user="y", max_tokens=10)
    inner.complete.assert_not_called()


def test_cost_gated_llm_falls_back_to_usage_context_account(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "1000")
    monkeypatch.setenv("USER_DAILY_CAP_USD", "5")
    _reset_cache()
    import pytest
    from app.infrastructure import cost_enforcer as ce
    from app.infrastructure.cost_manager import reset_usage_context, set_usage_context

    inner = MagicMock()
    gated = ce.CostGatedLLM(inner)
    tokens = set_usage_context(account_id=7, user_id=99, feature="drafting")
    try:
        with patch.object(ce, "_read_global_month_total_usd", return_value=0.0), \
             patch.object(ce, "_read_user_day_total_usd", return_value=6.50) as read_user:
            with pytest.raises(ce.CostBudgetExceededError) as exc:
                gated.complete(system="x", user="y", max_tokens=10)
    finally:
        reset_usage_context(tokens)

    assert exc.value.scope == "user_daily"
    read_user.assert_called_once_with(7)
    inner.complete.assert_not_called()


def test_compose_stream_bg_sets_llm_attribution_for_cost_gate(monkeypatch):
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_MONTHLY_CAP_USD", "1000")
    monkeypatch.setenv("USER_DAILY_CAP_USD", "5")
    _reset_cache()
    from app.api import routes_misc
    from app.infrastructure import cost_enforcer as ce

    inner = MagicMock()
    gated = ce.CostGatedLLM(inner)
    emitted_errors: list[dict] = []

    def fake_emit_error(**kwargs):
        emitted_errors.append(kwargs)

    with patch.object(ce, "_read_global_month_total_usd", return_value=0.0), \
         patch.object(ce, "_read_user_day_total_usd", return_value=6.50) as read_user, \
         patch("app.api.websocket.emit_draft_error", side_effect=fake_emit_error), \
         patch("app.api.websocket.emit_draft_chunk"), \
         patch("app.api.websocket.emit_draft_complete"):
        routes_misc._compose_stream_bg(
            compose_id="compose-cost-gate",
            system_prompt="system",
            user_prompt="user",
            llm=gated,
            typical_signature=None,
            account_id=7,
        )

    read_user.assert_called_once_with(7)
    inner.stream.assert_not_called()
    assert emitted_errors


def test_container_wraps_when_env_on(monkeypatch):
    """Container.llm_drafting becomes CostGatedLLM when env is on."""
    monkeypatch.setenv("COST_ENFORCEMENT_ENABLED", "true")
    # Force fresh container so the lazy property re-resolves.
    import importlib
    import app.infrastructure.container as container_module
    container_module._container = None
    importlib.reload(container_module)
    from app.infrastructure.cost_enforcer import CostGatedLLM
    c = container_module.get_container()
    assert isinstance(c.llm_drafting, CostGatedLLM), (
        "Container.llm_drafting must be wrapped when enforcement is on"
    )


def test_container_does_not_wrap_when_env_off(monkeypatch):
    monkeypatch.delenv("COST_ENFORCEMENT_ENABLED", raising=False)
    import importlib
    import app.infrastructure.container as container_module
    container_module._container = None
    importlib.reload(container_module)
    from app.infrastructure.cost_enforcer import CostGatedLLM
    c = container_module.get_container()
    assert not isinstance(c.llm_drafting, CostGatedLLM), (
        "When enforcement is off, no wrapper — direct LLM port"
    )


def test_top_spenders_empty_state():
    """get_top_spenders_today must not raise even on a fresh DB."""
    from app.infrastructure.cost_enforcer import get_top_spenders_today
    out = get_top_spenders_today()
    # Empty list or list of dicts — both acceptable; must not raise.
    assert isinstance(out, list)
