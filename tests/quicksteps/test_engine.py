# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Engine tests — sequential execution, idempotency, pre-flight, partial failure.

The engine accepts injection points so we can drive it with stub providers
and stub email loaders. No Flask app context required.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from app.quicksteps import engine


# --------------------------------------------------------------------------- #
# Stub helpers
# --------------------------------------------------------------------------- #

@dataclass
class FakeEmail:
    sender: str = "boss@example.com"
    sender_name: str = "The Boss"
    subject: str = "Status?"
    recipients: str = "me@example.com"
    cc: str = ""
    body_text: str = "Hi"
    body_html: str = "<p>Hi</p>"
    thread_id: str = "thread-deadbeef-12345"
    date: datetime = field(default_factory=lambda: datetime(2026, 5, 6, 9, 30))


class FakeProvider:
    """Records calls so tests can assert on side-effects."""

    def __init__(self, *, archive_ok: bool = True, delete_ok: bool = True,
                 read_ok: bool = True, spam_ok: bool = True,
                 reply_id: str | None = "sent-msg-1",
                 forward_id: str | None = "sent-msg-2") -> None:
        self.archive_ok = archive_ok
        self.delete_ok = delete_ok
        self.read_ok = read_ok
        self.spam_ok = spam_ok
        self.reply_id = reply_id
        self.forward_id = forward_id
        self.calls: list[tuple[str, dict]] = []

    def archive_email(self, raw_id: str) -> bool:
        self.calls.append(("archive", {"raw_id": raw_id}))
        return self.archive_ok

    def delete_email(self, raw_id: str) -> bool:
        self.calls.append(("delete", {"raw_id": raw_id}))
        return self.delete_ok

    def mark_as_read(self, raw_id: str) -> bool:
        self.calls.append(("mark_as_read", {"raw_id": raw_id}))
        return self.read_ok

    def mark_as_unread(self, raw_id: str) -> bool:
        self.calls.append(("mark_as_unread", {"raw_id": raw_id}))
        return self.read_ok

    def move_to_spam(self, raw_id: str) -> bool:
        self.calls.append(("spam", {"raw_id": raw_id}))
        return self.spam_ok

    def send_reply_directly(self, **kwargs):
        self.calls.append(("reply", kwargs))
        return self.reply_id

    def send_new_directly(self, **kwargs):
        self.calls.append(("forward", kwargs))
        return self.forward_id


def _step(actions: list[dict], step_id: str = "11111111-1111-4111-8111-111111111111") -> dict:
    return {"id": step_id, "name": "test", "actions": actions, "enabled": True}


def _execute(*, step, account_id: int = 1, email_id: str = "msg-abc",
             email: Any = None, provider: Any = None,
             account: tuple[str, str] = ("user@example.com", "User Name"),
             idempotency_key: str | None = None):
    """Drive the engine with stubbed provider + email + account loader."""
    p = provider or FakeProvider()
    e = email if email is not None else FakeEmail()
    return engine.execute(
        account_id=account_id,
        step=step,
        email_id=email_id,
        idempotency_key=idempotency_key,
        provider_factory=lambda: p,
        email_loader=lambda _provider, _eid, _aid: e,
        account_loader=lambda _aid: account,
    ), p


@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    engine._idem_clear_for_tests()
    yield
    engine._idem_clear_for_tests()


# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #

class TestPreflight:
    def test_empty_actions_fail(self):
        report, _ = _execute(step=_step([]))
        assert report.success is False
        assert report.error == "no_actions"

    def test_unknown_action_type_short_circuits(self):
        # validate_quick_step would catch this — but the engine is a defense
        # in depth: directly-injected steps from internal code should fail
        # cleanly rather than throw.
        report, p = _execute(step=_step([{"type": "wat"}]))
        assert report.success is False
        assert report.error and report.error.startswith("unknown_action")
        assert p.calls == []

    def test_email_not_found_short_circuits(self):
        report = engine.execute(
            account_id=1,
            step=_step([{"type": "archive"}]),
            email_id="missing",
            provider_factory=lambda: FakeProvider(),
            email_loader=lambda *_: None,
            account_loader=lambda _aid: ("u@x", "U"),
        )
        assert report.success is False
        assert report.error == "email_not_found"

    def test_provider_unavailable_short_circuits(self):
        def boom():
            raise RuntimeError("no token")
        report = engine.execute(
            account_id=1,
            step=_step([{"type": "archive"}]),
            email_id="x",
            provider_factory=boom,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _aid: ("u@x", "U"),
        )
        assert report.success is False
        assert "provider_unavailable" in (report.error or "")

    def test_template_unknown_variable_blocks_send(self):
        # The pre-flight step must catch typos like {sendr.firstname} BEFORE
        # we hit the provider — partial sends are the worst UX.
        report, p = _execute(step=_step([
            {"type": "reply_template", "payload": {
                "body": "Hi {sendr.firstname}",  # typo
                "replyAll": False,
                "includeQuoted": True,
            }},
        ]))
        assert report.success is False
        assert report.error and report.error.startswith("template_unknown_variables")
        assert p.calls == []  # provider was never asked to send


