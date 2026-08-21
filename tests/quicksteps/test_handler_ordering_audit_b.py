# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Audit fix Cluster B (2026-05-10) — Quick Step handler ordering.

Source: tasks/audit-reports/2026-05-10_2219/02-backend-silent.md (B-02, B-03,
B-04) and 03-ui-live.md (U-04).

Three commit-before-remote bugs and one false-positive bug:

  * B-02 — handle_archive: cache evict + WS emit fire BEFORE
    provider.archive_email. If the provider call then fails (Gmail 5xx),
    the inbox UI has already removed the email; at the next refresh it
    reappears, creating a "ghost archive" UX with no toast.
    Fix: provider call first; cache evict + WS emit only on success.

  * B-03 — handle_delete: same pattern with delete_email + folder=trash.
    Fix: same — provider first, then evict + emit on success.

  * B-04 — handle_mark_read: marks the cache + emits emit_email_updated
    even when provider.mark_as_read/unread returns False. The UI flips to
    "read" visually but the result reports ok=False — divergence between
    visual state and chain state. Fix: only update cache + emit when the
    provider succeeded.

  * U-04 — handle_rsvp_meeting: returns ok=True with artifact.skipped on
    THREE distinct conditions: real calendar conflict, deep-work conflict,
    AND not-a-meeting (no iCal payload). The first two are legitimate
    skip-because-busy outcomes; the third is a contract violation — the
    user (or auto-trigger) targeted an email that isn't actually
    RSVP-able, and getting a green "executed" toast erodes trust. Fix:
    distinguish — keep ok=True for genuine busy skips, return
    ok=False/error=not_a_meeting when there is no iCal to RSVP against.

Run: pytest tests/quicksteps/test_handler_ordering_audit_b.py -v
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch


from app.quicksteps.handlers.archive import handle_archive
from app.quicksteps.handlers.delete import handle_delete
from app.quicksteps.handlers.mark_read import handle_mark_read
from app.quicksteps.types import ExecutionContext


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@dataclass
class _FakeEmail:
    id: str = "msg-42"


def _make_ctx(*, provider, email_id: str = "msg-42") -> ExecutionContext:
    return ExecutionContext(
        provider=provider,
        account_id=1,
        account_email="user@example.com",
        account_display_name="User",
        email=_FakeEmail(id=email_id),
        email_id=email_id,
        raw_id=email_id,
        template_vars={},
    )


# --------------------------------------------------------------------------- #
# B-02 — archive must NOT touch cache / WS before provider succeeds
# --------------------------------------------------------------------------- #


class TestB02ArchiveOrdering:
    @patch("app.quicksteps.handlers.archive.emit")
    @patch("app.quicksteps.handlers.archive.evict_caches")
    def test_provider_failure_does_not_evict_cache(self, mock_evict, mock_emit):
        """When provider.archive_email returns False, evict_caches MUST NOT
        have been called — otherwise the inbox list lies until the next
        refresh restores reality."""
        provider = MagicMock()
        provider.archive_email.return_value = False
        ctx = _make_ctx(provider=provider)

        result = handle_archive(ctx, {})

        assert result.ok is False
        assert result.error == "provider_archive_failed"
        mock_evict.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.archive.emit")
    @patch("app.quicksteps.handlers.archive.evict_caches")
    def test_provider_exception_does_not_evict_cache(self, mock_evict, mock_emit):
        provider = MagicMock()
        provider.archive_email.side_effect = RuntimeError("Gmail 503")
        ctx = _make_ctx(provider=provider)

        result = handle_archive(ctx, {})

        assert result.ok is False
        assert "archive_error" in (result.error or "")
        mock_evict.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.archive.emit")
    @patch("app.quicksteps.handlers.archive.evict_caches")
    def test_provider_success_does_evict_and_emit(self, mock_evict, mock_emit):
        """Happy path regression guard: ordering must not skip the side
        effects when provider succeeds."""
        provider = MagicMock()
        provider.archive_email.return_value = True
        ctx = _make_ctx(provider=provider)

        result = handle_archive(ctx, {})

        assert result.ok is True
        mock_evict.assert_called_once()
        mock_emit.assert_called_once()

    @patch("app.quicksteps.handlers.archive.emit")
    @patch("app.quicksteps.handlers.archive.evict_caches")
    def test_sent_item_shortcut_still_evicts(self, mock_evict, mock_emit):
        """Sent-prefixed ids are a known no-op on the provider side — the
        cache eviction + WS emit must still fire so the UI reflects the
        archive locally."""
        provider = MagicMock()
        ctx = _make_ctx(provider=provider, email_id="sent:msg-42")

        result = handle_archive(ctx, {})

        assert result.ok is True
        provider.archive_email.assert_not_called()
        mock_evict.assert_called_once()
        mock_emit.assert_called_once()


# --------------------------------------------------------------------------- #
# B-03 — delete must NOT touch cache / WS before provider succeeds
# --------------------------------------------------------------------------- #


