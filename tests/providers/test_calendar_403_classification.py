# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit 2026-05-27: a calendar event MOVE (drag-drop) on a meeting the user
did not organize returns Google `403 forbiddenForNonOrganizer`. The provider
used to map ANY 403 on a write op to `CalendarScopeError` → the UI showed the
misleading `missing_calendar_scope` (suggesting a re-auth that does nothing,
since the token already has full calendar write scope).

These tests pin the fix: only genuinely scope-related 403 reasons map to
`CalendarScopeError`; every other 403 (non-organizer, read-only calendar)
maps to the new `CalendarEventPermissionError`.
"""
from __future__ import annotations

import json

import pytest

from app.interfaces import calendar_provider as cp
from app.providers import gmail_calendar as gc


class _FakeResp:
    def __init__(self, status: int):
        self.status = status


class _FakeHttpError(Exception):
    """Minimal stand-in for googleapiclient.errors.HttpError."""

    def __init__(self, status: int, content):
        super().__init__(f"HTTP {status}")
        self.resp = _FakeResp(status)
        self.content = content.encode("utf-8") if isinstance(content, str) else content


def _err(reason: str) -> _FakeHttpError:
    return _FakeHttpError(403, json.dumps({"error": {"code": 403, "errors": [{"reason": reason}]}}))


def test_extract_403_reason_parses_google_error():
    assert gc._extract_403_reason(_err("forbiddenForNonOrganizer")) == "forbiddenForNonOrganizer"
    assert gc._extract_403_reason(_err("insufficientPermissions")) == "insufficientPermissions"


def test_extract_403_reason_empty_on_garbage():
    assert gc._extract_403_reason(_FakeHttpError(403, b"not json")) == ""
    assert gc._extract_403_reason(_FakeHttpError(403, b"")) == ""


def test_scope_reasons_classified_as_scope():
    assert gc._is_scope_403_reason("insufficientPermissions") is True
    assert gc._is_scope_403_reason("ACCESS_TOKEN_SCOPE_INSUFFICIENT") is True
    # Case-insensitive.
    assert gc._is_scope_403_reason("insufficientpermissions") is True


def test_non_scope_reasons_not_classified_as_scope():
    assert gc._is_scope_403_reason("forbiddenForNonOrganizer") is False
    assert gc._is_scope_403_reason("forbidden") is False
    assert gc._is_scope_403_reason("") is False


def test_raise_for_write_403_scope_reason_raises_scope_error():
    with pytest.raises(cp.CalendarScopeError):
        gc._raise_for_calendar_write_403(_err("insufficientPermissions"), "acct-1")


def test_raise_for_write_403_non_organizer_raises_permission_error():
    with pytest.raises(cp.CalendarEventPermissionError) as ei:
        gc._raise_for_calendar_write_403(_err("forbiddenForNonOrganizer"), "acct-1")
    assert ei.value.reason == "forbiddenForNonOrganizer"


def test_raise_for_write_403_unknown_reason_defaults_to_permission_error():
    # An ambiguous/unknown 403 on a write op is treated as a permission issue
    # (the token usually has scope) — never a silent re-auth prompt.
    with pytest.raises(cp.CalendarEventPermissionError):
        gc._raise_for_calendar_write_403(_err(""), "acct-1")
