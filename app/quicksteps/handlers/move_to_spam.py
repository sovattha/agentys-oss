# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""move_to_spam handler."""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit, evict_caches
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_move_to_spam(ctx: ExecutionContext, _payload: dict) -> ActionResult:
    """Move the email to the spam folder."""
    try:
        if not hasattr(ctx.provider, "move_to_spam"):
            return ActionResult(ok=False, error="move_to_spam_not_supported")
        success = ctx.provider.move_to_spam(ctx.raw_id)
        if success:
            evict_caches(ctx.email_id, ctx.raw_id)
            emit("emit_email_spam_changed", ctx, payload={"is_spam": True})
            return ActionResult(ok=True)
        return ActionResult(ok=False, error="provider_spam_failed")
    except Exception as exc:  # noqa: BLE001
        logger.error("move_to_spam handler failed: %s", exc)
        return ActionResult(ok=False, error=f"spam_error: {exc}")