class TestB03DeleteOrdering:
    @patch("app.quicksteps.handlers.delete.emit")
    @patch("app.quicksteps.handlers.delete.evict_caches")
    def test_provider_failure_does_not_evict_cache(self, mock_evict, mock_emit):
        provider = MagicMock()
        provider.delete_email.return_value = False
        ctx = _make_ctx(provider=provider)

        result = handle_delete(ctx, {})

        assert result.ok is False
        assert result.error == "provider_delete_failed"
        mock_evict.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.delete.emit")
    @patch("app.quicksteps.handlers.delete.evict_caches")
    def test_provider_exception_does_not_evict_cache(self, mock_evict, mock_emit):
        provider = MagicMock()
        provider.delete_email.side_effect = RuntimeError("Gmail 5xx")
        ctx = _make_ctx(provider=provider)

        result = handle_delete(ctx, {})

        assert result.ok is False
        assert "delete_error" in (result.error or "")
        mock_evict.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.delete.emit")
    @patch("app.quicksteps.handlers.delete.evict_caches")
    def test_provider_success_evicts_and_emits(self, mock_evict, mock_emit):
        provider = MagicMock()
        provider.delete_email.return_value = True
        ctx = _make_ctx(provider=provider)

        result = handle_delete(ctx, {})

        assert result.ok is True
        mock_evict.assert_called_once()
        mock_emit.assert_called_once()


# --------------------------------------------------------------------------- #
# B-04 — mark_read must NOT update cache when provider fails
# --------------------------------------------------------------------------- #


class TestB04MarkReadOrdering:
    @patch("app.quicksteps.handlers.mark_read.emit")
    @patch("app.quicksteps.handlers.mark_read.update_cached_read_flag")
    def test_provider_failure_does_not_update_cache(self, mock_update, mock_emit):
        """Before the fix: provider returned False, cache + WS still
        updated, user saw the email as 'read' while ok=False was reported.
        After the fix: no cache update, no WS emit, ok=False with reason."""
        provider = MagicMock()
        provider.mark_as_read.return_value = False
        ctx = _make_ctx(provider=provider)

        result = handle_mark_read(ctx, {"value": True})

        assert result.ok is False
        assert "provider_mark_read_failed" in (result.error or "")
        mock_update.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.mark_read.emit")
    @patch("app.quicksteps.handlers.mark_read.update_cached_read_flag")
    def test_provider_exception_does_not_update_cache(self, mock_update, mock_emit):
        provider = MagicMock()
        provider.mark_as_read.side_effect = RuntimeError("transient")
        ctx = _make_ctx(provider=provider)

        result = handle_mark_read(ctx, {"value": True})

        assert result.ok is False
        assert "mark_read_error" in (result.error or "")
        mock_update.assert_not_called()
        mock_emit.assert_not_called()

    @patch("app.quicksteps.handlers.mark_read.emit")
    @patch("app.quicksteps.handlers.mark_read.update_cached_read_flag")
    def test_provider_success_updates_cache_and_emits(self, mock_update, mock_emit):
        provider = MagicMock()
        provider.mark_as_read.return_value = True
        ctx = _make_ctx(provider=provider)

        result = handle_mark_read(ctx, {"value": True})

        assert result.ok is True
        mock_update.assert_called_once()
        mock_emit.assert_called_once()

    @patch("app.quicksteps.handlers.mark_read.emit")
    @patch("app.quicksteps.handlers.mark_read.update_cached_read_flag")
    def test_mark_unread_provider_failure_does_not_update_cache(
        self, mock_update, mock_emit
    ):
        """Symmetry: mark-as-unread (value=False) must obey the same
        contract — no cache mutation if the provider rejected the change."""
        provider = MagicMock()
        provider.mark_as_unread.return_value = False
        ctx = _make_ctx(provider=provider)

        result = handle_mark_read(ctx, {"value": False})

        assert result.ok is False
        mock_update.assert_not_called()
        mock_emit.assert_not_called()


# --------------------------------------------------------------------------- #
# U-04 — rsvp_meeting on a non-meeting must be ok=False, not skipped=true
# --------------------------------------------------------------------------- #


class TestU04RsvpNotAMeeting:
    """When the provider tells us the email has no iCal payload, we must
    NOT report ok=True with skipped — that erodes user trust in the Quick
    Steps engine. (Free/busy gating now lives in the calendar_invite + free
    trigger condition, not in this handler — see test_auto_trigger.py.)"""

    def _setup_cal(self, monkeypatch, *, rsvp_result):
        """Mount a fake calendar provider that returns the given rsvp result."""
        from app import multi_accounts
        from app.providers import calendar_factory

        class _Cfg:
            id = "oauth-hex-1"

        class _Mgr:
            def get_account_by_email(self, _email):
                return _Cfg()

        cal = MagicMock()
        cal.rsvp_event.return_value = rsvp_result

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(calendar_factory, "create_calendar_provider", lambda _id: cal)
        return cal

    def _ctx(self) -> ExecutionContext:
        return ExecutionContext(
            provider=object(),
            account_id=1,
            account_email="user@example.com",
            account_display_name="User",
            email=_FakeEmail(),
            email_id="msg-1",
            raw_id="msg-1",
            template_vars={},
        )

    def test_no_ical_uid_returns_not_a_meeting_failure(self, monkeypatch):
        from app.quicksteps.handlers.rsvp import handle_rsvp_meeting

        self._setup_cal(
            monkeypatch,
            rsvp_result={"ok": False, "error": "no_ical_uid"},
        )

        result = handle_rsvp_meeting(self._ctx(), {})

        assert result.ok is False, (
            "Non-meeting email must surface as failure, not silent skip-success"
        )
        assert result.error == "not_a_meeting"

    def test_event_not_found_returns_not_a_meeting_failure(self, monkeypatch):
        from app.quicksteps.handlers.rsvp import handle_rsvp_meeting

        self._setup_cal(
            monkeypatch,
            rsvp_result={"ok": False, "error": "event_not_found"},
        )

        result = handle_rsvp_meeting(self._ctx(), {})

        assert result.ok is False
        assert result.error == "not_a_meeting"
