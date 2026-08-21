# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Delete handler — terminal action; the schema validator forbids any
action after this in a chain."""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit, evict_caches
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_delete(ctx: ExecutionContext, _payload: dict) -> ActionResult:
    """Move the email to trash. Always terminal — the engine validator forbids
    actions after delete.

    Audit Cluster B (2026-05-10) B-03: do NOT evict cache or emit the WS
    event before the provider call. A 5xx from Gmail would otherwise leave
    the inbox UI showing a vanishing-then-reappearing email with no toast.
    Order now: provider first, side effects only on success.
    """
    try:
        if not hasattr(ctx.provider, "delete_email"):
            return ActionResult(ok=False, error="delete_not_supported")
        success = ctx.provider.delete_email(ctx.raw_id)
        if not success:
            return ActionResult(ok=False, error="provider_delete_failed")
        evict_caches(ctx.email_id, ctx.raw_id, folder="trash")
        emit("emit_email_deleted", ctx)
        return ActionResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("delete handler failed: %s", exc)
        return ActionResult(ok=False, error=f"delete_error: {exc}")
