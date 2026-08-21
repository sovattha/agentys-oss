# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""RSVP handler — OAuth account-id bridge.

Locks the bridge failure paths so a missing email or unregistered
multi-account config returns ``calendar_account_unresolved`` instead of
silently falling back to ``str(ctx.account_id)``. The previous fallback
was at best a 401 against the wrong calendar; on shared infra it could
even succeed against another user's OAuth session if the int id
collision happened to align.
"""
from __future__ import annotations

from dataclasses import dataclass


from app.quicksteps.registry import ExecutionContext, handle_rsvp_meeting


@dataclass
class _FakeEmail:
    sender: str = "host@x.com"
    subject: str = "Invite"
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    id: str = "msg-1"


def _ctx(*, account_email: str = "user@example.com", account_id: int = 1) -> ExecutionContext:
    return ExecutionContext(
        provider=object(),
        account_id=account_id,
        account_email=account_email,
        account_display_name="User",
        email=_FakeEmail(),
        email_id="msg-1",
        raw_id="msg-1",
        template_vars={},
    )


class TestOAuthBridge:
    def test_missing_account_email_returns_unresolved(self):
        # Engine couldn't load the Account row — there's nothing to map to
        # an OAuth session. Must NOT fall through to a calendar provider.
        result = handle_rsvp_meeting(_ctx(account_email=""), {})
        assert result.ok is False
        assert result.error == "calendar_account_unresolved"

    def test_unknown_account_email_returns_unresolved(self, monkeypatch):
        from app import multi_accounts

        class _EmptyMgr:
            def get_account_by_email(self, _email):
                return None

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _EmptyMgr())
        result = handle_rsvp_meeting(_ctx(account_email="ghost@nowhere.com"), {})
        assert result.ok is False
        assert result.error == "calendar_account_unresolved"

    def test_multi_account_lookup_exception_is_unresolved(self, monkeypatch):
        from app import multi_accounts

        class _BoomMgr:
            def get_account_by_email(self, _email):
                raise RuntimeError("DB unavailable")

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _BoomMgr())
        result = handle_rsvp_meeting(_ctx(), {})
        assert result.ok is False
        assert result.error == "calendar_account_unresolved"

    def test_calendar_provider_unavailable_after_resolution(self, monkeypatch):
        # OAuth bridge resolves cleanly but the calendar provider can't be
        # built (e.g. token expired). Must surface a distinct error code so
        # operations can tell "no OAuth at all" from "OAuth ok, calendar
        # backend down". calendar_not_supported preserves prior contract.
        from app import multi_accounts
        from app.providers import calendar_factory

        class _FakeCfg:
            id = "abc-hex"

        class _Mgr:
            def get_account_by_email(self, _email):
                return _FakeCfg()

        def _boom(_id):
            raise RuntimeError("token expired")

        monkeypatch.setattr(multi_accounts, "get_account_manager", lambda: _Mgr())
        monkeypatch.setattr(calendar_factory, "create_calendar_provider", _boom)

        result = handle_rsvp_meeting(_ctx(), {})
        assert result.ok is False
        assert result.error == "calendar_not_supported"
