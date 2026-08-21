# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Quick Step action handlers, one per file.

Replaces the former 700-line ``registry.py`` monolith. Each module owns
exactly one ``handle_*`` function plus its narrow private helpers; shared
helpers (cache eviction, websocket emit, signature append) live in
``_shared.py``. The dispatch table assembled in :mod:`app.quicksteps.registry`
imports the handlers from here so the engine entrypoint stays unchanged.
"""
from app.quicksteps.handlers.archive import handle_archive
from app.quicksteps.handlers.delete import handle_delete
from app.quicksteps.handlers.forward import handle_forward
from app.quicksteps.handlers.mark_read import handle_mark_read
from app.quicksteps.handlers.move_to_spam import handle_move_to_spam
from app.quicksteps.handlers.pin import handle_pin
from app.quicksteps.handlers.reply import handle_reply_template
from app.quicksteps.handlers.rsvp import handle_rsvp_meeting
from app.quicksteps.handlers.unarchive import handle_unarchive
from app.quicksteps.handlers.create_snoozed_followup_draft import (
    handle_create_snoozed_followup_draft,
)
from app.quicksteps.handlers.mark_with_emoji import handle_mark_with_emoji
from app.quicksteps.handlers.apply_label import handle_apply_label
from app.quicksteps.handlers.deadline_actions import (
    handle_create_calendar_event,
    handle_create_reminder,
)

__all__ = [
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
