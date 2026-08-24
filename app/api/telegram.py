# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
API endpoints for Telegram integration.

Provides REST API to:
- List Telegram messages pending response
- Generate AI suggestions for Telegram messages
- Send responses via Telegram bot
"""
import logging
import os
import threading
from typing import Any, Optional

from flask import Blueprint, request, jsonify

from app.telegram_integration import get_telegram_bot, TelegramMessage
from app.message_router import (
    get_message_router,
    create_incoming_message,
    MessageChannel,
)
from app.providers.telegram_adapter import TelegramAdapter, get_telegram_adapter

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram", __name__)


# F-04 (regression audit, 2026-04-29): per-tenant outbound adapter registry.
# `respond_to_message` previously used the env-singleton adapter for every
# tenant — meaning a tenant who configured their own bot_token saw outbound
# replies sent from the wrong identity (or failed silently when env unset).
# Now: if a tenant has their own bot_token configured, send via a dedicated
# adapter constructed from that token. The env adapter is kept only as the
# default-pool fallback for tenants without a personal bot.
_tenant_adapters: dict[str, TelegramAdapter] = {}
_tenant_adapters_lock = threading.Lock()
# Cap: bounded so token rotations (audit follow-up 2026-04-29) cannot
# leak adapters indefinitely. 200 covers single-instance fan-out far
# beyond any realistic tenant count.
_TENANT_ADAPTERS_MAX = 200


def _get_outbound_telegram_adapter(bot) -> Optional[TelegramAdapter]:
    """Resolve the adapter to use for an outbound send for `bot`.

    F-04: returns the per-tenant adapter when `bot.config.bot_token` is
    set and differs from the env-singleton's token. Falls back to the
    global env adapter for tenants without a configured token.

    Token rotation safety (audit follow-up 2026-04-29): cache keyed by
    token string, so any rotation produces a fresh entry. Soft FIFO cap
    prevents unbounded growth from a token-rotation flood.
    """
    cfg = getattr(bot, "config", None)
    tenant_token = (getattr(cfg, "bot_token", None) or "").strip()
    env_token = (os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()

    if tenant_token and tenant_token != env_token:
        with _tenant_adapters_lock:
            adapter = _tenant_adapters.get(tenant_token)
            if adapter is None:
                if len(_tenant_adapters) >= _TENANT_ADAPTERS_MAX:
                    try:
                        oldest_token = next(iter(_tenant_adapters))
                        _tenant_adapters.pop(oldest_token, None)
                        logger.info(
                            "[F-04] tenant adapter cache at cap, evicted oldest"
                        )
                    except StopIteration:
                        pass
                try:
                    adapter = TelegramAdapter(bot_token=tenant_token)
                    adapter.connect()
                except Exception as exc:
                    logger.warning("[F-04] tenant Telegram adapter init failed: %s", exc)
                    return None
                _tenant_adapters[tenant_token] = adapter
            return adapter

    return get_telegram_adapter()


def evict_outbound_telegram_adapter(token: Optional[str]) -> bool:
    """Drop a cached per-tenant adapter (account-deletion / token rotation).

    F-04 follow-up: pair with `app.telegram_integration.evict_telegram_bot`
    so a tenant who deletes their config or rotates their token has the
    cached adapter invalidated and the connection thread freed. Returns
    True when an adapter was actually evicted.
    """
    if not token:
        return False
    with _tenant_adapters_lock:
        return _tenant_adapters.pop(token, None) is not None


def _scoped_bot_or_404():
    """Resolve the per-tenant Telegram bot for the JWT caller.

    F-01 (regression audit, 2026-04-29): the original F-11 fix only
    wired the per-tenant scoping into `list_messages`; the other 6
    handlers (`get_message`, `suggest_response`, `respond_to_message`,
    `skip_message`, `get_config`, `get_stats`) still hit the default
    admin pool, so a tenant who listed their own messages couldn't
    operate on them and any tenant could read/mutate the default-pool
    history (cron alerts, ops content). This helper centralises the
    resolution so every handler stays consistent.

    Returns (bot, None) on success, (None, flask_response) when the
    caller has no resolved account — handlers must return that response
    immediately (do NOT fall back to the default pool, which contains
    cross-tenant content).
    """
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        _NO_ACCOUNT_SENTINEL,
    )
    account_id = _resolve_account_id_for_user()
    if account_id == _NO_ACCOUNT_SENTINEL or not account_id:
        return None, (jsonify({"error": "Message not found"}), 404)
    return get_telegram_bot(account_id=str(account_id)), None


def _message_to_dict(msg: TelegramMessage) -> dict[str, Any]:
    """Convert a TelegramMessage to API response format."""
    return {
        "id": msg.id,
        "channel": "telegram",
        "sender_id": msg.author_id,
        "sender_name": msg.author_name,
        "content": msg.content,
        "received_at": msg.created_at,
        "conversation_id": msg.chat_id,
        "has_attachments": False,
        "chat_id": msg.chat_id,
        "chat_type": msg.metadata.get("chat_type"),
        "responded": msg.responded,
        "response_content": msg.response_content,
    }


@telegram_bp.route("/messages", methods=["GET"])
def list_messages():
    """
    List Telegram messages pending response.
    ---
    tags:
      - Telegram
    parameters:
      - name: limit
        in: query
        type: integer
        default: 50
        description: Maximum number of messages to return
      - name: pending_only
        in: query
        type: boolean
        default: true
        description: Only return messages without response
    responses:
      200:
        description: List of Telegram messages
    """
    # F-11 (audit issue #209) → F-01 (regression audit, 2026-04-29):
    # per-tenant scoping centralised via `_scoped_bot_or_404`. Same
    # behavior as before for `list_messages`, just sharing the
    # resolution code with the 6 sibling handlers that had been
    # hitting the cross-tenant default pool.
    bot, err = _scoped_bot_or_404()
    if err:
        # Empty list rather than 404 here — list_messages is the
        # discovery surface; an empty inbox is a valid state.
        return jsonify({"count": 0, "messages": []})

    limit = request.args.get("limit", 50, type=int)
    limit = max(1, min(100, limit))
    pending_only = request.args.get("pending_only", "true").lower() == "true"

    messages = bot.history

    if pending_only:
        messages = [m for m in messages if not m.responded]

    messages = messages[-limit:]

    return jsonify({
        "count": len(messages),
        "messages": [_message_to_dict(m) for m in messages],
    })


@telegram_bp.route("/messages/<message_id>", methods=["GET"])
def get_message(message_id: str):
    """
    Get a specific Telegram message.
    ---
    tags:
      - Telegram
    parameters:
      - name: message_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Telegram message details
      404:
        description: Message not found
    """
    # F-01 (regression audit, 2026-04-29): scope to the JWT caller's bot.
    bot, err = _scoped_bot_or_404()
    if err:
        return err

    for msg in bot.history:
        if msg.id == message_id:
            return jsonify(_message_to_dict(msg))

    return jsonify({"error": "Message not found"}), 404


@telegram_bp.route("/messages/<message_id>/suggest", methods=["POST"])
def suggest_response(message_id: str):
    """
    Generate AI suggestion for a Telegram message.
    ---
    tags:
      - Telegram
    parameters:
      - name: message_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Suggested response
      404:
        description: Message not found
    """
    # F-01 (regression audit, 2026-04-29): scope to caller's bot.
    bot, err = _scoped_bot_or_404()
    if err:
        return err
    msg = None

    for m in bot.history:
        if m.id == message_id:
            msg = m
            break

    if not msg:
        return jsonify({"error": "Message not found"}), 404

    router = get_message_router()
    incoming = create_incoming_message(
        channel=MessageChannel.TELEGRAM,
        content=msg.content,
        sender_id=msg.author_id,
        sender_name=msg.author_name,
        conversation_id=msg.chat_id,
        metadata={
            "chat_type": msg.metadata.get("chat_type"),
        },
    )

    try:
        context = router.route(incoming)

        return jsonify({
            "message_id": message_id,
            "suggestion": {
                "content": f"Réponse suggérée pour: {msg.content[:50]}...",
                "confidence": context.final_decision.confidence if context.final_decision else 0.8,
                "agent_id": context.final_decision.target_agent if context.final_decision else "general",
                "category": context.final_decision.category.value if context.final_decision else "general",
            },
        })
    except Exception as e:
        logger.error(f"Error generating suggestion: {e}")
        return jsonify({
            "message_id": message_id,
            "suggestion": {
                "content": "",
                "confidence": 0,
                "agent_id": "error",
            },
            "error": str(e),
        }), 500


@telegram_bp.route("/messages/<message_id>/respond", methods=["POST"])
def respond_to_message(message_id: str):
    """
    Send a response to a Telegram message.
    ---
    tags:
      - Telegram
    parameters:
      - name: message_id
        in: path
        type: string
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            content:
              type: string
              description: Response content
            send:
              type: boolean
              description: Whether to send via Telegram bot (default false)
    responses:
      200:
        description: Response sent
      400:
        description: Invalid request
      404:
        description: Message not found
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "content is required"}), 400

    content = data["content"].strip()
    if not content:
        return jsonify({"error": "content cannot be empty"}), 400

    should_send = data.get("send", False)

    # F-01 (regression audit, 2026-04-29): scope to caller's bot.
    bot, err = _scoped_bot_or_404()
    if err:
        return err
    msg = None
    msg_index = -1

    for i, m in enumerate(bot.history):
        if m.id == message_id:
            msg = m
            msg_index = i
            break

    if not msg:
        return jsonify({"error": "Message not found"}), 404

    msg.responded = True
    msg.response_content = content
    bot.history[msg_index] = msg
    bot._save()

    result = {
        "success": True,
        "message_id": message_id,
        "response_content": content,
    }

    if should_send:
        # F-04 (regression audit, 2026-04-29): use the per-tenant adapter
        # so the outbound message is signed by the tenant's own bot token
        # instead of leaking the env-singleton (ops bot) into the chat.
        adapter = _get_outbound_telegram_adapter(bot)
        if adapter and adapter.is_connected():
            sent_id = adapter.send_message(
                msg.chat_id, content, reply_to_id=message_id
            )
            if sent_id:
                result["sent"] = True
                result["sent_message_id"] = sent_id
            else:
                result["sent"] = False
                result["error"] = "Failed to send message via Telegram"
        else:
            result["sent"] = False
            result["error"] = "Telegram adapter not connected"

    return jsonify(result)


