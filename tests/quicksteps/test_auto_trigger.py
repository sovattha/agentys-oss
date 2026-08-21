# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Auto-trigger executor.

Covers the chained-step state isolation: when a Quick Step fires multiple
auto-triggers on the same email, downstream condition checks must see the
email as it was *delivered* (not as the previous step left it). The fix
takes a snapshot at function entry and feeds the snapshot — not the live
provider object — to the matcher.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


from app.quicksteps import auto_trigger


@dataclass
class _MutableEmail:
    """Mimics the SQLA Email row enough to drive the matcher."""
    sender: str = "alice@x.com"
    subject: str = ""
    body: str = ""
    body_html: str = ""
    recipients: str = ""
    attachments_meta: str = ""
    id: str = "msg-1"


def _trigger(ctype: str, value: str, *, negate: bool = False) -> dict:
    return {"type": ctype, "value": value, **({"negate": True} if negate else {})}


# --------------------------------------------------------------------------- #
# Snapshot — frozen at function entry
# --------------------------------------------------------------------------- #

class TestSnapshot:
    def test_snapshot_freezes_sender(self):
        email = _MutableEmail(sender="orig@x.com")
        snap = auto_trigger._EmailSnapshot.of(email)
        # Mutating the source after snapshot must not change the snapshot.
        email.sender = "tampered@y.com"
        assert snap.sender == "orig@x.com"

    def test_snapshot_handles_missing_attrs(self):
        class Bare:  # no attributes
            pass
        snap = auto_trigger._EmailSnapshot.of(Bare())
        assert snap.sender == ""
        assert snap.body == ""

    def test_match_condition_reads_snapshot_fields(self):
        snap = auto_trigger._EmailSnapshot.of(
            _MutableEmail(sender="vip@enterprise.com", subject="Q4 review")
        )
        assert auto_trigger._match_condition(
            _trigger("sender", "vip@enterprise.com"), snap,
        ) is True
        assert auto_trigger._match_condition(
            _trigger("subject_keyword", "q4"), snap,
        ) is True


# --------------------------------------------------------------------------- #
# Chain isolation — downstream steps must not see step-1 side effects
# --------------------------------------------------------------------------- #

class TestRunAutoTriggers:
    def test_chain_uses_snapshot_not_live_email(self, monkeypatch):
        """Step 1 mutates the email; step 2's matcher must still see the
        original sender. Without the snapshot, the second step would mismatch
        because Quick Step 1's archive handler had cleared the field."""
        email = _MutableEmail(sender="critical@vip.com", subject="urgent")
        executed: list[str] = []

        # Two steps that both gate on sender == critical@vip.com.
        steps = [
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "step-1",
                "enabled": True,
                "autoEnabled": True,
                "triggerOperator": "AND",
                "triggers": [_trigger("sender", "critical@vip.com")],
                "actions": [{"type": "archive"}],
            },
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "name": "step-2",
                "enabled": True,
                "autoEnabled": True,
                "triggerOperator": "AND",
                "triggers": [_trigger("sender", "critical@vip.com")],
                "actions": [{"type": "mark_read", "payload": {"value": True}}],
            },
        ]

        from app.quicksteps import store as store_module
        monkeypatch.setattr(store_module, "load_quick_steps", lambda _aid: steps)

        # Simulate a hostile execute(): the moment it's called, mutate the
        # email so a later trigger eval against the live object would miss.
        from app.quicksteps import engine as engine_module

        class _R:  # report stub
            success = True
            error = None

        def fake_execute(*, account_id, step, email_id, source="manual", **_):
            executed.append(step["name"])
            email.sender = "tampered@elsewhere.com"
            return _R()

        monkeypatch.setattr(engine_module, "execute", fake_execute)

        auto_trigger.run_auto_triggers(account_id=1, email_id="msg-1", email=email)
        # Both steps must have fired despite the in-flight mutation.
        assert executed == ["step-1", "step-2"]

    def test_disabled_step_is_skipped(self, monkeypatch):
        steps = [{
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "off",
            "enabled": False,
            "autoEnabled": True,
            "triggerOperator": "OR",
            "triggers": [_trigger("sender", "x@y.com")],
            "actions": [{"type": "archive"}],
        }]
        from app.quicksteps import store as store_module
        monkeypatch.setattr(store_module, "load_quick_steps", lambda _aid: steps)
        called = []
        from app.quicksteps import engine as engine_module
        monkeypatch.setattr(
            engine_module, "execute",
            lambda **kw: called.append(kw) or type("R", (), {"success": True, "error": None})(),
        )
        auto_trigger.run_auto_triggers(
            account_id=1, email_id="m", email=_MutableEmail(sender="x@y.com"),
        )
        assert called == []

    def test_no_account_id_short_circuits(self, monkeypatch):
        # Defensive: account_id=0 must not even hit load_quick_steps.
        from app.quicksteps import store as store_module
        called = []
        monkeypatch.setattr(
            store_module, "load_quick_steps",
            lambda aid: called.append(aid) or [],
        )
        auto_trigger.run_auto_triggers(account_id=0, email_id="m", email=_MutableEmail())
        assert called == []


