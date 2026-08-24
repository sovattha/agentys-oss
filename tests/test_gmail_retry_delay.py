# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for Gmail 429 retry-delay extraction (N1 rate-limit honoring)."""
import threading
import time
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from app.providers.gmail_adapter import (
    GMAIL_MAX_HONORED_RETRY_DELAY,
    GmailAdapter,
    _GmailQuotaCoordinator,
    _extract_gmail_retry_delay,
    _parse_duration_seconds,
)


def _make_http_error(status: int, content: bytes | str | None, retry_after: str | None = None) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.get = MagicMock(return_value=retry_after)
    if isinstance(content, str):
        content = content.encode("utf-8")
    return HttpError(resp=resp, content=content or b"")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("30s", 30.0),
        ("1.5s", 1.5),
        ("0s", 0.0),
        ("5", None),  # missing 's' suffix → not a duration
        (45, 45.0),
        (45.5, 45.5),
        (None, None),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_duration_seconds(value, expected):
    assert _parse_duration_seconds(value) == expected


def test_extract_retry_delay_from_retryinfo_detail():
    body = (
        '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","details":'
        '[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"30s"}]}}'
    )
    err = _make_http_error(429, body)
    assert _extract_gmail_retry_delay(err) == 30.0


def test_extract_retry_delay_caps_at_max():
    body = (
        '{"error":{"code":429,"details":'
        '[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"3600s"}]}}'
    )
    err = _make_http_error(429, body)
    assert _extract_gmail_retry_delay(err) == GMAIL_MAX_HONORED_RETRY_DELAY


def test_extract_retry_delay_falls_back_to_header():
    err = _make_http_error(429, '{"error":{"code":429}}', retry_after="12")
    assert _extract_gmail_retry_delay(err) == 12.0


def test_extract_retry_delay_returns_none_when_no_signal():
    err = _make_http_error(429, '{"error":{"code":429,"message":"quota exceeded"}}')
    assert _extract_gmail_retry_delay(err) is None


def test_extract_retry_delay_handles_malformed_json():
    err = _make_http_error(429, "not-json{")
    assert _extract_gmail_retry_delay(err) is None


def test_extract_retry_delay_ignores_non_retryinfo_details():
    body = (
        '{"error":{"code":429,"details":'
        '[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"RATE_LIMIT_EXCEEDED"}]}}'
    )
    err = _make_http_error(429, body)
    assert _extract_gmail_retry_delay(err) is None


def test_extract_retry_delay_rejects_non_http_error():
    assert _extract_gmail_retry_delay(ValueError("boom")) is None  # type: ignore[arg-type]


def test_quota_coordinator_sleeps_before_next_call_after_429(monkeypatch):
    body = (
        '{"error":{"code":429,"details":'
        '[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"2s"}]}}'
    )
    err = _make_http_error(429, body)
    coordinator = _GmailQuotaCoordinator("quota-test")

    with pytest.raises(HttpError):
        coordinator.run("messages.list", lambda: (_ for _ in ()).throw(err))

    sleeps = []
    monkeypatch.setattr("app.providers.gmail_adapter.time.sleep", sleeps.append)

    assert coordinator.run("messages.list", lambda: "ok") == "ok"
    assert sleeps
    assert 0 < sleeps[0] <= 2.0


def test_quota_coordinator_does_not_serialize_all_network_calls():
    coordinator = _GmailQuotaCoordinator("parallel-quota-test")
    slow_started = threading.Event()
    release_slow = threading.Event()
    slow_result: list[str] = []

    def slow_call() -> str:
        slow_started.set()
        assert release_slow.wait(2), "slow call was not released"
        return "slow"

    worker = threading.Thread(
        target=lambda: slow_result.append(coordinator.run("messages.list.sent", slow_call)),
        daemon=True,
    )
    worker.start()
    assert slow_started.wait(1), "slow Gmail call did not start"

    start = time.perf_counter()
    assert coordinator.run("history.list", lambda: "fast") == "fast"
    elapsed = time.perf_counter() - start

    release_slow.set()
    worker.join(timeout=1)

    assert elapsed < 0.2
    assert slow_result == ["slow"]


def test_batch_fetch_defers_429_ids_instead_of_immediate_retry(monkeypatch):
    err = _make_http_error(429, '{"error":{"code":429}}')

    class FakeBatch:
        def __init__(self):
            self.callbacks = []

        def add(self, request, callback, request_id):
            self.callbacks.append((request_id, callback))

        def execute(self):
            for request_id, callback in self.callbacks:
                if request_id == "rate-limited":
                    callback(request_id, None, err)
                else:
                    callback(request_id, {"id": request_id}, None)

    adapter = GmailAdapter.__new__(GmailAdapter)
    adapter.account_id = "batch-quota-test"
    adapter.token_file = "token.json"
    adapter._quota = _GmailQuotaCoordinator("batch-quota-test")

    fake_batch = FakeBatch()
    service = MagicMock()
    service.new_batch_http_request.return_value = fake_batch
    adapter._service_storage = MagicMock()
    adapter._service_storage.service = service

    sleeps = []
    monkeypatch.setattr("app.providers.gmail_adapter.time.sleep", sleeps.append)

    result = adapter._batch_fetch_messages(["ok", "rate-limited"], format="metadata")

    assert result == [{"id": "ok"}]
    assert service.users().messages().get.call_count == 2
