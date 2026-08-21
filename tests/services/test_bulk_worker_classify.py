# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""L1 unit tests for `_classify_provider_error`.

The bulk worker decides retry / skip / fail / penalize purely from the
exception it catches — getting this classification wrong means we
either burn through items uselessly (treating 401 as transient) or
silently drop legit work (treating a real failure as 404-skipped). So
this is the linchpin and deserves exhaustive coverage.

Pure function, no DB, no threads.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.interfaces.email_provider import InsufficientScopeError
from app.services.bulk_jobs.worker import (
    DEFAULT_RETRY_AFTER_S,
    _classify_provider_error,
)


def _http_error(
    status: int,
    *,
    headers: dict[str, str] | None = None,
    message: str = "",
) -> Exception:
    """Build a duck-typed exception that mimics googleapiclient.HttpError."""
    resp = SimpleNamespace(status=status, headers=headers or {})
    err = RuntimeError(message or f"HTTP {status}")
    err.resp = resp  # type: ignore[attr-defined]
    return err


def _requests_http_error(
    status: int,
    *,
    headers: dict[str, str] | None = None,
    message: str = "",
) -> Exception:
    """Build a duck-typed exception that mimics requests.HTTPError."""
    response = SimpleNamespace(status_code=status, headers=headers or {})
    err = RuntimeError(message or f"HTTP {status}")
    err.response = response  # type: ignore[attr-defined]
    return err


# ── 4xx that should be SKIPPED ────────────────────────────────────────
def test_404_is_skipped() -> None:
    outcome = _classify_provider_error(_http_error(404))
    assert outcome.skipped_reason and "404" in outcome.skipped_reason
    assert outcome.succeeded is False
    assert outcome.rate_limited_seconds is None


def test_410_is_skipped() -> None:
    outcome = _classify_provider_error(_http_error(410))
    assert outcome.skipped_reason


def test_message_no_such_message_is_skipped() -> None:
    outcome = _classify_provider_error(RuntimeError("No such message"))
    assert outcome.skipped_reason


# ── 401 / 403 = FATAL auth ─────────────────────────────────────────────
def test_401_is_fatal_auth() -> None:
    outcome = _classify_provider_error(_http_error(401))
    assert outcome.auth_failed is True
    assert outcome.transient is False


def test_403_is_fatal_auth() -> None:
    outcome = _classify_provider_error(_http_error(403))
    assert outcome.auth_failed is True


def test_invalid_grant_message_is_fatal_auth() -> None:
    outcome = _classify_provider_error(
        RuntimeError("Token error: invalid_grant")
    )
    assert outcome.auth_failed is True


# ── 429 / 503 = rate limit, honor Retry-After ──────────────────────────
def test_429_with_retry_after_is_rate_limited() -> None:
    outcome = _classify_provider_error(
        _http_error(429, headers={"Retry-After": "12"})
    )
    assert outcome.rate_limited_seconds == 12.0
    assert outcome.succeeded is False


def test_429_without_retry_after_uses_default() -> None:
    outcome = _classify_provider_error(_http_error(429))
    assert outcome.rate_limited_seconds == DEFAULT_RETRY_AFTER_S


def test_503_is_rate_limited() -> None:
    outcome = _classify_provider_error(_http_error(503, headers={"Retry-After": "5"}))
    assert outcome.rate_limited_seconds == 5.0


def test_message_quota_exceeded_is_rate_limited() -> None:
    outcome = _classify_provider_error(RuntimeError("quota exceeded for user"))
    assert outcome.rate_limited_seconds == DEFAULT_RETRY_AFTER_S


# ── Scope OAuth manquant = FATAL, mais PAS auth_failed ─────────────────
# (audit 2026-06-09 : messages.delete sans le scope complet provoquait une
# tempête de retries — reconnecter le compte ne change pas les scopes
# demandés, donc auth_failed/« reconnecter » serait un mauvais CTA)
def test_insufficient_scope_is_fatal_not_auth() -> None:
    outcome = _classify_provider_error(
        InsufficientScopeError(
            "messages.delete needs full scope",
            required_scope="https://mail.google.com/",
        )
    )
    assert outcome.succeeded is False
    assert outcome.transient is False
    assert outcome.auth_failed is False
    assert "insufficient OAuth scope" in (outcome.error or "")


# ── 5xx (non-503) = transient → retry ──────────────────────────────────
def test_500_is_transient() -> None:
    outcome = _classify_provider_error(_http_error(500))
    assert outcome.succeeded is False
    assert outcome.transient is True
    assert outcome.skipped_reason is None
    assert outcome.auth_failed is False


# ── requests.HTTPError shape (Microsoft Graph path) ────────────────────
def test_requests_style_404_is_skipped() -> None:
    outcome = _classify_provider_error(_requests_http_error(404))
    assert outcome.skipped_reason


def test_requests_style_429_with_retry_after() -> None:
    outcome = _classify_provider_error(
        _requests_http_error(429, headers={"retry-after": "8"})
    )
    assert outcome.rate_limited_seconds == 8.0


# ── No HTTP shape, plain exception → transient ─────────────────────────
def test_unrecognized_exception_is_transient() -> None:
    outcome = _classify_provider_error(RuntimeError("network goblin"))
    assert outcome.succeeded is False
    assert outcome.transient is True
    assert outcome.auth_failed is False
    assert outcome.skipped_reason is None


def test_malformed_retry_after_falls_back_to_default() -> None:
    outcome = _classify_provider_error(
        _http_error(429, headers={"Retry-After": "abc"})
    )
    assert outcome.rate_limited_seconds == DEFAULT_RETRY_AFTER_S
