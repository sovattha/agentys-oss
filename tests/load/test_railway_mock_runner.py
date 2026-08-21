from types import SimpleNamespace

import pytest

from scripts.load_test_railway_mock import (
    Counters,
    classify_stage,
    initial_user_delay,
    next_poll_interval_seconds,
    parse_provider_mix,
    percentile,
    validate_live_service_guard,
)


def test_percentile_uses_nearest_rank():
    assert percentile([10, 20, 30, 40], 95) == 40
    assert percentile([10, 20, 30, 40], 50) == 20


def test_provider_mix_parses_weighted_operations():
    assert parse_provider_mix("detail:8,list:1,sent:1") == [
        ("detail", 8),
        ("list", 1),
        ("sent", 1),
    ]


def test_burst_shape_starts_users_without_period_spread(monkeypatch):
    monkeypatch.setattr("scripts.load_test_railway_mock.random.uniform", lambda start, end: end)

    assert initial_user_delay(
        user_index=999,
        stage_users=1000,
        period_seconds=60,
        traffic_shape="burst",
        burst_window_seconds=3,
    ) == 3


def test_steady_shape_spreads_users_over_period():
    assert initial_user_delay(
        user_index=500,
        stage_users=1000,
        period_seconds=60,
        traffic_shape="steady",
        burst_window_seconds=0,
    ) == 30


def test_poll_interval_backs_off_to_reduce_status_traffic():
    assert next_poll_interval_seconds(1, 1.0, 5.0) == 1.0
    assert next_poll_interval_seconds(2, 1.0, 5.0) == 1.5
    assert next_poll_interval_seconds(10, 1.0, 5.0) == 5.0


def test_classify_draft_stage_degrades_on_ready_latency():
    status, reason = classify_stage(
        scenario="draft-users",
        counters=Counters(attempts=10, accepted=10, completed=10),
        drain_completed=True,
        response_p95_ms=120,
        ready_p95_ms=45_000,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "degraded"
    assert "draft_ready_p95=45000ms" in reason


def test_classify_draft_stage_reports_backpressure_reasons():
    status, reason = classify_stage(
        scenario="draft-users",
        counters=Counters(
            attempts=100,
            accepted=95,
            completed=95,
            backpressure=5,
            backpressure_reasons={"redis_lock_timeout": 5},
        ),
        drain_completed=True,
        response_p95_ms=120,
        ready_p95_ms=500,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "degraded"
    assert "backpressure=5.00%" in reason
    assert "redis_lock_timeout" in reason


def test_classify_provider_stage_degrades_on_provider_backoff():
    status, reason = classify_stage(
        scenario="provider",
        counters=Counters(attempts=100, ok=95, backpressure=5, provider_backoff=5),
        drain_completed=True,
        response_p95_ms=180,
        ready_p95_ms=None,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "degraded"
    assert "provider_backoff=5.00%" in reason


def test_classify_full_flow_combines_draft_and_provider_signals():
    status, reason = classify_stage(
        scenario="full-flow",
        counters=Counters(
            attempts=100,
            accepted=25,
            completed=25,
            backpressure=5,
            provider_backoff=3,
        ),
        drain_completed=True,
        response_p95_ms=180,
        ready_p95_ms=45_000,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "degraded"
    assert "draft_ready_p95=45000ms" in reason
    assert "provider_backoff=3.00%" in reason


def test_live_service_mode_requires_explicit_acknowledgement():
    args = SimpleNamespace(
        llm_mode="live",
        provider_mode="mock",
        allow_live_services=False,
        max_live_users=25,
        allow_high_volume_live_services=False,
    )

    with pytest.raises(ValueError, match="--allow-live-services"):
        validate_live_service_guard(args, [1])


def test_live_service_mode_caps_user_count_by_default():
    args = SimpleNamespace(
        llm_mode="mock",
        provider_mode="live",
        allow_live_services=True,
        max_live_users=25,
        allow_high_volume_live_services=False,
    )

    with pytest.raises(ValueError, match="capped"):
        validate_live_service_guard(args, [50])


def test_classify_stage_crashes_on_server_errors():
    status, reason = classify_stage(
        scenario="provider",
        counters=Counters(attempts=100, ok=95, server_errors=5),
        drain_completed=True,
        response_p95_ms=180,
        ready_p95_ms=None,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "crashed"
    assert "server=5.00%" in reason


def test_classify_stage_crashes_on_unexpected_statuses():
    status, reason = classify_stage(
        scenario="provider",
        counters=Counters(attempts=100, ok=80, other_status={"404": 20}),
        drain_completed=True,
        response_p95_ms=180,
        ready_p95_ms=None,
        max_failure_rate=0.01,
        response_p95_degraded_ms=1000,
        draft_ready_p95_degraded_ms=30_000,
        provider_backoff_degraded_rate=0.01,
    )

    assert status == "crashed"
    assert "unexpected_status=20.00%" in reason