# --------------------------------------------------------------------------- #
# Sequential execution
# --------------------------------------------------------------------------- #

class TestSequentialExecution:
    def test_single_archive(self):
        report, p = _execute(step=_step([{"type": "archive"}]))
        assert report.success is True
        assert report.executed == 1
        assert [a.type for a in report.actions] == ["archive"]
        assert p.calls[0][0] == "archive"

    def test_chain_runs_in_order(self):
        report, p = _execute(step=_step([
            {"type": "mark_read", "payload": {"value": True}},
            {"type": "archive"},
        ]))
        assert report.success is True
        assert report.executed == 2
        assert [c[0] for c in p.calls] == ["mark_as_read", "archive"]

    def test_failure_halts_chain(self):
        provider = FakeProvider(archive_ok=False)
        report, p = _execute(
            provider=provider,
            step=_step([
                {"type": "archive"},                       # fails
                {"type": "mark_read", "payload": {"value": True}},  # must NOT run
            ]),
        )
        assert report.success is False
        assert report.executed == 0
        assert [a.ok for a in report.actions] == [False]
        assert "mark_as_read" not in [c[0] for c in p.calls]

    def test_partial_success_reports_executed_count(self):
        provider = FakeProvider(archive_ok=False)
        report, _ = _execute(
            provider=provider,
            step=_step([
                {"type": "mark_read", "payload": {"value": True}},  # OK
                {"type": "archive"},                                # FAIL
            ]),
        )
        assert report.success is False
        assert report.executed == 1
        assert [a.ok for a in report.actions] == [True, False]


# --------------------------------------------------------------------------- #
# Reply / forward — wiring + side effects
# --------------------------------------------------------------------------- #

class TestReplyAndForward:
    def test_reply_template_substitutes_variables(self):
        report, p = _execute(step=_step([
            {"type": "reply_template", "payload": {
                "body": "Hi {sender.firstname}, got it.",
                "replyAll": False,
                "includeQuoted": False,
            }},
        ]))
        assert report.success is True
        reply_call = next(c for c in p.calls if c[0] == "reply")
        assert "Hi The" in reply_call[1]["body"]  # 'The Boss' → first word 'The'
        assert reply_call[1]["to"] == ["boss@example.com"]

    def test_forward_uses_recipients_and_subject(self):
        report, p = _execute(step=_step([
            {"type": "forward", "payload": {
                "to": ["assistant@example.com"],
                "subject_prefix": "Tr:",
            }},
        ]))
        assert report.success is True
        fwd = next(c for c in p.calls if c[0] == "forward")
        assert fwd[1]["to"] == ["assistant@example.com"]
        assert fwd[1]["subject"].startswith("Tr:")
        assert "Status?" in fwd[1]["subject"]

    def test_reply_then_forward_chain(self):
        report, p = _execute(step=_step([
            {"type": "reply_template", "payload": {
                "body": "Got it",
                "replyAll": False,
                "includeQuoted": False,
            }},
            {"type": "forward", "payload": {"to": ["assistant@example.com"]}},
            {"type": "archive"},
        ]))
        assert report.success is True
        assert report.executed == 3
        assert [c[0] for c in p.calls] == ["reply", "forward", "archive"]

    def test_reply_send_failure_halts_before_archive(self):
        provider = FakeProvider(reply_id=None)
        report, p = _execute(
            provider=provider,
            step=_step([
                {"type": "reply_template", "payload": {
                    "body": "Hi", "replyAll": False, "includeQuoted": False,
                }},
                {"type": "archive"},
            ]),
        )
        assert report.success is False
        assert "archive" not in [c[0] for c in p.calls]

    def test_reply_template_triggers_auto_archive_helper(self, monkeypatch):
        """After a reply lands, the helper that mirrors the regular
        reply path's auto-archive behaviour must fire so users get the
        same UX as a manual reply (Ctrl+1 should clear an Action email
        from the inbox just like clicking Reply does)."""
        from app.api import routes_helpers as rh

        calls: list[tuple[str, str]] = []

        def fake_auto_archive(provider, email_id):
            calls.append((getattr(provider, "_kind", "fake"), email_id))

        monkeypatch.setattr(rh, "_auto_archive_if_action", fake_auto_archive)

        report, _ = _execute(step=_step([
            {"type": "reply_template", "payload": {
                "body": "Got it",
                "replyAll": False,
                "includeQuoted": False,
            }},
        ]))
        assert report.success is True
        assert len(calls) == 1
        assert calls[0][1] == "msg-abc"  # raw_id forwarded

    def test_reply_failure_does_not_trigger_auto_archive(self, monkeypatch):
        """If the reply itself failed, the helper must NOT run — we
        don't want to archive an email whose reply never went out."""
        from app.api import routes_helpers as rh

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            rh, "_auto_archive_if_action",
            lambda provider, email_id: calls.append(("called", email_id)),
        )

        provider = FakeProvider(reply_id=None)  # reply send fails
        report, _ = _execute(provider=provider, step=_step([
            {"type": "reply_template", "payload": {
                "body": "Got it",
                "replyAll": False,
                "includeQuoted": False,
            }},
        ]))
        assert report.success is False
        assert calls == []

    def test_html_in_template_value_does_not_escape_markup(self):
        # User's template HTML is preserved; only substituted values are escaped.
        report, p = _execute(step=_step([
            {"type": "reply_template", "payload": {
                "body": "<p>Hello <b>{sender.firstname}</b></p>",
                "replyAll": False,
                "includeQuoted": False,
            }},
        ]))
        body = next(c for c in p.calls if c[0] == "reply")[1]["body"]
        assert "<p>Hello <b>The</b></p>" in body


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #

