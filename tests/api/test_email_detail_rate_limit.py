"""Regression tests for email detail provider-fetch backpressure."""

from __future__ import annotations

import inspect
import time
from contextlib import contextmanager
from unittest.mock import Mock

from flask import Flask
import pytest

from app.api import routes_emails


def test_provider_detail_busy_response_is_retryable() -> None:
    app = Flask(__name__)
    with app.app_context():
        response = routes_emails._provider_detail_busy_response()
        body = response.get_json()

    assert response.status_code == 429
    assert body["error"] == "rate_limited"
    assert body["code"] == "EMAIL_DETAIL_FETCH_BUSY"
    assert body["retry_after"] == routes_emails._PROVIDER_DETAIL_RETRY_AFTER_SECONDS
    assert response.headers["Retry-After"] == str(
        routes_emails._PROVIDER_DETAIL_RETRY_AFTER_SECONDS
    )


def test_provider_detail_quota_backoff_response_is_retryable() -> None:
    class FakeQuotaBackoff(Exception):
        retry_after = 17

    app = Flask(__name__)
    with app.app_context():
        response = routes_emails._provider_detail_quota_backoff_response(FakeQuotaBackoff())
        body = response.get_json()

    assert response.status_code == 429
    assert body["error"] == "rate_limited"
    assert body["code"] == "EMAIL_PROVIDER_BACKOFF"
    assert body["provider"] == "gmail"
    assert body["server_status"] == "ok"
    assert body["retry_after"] == 17
    assert response.headers["Retry-After"] == "17"


def test_gmail_quota_gate_can_fail_fast_for_user_facing_fetch() -> None:
    from app.providers.gmail_adapter import GmailQuotaBackoffError, _GmailQuotaCoordinator

    gate = _GmailQuotaCoordinator("acct-test")
    gate._next_allowed_at = time.monotonic() + 60

    started = time.monotonic()
    with pytest.raises(GmailQuotaBackoffError) as exc:
        gate.run("messages.get", lambda: None, max_wait_seconds=2)

    assert exc.value.retry_after >= 50
    assert time.monotonic() - started < 0.5


def test_gmail_quota_gate_extends_low_priority_cooldown(monkeypatch) -> None:
    from app.providers.gmail_adapter import _GmailQuotaCoordinator

    monkeypatch.setenv("GMAIL_LOW_PRIORITY_BACKOFF_SECONDS", "120")
    gate = _GmailQuotaCoordinator("acct-test")

    gate._record_rate_limit("messages.batch_get", [])

    assert gate.retry_after_seconds() <= 5
    assert 100 <= gate.low_priority_retry_after_seconds() <= 120


def test_provider_detail_fetch_ignores_unconfigured_mock_quota_limiter() -> None:
    provider = Mock()
    expected = object()
    provider.get_message_by_id.return_value = expected

    assert routes_emails._get_email_by_id_for_detail(provider, "msg-1") is expected
    assert not provider.limited_quota_wait.called


def test_provider_detail_fetch_uses_real_provider_quota_limiter() -> None:
    calls = []
    expected = object()

    class Provider:
        @contextmanager
        def limited_quota_wait(self, seconds):
            calls.append(seconds)
            yield

        def get_message_by_id(self, _email_id):
            return expected

    assert routes_emails._get_email_by_id_for_detail(Provider(), "msg-1") is expected
    assert calls == [routes_emails._PROVIDER_DETAIL_QUOTA_WAIT_SECONDS]


def test_provider_detail_fetch_propagates_quota_backoff() -> None:
    class FakeQuotaBackoff(Exception):
        code = "GMAIL_QUOTA_BACKOFF"
        retry_after = 12

    class Provider:
        def get_message_by_id(self, _email_id):
            raise FakeQuotaBackoff()

    with pytest.raises(FakeQuotaBackoff):
        routes_emails._get_email_by_id_for_detail(Provider(), "msg-1")


def test_provider_detail_fetch_default_concurrency_matches_metadata_only_mode() -> None:
    # Metadata-only detail views fetch bodies from the provider more often than
    # the old full-cache mode. Two slots caused normal email opening to return
    # hard 429s while earlier detail fetches were still running.
    assert routes_emails._PROVIDER_DETAIL_CONCURRENCY >= 4
    assert routes_emails._PROVIDER_DETAIL_WAIT_SECONDS <= 10


def test_get_email_does_not_release_detail_slot_before_acquire() -> None:
    source = inspect.getsource(routes_emails.get_email)

    assert "_provider_detail_slot_acquired = False" in source
    assert "_provider_detail_slot_acquired = True" in source
    assert "nonlocal _provider_detail_slot_acquired" in source
    assert "_release_provider_detail_slot()" in source


def test_get_email_uses_user_facing_provider_quota_deadline() -> None:
    source = inspect.getsource(routes_emails.get_email)

    assert "_get_email_by_id_for_detail(provider, raw_email_id)" in source
    assert "_provider_detail_quota_backoff_response" in source