@telegram_bp.route("/messages/<message_id>/skip", methods=["POST"])
def skip_message(message_id: str):
    """
    Mark a Telegram message as skipped (no response needed).
    ---
    tags:
      - Telegram
    parameters:
      - name: message_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Message skipped
      404:
        description: Message not found
    """
    # F-01 (regression audit, 2026-04-29): scope to caller's bot.
    bot, err = _scoped_bot_or_404()
    if err:
        return err

    for i, m in enumerate(bot.history):
        if m.id == message_id:
            m.responded = True
            m.response_content = "[SKIPPED]"
            bot.history[i] = m
            bot._save()
            return jsonify({"success": True, "message_id": message_id})

    return jsonify({"error": "Message not found"}), 404


@telegram_bp.route("/config", methods=["GET"])
def get_config():
    """
    Get Telegram bot configuration.
    ---
    tags:
      - Telegram
    responses:
      200:
        description: Bot configuration
    """
    # F-01 (regression audit, 2026-04-29): per-tenant config; without
    # account context, return "not configured" rather than the default
    # pool's bot_token (which is operational shared infra).
    bot, err = _scoped_bot_or_404()
    if err:
        return jsonify({
            "configured": False,
            "bot_token_set": False,
            "bot_name": None,
            "notifications_chat_id_set": False,
            "support_chat_id_set": False,
        })
    return jsonify({
        "configured": bot.is_configured(),
        "bot_token_set": bool(bot.config.bot_token),
        "bot_name": bot.config.bot_name,
        "notifications_chat_id_set": bool(bot.config.notifications_chat_id),
        "support_chat_id_set": bool(bot.config.support_chat_id),
    })


@telegram_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Get Telegram integration statistics.
    ---
    tags:
      - Telegram
    responses:
      200:
        description: Statistics
    """
    # F-01 (regression audit, 2026-04-29): per-tenant stats.
    bot, err = _scoped_bot_or_404()
    if err:
        return jsonify({"open_tickets": 0, "resolved_tickets": 0,
                        "total_messages": 0, "configured": False, "enabled": False})
    stats = bot.get_stats()
    return jsonify(stats)
