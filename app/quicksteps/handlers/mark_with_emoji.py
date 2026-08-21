# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""mark_with_emoji handler — stamp an emoji + optional text on the email row.

Persists to ``emails.emoji_marker_json``; the inbox row reads this back
and renders a chip right after the subject. Optional ``include_deadline``
merges the auto-detected deadline date into the chip and hides the
standalone clock chip for that row.
"""
from __future__ import annotations

import json
import logging

from app.quicksteps.types import ActionResult, ExecutionContext

logger = logging.getLogger(__name__)


def handle_mark_with_emoji(ctx: ExecutionContext, payload: dict) -> ActionResult:
    """Write the emoji marker payload onto the email row + notify the FE."""
    # emoji and text are each optional, but at least one must be present.
    # The "No emoji" picker tile sends emoji="" with a text companion; an
    # empty marker (neither) is rejected so we never stamp a blank chip.
    emoji = payload.get("emoji")
    text = payload.get("text")
    marker: dict = {}
    if isinstance(emoji, str) and emoji.strip():
        marker["emoji"] = emoji
    if isinstance(text, str) and text.strip():
        marker["text"] = text.strip()
    if not marker:
        return ActionResult(ok=False, error="mark_with_emoji_empty_marker")

    if payload.get("include_deadline"):
        marker["include_deadline"] = True
    # Optional color (palette member, already validated by the schema) and
    # chip toggle ride along in the JSON. chip is only persisted when False —
    # True is the default rendering, so omitting it keeps legacy rows and
    # chip=True rows decoding identically.
    color = payload.get("color")
    if isinstance(color, str) and color:
        marker["color"] = color
    if payload.get("chip") is False:
        marker["chip"] = False

    try:
        from app.api.routes_helpers import get_db_session
        from app.db.repositories.email_repository import EmailRepository
        from app.api import websocket as ws_module

        marker_json = json.dumps(marker, ensure_ascii=False)
        with get_db_session() as session:
            repo = EmailRepository(session)
            row = repo.get_by_email_id(
                ctx.email_id, account_id=ctx.account_id,
            )
            # Sent-side fallback: the auto-trigger fires immediately after the
            # send-completion hook with `ctx.email_id == f"compose-{ts}"` (the
            # synthetic id from routes_emails.py:~8709). The real provider
            # message id hasn't been threaded back yet, so the lookup above
            # misses. The SentEmail dataclass carries the REAL thread_id, so
            # fall back to the most-recent sent row in that thread.
            if row is None:
                thread_id = getattr(getattr(ctx, "email", None), "thread_id", None)
                if thread_id:
                    try:
                        thread_rows = repo.get_by_thread(thread_id, ctx.account_id)
                        sent_rows = [r for r in thread_rows if getattr(r, "is_sent", False)]
                        if sent_rows:
                            row = max(
                                sent_rows,
                                key=lambda r: getattr(r, "date", None)
                                              or getattr(r, "created_at", None),
                            )
                    except Exception as _fallback_exc:  # noqa: BLE001
                        logger.debug(
                            "mark_with_emoji: thread_id fallback failed for %s: %s",
                            thread_id, _fallback_exc,
                        )
            if row is None:
                return ActionResult(ok=False, error="email_not_found")
            row.emoji_marker_json = marker_json
            session.commit()

        # Invalidate in-memory caches ONLY — do NOT call evict_caches /
        # _evict_email_from_all_caches here. Without a ``move_to_folder``
        # arg those helpers schedule a background SQLite DELETE of the row
        # we just wrote to, wiping the marker we just stamped. The email
        # is staying in the inbox; we only need the list/detail/label
        # caches to drop their stale copy so the next /api/emails serves
        # the freshly-stamped row.
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
            logger.debug("mark_with_emoji: cache invalidation suppressed: %s", _cache_exc)

        # Push the update so the chip appears without a list refetch. The
        # frontend's `useWebSocketSync` already merges `updates` into the
        # inbox row state via the `email_updated` → `agentys:email-patch`
        # event chain.
        try:
            ws_module.emit_email_updated(
                ctx.email_id,
                {"emoji_marker": marker},
                account_id=ctx.account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("mark_with_emoji: ws emit suppressed: %s", exc)

        return ActionResult(ok=True, artifact={"emoji_marker": marker})
    except Exception as exc:  # noqa: BLE001
        logger.error("mark_with_emoji handler failed: %s", exc, exc_info=True)
        return ActionResult(ok=False, error=f"mark_with_emoji_error: {exc}")
