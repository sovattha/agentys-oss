# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Validation for Quick Step payloads.

Plain-dict validation matching the existing settings.py pattern in this
codebase (no Pydantic — it's not a dependency). Each validator returns
either a cleaned value or raises ``ValidationError`` with a user-facing
message that the route layer surfaces as a 400 response.

Action grammar (v1):
- ``archive``                     no payload
- ``delete``                      no payload
- ``mark_read``       payload: {value: bool}
- ``move_to_spam``               no payload
- ``reply_template``  payload: {body: str, replyAll: bool, includeQuoted: bool}
- ``forward``         payload: {to: list[str], subject_prefix?: str, body?: str}

Reserved shortcuts cannot be assigned (collide with existing app bindings).
"""
from __future__ import annotations

import re
import threading
from typing import Any


class ValidationError(ValueError):
    """User-facing validation failure. Message is safe to surface as 400 body."""


_ALLOWED_ACTION_TYPES = frozenset({
    "archive",
    "unarchive",
    "delete",
    "mark_read",
    "move_to_spam",
    "pin",
    "reply_template",
    "forward",
    "rsvp_meeting",
    # Eager-create a PendingDraft for a sent thread and snooze it for
    # ``delay_days`` in "Later". When the snooze elapses the wake-time
    # sweep checks if the recipient replied — if so the draft is deleted,
    # otherwise it surfaces in regular Drafts with the ⚡ Auto badge.
    # firesOn="sent" only (cross-flow guard below).
    "create_snoozed_followup_draft",
    # Stamp a curated emoji + optional text on the email row. Renders as a
    # chip right after the subject (e.g. "Re: Invoice 💰 Stripe · Mar 15").
    # Optional ``include_deadline`` merges the auto-detected deadline into
    # the chip and hides the standalone clock chip. firesOn="received" only.
    "mark_with_emoji",
    # Apply a label to the email's LabelStore assignment. payload: {label}.
    # A default-category name (Action/FYI/Noise) replaces the category; any
    # other name is added as a custom label — LabelAssignment.add_label
    # owns that routing.
    "apply_label",
    # Schedule a local reminder ``days_before`` the deadline detected on the
    # email (``emails.deadline_at``, else a live extract). Non-destructive,
    # no provider write — fires through reminder_service. firesOn="received".
    "create_reminder",
    # Create an event on the connected calendar ``days_before`` the detected
    # deadline (duration ``duration_minutes``). Needs calendar write scope.
    # firesOn="received".
    "create_calendar_event",
})

# Curated whitelist of emojis the ``mark_with_emoji`` action accepts.
# Work-relevant only — keeps the picker scannable and prevents users from
# planting "🥑" on a client email by accident. Order is the picker's
# display order (urgency → status → context → outcomes).
_EMOJI_MARKER_WHITELIST = frozenset({
    "🔥", "🚨", "⚠️", "⏰",
    "✅", "📌",
    "💰", "💼", "📋", "🎯",
    "⭐", "🤝",
    "📞", "💬",
    "🎉", "🔒", "📊",
    "🔁",
})

# Max length of the optional ``text`` companion field on mark_with_emoji.
# Short enough that "{emoji} {text} · {date}" doesn't blow past the
# subject-line ellipsis budget on a 320 px row.
_EMOJI_MARKER_TEXT_MAX = 24

# Palette-constrained color the ``mark_with_emoji`` action accepts on its
# optional ``color`` field. MUST mirror ``LABEL_COLORS`` in
# agentys-app/src/types/labels.ts — the FE swatch picker reuses that palette,
# and the inbox row applies the value as a CSS color, so anything off-palette
# is both a contrast risk (dark mode) and a style-injection vector. Keep the
# two lists in lockstep.
_EMOJI_MARKER_COLOR_WHITELIST = frozenset({
    "#dc2626",  # Red
    "#ea580c",  # Orange
    "#eab308",  # Yellow
    "#22c55e",  # Green
    "#0d9488",  # Teal
    "#3b82f6",  # Blue
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#6b7280",  # Grey
    "#1f2937",  # Dark
})

# Trigger condition vocabulary (v2, 2026-05-14). Each condition is a
# ``{type, match_mode?, value, negate?}`` dict. The five text/calendar
# types carry a polymorphic ``match_mode`` (see _MATCH_MODE_VALUES); the
# rest have none. Legacy v1 conditions — where the ``type`` itself
# encoded the operator (``sender_regex``, ``subject_keyword``,
# ``is_calendar_invite`` …) — are upgraded by ``migrate_legacy_condition``
# before they ever reach validation. Mirrors TriggerConditionType in
# agentys-app/src/types/quickStep.ts.
_TRIGGER_CONDITION_TYPES = frozenset({
    # Who it's from — match_mode is one of is / contains / matches.
    "sender",
    "sender_domain",
    "recipient",
    # What's in it.
    "email_text",  # match_mode: anywhere / subject / body
    "has_attachment",
    # True iff the email-ingest pipeline extracted a deadline from the
    # body and stamped `emails.deadline_at`. Detection is automatic on
    # every received email — this condition just exposes the result.
    "has_deadline_detected",
    # What it is.
    "has_label",
    "is_read",
    # Calendar invitation. match_mode "any" matches every invite; "free"
    # additionally requires the user to be free at the proposed slot
    # (reads the invite's [DTSTART, DTEND] window, not "now").
    "calendar_invite",
    # Temporal — value is a positive int (days).
    "email_older_than_days",
    "no_reply_after_days",
    # Sent-side helper: a thread the user started (not a reply). Cheap
    # heuristic (no In-Reply-To header / no "Re:" subject prefix). Use
    # ``negate=true`` to match the inverse (reply / thread continuation)
    # — no separate ``is_reply`` condition exists.
    "is_new_thread",
    # Reply-side helper: true iff the user has sent at least one message
    # in this thread. Turns "reply then archive" into a regular rule.
    "thread_has_user_reply",
    # Workflow — value is the UUID of another (or the same) Quick Step.
    # True iff that step has already auto-fired successfully on any email
    # in the current thread. Unlocks reactive chains across emails.
    "previously_auto_actioned_by",
    # True iff the ``mark_with_emoji`` action already stamped a marker on
    # this email. Lets users chain rules ("if marked 💰 → label 'Billing'")
    # without repeating the emoji-marker condition inline.
    "has_emoji_marker",
})

# Condition types that carry a polymorphic ``match_mode`` field. The
# allowed values are type-specific. Every other condition type MUST NOT
# carry a match_mode — ``_validate_trigger_condition`` rejects a stray
# one. Mirrors TriggerMatchMode in agentys-app/src/types/quickStep.ts.
_MATCH_MODE_VALUES: dict[str, frozenset] = {
    "sender": frozenset({"is", "contains", "matches"}),
    "sender_domain": frozenset({"is", "contains", "matches"}),
    "recipient": frozenset({"is", "contains", "matches"}),
    "email_text": frozenset({"anywhere", "subject", "body"}),
    "calendar_invite": frozenset({"any", "free"}),
}

# Condition types whose ``value`` must be a positive integer (we accept the
# raw int as a string for transport, but the validator coerces+enforces it).
_INT_VALUE_CONDITION_TYPES = frozenset({
    "email_older_than_days",
    "no_reply_after_days",
})

# Hard caps on temporal values to keep evaluation cheap and predictable.
_MAX_DAYS_VALUE = 365  # 1 year — beyond this the condition is almost never useful
_MAX_REGEX_LENGTH = 200  # already enforced by TRIGGER_VALUE_MAX_LENGTH but explicit here

# Hotkeys already wired into App.tsx (lines ~795-908) and Linear-style nav.
# A Quick Step shortcut MUST NOT collide with any of these — see App.tsx.
_RESERVED_SHORTCUTS = frozenset({
    "e", "delete", "backspace",
    "r", "a", "f",
    "j", "k", "?", "/", "escape", "esc",
    "arrowup", "arrowdown", "arrowleft", "arrowright",
})

_SHORTCUT_PATTERN = re.compile(
    r"^(?:(?:ctrl|shift|alt|meta)\+){0,3}"
    r"(?:[a-z0-9]|f[1-9]|f1[0-2]|"
    r"delete|backspace|escape|esc|enter|return|tab|space|"
    r"arrowup|arrowdown|arrowleft|arrowright)$"
)

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

NAME_MAX_LENGTH = 80
ICON_MAX_LENGTH = 40
# Free-text description shown on the Quick Step card in place of the
# auto-generated trigger summary. Optional. 200 chars is enough for a
# clarifying sentence ("Forward shipping notifs to ops, archive after")
# without bloating the card layout.
DESCRIPTION_MAX_LENGTH = 200
TEMPLATE_BODY_MAX_LENGTH = 8000
SUBJECT_PREFIX_MAX_LENGTH = 80
LABEL_NAME_MAX_LENGTH = 80
TRIGGER_VALUE_MAX_LENGTH = 200
MAX_ACTIONS_PER_STEP = 10
MAX_TRIGGERS_PER_STEP = 5
MAX_FORWARD_RECIPIENTS = 10
MAX_QUICK_STEPS_PER_ACCOUNT = 50


def _normalize_shortcut(raw: str) -> str:
    """Lowercase + sort modifiers so 'Shift+Ctrl+1' == 'Ctrl+Shift+1'."""
    parts = [p.strip().lower() for p in raw.split("+") if p.strip()]
    if not parts:
        raise ValidationError("Shortcut cannot be empty")
    modifier_order = {"ctrl": 0, "shift": 1, "alt": 2, "meta": 3}
    seen: set[str] = set()
    modifiers: list[str] = []
    for p in parts[:-1]:
        if p in modifier_order and p not in seen:
            seen.add(p)
            modifiers.append(p)
        elif p not in modifier_order:
            modifiers.append(p)  # let regex reject "abc+x"-style garbage
    modifiers.sort(key=lambda m: modifier_order.get(m, 99))
    key = parts[-1]
    return "+".join([*modifiers, key])


def _validate_shortcut(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValidationError("Shortcut must be a string")
    normalized = _normalize_shortcut(raw)
    if not _SHORTCUT_PATTERN.match(normalized):
        raise ValidationError(
            "Shortcut must be a single key (1-9, a-z, F1-F12) "
            "optionally combined with Ctrl/Shift/Alt/Meta"
        )
    base_key = normalized.split("+")[-1]
    if base_key in _RESERVED_SHORTCUTS and "+" not in normalized:
        raise ValidationError(
            f"Shortcut '{raw}' is reserved by the app — "
            "use a digit (1-9) or a Ctrl/Shift+key combo"
        )
    return normalized


def _validate_email(raw: Any, field: str) -> str:
    if not isinstance(raw, str):
        raise ValidationError(f"{field} must be a string")
    cleaned = raw.strip().lower()
    if not _EMAIL_PATTERN.match(cleaned):
        raise ValidationError(f"{field} is not a valid email address")
    if len(cleaned) > 254:
        raise ValidationError(f"{field} exceeds 254 characters")
    return cleaned


def _validate_string(raw: Any, field: str, *, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(raw, str):
        raise ValidationError(f"{field} must be a string")
    cleaned = raw.strip() if not allow_empty else raw
    if not allow_empty and not cleaned:
        raise ValidationError(f"{field} cannot be empty")
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} exceeds {max_len} characters")
    return cleaned


def _validate_bounded_int(
    payload: dict, key: str, field: str, *, default: int, lo: int, hi: int
) -> int:
    """Coerce ``payload[key]`` to an int in ``[lo, hi]`` (default when absent).

    Mirrors the ``delay_days`` validation pattern. ``bool`` is rejected
    explicitly because ``isinstance(True, int)`` is True in Python and we
    don't want ``days_before=true`` to silently mean 1."""
    raw_value = payload.get(key, default)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, str)):
        raise ValidationError(f"{field} must be an integer")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer") from None
    if value < lo or value > hi:
        raise ValidationError(f"{field} must be between {lo} and {hi}")
    return value


