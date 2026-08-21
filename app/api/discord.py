"""
API endpoints for Discord integration.

Provides REST API to:
- List Discord messages pending response
- Generate AI suggestions for Discord messages
- Send responses via Discord bot
"""
import logging
import os
import threading
from typing import Any, Optional

from flask import Blueprint, request, jsonify

from app.discord_integration import get_discord_bot, DiscordMessage
from app.message_router import (
    get_message_router,
    create_incoming_message,
    MessageChannel,
)
from app.providers.discord_adapter import DiscordAdapter, get_discord_adapter

logger = logging.getLogger(__name__)

discord_bp = Blueprint("discord", __name__)


# F-04 (regression audit, 2026-04-29): per-tenant outbound adapter registry.
# Same rationale as telegram.py — see that file's `_get_outbound_telegram_adapter`.
_tenant_adapters: dict[str, DiscordAdapter] = {}
_tenant_adapters_lock = threading.Lock()
_TENANT_ADAPTERS_MAX = 200


def _get_outbound_discord_adapter(bot) -> Optional[DiscordAdapter]:
    """Resolve the adapter to use for an outbound send for `bot`.

    F-04: returns the per-tenant adapter when `bot.config.bot_token` is
    set and differs from the env-singleton's token. Falls back to the
    global env adapter for tenants without a configured token.

    Token rotation safety (audit follow-up 2026-04-29): same FIFO cap
    pattern as telegram.py — see that file for details.
    """
    cfg = getattr(bot, "config", None)
    tenant_token = (getattr(cfg, "bot_token", None) or "").strip()
    env_token = (os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()

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
                    adapter = DiscordAdapter(bot_token=tenant_token)
                    adapter.connect()
                except Exception as exc:
                    logger.warning("[F-04] tenant Discord adapter init failed: %s", exc)
                    return None
                _tenant_adapters[tenant_token] = adapter
            return adapter

    return get_discord_adapter()


def evict_outbound_discord_adapter(token: Optional[str]) -> bool:
    """Drop a cached per-tenant adapter (account-deletion / token rotation).

    F-04 follow-up: same shape as `app.api.telegram.evict_outbound_telegram_adapter`.
    """
    if not token:
        return False
    with _tenant_adapters_lock:
        return _tenant_adapters.pop(token, None) is not None


def _scoped_bot_or_404():
    """Resolve the per-tenant Discord bot for the JWT caller.

    F-01 (regression audit, 2026-04-29): same shape as the helper in
    `app/api/telegram.py`. The original F-11 fix only wired per-tenant
    scoping into `list_messages`; the other 6 handlers were still
    hitting the cross-tenant default pool. This helper centralises the
    resolution.
    """
    from app.api.routes_helpers import (
        _resolve_account_id_for_user,
        _NO_ACCOUNT_SENTINEL,
    )
    account_id = _resolve_account_id_for_user()
    if account_id == _NO_ACCOUNT_SENTINEL or not account_id:
        return None, (jsonify({"error": "Message not found"}), 404)
    return get_discord_bot(account_id=str(account_id)), None


def _message_to_dict(msg: DiscordMessage) -> dict[str, Any]:
    """Convert a DiscordMessage to API response format."""
    return {
        "id": msg.id,
        "channel": "discord",
        "sender_id": msg.author_id,
        "sender_name": msg.author_name,
        "content": msg.content,
        "received_at": msg.created_at,
        "conversation_id": msg.channel_id,
        "has_attachments": False,
        "channel_id": msg.channel_id,
        "channel_name": msg.metadata.get("channel_name"),
        "guild_id": msg.metadata.get("guild_id"),
        "guild_name": msg.metadata.get("guild_name"),
        "message_url": msg.metadata.get("message_url"),
        "responded": msg.responded,
        "response_content": msg.response_content,
    }


@discord_bp.route("/messages", methods=["GET"])
def list_messages():
    """
    List Discord messages pending response.
    ---
    tags:
      - Discord
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
        description: List of Discord messages
    """
    # F-01 (regression audit, 2026-04-29): scoped via shared helper.
    bot, err = _scoped_bot_or_404()
    if err:
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


@discord_bp.route("/messages/<message_id>", methods=["GET"])
def get_message(message_id: str):
    """
    Get a specific Discord message.
    ---
    tags:
      - Discord
    parameters:
      - name: message_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Discord message details
      404:
        description: Message not found
    """
    # F-01 (regression audit, 2026-04-29): scope to JWT caller.
    bot, err = _scoped_bot_or_404()
    if err:
        return err

    for msg in bot.history:
        if msg.id == message_id:
            return jsonify(_message_to_dict(msg))

    return jsonify({"error": "Message not found"}), 404


@discord_bp.route("/messages/<message_id>/suggest", methods=["POST"])
def suggest_response(message_id: str):
    """
    Generate AI suggestion for a Discord message.
    ---
    tags:
      - Discord
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
    # F-01 (regression audit, 2026-04-29): scope to JWT caller.
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
        channel=MessageChannel.DISCORD,
        content=msg.content,
        sender_id=msg.author_id,
        sender_name=msg.author_name,
        conversation_id=msg.channel_id,
        metadata={
            "guild_id": msg.metadata.get("guild_id"),
            "channel_name": msg.metadata.get("channel_name"),
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


@discord_bp.route("/messages/<message_id>/respond", methods=["POST"])
def respond_to_message(message_id: str):
    """
    Send a response to a Discord message.
    ---
    tags:
      - Discord
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
              description: Whether to send via Discord bot (default false)
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

    # F-01 (regression audit, 2026-04-29): scope to JWT caller.
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
        # instead of leaking the env-singleton (ops bot) into the channel.
        adapter = _get_outbound_discord_adapter(bot)
        if adapter and adapter.is_connected():
            sent_id = adapter.send_message(
                msg.channel_id, content, reply_to_id=message_id
            )
            if sent_id:
                result["sent"] = True
                result["sent_message_id"] = sent_id
            else:
                result["sent"] = False
                result["error"] = "Failed to send message via Discord"
        else:
            result["sent"] = False
            result["error"] = "Discord adapter not connected"

    return jsonify(result)


@discord_bp.route("/messages/<message_id>/skip", methods=["POST"])
def skip_message(message_id: str):
    """
    Mark a Discord message as skipped (no response needed).
    ---
    tags:
      - Discord
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
    # F-01 (regression audit, 2026-04-29): scope to JWT caller.
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


@discord_bp.route("/config", methods=["GET"])
def get_config():
    """
    Get Discord bot configuration.
    ---
    tags:
      - Discord
    responses:
      200:
        description: Bot configuration
    """
    # F-01 (regression audit, 2026-04-29): per-tenant config; without
    # account context return "not configured" rather than the default
    # pool's webhook (which is operational shared infra).
    try:
        bot, err = _scoped_bot_or_404()
        if err:
            return jsonify({
                "configured": False,
                "webhook_url_set": False,
                "bot_name": None,
                "avatar_url_set": False,
            })
        return jsonify({
            "configured": bot.is_configured(),
            "webhook_url_set": bool(bot.config.webhook_url),
            "bot_name": getattr(bot.config, "bot_name", None),
            "avatar_url_set": bool(getattr(bot.config, "avatar_url", None)),
        })
    except Exception as e:
        logger.warning(f"Discord config error: {e}")
        return jsonify({
            "configured": False,
            "webhook_url_set": False,
            "bot_name": None,
            "avatar_url_set": False,
        })


@discord_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Get Discord integration statistics.
    ---
    tags:
      - Discord
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
