# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression (chaos audit 2026-06-02, fault-injection lens).

After a draft reply is SENT, `send_draft` archives the ORIGINAL email in a
background thread and used to emit "email archived" UNCONDITIONALLY — so when
that background archive failed (Gmail 429, OAuth token expiry, timeout), the
failure was swallowed and the original silently reappeared in the inbox at the
next sync with no toast. The post-send path now emits the REAL outcome via
`_emit_archive_outcome`, mirroring the manual-archive path (Cluster E #325):
success -> emit_email_archived, failure -> emit_email_updated({archive_failed})
so the frontend reverts the optimistic remove and warns the user.
"""

from __future__ import annotations

from unittest.mock import patch

from app.api.routes_emails import _emit_archive_outcome


def test_successful_archive_emits_archived_only():
    with patch("app.api.websocket.emit_email_archived") as m_archived, \
         patch("app.api.websocket.emit_email_updated") as m_updated:
        _emit_archive_outcome("eid-1", True, 7)
    m_archived.assert_called_once()
    m_updated.assert_not_called()


def test_failed_archive_surfaces_archive_failed():
    with patch("app.api.websocket.emit_email_archived") as m_archived, \
         patch("app.api.websocket.emit_email_updated") as m_updated:
        _emit_archive_outcome("eid-1", False, 7)
    # No false "archived" signal …
    m_archived.assert_not_called()
    # … and the failure is surfaced so the FE reverts + toasts.
    m_updated.assert_called_once()
    args, kwargs = m_updated.call_args
    patch_payload = args[1]
    assert patch_payload.get("archive_failed") is True


def test_archive_outcome_keys_off_truthiness_of_the_archive_result():
    # _safe_call returns None on a swallowed exception (429 / token expiry) —
    # bool(None) is False, so None must be treated as a failure, not a success.
    for falsy in (None, False, 0):
        with patch("app.api.websocket.emit_email_archived") as m_archived, \
             patch("app.api.websocket.emit_email_updated") as m_updated:
            _emit_archive_outcome("eid-x", bool(falsy), 1)
        m_archived.assert_not_called()
        m_updated.assert_called_once()