def _validate_action(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError(f"Action #{index + 1} must be an object")
    action_type = raw.get("type")
    if action_type not in _ALLOWED_ACTION_TYPES:
        raise ValidationError(
            f"Action #{index + 1} has unknown type '{action_type}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_ACTION_TYPES))}"
        )
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValidationError(f"Action #{index + 1} payload must be an object")

    cleaned_payload: dict = {}

    if action_type == "mark_read":
        if "value" not in payload:
            raise ValidationError(f"Action #{index + 1} 'mark_read' requires payload.value (bool)")
        cleaned_payload["value"] = bool(payload["value"])

    elif action_type == "reply_template":
        snippet_id = payload.get("snippet_id")
        if snippet_id is not None:
            if not isinstance(snippet_id, str) or not snippet_id.strip():
                raise ValidationError(
                    f"Action #{index + 1} reply_template.snippet_id must be a non-empty string"
                )
            cleaned_payload["snippet_id"] = snippet_id.strip()
        body = payload.get("body", "")
        cleaned_payload["body"] = _validate_string(
            body, f"Action #{index + 1} reply_template.body",
            max_len=TEMPLATE_BODY_MAX_LENGTH,
            allow_empty=bool(snippet_id),
        )
        cleaned_payload["replyAll"] = bool(payload.get("replyAll", False))
        cleaned_payload["includeQuoted"] = bool(payload.get("includeQuoted", True))

    elif action_type == "rsvp_meeting":
        response = payload.get("response", "accepted")
        if response not in ("accepted", "declined", "tentative"):
            raise ValidationError(
                f"Action #{index + 1} rsvp_meeting.response must be accepted, declined, or tentative"
            )
        cleaned_payload["response"] = response

    elif action_type == "create_snoozed_followup_draft":
        body = payload.get("body", "")
        cleaned_payload["body"] = _validate_string(
            body,
            f"Action #{index + 1} create_snoozed_followup_draft.body",
            max_len=TEMPLATE_BODY_MAX_LENGTH,
            allow_empty=False,
        )
        delay_raw = payload.get("delay_days", 7)
        try:
            delay_days = int(delay_raw)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Action #{index + 1} create_snoozed_followup_draft.delay_days "
                "must be a positive integer"
            ) from None
        if delay_days < 1 or delay_days > _MAX_DAYS_VALUE:
            raise ValidationError(
                f"Action #{index + 1} create_snoozed_followup_draft.delay_days "
                f"must be between 1 and {_MAX_DAYS_VALUE}"
            )
        cleaned_payload["delay_days"] = delay_days

    elif action_type == "mark_with_emoji":
        # emoji is optional IFF a text companion is present — the "No emoji"
        # picker tile builds text-only chips. A non-empty emoji must still be
        # whitelisted; an empty/omitted emoji is allowed only alongside text.
        emoji = payload.get("emoji")
        if emoji:
            if not isinstance(emoji, str) or emoji not in _EMOJI_MARKER_WHITELIST:
                raise ValidationError(
                    f"Action #{index + 1} mark_with_emoji.emoji must be one of the curated set "
                    f"(got {emoji!r})"
                )
            cleaned_payload["emoji"] = emoji
        elif emoji is not None and not isinstance(emoji, str):
            raise ValidationError(
                f"Action #{index + 1} mark_with_emoji.emoji must be a string"
            )

        text = payload.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise ValidationError(
                    f"Action #{index + 1} mark_with_emoji.text must be a string"
                )
            cleaned_text = text.strip()
            if cleaned_text:
                if len(cleaned_text) > _EMOJI_MARKER_TEXT_MAX:
                    raise ValidationError(
                        f"Action #{index + 1} mark_with_emoji.text exceeds "
                        f"{_EMOJI_MARKER_TEXT_MAX} characters"
                    )
                cleaned_payload["text"] = cleaned_text

        # Reject the empty marker (neither emoji nor text) — nothing to stamp.
        if "emoji" not in cleaned_payload and "text" not in cleaned_payload:
            raise ValidationError(
                f"Action #{index + 1} mark_with_emoji requires an emoji or text"
            )

        cleaned_payload["include_deadline"] = bool(payload.get("include_deadline", False))

        # Optional palette-constrained color. Reject off-palette values: the FE
        # swatch picker only ever sends a LABEL_COLORS member, and the inbox row
        # applies it as a CSS color, so an arbitrary string is both a contrast
        # risk and a style-injection vector.
        color = payload.get("color")
        if color is not None:
            if not isinstance(color, str) or color not in _EMOJI_MARKER_COLOR_WHITELIST:
                raise ValidationError(
                    f"Action #{index + 1} mark_with_emoji.color must be one of the "
                    f"palette (got {color!r})"
                )
            cleaned_payload["color"] = color

        # Chip toggle: True (default) renders the pill, False renders the
        # marker bare (no background/border). Mirrors include_deadline above —
        # always materialized as a bool so the rule record is explicit.
        cleaned_payload["chip"] = bool(payload.get("chip", True))

    elif action_type == "apply_label":
        # Label name the rule stamps onto the email's LabelStore assignment.
        # Shape-only validation — we do NOT check the label still exists, so
        # a rule survives a label rename/delete (it just stops having an
        # effect, like previously_auto_actioned_by referencing a deleted step).
        cleaned_payload["label"] = _validate_string(
            payload.get("label"),
            f"Action #{index + 1} apply_label.label",
            max_len=LABEL_NAME_MAX_LENGTH,
            allow_empty=False,
        )

    elif action_type == "create_reminder":
        # ``days_before`` = how many days before the detected deadline the
        # reminder fires. 0 = on the deadline day itself.
        cleaned_payload["days_before"] = _validate_bounded_int(
            payload, "days_before",
            f"Action #{index + 1} create_reminder.days_before",
            default=2, lo=0, hi=_MAX_DAYS_VALUE,
        )

    elif action_type == "create_calendar_event":
        cleaned_payload["days_before"] = _validate_bounded_int(
            payload, "days_before",
            f"Action #{index + 1} create_calendar_event.days_before",
            default=2, lo=0, hi=_MAX_DAYS_VALUE,
        )
        # Event length in minutes (1 min .. 24 h).
        cleaned_payload["duration_minutes"] = _validate_bounded_int(
            payload, "duration_minutes",
            f"Action #{index + 1} create_calendar_event.duration_minutes",
            default=30, lo=1, hi=24 * 60,
        )

    elif action_type == "forward":
        to_groups = payload.get("to_groups") or []
        if to_groups:
            if not isinstance(to_groups, list):
                raise ValidationError(f"Action #{index + 1} forward.to_groups must be a list")
            cleaned_payload["to_groups"] = [str(gid).strip() for gid in to_groups[:20] if str(gid).strip()]

        recipients = payload.get("to") or []
        has_groups = bool(cleaned_payload.get("to_groups"))
        if not isinstance(recipients, list) or (not recipients and not has_groups):
            raise ValidationError(
                f"Action #{index + 1} forward requires at least one recipient (to or to_groups)"
            )
        if len(recipients) > MAX_FORWARD_RECIPIENTS:
            raise ValidationError(
                f"Action #{index + 1} forward.to exceeds {MAX_FORWARD_RECIPIENTS} recipients"
            )
        cleaned_payload["to"] = [
            _validate_email(r, f"Action #{index + 1} forward.to[{i}]")
            for i, r in enumerate(recipients)
        ]
        if payload.get("subject_prefix"):
            cleaned_payload["subject_prefix"] = _validate_string(
                payload["subject_prefix"],
                f"Action #{index + 1} forward.subject_prefix",
                max_len=SUBJECT_PREFIX_MAX_LENGTH,
                allow_empty=False,
            )
        if payload.get("body"):
            cleaned_payload["body"] = _validate_string(
                payload["body"],
                f"Action #{index + 1} forward.body",
                max_len=TEMPLATE_BODY_MAX_LENGTH,
                allow_empty=False,
            )

    cleaned: dict = {"type": action_type, "payload": cleaned_payload}
    guard_raw = raw.get("if")
    if guard_raw:
        cleaned["if"] = _validate_action_guard(guard_raw, index)
    return cleaned


