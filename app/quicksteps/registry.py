# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Action dispatch table for the Quick Step engine.

Was a 700-line monolith; now a thin facade that re-exports the per-handler
modules. Splitting was tracked in the audit follow-up — each handler lives
in :mod:`app.quicksteps.handlers` and shared plumbing in
:mod:`app.quicksteps.handlers._shared`. Public callers
(``app.quicksteps.engine``, tests, route layer) still import
``ACTION_HANDLERS``, ``ExecutionContext``, ``ActionResult`` from here so
the move is invisible to the rest of the codebase.
"""
from __future__ import annotations

from app.quicksteps.handlers import (
    handle_apply_label,
    handle_archive,
    handle_create_calendar_event,
    handle_create_reminder,
    handle_create_snoozed_followup_draft,
    handle_delete,
    handle_forward,
    handle_mark_read,
    handle_mark_with_emoji,
    handle_move_to_spam,
    handle_pin,
    handle_reply_template,
    handle_rsvp_meeting,
    handle_unarchive,
)
from app.quicksteps.types import ActionHandler, ActionResult, ExecutionContext

ACTION_HANDLERS: dict[str, ActionHandler] = {
    "archive": handle_archive,
    "unarchive": handle_unarchive,
    "delete": handle_delete,
    "mark_read": handle_mark_read,
    "move_to_spam": handle_move_to_spam,
    "pin": handle_pin,
    "reply_template": handle_reply_template,
    "forward": handle_forward,
    "rsvp_meeting": handle_rsvp_meeting,
    "create_snoozed_followup_draft": handle_create_snoozed_followup_draft,
    "mark_with_emoji": handle_mark_with_emoji,
    "apply_label": handle_apply_label,
    "create_reminder": handle_create_reminder,
    "create_calendar_event": handle_create_calendar_event,
}

__all__ = [
    "ACTION_HANDLERS",
    "ActionHandler",
    "ActionResult",
    "ExecutionContext",
    "handle_apply_label",
    "handle_archive",
    "handle_create_calendar_event",
    "handle_create_reminder",
    "handle_create_snoozed_followup_draft",
    "handle_delete",
    "handle_forward",
    "handle_mark_read",
    "handle_mark_with_emoji",
    "handle_move_to_spam",
    "handle_pin",
    "handle_reply_template",
    "handle_rsvp_meeting",
    "handle_unarchive",
]
