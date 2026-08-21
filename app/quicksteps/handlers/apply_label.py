# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""apply_label handler — add a label to the email's LabelStore assignment.

Routes through ``LabelAssignment.add_label`` so a default-category name
(Action/FYI/Noise) replaces the email's category, while any other name is
appended as a custom label. The Agentys LabelStore is the source of truth
for the inbox's label chips — we deliberately do NOT push the label to the
mail provider (mirrors the manual /api/labels assign route + the RSVP
relabel path).
"""
from __future__ import annotations

import logging

from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_apply_label(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Add ``payload['label']`` to the email's label assignment."""
    label = payload.get("label")
    if not isinstance(label, str) or not label.strip():
        return ActionResult(ok=False, error="apply_label_missing_label")
    label = label.strip()

    try:
        from app.domain.entities.email_labels import LabelAssignment
        from app.infrastructure.container import get_container

        store = get_container().get_label_store(
            account_id=ctx.account_id if ctx.account_id else None,
        )
        if store is None:
            return ActionResult(ok=False, error="label_store_unavailable")

        # Mutate the existing assignment in place when there is one so the
        # classifier's category + any prior custom labels survive; otherwise
        # start a fresh rule-assigned record. add_label() owns the routing
        # between default-category and custom labels.
        assignment = store.get_assignment(ctx.email_id)
        if assignment is None:
            assignment = LabelAssignment(email_id=ctx.email_id, assigned_by="rule")
        assignment.add_label(label, 1.0, "Quick Step")
        store.save_assignment(assignment)

        # Invalidate in-memory caches ONLY — same rationale as the
        # mark_with_emoji handler: the email stays in place, we just need
        # the next /api/emails read to serve the fresh label set rather
        # than a stale cached row.
        try:
            from app.api.routes_helpers import (
                _email_detail_cache,
                _email_detail_cache_lock,
                _invalidate_folder_cache,
                _invalidate_label_batch_cache,
            )
            _invalidate_folder_cache()
            _invalidate_label_batch_cache()
            with _email_detail_cache_lock:
                _email_detail_cache.pop(str(ctx.email_id), None)
        except Exception as _cache_exc:  # noqa: BLE001
            logger.debug("apply_label: cache invalidation suppressed: %s", _cache_exc)

        # Push the new label set so the inbox row updates without a refetch.
        try:
            from app.api import websocket as ws_module
            ws_module.emit_email_updated(
                ctx.email_id,
                {"labels": list(assignment.labels)},
                account_id=ctx.account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("apply_label: ws emit suppressed: %s", exc)

        return ActionResult(
            ok=True,
            artifact={"label": label, "labels": list(assignment.labels)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("apply_label handler failed: %s", exc, exc_info=True)
        return ActionResult(ok=False, error=f"apply_label_error: {exc}")