def _validate_action_guard(raw: Any, action_index: int) -> dict:
    """Validate a per-action ``if`` guard {triggers, operator}.

    Reuses the same trigger-condition vocabulary as the step-level
    auto-trigger so the validation rules stay aligned.
    """
    if not isinstance(raw, dict):
        raise ValidationError(f"Action #{action_index + 1} 'if' must be an object")
    triggers_raw = raw.get("triggers") or []
    if not isinstance(triggers_raw, list):
        raise ValidationError(f"Action #{action_index + 1} 'if.triggers' must be a list")
    if len(triggers_raw) > MAX_TRIGGERS_PER_STEP:
        raise ValidationError(
            f"Action #{action_index + 1} 'if.triggers' exceeds {MAX_TRIGGERS_PER_STEP}"
        )
    triggers = [_validate_trigger_condition(t, i) for i, t in enumerate(triggers_raw)]
    operator = raw.get("operator", "AND")
    if operator not in ("AND", "OR"):
        raise ValidationError(
            f"Action #{action_index + 1} 'if.operator' must be 'AND' or 'OR'"
        )
    return {"triggers": triggers, "operator": operator}


# Legacy v1 condition types (pre-2026-05-14) folded into a
# ``{type, match_mode}`` pair. Maps old type → (new type, match_mode).
_LEGACY_CONDITION_ALIASES: dict[str, tuple[str, str]] = {
    "sender_regex": ("sender", "matches"),
    "sender_domain_regex": ("sender_domain", "matches"),
    "subject_keyword": ("email_text", "subject"),
    "content_keyword": ("email_text", "body"),
    "subject_or_body_keyword": ("email_text", "anywhere"),
    "is_calendar_invite": ("calendar_invite", "any"),
    "available_for_invite": ("calendar_invite", "free"),
}