# --------------------------------------------------------------------------- #
# match_mode — v2 polymorphic condition matching
# --------------------------------------------------------------------------- #

def _cond(ctype: str, value: str = "true", *, match_mode: str | None = None,
          negate: bool = False) -> dict:
    """Build a v2-shape trigger condition."""
    cond: dict = {"type": ctype, "value": value}
    if match_mode is not None:
        cond["match_mode"] = match_mode
    if negate:
        cond["negate"] = True
    return cond


class TestSenderMatchModes:
    def test_sender_is_exact(self):
        email = _MutableEmail(sender="boss@acme.com")
        assert auto_trigger._match_condition(
            _cond("sender", "boss@acme.com", match_mode="is"), email) is True
        assert auto_trigger._match_condition(
            _cond("sender", "boss@acme", match_mode="is"), email) is False

    def test_sender_contains(self):
        # New capability: substring match against the full address.
        email = _MutableEmail(sender="boss@acme.com")
        assert auto_trigger._match_condition(
            _cond("sender", "acme", match_mode="contains"), email) is True
        assert auto_trigger._match_condition(
            _cond("sender", "boss", match_mode="contains"), email) is True
        assert auto_trigger._match_condition(
            _cond("sender", "zzz", match_mode="contains"), email) is False

    def test_sender_matches_regex(self):
        assert auto_trigger._match_condition(
            _cond("sender", "noreply|no-reply", match_mode="matches"),
            _MutableEmail(sender="noreply@acme.com")) is True
        assert auto_trigger._match_condition(
            _cond("sender", "noreply|no-reply", match_mode="matches"),
            _MutableEmail(sender="hi@acme.com")) is False

    def test_sender_matches_bad_regex_fails_closed(self):
        # A stored unparseable pattern must not raise — fail closed.
        assert auto_trigger._match_condition(
            _cond("sender", "(", match_mode="matches"),
            _MutableEmail(sender="x@y.com")) is False

    def test_sender_negate_with_match_mode(self):
        email = _MutableEmail(sender="boss@acme.com")
        assert auto_trigger._match_condition(
            _cond("sender", "acme", match_mode="contains", negate=True), email) is False
        assert auto_trigger._match_condition(
            _cond("sender", "zzz", match_mode="contains", negate=True), email) is True


