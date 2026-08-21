# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Legacy → v2 trigger-condition migration.

``migrate_legacy_condition`` upgrades the pre-2026-05-14 condition
vocabulary — where the ``type`` string encoded the match operator
(``sender_regex``, ``subject_keyword``, ``is_calendar_invite`` …) — to
the current ``{type, match_mode}`` shape. It is the single migration
helper called from three layers (write-path validation, read-path
normalization, matcher entry), so it MUST be total and idempotent.
"""
from __future__ import annotations

from app.quicksteps.schema import migrate_legacy_condition


class TestRegexVariantsFold:
    def test_sender_regex_becomes_sender_matches(self):
        out = migrate_legacy_condition({"type": "sender_regex", "value": "noreply|no-reply"})
        assert out == {"type": "sender", "match_mode": "matches", "value": "noreply|no-reply"}

    def test_sender_domain_regex_becomes_sender_domain_matches(self):
        out = migrate_legacy_condition(
            {"type": "sender_domain_regex", "value": r"\.google\.com$"}
        )
        assert out == {
            "type": "sender_domain",
            "match_mode": "matches",
            "value": r"\.google\.com$",
        }


class TestKeywordVariantsFold:
    def test_subject_keyword_becomes_email_text_subject(self):
        out = migrate_legacy_condition({"type": "subject_keyword", "value": "invoice"})
        assert out == {"type": "email_text", "match_mode": "subject", "value": "invoice"}

    def test_content_keyword_becomes_email_text_body(self):
        out = migrate_legacy_condition({"type": "content_keyword", "value": "?"})
        assert out == {"type": "email_text", "match_mode": "body", "value": "?"}

    def test_subject_or_body_keyword_becomes_email_text_anywhere(self):
        out = migrate_legacy_condition({"type": "subject_or_body_keyword", "value": "urgent"})
        assert out == {"type": "email_text", "match_mode": "anywhere", "value": "urgent"}


class TestIsNewThreadFalseNormalization:
    """`is_new_thread value="false"` (the "Follow-up existing thread" starter)
    is canonicalised onto the ``negate`` field — the only encoding the
    editor's label/badge/toggle understand. Without it the row is mislabeled
    "new thread" and re-save would corrupt value back to "true". Lossless for
    the matcher (value="false" ≡ value="true"+negate flipped); idempotent.
    """

    def test_value_false_becomes_negate_true(self):
        out = migrate_legacy_condition({"type": "is_new_thread", "value": "false"})
        assert out == {"type": "is_new_thread", "value": "true", "negate": True}

    def test_idempotent(self):
        once = migrate_legacy_condition({"type": "is_new_thread", "value": "false"})
        assert migrate_legacy_condition(once) == once

    def test_value_true_untouched(self):
        out = migrate_legacy_condition({"type": "is_new_thread", "value": "true"})
        assert out == {"type": "is_new_thread", "value": "true"}

    def test_double_negative_collapses(self):
        # value="false" + negate=true == new thread == value="true" + negate=false
        out = migrate_legacy_condition(
            {"type": "is_new_thread", "value": "false", "negate": True}
        )
        assert out == {"type": "is_new_thread", "value": "true", "negate": False}


class TestCalendarVariantsFold:
    def test_is_calendar_invite_becomes_calendar_invite_any(self):
        out = migrate_legacy_condition({"type": "is_calendar_invite", "value": "true"})
        assert out == {"type": "calendar_invite", "match_mode": "any", "value": "true"}

    def test_available_for_invite_becomes_calendar_invite_free(self):
        out = migrate_legacy_condition({"type": "available_for_invite", "value": "true"})
        assert out == {"type": "calendar_invite", "match_mode": "free", "value": "true"}

    def test_calendar_invite_value_injected_when_legacy_lacked_one(self):
        # A legacy is_calendar_invite with no value still has to survive the
        # matcher's empty-value guard — migration injects the sentinel.
        out = migrate_legacy_condition({"type": "is_calendar_invite"})
        assert out == {"type": "calendar_invite", "match_mode": "any", "value": "true"}

    def test_new_shape_calendar_invite_without_value_gets_sentinel(self):
        # Defense-in-depth: a value-less new-shape calendar_invite (frontend
        # bug / partial record) gets the sentinel rather than silently never
        # matching.
        out = migrate_legacy_condition({"type": "calendar_invite", "match_mode": "free"})
        assert out == {"type": "calendar_invite", "match_mode": "free", "value": "true"}


class TestImplicitMatchMode:
    def test_bare_sender_gets_is(self):
        # Legacy ``sender`` did exact match — that becomes match_mode "is".
        out = migrate_legacy_condition({"type": "sender", "value": "boss@acme.com"})
        assert out == {"type": "sender", "match_mode": "is", "value": "boss@acme.com"}

    def test_bare_sender_domain_gets_is(self):
        out = migrate_legacy_condition({"type": "sender_domain", "value": "acme.com"})
        assert out == {"type": "sender_domain", "match_mode": "is", "value": "acme.com"}

    def test_bare_recipient_gets_contains(self):
        # Legacy ``recipient`` did substring match — that becomes "contains".
        out = migrate_legacy_condition({"type": "recipient", "value": "team@acme.com"})
        assert out == {"type": "recipient", "match_mode": "contains", "value": "team@acme.com"}


class TestPassthroughTypes:
    def test_has_label_unchanged(self):
        cond = {"type": "has_label", "value": "VIP"}
        assert migrate_legacy_condition(cond) == cond

    def test_is_read_unchanged(self):
        cond = {"type": "is_read", "value": "true"}
        assert migrate_legacy_condition(cond) == cond

    def test_has_attachment_unchanged(self):
        cond = {"type": "has_attachment", "value": "true"}
        assert migrate_legacy_condition(cond) == cond

    def test_email_older_than_days_unchanged(self):
        cond = {"type": "email_older_than_days", "value": "30"}
        assert migrate_legacy_condition(cond) == cond

    def test_workflow_and_boolean_types_unchanged(self):
        for ctype in (
            "is_new_thread",
            "thread_has_user_reply",
            "previously_auto_actioned_by",
            "has_emoji_marker",
            "has_deadline_detected",
            "no_reply_after_days",
        ):
            cond = {"type": ctype, "value": "true"}
            assert migrate_legacy_condition(cond) == cond


class TestIdempotency:
    def test_already_migrated_sender_unchanged(self):
        cond = {"type": "sender", "match_mode": "matches", "value": "noreply"}
        assert migrate_legacy_condition(cond) == cond

    def test_already_migrated_email_text_unchanged(self):
        cond = {"type": "email_text", "match_mode": "body", "value": "?"}
        assert migrate_legacy_condition(cond) == cond

    def test_double_migration_is_stable(self):
        once = migrate_legacy_condition({"type": "sender_regex", "value": "x"})
        twice = migrate_legacy_condition(once)
        assert once == twice

    def test_explicit_match_mode_on_legacy_alias_preserved(self):
        # If a record somehow carries a legacy type AND a match_mode,
        # setdefault keeps the explicit one rather than overwriting it.
        out = migrate_legacy_condition(
            {"type": "sender_regex", "match_mode": "contains", "value": "x"}
        )
        assert out == {"type": "sender", "match_mode": "contains", "value": "x"}


class TestFieldPreservation:
    def test_negate_preserved_through_alias(self):
        out = migrate_legacy_condition(
            {"type": "subject_keyword", "value": "spam", "negate": True}
        )
        assert out == {
            "type": "email_text",
            "match_mode": "subject",
            "value": "spam",
            "negate": True,
        }

    def test_negate_preserved_through_implicit_mode(self):
        out = migrate_legacy_condition({"type": "sender", "value": "x", "negate": True})
        assert out["negate"] is True
        assert out["match_mode"] == "is"

    def test_does_not_mutate_input(self):
        original = {"type": "sender_regex", "value": "x"}
        migrate_legacy_condition(original)
        assert original == {"type": "sender_regex", "value": "x"}


class TestTotality:
    def test_non_dict_returned_unchanged(self):
        assert migrate_legacy_condition("nope") == "nope"
        assert migrate_legacy_condition(None) is None
        assert migrate_legacy_condition(42) == 42

    def test_unknown_type_passthrough(self):
        cond = {"type": "totally_made_up", "value": "x"}
        assert migrate_legacy_condition(cond) == cond

    def test_missing_type_passthrough(self):
        cond = {"value": "x"}
        assert migrate_legacy_condition(cond) == cond

    def test_empty_dict_passthrough(self):
        assert migrate_legacy_condition({}) == {}