# Legacy v1 types that keep their key but had an operator baked into the
# matcher: ``sender`` / ``sender_domain`` did exact-match, ``recipient``
# did substring. Map them to the equivalent explicit match_mode.
_LEGACY_IMPLICIT_MATCH_MODE: dict[str, str] = {
    "sender": "is",
    "sender_domain": "is",
    "recipient": "contains",
}


def migrate_legacy_condition(raw: Any) -> Any:
    """Upgrade a pre-``match_mode`` trigger condition to the current shape.

    Total and idempotent: a condition already in the new shape — or one
    this function doesn't recognise — is returned with nothing dropped.
    Never raises; a non-dict input is handed straight back so the
    caller's own validation produces the user-facing error rather than
    this helper turning a clean 400 into a 500.

    The v1 vocabulary, where ``type`` encoded the operator, collapses to
    15 types + a polymorphic ``match_mode``:
      - regex variants            → base type + match_mode="matches"
      - subject/content/both kw   → email_text  + match_mode=<scope>
      - calendar invite variants  → calendar_invite + match_mode + value
      - sender/domain/recipient   → keep type, add the implicit match_mode
    ``value`` and ``negate`` are always carried over.
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    ctype = out.get("type")

    alias = _LEGACY_CONDITION_ALIASES.get(ctype)
    if alias is not None:
        new_type, match_mode = alias
        out["type"] = new_type
        # setdefault keeps idempotency — a re-migrated condition retains
        # whatever match_mode it already carries.
        out.setdefault("match_mode", match_mode)
        ctype = new_type
    elif ctype in _LEGACY_IMPLICIT_MATCH_MODE:
        out.setdefault("match_mode", _LEGACY_IMPLICIT_MATCH_MODE[ctype])

    # calendar_invite is a "badge" condition — the matcher's empty-value
    # guard drops it unless ``value`` is truthy. Inject the sentinel
    # whether the input was legacy (is_calendar_invite) or a value-less
    # new-shape condition.
    if ctype == "calendar_invite" and not out.get("value"):
        out["value"] = "true"

    # is_new_thread has two equivalent encodings of its "reply / existing
    # thread" sense: value="false" (used by the "Follow-up existing thread"
    # starter) and value="true"+negate=true (what the editor produces). The
    # editor renders the type label, the badge, and the negate toggle off
    # the ``negate`` field ONLY — so the value="false" form is mislabeled as
    # "new thread" and, because the badge value is fixed to "true", would be
    # silently corrupted to value="true" on re-save. Canonicalise onto the
    # negate field here (lossless for the matcher: value="false" ≡
    # value="true"+negate flipped). Idempotent — only fires while value is
    # falsy, and runs on both read and write paths.
    if ctype == "is_new_thread" and str(out.get("value", "")).strip().lower() in (
        "false", "no", "0", "non",
    ):
        out["value"] = "true"
        out["negate"] = not bool(out.get("negate", False))

    return out


def _validate_trigger_condition(raw: Any, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError(f"Trigger #{index + 1} must be an object")
    # Write-path migration layer: upgrade legacy {type-encodes-operator}
    # conditions to the {type, match_mode} shape before validating.
    # Idempotent — new-shape input passes straight through. Any save
    # therefore re-canonicalises the persisted JSON.
    raw = migrate_legacy_condition(raw)
    ctype = raw.get("type")
    if ctype not in _TRIGGER_CONDITION_TYPES:
        raise ValidationError(
            f"Trigger #{index + 1} has unknown type '{ctype}'. "
            f"Allowed: {', '.join(sorted(_TRIGGER_CONDITION_TYPES))}"
        )
    value = _validate_string(
        raw.get("value", ""),
        f"Trigger #{index + 1} value",
        max_len=TRIGGER_VALUE_MAX_LENGTH,
        allow_empty=False,
    )

    # ``match_mode`` is required on the types that carry one (sender,
    # sender_domain, recipient, email_text, calendar_invite) and rejected
    # on every other type. Allowed values are type-specific.
    allowed_modes = _MATCH_MODE_VALUES.get(ctype)
    match_mode = raw.get("match_mode")
    if allowed_modes is None:
        if match_mode is not None:
            raise ValidationError(
                f"Trigger #{index + 1} type '{ctype}' does not take a match_mode"
            )
    elif match_mode not in allowed_modes:
        raise ValidationError(
            f"Trigger #{index + 1} type '{ctype}' requires match_mode to be "
            f"one of: {', '.join(sorted(allowed_modes))}"
        )

    # Type-specific value validation. The frontend stores ints as strings,
    # so we coerce here and re-emit as canonical text.
    if ctype in _INT_VALUE_CONDITION_TYPES:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                f"Trigger #{index + 1} value for '{ctype}' must be a positive integer"
            ) from None
        if n < 1:
            raise ValidationError(
                f"Trigger #{index + 1} value for '{ctype}' must be ≥ 1"
            )
        if n > _MAX_DAYS_VALUE:
            raise ValidationError(
                f"Trigger #{index + 1} value for '{ctype}' must be ≤ {_MAX_DAYS_VALUE}"
            )
        value = str(n)

    elif ctype == "previously_auto_actioned_by":
        # Value is the UUID of a Quick Step. We don't check existence here —
        # steps can be deleted/renamed and the persisted condition stays valid
        # (it just stops matching). Only the shape is enforced.
        if not _UUID_PATTERN.match(value):
            raise ValidationError(
                f"Trigger #{index + 1} value for 'previously_auto_actioned_by' "
                "must be a Quick Step UUID"
            )

    # Regex validation keys off ``match_mode`` rather than the condition type:
    # any text-target condition with match_mode="matches" carries a
    # regex pattern in ``value``. Compile-test it and reject ReDoS shapes.
    if match_mode == "matches":
        if len(value) > _MAX_REGEX_LENGTH:
            raise ValidationError(
                f"Trigger #{index + 1} regex pattern exceeds {_MAX_REGEX_LENGTH} characters"
            )
        # Static ReDoS shape rejection (cheap, catches known categories).
        # Audit F-08 (2026-05-16): the previous single pattern only caught
        # ``(a+)+`` / ``(.*)*``. Alternation-with-quantifier ``(a|aa)+`` and
        # overlapping quantifiers ``\w+\w+`` slipped through and hung the
        # auto-trigger daemon (no timeout on the runtime re.search at
        # auto_trigger.py). Backed by the runtime-budget check below for
        # the patterns this enumeration misses.
        _REDOS_PATTERNS = (
            r"\([^)]*[+*]\)[+*]",          # (a+)+, (.*)*
            r"\([^|)]*\|[^)]*\)[+*]",      # (a|b)+, (a|aa|aaa)+
        )
        for _shape in _REDOS_PATTERNS:
            if re.search(_shape, value):
                raise ValidationError(
                    f"Trigger #{index + 1} regex has a catastrophic-backtracking shape"
                )
        try:
            _compiled = re.compile(value)
        except re.error as exc:
            raise ValidationError(
                f"Trigger #{index + 1} regex is invalid: {exc}"
            ) from exc
        # Runtime time-budget guard: any regex that backtracks for more
        # than 250ms on a synthetic 60-char near-miss input is rejected.
        # Python's `re` has no timeout, so we run the search in a daemon
        # thread and bail if it doesn't return in time. The thread leaks
        # if the regex is truly catastrophic, but daemon=True means it
        # dies with the process — bounded foot-gun.
        _canary = "a" * 60 + "!"
        _result: dict = {"done": False}

        def _probe() -> None:
            try:
                _compiled.search(_canary)
            except Exception:
                pass
            finally:
                _result["done"] = True

        _t = threading.Thread(target=_probe, daemon=True)
        _t.start()
        _t.join(timeout=0.25)
        if not _result["done"]:
            raise ValidationError(
                f"Trigger #{index + 1} regex exceeds the 250ms evaluation budget "
                "(likely catastrophic backtracking — rewrite without unbounded alternation)"
            )

    cleaned: dict = {"type": ctype}
    if match_mode is not None:
        cleaned["match_mode"] = match_mode
    cleaned["value"] = value
    # Belt-and-suspenders for audit F-03: temporal "older than N days"
    # conditions don't expose the negate toggle in the UI (the type label
    # already carries the comparison), so a persisted `negate=true` would
    # silently invert the comparison with no UI to undo it. Drop it on
    # the way in so a stale value from any client (or an older payload)
    # can't corrupt rule semantics.
    if bool(raw.get("negate", False)) and ctype not in (
        "email_older_than_days",
        "no_reply_after_days",
    ):
        cleaned["negate"] = True
    return cleaned


def _validate_triggers(raw: Any) -> list[dict]:
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise ValidationError("triggers must be a list")
    if len(raw) > MAX_TRIGGERS_PER_STEP:
        raise ValidationError(f"triggers exceed the {MAX_TRIGGERS_PER_STEP}-condition limit per Quick Step")
    return [_validate_trigger_condition(t, i) for i, t in enumerate(raw)]


def _validate_actions(raw: Any) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError("actions must be a non-empty list")
    if len(raw) > MAX_ACTIONS_PER_STEP:
        raise ValidationError(f"actions exceed the {MAX_ACTIONS_PER_STEP}-action limit per Quick Step")
    cleaned = [_validate_action(a, i) for i, a in enumerate(raw)]
    # ``delete`` is terminal — no actions can run after it (the email is gone).
    for i, a in enumerate(cleaned[:-1]):
        if a["type"] == "delete":
            raise ValidationError(
                f"Action #{i + 1} is 'delete' — no actions can follow it (email is removed)"
            )
    return cleaned


def validate_quick_step(raw: Any, *, existing_id: str | None = None) -> dict:
    """Validate and normalize one Quick Step payload.

    Returns a clean dict ready to persist. Raises ``ValidationError`` on
    any structural or semantic problem with a message safe to surface to
    the user as the body of a 400 response.

    ``existing_id`` lets PATCH callers pass the URL id so the body's
    optional ``id`` field can be omitted (or must match if provided).
    """
    if not isinstance(raw, dict):
        raise ValidationError("Quick Step must be a JSON object")

    step_id = raw.get("id") or existing_id
    if step_id is None:
        raise ValidationError("Quick Step 'id' is required (UUID v4)")
    if not isinstance(step_id, str) or not _UUID_PATTERN.match(step_id):
        raise ValidationError("Quick Step 'id' must be a UUID v4 string")
    if existing_id is not None and step_id != existing_id:
        raise ValidationError("Body 'id' does not match URL id")

    name = _validate_string(raw.get("name"), "name", max_len=NAME_MAX_LENGTH)

    # Optional free-text description. Empty or whitespace-only values
    # are normalized to None so the card can fall back to the
    # auto-generated trigger summary cleanly.
    description: str | None = None
    desc_raw = raw.get("description")
    if isinstance(desc_raw, str) and desc_raw.strip():
        description = _validate_string(
            desc_raw, "description", max_len=DESCRIPTION_MAX_LENGTH,
        )

    icon: str | None = None
    if raw.get("icon"):
        icon = _validate_string(raw["icon"], "icon", max_len=ICON_MAX_LENGTH)

    shortcut: str | None = None
    if raw.get("shortcut"):
        shortcut = _validate_shortcut(raw["shortcut"])

    actions = _validate_actions(raw.get("actions"))
    enabled = bool(raw.get("enabled", True))
    confirm_before_run = bool(raw.get("confirmBeforeRun", _has_irreversible_action(actions)))

    auto_enabled = bool(raw.get("autoEnabled", False))
    # Show a ⚡ Auto badge on emails this rule auto-actions (issue #457
    # follow-up + UX request 2026-05-12). Default True so new rules are
    # transparent out-of-the-box ; user toggles off per-rule when the
    # badge contradicts the rule's purpose (e.g. silent label-only rule).
    # The UI only surfaces the toggle when autoEnabled=true — a manual-only
    # rule never auto-actions, so the field has no observable effect there,
    # but we still preserve it on save so toggling autoEnabled back on
    # restores the user's prior choice.
    show_auto_badge = bool(raw.get("showAutoBadge", True))
    trigger_operator = raw.get("triggerOperator", "OR")
    if trigger_operator not in ("AND", "OR"):
        raise ValidationError("triggerOperator must be 'AND' or 'OR'")
    triggers = _validate_triggers(raw.get("triggers"))
    # Audit 2026-05-11 (P1): autoEnabled with no triggers is dead config —
    # the auto-trigger background loop never fires because there's nothing
    # to match. The editor relies on the schema rejecting this; align the
    # backend so legacy / mobile / MCP clients can't create silent dead rules.
    if auto_enabled and not triggers:
        raise ValidationError(
            "autoEnabled requires at least one trigger condition"
        )

    # Which side of the mail flow this step evaluates against. Default
    # "received" preserves the pre-feature behavior — every legacy step
    # keeps running against incoming emails only. "sent" lets users build
    # follow-up-on-send rules (create_snoozed_followup_draft after N days),
    # fired by the immediate post-send hook in app/api/quicksteps_scheduler.py.
    fires_on = raw.get("firesOn", "received")
    if fires_on not in ("received", "sent"):
        raise ValidationError("firesOn must be 'received' or 'sent'")
    # Cross-flow safety: create_snoozed_followup_draft only makes sense on
    # sent, and the rest of the action grammar (archive, delete, mark_read,
    # …) only makes sense on received. Reject configs that pair them wrong
    # so daemons don't have to defend at runtime.
    # mark_with_emoji is shape-agnostic — its handler writes
    # `emails.emoji_marker_json` on whatever row matches (email_id, account_id),
    # which works for sent rows too. Lets users visually flag sent threads
    # (e.g. 🔁 = "awaiting follow-up") alongside the snoozed-followup draft.
    _SENT_ALLOWED_ACTIONS = {"create_snoozed_followup_draft", "mark_with_emoji"}
    _SENT_ONLY_ACTIONS = {"create_snoozed_followup_draft"}
    for sent_only in _SENT_ONLY_ACTIONS:
        if any(a["type"] == sent_only for a in actions) and fires_on != "sent":
            raise ValidationError(
                f"{sent_only} action requires firesOn='sent' "
                "(it operates on emails the user sent)"
            )
    if fires_on == "sent":
        bad = [a["type"] for a in actions if a["type"] not in _SENT_ALLOWED_ACTIONS]
        if bad:
            raise ValidationError(
                f"firesOn='sent' Quick Steps only support {sorted(_SENT_ALLOWED_ACTIONS)} actions "
                f"(got: {bad})"
            )

    return {
        "id": step_id,
        "name": name,
        "description": description,
        "icon": icon,
        "shortcut": shortcut,
        "actions": actions,
        "enabled": enabled,
        "confirmBeforeRun": confirm_before_run,
        "autoEnabled": auto_enabled,
        "showAutoBadge": show_auto_badge,
        "triggerOperator": trigger_operator,
        "triggers": triggers,
        "firesOn": fires_on,
    }


def _has_irreversible_action(actions: list[dict]) -> bool:
    """Default ``confirmBeforeRun`` to True when the chain sends real email."""
    return any(a["type"] in ("reply_template", "forward") for a in actions)


def validate_collection(raw: Any) -> list[dict]:
    """Validate a full list of Quick Steps. Used when seeding from import."""
    if not isinstance(raw, list):
        raise ValidationError("Quick Steps payload must be a JSON list")
    if len(raw) > MAX_QUICK_STEPS_PER_ACCOUNT:
        raise ValidationError(
            f"Cannot store more than {MAX_QUICK_STEPS_PER_ACCOUNT} Quick Steps per account"
        )
    cleaned: list[dict] = []
    seen_ids: set[str] = set()
    seen_shortcuts: dict[str, str] = {}
    for i, step in enumerate(raw):
        try:
            clean = validate_quick_step(step)
        except ValidationError as exc:
            raise ValidationError(f"Quick Step #{i + 1}: {exc}") from exc
        if clean["id"] in seen_ids:
            raise ValidationError(f"Duplicate Quick Step id at position #{i + 1}")
        seen_ids.add(clean["id"])
        if clean["shortcut"]:
            collision = seen_shortcuts.get(clean["shortcut"])
            if collision:
                raise ValidationError(
                    f"Shortcut '{clean['shortcut']}' is used by both '{collision}' "
                    f"and '{clean['name']}'"
                )
            seen_shortcuts[clean["shortcut"]] = clean["name"]
        cleaned.append(clean)
    return cleaned
