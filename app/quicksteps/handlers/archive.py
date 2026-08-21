# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Archive handler — move email out of INBOX."""
from __future__ import annotations

import logging

from app.quicksteps.handlers._shared import emit, evict_caches
from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_archive(ctx: ExecutionContext, _payload: dict) -> ActionResult:
    """Archive the email (move out of INBOX). Sent-cached items are no-ops
    on the provider side but still get cache-evicted to refresh the UI.

    Audit Cluster B (2026-05-10) B-02: do NOT evict cache or emit the WS
    event before the provider call. A 5xx from Gmail would otherwise leave
    the inbox UI lying — the row disappears optimistically and resurfaces
    at the next refresh, with no toast. Order now: provider first, side
    effects only on success.
    """
    try:
        # Sent items are already outside INBOX — provider call would fail.
        if ctx.email_id.startswith("sent:"):
            evict_caches(ctx.email_id, ctx.raw_id, folder="archived")
            emit("emit_email_archived", ctx)
            return ActionResult(ok=True)

        if not hasattr(ctx.provider, "archive_email"):
            return ActionResult(ok=False, error="archive_not_supported")

        success = ctx.provider.archive_email(ctx.raw_id)
        if not success:
            return ActionResult(ok=False, error="provider_archive_failed")
        evict_caches(ctx.email_id, ctx.raw_id, folder="archived")
        emit("emit_email_archived", ctx)
        return ActionResult(ok=True)
    except Exception as exc:  # noqa: BLE001 — engine reports, never crashes
        logger.error("archive handler failed: %s", exc)
        return ActionResult(ok=False, error=f"archive_error: {exc}")