class TestInvalidRegexWarning:
    """B-08 (audit 2026-06-11): the fail-closed `except re.error` was mute —
    a Quick Step persisted with a bad pattern never fired again with zero
    telemetry. Now: one WARNING per pattern (throttled), step_id included."""

    def test_invalid_regex_warns_once_per_pattern_with_step_id(self, monkeypatch, caplog):
        import logging

        # Isole le throttle module-level entre les tests.
        monkeypatch.setattr(auto_trigger, "_warned_invalid_regex_patterns", set())
        email = _MutableEmail(sender="alice@x.com")
        step = {
            "id": "33333333-3333-4333-8333-333333333333",
            "triggerOperator": "AND",
            "triggers": [_cond("sender", "([", match_mode="matches")],
        }

        with caplog.at_level(logging.WARNING, logger="app.quicksteps.auto_trigger"):
            # Fail-closed conservé sur les deux évaluations.
            assert auto_trigger._evaluate_triggers(step, email) is False
            assert auto_trigger._evaluate_triggers(step, email) is False

        records = [
            r for r in caplog.records if "invalid stored regex" in r.getMessage()
        ]
        assert len(records) == 1, "le warning doit être throttlé à 1 par pattern"
        assert "33333333-3333-4333-8333-333333333333" in records[0].getMessage()
        assert "([" in records[0].getMessage()

    def test_distinct_invalid_patterns_each_warn(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(auto_trigger, "_warned_invalid_regex_patterns", set())
        with caplog.at_level(logging.WARNING, logger="app.quicksteps.auto_trigger"):
            assert auto_trigger._regex_search("([", "target") is False
            assert auto_trigger._regex_search("(?P<", "target") is False

        records = [
            r for r in caplog.records if "invalid stored regex" in r.getMessage()
        ]
        assert len(records) == 2

    def test_valid_regex_logs_nothing(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(auto_trigger, "_warned_invalid_regex_patterns", set())
        with caplog.at_level(logging.WARNING, logger="app.quicksteps.auto_trigger"):
            assert auto_trigger._regex_search("noreply|no-reply", "noreply@x.com") is True

        assert not [
            r for r in caplog.records if "invalid stored regex" in r.getMessage()
        ]


class TestSenderDomainMatchModes:
    def test_domain_is_exact(self):
        email = _MutableEmail(sender="boss@acme.com")
        assert auto_trigger._match_condition(
            _cond("sender_domain", "acme.com", match_mode="is"), email) is True
        assert auto_trigger._match_condition(
            _cond("sender_domain", "acme", match_mode="is"), email) is False

    def test_domain_contains(self):
        # New capability: substring match against the domain.
        email = _MutableEmail(sender="boss@mail.acme.com")
        assert auto_trigger._match_condition(
            _cond("sender_domain", "acme", match_mode="contains"), email) is True

    def test_domain_matches_regex(self):
        email = _MutableEmail(sender="boss@docs.google.com")
        assert auto_trigger._match_condition(
            _cond("sender_domain", r"\.google\.com$", match_mode="matches"), email) is True


class TestRecipientMatchModes:
    def test_recipient_contains_is_legacy_default(self):
        email = _MutableEmail(recipients="team@acme.com, ops@acme.com")
        assert auto_trigger._match_condition(
            _cond("recipient", "team@acme.com", match_mode="contains"), email) is True
        assert auto_trigger._match_condition(
            _cond("recipient", "acme.com", match_mode="contains"), email) is True

    def test_recipient_is_matches_one_parsed_address(self):
        # New capability: "is" compares against each parsed To/Cc address,
        # not the whole joined string.
        email = _MutableEmail(recipients="team@acme.com, ops@acme.com")
        assert auto_trigger._match_condition(
            _cond("recipient", "ops@acme.com", match_mode="is"), email) is True
        assert auto_trigger._match_condition(
            _cond("recipient", "team@acme.com", match_mode="is"), email) is True
        # A substring of an address is NOT an exact address match.
        assert auto_trigger._match_condition(
            _cond("recipient", "acme.com", match_mode="is"), email) is False

    def test_recipient_matches_regex(self):
        # New capability.
        email = _MutableEmail(recipients="alerts+billing@acme.com")
        assert auto_trigger._match_condition(
            _cond("recipient", r"alerts\+\w+@", match_mode="matches"), email) is True


class TestEmailTextScopes:
    def test_subject_scope(self):
        email = _MutableEmail(subject="Invoice #42", body="please pay")
        assert auto_trigger._match_condition(
            _cond("email_text", "invoice", match_mode="subject"), email) is True
        # "pay" is in the body, not the subject — subject scope must miss it.
        assert auto_trigger._match_condition(
            _cond("email_text", "pay", match_mode="subject"), email) is False

    def test_body_scope(self):
        email = _MutableEmail(subject="Invoice #42", body="please pay")
        assert auto_trigger._match_condition(
            _cond("email_text", "pay", match_mode="body"), email) is True
        assert auto_trigger._match_condition(
            _cond("email_text", "invoice", match_mode="body"), email) is False

    def test_anywhere_scope(self):
        email = _MutableEmail(subject="Invoice #42", body="please pay")
        assert auto_trigger._match_condition(
            _cond("email_text", "invoice", match_mode="anywhere"), email) is True
        assert auto_trigger._match_condition(
            _cond("email_text", "pay", match_mode="anywhere"), email) is True
        assert auto_trigger._match_condition(
            _cond("email_text", "zzz", match_mode="anywhere"), email) is False


class TestCalendarInviteMatchModes:
    def test_any_detects_ics_attachment(self):
        email = _MutableEmail(attachments_meta="invite.ics")
        assert auto_trigger._match_condition(
            _cond("calendar_invite", "true", match_mode="any"), email) is True

    def test_any_misses_plain_email(self):
        email = _MutableEmail(subject="lunch?", body="wanna grab food")
        assert auto_trigger._match_condition(
            _cond("calendar_invite", "true", match_mode="any"), email) is False

    def test_free_matches_when_user_is_free(self, monkeypatch):
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        )
        monkeypatch.setattr(auto_trigger, "_extract_invite_window", lambda *a, **k: window)
        monkeypatch.setattr(auto_trigger, "_is_user_busy_window", lambda *a, **k: False)
        assert auto_trigger._match_condition(
            _cond("calendar_invite", "true", match_mode="free"),
            _MutableEmail(), account_id=1) is True

    def test_free_misses_when_user_is_busy(self, monkeypatch):
        window = (
            datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        )
        monkeypatch.setattr(auto_trigger, "_extract_invite_window", lambda *a, **k: window)
        monkeypatch.setattr(auto_trigger, "_is_user_busy_window", lambda *a, **k: True)
        assert auto_trigger._match_condition(
            _cond("calendar_invite", "true", match_mode="free"),
            _MutableEmail(), account_id=1) is False

    def test_free_fails_closed_without_invite_window(self, monkeypatch):
        # Not a calendar invite → no window → fail closed.
        monkeypatch.setattr(auto_trigger, "_extract_invite_window", lambda *a, **k: None)
        assert auto_trigger._match_condition(
            _cond("calendar_invite", "true", match_mode="free"),
            _MutableEmail(), account_id=1) is False

    def test_is_user_busy_window_returns_true_on_deepwork_conflict(self, monkeypatch):
        # Deep-work / focus blocks are local settings the calendar provider
        # never sees. _is_user_busy_window checks them first and short-circuits
        # to busy=True without touching the calendar — so a focus-time conflict
        # is caught even when the calendar API is unreachable.
        monkeypatch.setattr(auto_trigger, "_has_deepwork_conflict", lambda *a, **k: True)
        start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        assert auto_trigger._is_user_busy_window(1, start, end) is True

    def test_is_user_busy_window_no_deepwork_falls_through_to_calendar(self, monkeypatch):
        # No deep-work conflict → fall through to the calendar freebusy check.
        # Here no OAuth account resolves, so the calendar path returns None
        # (fail-closed) — proving the deep-work check didn't swallow the call.
        monkeypatch.setattr(auto_trigger, "_has_deepwork_conflict", lambda *a, **k: False)
        monkeypatch.setattr(auto_trigger, "_resolve_oauth_account_id", lambda *a, **k: None)
        start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        assert auto_trigger._is_user_busy_window(1, start, end) is None


class TestLegacyConditionBackCompat:
    """Legacy v1 conditions still match — migration runs at _match_condition
    entry, so a row persisted before the v2 refactor fires identically."""

    def test_legacy_sender_regex_still_matches(self):
        assert auto_trigger._match_condition(
            {"type": "sender_regex", "value": "noreply"},
            _MutableEmail(sender="noreply@acme.com")) is True

    def test_legacy_subject_or_body_keyword_still_matches(self):
        assert auto_trigger._match_condition(
            {"type": "subject_or_body_keyword", "value": "invoice"},
            _MutableEmail(subject="", body="the invoice is attached")) is True

    def test_legacy_is_calendar_invite_still_matches(self):
        assert auto_trigger._match_condition(
            {"type": "is_calendar_invite", "value": "true"},
            _MutableEmail(attachments_meta="x.ics")) is True

    def test_legacy_bare_sender_still_exact_matches(self):
        # v1 bare ``sender`` did exact match — migration maps it to "is".
        email = _MutableEmail(sender="boss@acme.com")
        assert auto_trigger._match_condition(
            {"type": "sender", "value": "boss@acme.com"}, email) is True
        assert auto_trigger._match_condition(
            {"type": "sender", "value": "acme.com"}, email) is False
