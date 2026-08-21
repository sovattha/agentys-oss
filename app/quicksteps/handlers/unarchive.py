# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Unarchive handler — move email back into INBOX.

The inverse of ``archive``. Required for reactive chains gated on
``previously_auto_actioned_by``: when Rule A auto-archived a thread and a
new reply arrives, Rule B can pull the thread back to inbox so the user
sees it. Without unarchive, the rescue path has no landing action.
"""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit, evict_caches
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_unarchive(ctx: ExecutionContext, _payload: dict) -> ActionResult:
    """Move the email back into INBOX. Mirrors ``handle_archive``'s ordering:
    provider call first, cache evict + WS event only on success — so a 5xx
    can't leave the UI showing a row that didn't actually move.
    """
    try:
        # Sent items never leave INBOX in the first place; treat as a no-op.
        if ctx.email_id.startswith("sent:"):
            evict_caches(ctx.email_id, ctx.raw_id, folder="inbox")
            emit("emit_email_restored", ctx)
            return ActionResult(ok=True)

        if not hasattr(ctx.provider, "move_to_inbox"):
            return ActionResult(ok=False, error="unarchive_not_supported")

        success = ctx.provider.move_to_inbox(ctx.raw_id)
        if not success:
            return ActionResult(ok=False, error="provider_unarchive_failed")
        evict_caches(ctx.email_id, ctx.raw_id, folder="inbox")
        emit("emit_email_restored", ctx)
        return ActionResult(ok=True)
    except Exception as exc:  # noqa: BLE001 — engine reports, never crashes
        logger.error("unarchive handler failed: %s", exc)
        return ActionResult(ok=False, error=f"unarchive_error: {exc}")
