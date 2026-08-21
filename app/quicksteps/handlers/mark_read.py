# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""mark_read handler — toggle the read flag with cache invalidation."""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit, update_cached_read_flag
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_mark_read(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Toggle the email's read flag. ``payload['value']`` is True for read,
    False for unread (validated by schema).

    Audit Cluster B (2026-05-10) B-04: do NOT update the cache or emit the
    WS event when the provider mark call returns False / raises. Previously
    the UI flipped to 'read' visually while the result reported ok=False —
    state divergence between visual and chain status. Order now: provider
    first, cache + emit only on success, explicit error code on failure.
    """
    try:
        target_read = bool(payload.get("value", True))
        method_name = "mark_as_read" if target_read else "mark_as_unread"
        if not hasattr(ctx.provider, method_name):
            return ActionResult(ok=False, error=f"{method_name}_not_supported")
        success = getattr(ctx.provider, method_name)(ctx.raw_id)
        if not success:
            return ActionResult(ok=False, error="provider_mark_read_failed")
        update_cached_read_flag(ctx, target_read)
        emit("emit_email_updated", ctx, payload={"is_read": target_read})
        return ActionResult(ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("mark_read handler failed: %s", exc)
        return ActionResult(ok=False, error=f"mark_read_error: {exc}")