class TestIdempotency:
    def test_same_key_returns_cached_report(self):
        step = _step([{"type": "archive"}])
        provider = FakeProvider()

        def loader(*_):
            return FakeEmail()

        def acct(_):
            return ("u@x", "U")

        first = engine.execute(
            account_id=1, step=step, email_id="msg-1",
            idempotency_key="key-A",
            provider_factory=lambda: provider,
            email_loader=loader, account_loader=acct,
        )
        second = engine.execute(
            account_id=1, step=step, email_id="msg-1",
            idempotency_key="key-A",
            provider_factory=lambda: provider,
            email_loader=loader, account_loader=acct,
        )

        assert first.success is True
        assert second.idempotent_replay is True
        assert second.success is True
        # Provider was only called ONCE despite two execute() calls
        assert sum(1 for c in provider.calls if c[0] == "archive") == 1

    def test_different_keys_run_independently(self):
        step = _step([{"type": "archive"}])
        provider = FakeProvider()

        engine.execute(
            account_id=1, step=step, email_id="m",
            idempotency_key="A",
            provider_factory=lambda: provider,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("u@x", "U"),
        )
        engine.execute(
            account_id=1, step=step, email_id="m",
            idempotency_key="B",
            provider_factory=lambda: provider,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("u@x", "U"),
        )
        assert sum(1 for c in provider.calls if c[0] == "archive") == 2

    def test_no_key_means_no_dedupe(self):
        step = _step([{"type": "archive"}])
        provider = FakeProvider()
        for _ in range(3):
            engine.execute(
                account_id=1, step=step, email_id="m",
                idempotency_key=None,
                provider_factory=lambda: provider,
                email_loader=lambda *_: FakeEmail(),
                account_loader=lambda _: ("u@x", "U"),
            )
        assert sum(1 for c in provider.calls if c[0] == "archive") == 3

    def test_key_is_account_scoped(self):
        # Same idempotency string from a different account must not collide.
        step = _step([{"type": "archive"}])
        provider_a = FakeProvider()
        provider_b = FakeProvider()
        engine.execute(
            account_id=1, step=step, email_id="m", idempotency_key="K",
            provider_factory=lambda: provider_a,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("a@x", "A"),
        )
        engine.execute(
            account_id=2, step=step, email_id="m", idempotency_key="K",
            provider_factory=lambda: provider_b,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("b@x", "B"),
        )
        assert len(provider_a.calls) == 1
        assert len(provider_b.calls) == 1

    def test_ttl_expiry(self):
        # Inject a MemoryIdempotencyStore with TTL=0 so the entry is stale
        # immediately — proves the TTL check actually fires on read.
        from app.quicksteps.idempotency import MemoryIdempotencyStore
        zero_ttl_store = MemoryIdempotencyStore(ttl_seconds=0.0)

        step = _step([{"type": "archive"}])
        provider = FakeProvider()
        engine.execute(
            account_id=1, step=step, email_id="m", idempotency_key="K",
            provider_factory=lambda: provider,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("u@x", "U"),
            idempotency_store=zero_ttl_store,
        )
        time.sleep(0.001)
        engine.execute(
            account_id=1, step=step, email_id="m", idempotency_key="K",
            provider_factory=lambda: provider,
            email_loader=lambda *_: FakeEmail(),
            account_loader=lambda _: ("u@x", "U"),
            idempotency_store=zero_ttl_store,
        )
        assert sum(1 for c in provider.calls if c[0] == "archive") == 2


# --------------------------------------------------------------------------- #
# Cross-tenant regression — engine MUST forward account_id to email_loader.
# --------------------------------------------------------------------------- #

class TestCrossTenantScoping:
    def test_email_loader_receives_account_id(self):
        captured = {}

        def loader(_provider, eid, aid):
            captured["account_id"] = aid
            captured["email_id"] = eid
            return FakeEmail()

        engine.execute(
            account_id=42,
            step=_step([{"type": "archive"}]),
            email_id="shared-id",
            provider_factory=lambda: FakeProvider(),
            email_loader=loader,
            account_loader=lambda _: ("u@x", "U"),
        )
        assert captured["account_id"] == 42
        assert captured["email_id"] == "shared-id"
