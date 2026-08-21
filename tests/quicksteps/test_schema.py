# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Schema validation for Quick Step payloads.

Locks down the action grammar so a malformed or hostile body never reaches
the execution engine. Every reject path returns a deterministic error
message — those messages are surfaced to the user, so we test them.
"""
from __future__ import annotations

import uuid

import pytest

from app.quicksteps import schema


def _new_id() -> str:
    return str(uuid.uuid4())


def _step(**overrides) -> dict:
    base = {
        "id": _new_id(),
        "name": "Test step",
        "actions": [{"type": "archive"}],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Identity / structure
# --------------------------------------------------------------------------- #

class TestStructuralValidation:
    def test_rejects_non_dict(self):
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step("not a dict")

    def test_rejects_missing_id(self):
        with pytest.raises(schema.ValidationError, match="id"):
            schema.validate_quick_step({"name": "x", "actions": [{"type": "archive"}]})

    def test_rejects_non_uuid_id(self):
        with pytest.raises(schema.ValidationError, match="UUID"):
            schema.validate_quick_step(_step(id="not-a-uuid"))

    def test_rejects_id_mismatch_on_patch(self):
        body = _step()
        with pytest.raises(schema.ValidationError, match="does not match"):
            schema.validate_quick_step(body, existing_id=_new_id())

    def test_accepts_omitted_id_when_existing_id_supplied(self):
        body = {"name": "x", "actions": [{"type": "archive"}]}
        target = _new_id()
        cleaned = schema.validate_quick_step(body, existing_id=target)
        assert cleaned["id"] == target


class TestNameAndIcon:
    def test_rejects_empty_name(self):
        with pytest.raises(schema.ValidationError, match="name"):
            schema.validate_quick_step(_step(name="   "))

    def test_rejects_oversized_name(self):
        with pytest.raises(schema.ValidationError, match="name"):
            schema.validate_quick_step(_step(name="x" * (schema.NAME_MAX_LENGTH + 1)))

    def test_strips_whitespace_from_name(self):
        cleaned = schema.validate_quick_step(_step(name="  Triage  "))
        assert cleaned["name"] == "Triage"

    def test_optional_icon(self):
        cleaned = schema.validate_quick_step(_step(icon="zap"))
        assert cleaned["icon"] == "zap"

    def test_rejects_oversized_icon(self):
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(_step(icon="x" * (schema.ICON_MAX_LENGTH + 1)))


# --------------------------------------------------------------------------- #
# Shortcuts
# --------------------------------------------------------------------------- #

class TestShortcutValidation:
    def test_simple_digit_shortcut(self):
        cleaned = schema.validate_quick_step(_step(shortcut="1"))
        assert cleaned["shortcut"] == "1"

    def test_modifier_combination_normalizes(self):
        cleaned = schema.validate_quick_step(_step(shortcut="Shift+Ctrl+a"))
        # Normalized order: ctrl, shift, alt, meta
        assert cleaned["shortcut"] == "ctrl+shift+a"

    def test_lowercase_normalization(self):
        cleaned = schema.validate_quick_step(_step(shortcut="CTRL+1"))
        assert cleaned["shortcut"] == "ctrl+1"

    def test_function_keys_allowed(self):
        cleaned = schema.validate_quick_step(_step(shortcut="f5"))
        assert cleaned["shortcut"] == "f5"

    @pytest.mark.parametrize("reserved", ["e", "r", "j", "k", "Delete", "Escape"])
    def test_rejects_reserved_bare_key(self, reserved):
        with pytest.raises(schema.ValidationError, match="reserved"):
            schema.validate_quick_step(_step(shortcut=reserved))

    def test_reserved_key_allowed_with_modifier(self):
        # Ctrl+E is fine even though bare 'e' is reserved.
        cleaned = schema.validate_quick_step(_step(shortcut="Ctrl+e"))
        assert cleaned["shortcut"] == "ctrl+e"

    @pytest.mark.parametrize("bad", ["  ", "ctrl+", "++", "++a", "abc", "shift"])
    def test_rejects_malformed_shortcut(self, bad):
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(_step(shortcut=bad))

    def test_duplicate_modifier_dedupes(self):
        cleaned = schema.validate_quick_step(_step(shortcut="ctrl+ctrl+a"))
        assert cleaned["shortcut"] == "ctrl+a"

    def test_empty_shortcut_treated_as_none(self):
        # Frontend may send "" to clear a shortcut — treat as no shortcut.
        cleaned = schema.validate_quick_step(_step(shortcut=""))
        assert cleaned["shortcut"] is None


# --------------------------------------------------------------------------- #
# Actions — per-type payload shape
# --------------------------------------------------------------------------- #

class TestActionGrammar:
    def test_rejects_empty_actions(self):
        with pytest.raises(schema.ValidationError, match="non-empty"):
            schema.validate_quick_step(_step(actions=[]))

    def test_rejects_non_list_actions(self):
        with pytest.raises(schema.ValidationError):
            schema.validate_quick_step(_step(actions={"type": "archive"}))

    def test_rejects_too_many_actions(self):
        actions = [{"type": "archive"}] * (schema.MAX_ACTIONS_PER_STEP + 1)
        with pytest.raises(schema.ValidationError, match="action limit"):
            schema.validate_quick_step(_step(actions=actions))

    def test_rejects_unknown_action_type(self):
        with pytest.raises(schema.ValidationError, match="unknown type"):
            schema.validate_quick_step(_step(actions=[{"type": "wat"}]))

    def test_mark_read_requires_value(self):
        with pytest.raises(schema.ValidationError, match="mark_read"):
            schema.validate_quick_step(_step(actions=[{"type": "mark_read", "payload": {}}]))

    def test_mark_read_coerces_to_bool(self):
        cleaned = schema.validate_quick_step(
            _step(actions=[{"type": "mark_read", "payload": {"value": 1}}])
        )
        assert cleaned["actions"][0]["payload"]["value"] is True

    def test_reply_template_requires_body(self):
        with pytest.raises(schema.ValidationError, match="reply_template.body"):
            schema.validate_quick_step(
                _step(actions=[{"type": "reply_template", "payload": {"body": "  "}}])
            )

    def test_reply_template_defaults(self):
        cleaned = schema.validate_quick_step(
            _step(actions=[{"type": "reply_template", "payload": {"body": "Hi {sender.firstname}"}}])
        )
        action = cleaned["actions"][0]
        assert action["payload"]["replyAll"] is False
        assert action["payload"]["includeQuoted"] is True

    def test_forward_requires_recipients(self):
        # Error message changed when to_groups was added — match the current
        # phrasing instead of the legacy "forward.to" wording.
        with pytest.raises(schema.ValidationError, match="at least one recipient"):
            schema.validate_quick_step(
                _step(actions=[{"type": "forward", "payload": {"to": []}}])
            )

    def test_forward_validates_each_recipient(self):
        with pytest.raises(schema.ValidationError, match="not a valid email"):
            schema.validate_quick_step(
                _step(actions=[{"type": "forward", "payload": {"to": ["ok@x.com", "garbage"]}}])
            )

    def test_forward_caps_recipients(self):
        many = [f"r{i}@example.com" for i in range(schema.MAX_FORWARD_RECIPIENTS + 1)]
        with pytest.raises(schema.ValidationError, match="recipients"):
            schema.validate_quick_step(
                _step(actions=[{"type": "forward", "payload": {"to": many}}])
            )

    def test_forward_lowercases_emails(self):
        cleaned = schema.validate_quick_step(
            _step(actions=[{"type": "forward", "payload": {"to": ["UP@CASE.com"]}}])
        )
        assert cleaned["actions"][0]["payload"]["to"] == ["up@case.com"]

    def test_delete_must_be_terminal(self):
        with pytest.raises(schema.ValidationError, match="delete"):
            schema.validate_quick_step(
                _step(actions=[{"type": "delete"}, {"type": "archive"}])
            )

    def test_delete_alone_is_fine(self):
        schema.validate_quick_step(_step(actions=[{"type": "delete"}]))

    def test_chain_archive_then_delete_is_fine(self):
        # delete is allowed as the LAST action even after another step.
        schema.validate_quick_step(_step(actions=[{"type": "archive"}, {"type": "delete"}]))


# --------------------------------------------------------------------------- #
# mark_with_emoji — emoji/text/color/chip grammar
# --------------------------------------------------------------------------- #


def _emoji_payload(**payload) -> dict:
    return _step(actions=[{"type": "mark_with_emoji", "payload": payload}])


class TestMarkWithEmojiPayload:
    # -- emoji whitelist (existing behaviour) -------------------------------- #
    def test_accepts_whitelisted_emoji(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰"))
        assert cleaned["actions"][0]["payload"]["emoji"] == "💰"

    def test_rejects_off_whitelist_emoji(self):
        with pytest.raises(schema.ValidationError, match="curated set"):
            schema.validate_quick_step(_emoji_payload(emoji="🥑"))

    # -- text-only marker (the "No emoji" tile, currently broken) ------------ #
    def test_accepts_text_only_when_emoji_omitted(self):
        cleaned = schema.validate_quick_step(_emoji_payload(text="VIP"))
        payload = cleaned["actions"][0]["payload"]
        assert payload["text"] == "VIP"
        assert "emoji" not in payload

    def test_accepts_text_only_with_empty_emoji_string(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="", text="VIP"))
        payload = cleaned["actions"][0]["payload"]
        assert payload["text"] == "VIP"
        assert "emoji" not in payload

    def test_rejects_both_emoji_and_text_empty(self):
        with pytest.raises(schema.ValidationError, match="emoji or text"):
            schema.validate_quick_step(_emoji_payload(emoji="", text="   "))

    def test_rejects_when_neither_emoji_nor_text_present(self):
        with pytest.raises(schema.ValidationError, match="emoji or text"):
            schema.validate_quick_step(_emoji_payload())

    # -- color (new: palette-constrained, mirrors LABEL_COLORS) -------------- #
    def test_accepts_palette_color(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰", color="#dc2626"))
        assert cleaned["actions"][0]["payload"]["color"] == "#dc2626"

    def test_rejects_off_palette_color(self):
        with pytest.raises(schema.ValidationError, match="color"):
            schema.validate_quick_step(_emoji_payload(emoji="💰", color="#000000"))

    def test_rejects_non_string_color(self):
        with pytest.raises(schema.ValidationError, match="color"):
            schema.validate_quick_step(_emoji_payload(emoji="💰", color=123))

    def test_color_absent_leaves_no_color_key(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰"))
        assert "color" not in cleaned["actions"][0]["payload"]

    def test_every_palette_color_is_accepted(self):
        # Lock the whitelist to LABEL_COLORS — divergence here means the
        # picker offers a swatch the validator rejects on save.
        for color in schema._EMOJI_MARKER_COLOR_WHITELIST:
            cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰", color=color))
            assert cleaned["actions"][0]["payload"]["color"] == color

    # -- chip toggle (new: bool, default True = current pill rendering) ------ #
    def test_chip_defaults_to_true(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰"))
        assert cleaned["actions"][0]["payload"]["chip"] is True

    def test_chip_false_is_preserved(self):
        cleaned = schema.validate_quick_step(_emoji_payload(emoji="💰", chip=False))
        assert cleaned["actions"][0]["payload"]["chip"] is False


# --------------------------------------------------------------------------- #
# confirmBeforeRun default
# --------------------------------------------------------------------------- #

class TestConfirmBeforeRunDefault:
    def test_archive_only_default_false(self):
        cleaned = schema.validate_quick_step(_step(actions=[{"type": "archive"}]))
        assert cleaned["confirmBeforeRun"] is False

    def test_chain_with_reply_default_true(self):
        cleaned = schema.validate_quick_step(
            _step(actions=[{"type": "reply_template", "payload": {"body": "ok"}}])
        )
        assert cleaned["confirmBeforeRun"] is True

    def test_chain_with_forward_default_true(self):
        cleaned = schema.validate_quick_step(
            _step(actions=[{"type": "forward", "payload": {"to": ["a@b.com"]}}])
        )
        assert cleaned["confirmBeforeRun"] is True

    def test_explicit_false_overrides_default(self):
        cleaned = schema.validate_quick_step(
            _step(
                actions=[{"type": "forward", "payload": {"to": ["a@b.com"]}}],
                confirmBeforeRun=False,
            )
        )
        assert cleaned["confirmBeforeRun"] is False


# --------------------------------------------------------------------------- #
# description — free-text override of the card's auto-summary line.
# Optional. Empty / whitespace-only normalize to None so the card falls
# back to the auto-generated trigger summary.
# --------------------------------------------------------------------------- #


class TestDescriptionField:
    def test_omitted_returns_none(self):
        cleaned = schema.validate_quick_step(_step())
        assert cleaned["description"] is None

    def test_explicit_value_round_trips(self):
        cleaned = schema.validate_quick_step(
            _step(description="Forward shipping notifs to ops, archive after."),
        )
        assert cleaned["description"] == "Forward shipping notifs to ops, archive after."

    def test_empty_string_normalized_to_none(self):
        cleaned = schema.validate_quick_step(_step(description=""))
        assert cleaned["description"] is None

    def test_whitespace_only_normalized_to_none(self):
        cleaned = schema.validate_quick_step(_step(description="   \n  "))
        assert cleaned["description"] is None

    def test_rejects_over_max_length(self):
        too_long = "a" * (schema.DESCRIPTION_MAX_LENGTH + 1)
        with pytest.raises(schema.ValidationError, match="description"):
            schema.validate_quick_step(_step(description=too_long))

    def test_accepts_at_max_length(self):
        at_max = "a" * schema.DESCRIPTION_MAX_LENGTH
        cleaned = schema.validate_quick_step(_step(description=at_max))
        assert cleaned["description"] == at_max

    def test_non_string_ignored(self):
        # Defensive: a malformed client (or a stale fixture) sending a
        # non-string field shouldn't crash the validator — we just
        # normalize to None so the card falls back to auto-summary.
        cleaned = schema.validate_quick_step(_step(description=42))
        assert cleaned["description"] is None


# --------------------------------------------------------------------------- #
# showAutoBadge — UX request 2026-05-12. Toggle controls the ⚡ Auto chip on
# emails this rule auto-actions. Default True so new rules are transparent.
# --------------------------------------------------------------------------- #

class TestShowAutoBadgeDefault:
    def test_omitted_defaults_to_true(self):
        cleaned = schema.validate_quick_step(_step())
        assert cleaned["showAutoBadge"] is True

    def test_explicit_true_preserved(self):
        cleaned = schema.validate_quick_step(_step(showAutoBadge=True))
        assert cleaned["showAutoBadge"] is True

    def test_explicit_false_preserved(self):
        cleaned = schema.validate_quick_step(_step(showAutoBadge=False))
        assert cleaned["showAutoBadge"] is False

    def test_truthy_non_bool_coerced(self):
        """Tolerate string / int truthy values from older clients."""
        cleaned = schema.validate_quick_step(_step(showAutoBadge=1))
        assert cleaned["showAutoBadge"] is True

    def test_falsy_non_bool_coerced(self):
        cleaned = schema.validate_quick_step(_step(showAutoBadge=0))
        assert cleaned["showAutoBadge"] is False

    def test_field_round_trips_with_auto_enabled(self):
        """A rule with autoEnabled+triggers must keep its badge toggle
        through validation — the route surface relies on this."""
        cleaned = schema.validate_quick_step(_step(
            autoEnabled=True,
            triggers=[{"type": "sender_domain", "value": "newsletter.io"}],
            showAutoBadge=False,
        ))
        assert cleaned["autoEnabled"] is True
        assert cleaned["showAutoBadge"] is False


# --------------------------------------------------------------------------- #
# Collection-level validation (used when importing/seeding)
# --------------------------------------------------------------------------- #

class TestCollection:
    def test_empty_list_ok(self):
        assert schema.validate_collection([]) == []

    def test_rejects_non_list(self):
        with pytest.raises(schema.ValidationError):
            schema.validate_collection({"oops": True})

    def test_rejects_overall_quota(self):
        too_many = [_step() for _ in range(schema.MAX_QUICK_STEPS_PER_ACCOUNT + 1)]
        with pytest.raises(schema.ValidationError, match="more than"):
            schema.validate_collection(too_many)

    def test_rejects_duplicate_ids(self):
        shared = _new_id()
        with pytest.raises(schema.ValidationError, match="Duplicate"):
            schema.validate_collection([_step(id=shared), _step(id=shared)])

    def test_rejects_duplicate_shortcuts(self):
        with pytest.raises(schema.ValidationError, match="used by both"):
            schema.validate_collection([
                _step(name="A", shortcut="1"),
                _step(name="B", shortcut="1"),
            ])

    def test_normalized_shortcut_collision_detected(self):
        # Different surface form, same normalized value.
        with pytest.raises(schema.ValidationError, match="used by both"):
            schema.validate_collection([
                _step(name="A", shortcut="Ctrl+Shift+1"),
                _step(name="B", shortcut="Shift+Ctrl+1"),
            ])


# --------------------------------------------------------------------------- #
# Trigger conditions — v2 {type, match_mode} grammar + legacy migration.
# `_validate_trigger_condition` runs `migrate_legacy_condition` first, then
# enforces: type in the 15-type set, match_mode required on the 5 operator-
# bearing types and rejected on the rest, regex checks gated on
# match_mode == "matches".
# --------------------------------------------------------------------------- #

class TestTriggerConditionValidation:
    def _triggers(self, *conditions) -> list[dict]:
        """Validate a step carrying ``conditions`` and return the cleaned
        trigger list. autoEnabled=True keeps it a realistic auto-rule
        (triggers are validated regardless of that flag)."""
        cleaned = schema.validate_quick_step(_step(
            autoEnabled=True,
            triggers=list(conditions),
        ))
        return cleaned["triggers"]

    # -- legacy input → new canonical output (locks the migration contract) - #

    def test_legacy_sender_regex_canonicalised(self):
        assert self._triggers({"type": "sender_regex", "value": "noreply"}) == [
            {"type": "sender", "match_mode": "matches", "value": "noreply"}
        ]

    def test_legacy_subject_or_body_keyword_canonicalised(self):
        assert self._triggers({"type": "subject_or_body_keyword", "value": "invoice"}) == [
            {"type": "email_text", "match_mode": "anywhere", "value": "invoice"}
        ]

    def test_legacy_is_calendar_invite_canonicalised(self):
        assert self._triggers({"type": "is_calendar_invite", "value": "true"}) == [
            {"type": "calendar_invite", "match_mode": "any", "value": "true"}
        ]

    def test_legacy_bare_sender_gets_default_match_mode(self):
        # A bare legacy ``sender`` is back-filled with match_mode="is" by
        # migration — it must NOT fail validation.
        assert self._triggers({"type": "sender", "value": "boss@acme.com"}) == [
            {"type": "sender", "match_mode": "is", "value": "boss@acme.com"}
        ]

    def test_legacy_negate_preserved(self):
        cleaned = self._triggers(
            {"type": "subject_keyword", "value": "spam", "negate": True}
        )
        assert cleaned == [
            {"type": "email_text", "match_mode": "subject", "value": "spam", "negate": True}
        ]

    # -- new-shape conditions round-trip ----------------------------------- #

    def test_new_shape_email_text_round_trips(self):
        assert self._triggers({"type": "email_text", "match_mode": "subject", "value": "x"}) == [
            {"type": "email_text", "match_mode": "subject", "value": "x"}
        ]

    def test_new_shape_calendar_invite_without_value_ok(self):
        # Migration injects value="true" so the matcher's empty-value guard
        # doesn't drop it; validation then accepts it.
        assert self._triggers({"type": "calendar_invite", "match_mode": "free"}) == [
            {"type": "calendar_invite", "match_mode": "free", "value": "true"}
        ]

    # -- match_mode required / rejected per type --------------------------- #

    def test_match_mode_rejected_on_non_operator_type(self):
        with pytest.raises(schema.ValidationError, match="does not take a match_mode"):
            self._triggers({"type": "has_label", "match_mode": "is", "value": "VIP"})

    def test_email_text_requires_match_mode(self):
        # email_text is a v2-only type — a bare one (no match_mode) is a
        # genuine error, not something migration back-fills.
        with pytest.raises(schema.ValidationError, match="requires match_mode"):
            self._triggers({"type": "email_text", "value": "x"})

    def test_invalid_match_mode_rejected(self):
        with pytest.raises(schema.ValidationError, match="requires match_mode"):
            self._triggers({"type": "sender", "match_mode": "bogus", "value": "x"})

    def test_unknown_condition_type_rejected(self):
        with pytest.raises(schema.ValidationError, match="unknown type"):
            self._triggers({"type": "made_up_type", "value": "x"})

    # -- regex validation keyed on match_mode == "matches" ----------------- #

    def test_redos_pattern_rejected_on_matches(self):
        # Audit F-08 (2026-05-16) reworded the ReDoS shape rejection from
        # "nested quantifiers" to "catastrophic-backtracking shape" and
        # expanded the patterns enumerated (now also catches
        # alternation-with-quantifier and overlapping quantifiers).
        with pytest.raises(schema.ValidationError, match="catastrophic-backtracking shape"):
            self._triggers({"type": "sender", "match_mode": "matches", "value": "(a+)+"})

    def test_invalid_regex_rejected_on_matches(self):
        with pytest.raises(schema.ValidationError, match="regex is invalid"):
            self._triggers({"type": "sender", "match_mode": "matches", "value": "("})

    def test_regex_shapes_allowed_when_match_mode_is_contains(self):
        # match_mode "contains" treats value as a literal substring, never a
        # regex — a "(a+)+" string must NOT trip the ReDoS guard.
        assert self._triggers({"type": "sender", "match_mode": "contains", "value": "(a+)+"}) == [
            {"type": "sender", "match_mode": "contains", "value": "(a+)+"}
        ]
