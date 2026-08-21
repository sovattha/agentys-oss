# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Shared helpers used by more than one handler.

Anything used by exactly one handler stays beside that handler — only
genuinely cross-cutting plumbing (cache eviction, websocket emit, read-flag
cache invalidation, signature append) lives here. Lazy imports keep the
module cheap to load and avoid the circular dependency with
``app.api.routes_helpers``.
"""
from __future__ import annotations

import logging

from app.quicksteps.types import ExecutionContext

logger = logging.getLogger(__name__)


def evict_caches(email_id: str, raw_id: str, folder: str | None = None) -> None:
    try:
        from app.api.routes_helpers import _evict_email_from_all_caches
        kwargs = {"move_to_folder": folder} if folder else {}
        _evict_email_from_all_caches(email_id, **kwargs)
        if raw_id != email_id:
            _evict_email_from_all_caches(raw_id, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache evict suppressed: %s", exc)


def emit(event_name: str, ctx: ExecutionContext, *, payload: dict | None = None) -> None:
    """Dispatch a websocket event by name AND broadcast to every Socket.IO
    client connected to the /daemon namespace.

    Why broadcast on top of per-account targeted emits: multi-account
    Tauri/desktop sessions have ONE FE tab subscribed to ONE account room,
    yet that tab shows a unified inbox aggregating other accounts' emails.
    The targeted emit (account_id=owner) reaches the owner's room; the
    user-visible room may be different. A namespace-level broadcast is
    safe for these UI-update events (archive/delete/read) because the FE
    list filter is keyed on email_id — events for unknown email_ids are
    no-ops, not errors. Cloud/multi-user installs use auth-gated rooms;
    the broadcast there reaches connected clients of a single user.
    """
    try:
        from app.api import websocket as ws_module
        emitter = getattr(ws_module, event_name, None)
        if emitter is None:
            logger.info("ws emit '%s': no emitter — skipping", event_name)
            return

        sent_via_targeted = False
        try:
            if payload is not None:
                ok = emitter(ctx.email_id, payload, account_id=ctx.account_id)
            else:
                ok = emitter(ctx.email_id, account_id=ctx.account_id)
            sent_via_targeted = bool(ok)
        except TypeError:
            try:
                if payload is not None:
                    emitter(ctx.email_id, payload)
                else:
                    emitter(ctx.email_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("ws legacy emit '%s' failed: %s", event_name, exc)

        logger.info(
            "ws emit '%s' email_id=%s owner_aid=%s targeted_sent=%s",
            event_name, ctx.email_id, ctx.account_id, sent_via_targeted,
        )

        # Namespace-level broadcast for UI-update events so the FE tab
        # (whichever account-room it sits in) receives the message.
        try:
            sio = ws_module.get_socketio()
            if sio is None:
                return
            event_short = event_name.removeprefix("emit_")  # "emit_email_archived" → "email_archived"
            data = {"email_id": ctx.email_id}
            if payload:
                data.update(payload)
            sio.emit(event_short, data, namespace="/daemon")
            logger.info("ws broadcast '%s' on /daemon", event_short)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ws broadcast failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("websocket emit '%s' suppressed: %s", event_name, exc)


def update_cached_read_flag(ctx: ExecutionContext, is_read: bool) -> None:
    try:
        from app.api.routes_helpers import (
            _email_detail_cache,
            _email_detail_cache_lock,
            _invalidate_folder_cache,
            _invalidate_label_batch_cache,
            EmailRepository,
            get_db_session,
        )
        _invalidate_folder_cache("inbox", "sent")
        with _email_detail_cache_lock:
            _email_detail_cache.pop(str(ctx.email_id), None)
        _invalidate_label_batch_cache()
        with get_db_session() as session:
            cached = EmailRepository(session).get_by_email_id(
                ctx.email_id, account_id=ctx.account_id
            )
            if cached:
                cached.is_read = is_read
                session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("read-flag cache update suppressed: %s", exc)


def append_signature(body_html: str, account_id: int) -> str:
    try:
        from app.utils.signature import append_signature as _impl
        return _impl(body_html, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("signature append suppressed: %s", exc)
        return body_html


__all__ = ["evict_caches", "emit", "update_cached_read_flag", "append_signature"]
