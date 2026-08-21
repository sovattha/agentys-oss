# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""forward.to_groups — contact-group expansion at execution time.

The schema accepts ``to_groups`` (a list of contact-group ids) and the
handler expands each to its member emails before sending, deduping against
the literal ``to`` list. These tests lock that behaviour down: the schema
validation was tested before, but the *expansion* in the handler had no
coverage.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.quicksteps.handlers.forward import handle_forward
from app.quicksteps.types import ExecutionContext


@dataclass
class _FakeEmail:
    sender: str = "boss@corp.com"
    sender_name: str = "Boss"
    subject: str = "Q3 report"
    body: str = "body text"
    body_html: str = ""
    recipients: str = "me@example.com"
    date: object = None
    id: str = "m1"


class _CapturingProvider:
    """Records the recipient list the forward was sent to."""

    def __init__(self):
        self.sent_to: list[str] | None = None

    def send_new_directly(self, *, to, subject, body, is_html, from_name):
        self.sent_to = to
        return "sent-1"


def _ctx(provider, *, account_id: int = 7) -> ExecutionContext:
    return ExecutionContext(
        provider=provider,
        account_id=account_id,
        account_email="me@example.com",
        account_display_name="Me",
        email=_FakeEmail(),
        email_id="m1",
        raw_id="m1",
        template_vars={},
    )


def _patch_groups(monkeypatch, groups_by_id: dict):
    from app.api import contact_groups
    monkeypatch.setattr(
        contact_groups, "_get_group_by_id", lambda gid: groups_by_id.get(gid)
    )


class TestForwardGroupExpansion:
    def test_group_expands_to_member_emails(self, monkeypatch):
        _patch_groups(monkeypatch, {
            "grp_1": {
                "id": "grp_1",
                "account_id": 7,
                "members": [{"email": "a@x.com"}, {"email": "b@x.com"}],
            },
        })
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider), {"to": [], "to_groups": ["grp_1"]})
        assert result.ok is True
        assert provider.sent_to == ["a@x.com", "b@x.com"]
        assert result.artifact["to"] == ["a@x.com", "b@x.com"]

    def test_group_only_forward_with_empty_to(self, monkeypatch):
        # A forward addressed ONLY to a group (no literal `to`) must still send.
        _patch_groups(monkeypatch, {
            "grp_1": {"id": "grp_1", "account_id": 7, "members": [{"email": "team@x.com"}]},
        })
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider), {"to_groups": ["grp_1"]})
        assert result.ok is True
        assert provider.sent_to == ["team@x.com"]

    def test_account_scoped_group_not_expanded(self, monkeypatch):
        # Group belongs to a different account → must NOT leak its members.
        _patch_groups(monkeypatch, {
            "grp_other": {
                "id": "grp_other",
                "account_id": 999,
                "members": [{"email": "leak@other.com"}],
            },
        })
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider, account_id=7), {"to": [], "to_groups": ["grp_other"]})
        # No recipients resolved → handler refuses to send.
        assert result.ok is False
        assert result.error == "forward_no_recipient"
        assert provider.sent_to is None

    def test_unknown_group_id_is_skipped(self, monkeypatch):
        _patch_groups(monkeypatch, {})  # _get_group_by_id returns None
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider), {"to": ["keep@x.com"], "to_groups": ["ghost"]})
        assert result.ok is True
        assert provider.sent_to == ["keep@x.com"]

    def test_member_already_in_to_is_not_duplicated(self, monkeypatch):
        _patch_groups(monkeypatch, {
            "grp_1": {
                "id": "grp_1",
                "account_id": 7,
                "members": [{"email": "a@x.com"}, {"email": "b@x.com"}],
            },
        })
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider), {"to": ["a@x.com"], "to_groups": ["grp_1"]})
        assert result.ok is True
        assert provider.sent_to == ["a@x.com", "b@x.com"]

    def test_dedup_is_case_insensitive_against_to(self, monkeypatch):
        # `to` carries a mixed-case address; the group lists the lowercase
        # form. The same human recipient must appear exactly once.
        _patch_groups(monkeypatch, {
            "grp_1": {
                "id": "grp_1",
                "account_id": 7,
                "members": [{"email": "Alice@X.com"}, {"email": "b@x.com"}],
            },
        })
        provider = _CapturingProvider()
        result = handle_forward(_ctx(provider), {"to": ["alice@x.com"], "to_groups": ["grp_1"]})
        assert result.ok is True
        # alice@x.com (from `to`) kept once; only b@x.com added from the group.
        assert provider.sent_to == ["alice@x.com", "b@x.com"]
