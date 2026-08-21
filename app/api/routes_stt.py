# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""REST endpoints for STT keyterms (project labels auto-seed + user
overrides). Consumed by the Settings UI to manage which words the
speech-to-text decoder boosts.

The merged list is also read server-side by ``_call_deepgram`` in
``routes_misc.py`` — frontend never has to push the list to the
transcribe endpoint, the backend resolves it from the auth context.
"""

from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from app.api.auth import require_auth_or_local
from app.api.routes_helpers import _resolve_account_id_for_user
from app.api.utils.errors import error_response
from app.services import stt_keyterms

logger = logging.getLogger(__name__)

stt_bp = Blueprint("stt", __name__)


# Write-time cap on the custom override list. Reconciled to the read-time
# effective cap (``stt_keyterms.KEYTERM_CAP``) so storage == what dictation
# actually boosts — past this, a stored word would never reach the decoder
# (the merge truncates at KEYTERM_CAP), so we reject the add cleanly instead
# of silently keeping a dead entry. Single source of truth lives in the
# service module.
_MAX_CUSTOM_TERMS_PER_ACCOUNT = stt_keyterms.KEYTERM_CAP


@stt_bp.route("/keyterms", methods=["GET"])
@require_auth_or_local
def list_keyterms():
    """Return ``{auto: [...], custom: [...]}`` for the current account.

    `auto` is read-only (from project labels). `custom` is the user's
    own overrides — what they can add/remove via POST/DELETE.
    """
    account_id = _resolve_account_id_for_user()
    if account_id is None or account_id < 0:
        return jsonify({"auto": [], "custom": [], "cap": _MAX_CUSTOM_TERMS_PER_ACCOUNT})
    return jsonify({
        "auto": stt_keyterms.list_auto(account_id),
        "custom": stt_keyterms.list_custom(account_id),
        # Effective limit dictation can boost — the UI shows "X / cap" and
        # disables the add field once reached.
        "cap": _MAX_CUSTOM_TERMS_PER_ACCOUNT,
    })


@stt_bp.route("/keyterms", methods=["POST"])
@require_auth_or_local
def add_keyterm():
    """Body: ``{"term": "..."}``. Returns 201 on insert, 200 on duplicate."""
    account_id = _resolve_account_id_for_user()
    if account_id is None or account_id < 0:
        return error_response("STT_NO_ACCOUNT", "No associated account", 404)

    payload = request.get_json(silent=True) or {}
    term = (payload.get("term") or "").strip()
    if not term:
        return error_response("STT_TERM_REQUIRED", "Field 'term' is required", 400)

    # Cap the override list at the dictation-effective limit: words beyond
    # this would be stored but never boosted (the merge truncates at
    # KEYTERM_CAP), so reject cleanly rather than keep a dead entry.
    existing = stt_keyterms.list_custom(account_id)
    if len(existing) >= _MAX_CUSTOM_TERMS_PER_ACCOUNT:
        return error_response(
            "STT_TERM_LIMIT_REACHED",
            f"Dictation can use up to {_MAX_CUSTOM_TERMS_PER_ACCOUNT} custom words; "
            "remove one to add another",
            409,
            context={"limit": _MAX_CUSTOM_TERMS_PER_ACCOUNT},
        )

    inserted = stt_keyterms.add_keyterm(account_id, term)
    custom = stt_keyterms.list_custom(account_id)
    return jsonify({"inserted": inserted, "custom": custom}), (201 if inserted else 200)


@stt_bp.route("/keyterms/auto/<path:term>", methods=["DELETE"])
@require_auth_or_local
def exclude_auto_keyterm(term: str):
    """Hide an auto-seeded term (project label) from the merged list."""
    account_id = _resolve_account_id_for_user()
    if account_id is None or account_id < 0:
        return error_response("STT_NO_ACCOUNT", "No associated account", 404)

    stt_keyterms.exclude_auto_keyterm(account_id, term)
    return jsonify({"excluded": True, "auto": stt_keyterms.list_auto(account_id)})


@stt_bp.route("/keyterms/<path:term>", methods=["DELETE"])
@require_auth_or_local
def delete_keyterm(term: str):
    """Remove a custom keyterm. Case-insensitive match. ``path:term``
    converter accepts terms containing slashes/dots without 404."""
    account_id = _resolve_account_id_for_user()
    if account_id is None or account_id < 0:
        return error_response("STT_NO_ACCOUNT", "No associated account", 404)

    removed = stt_keyterms.remove_keyterm(account_id, term)
    if not removed:
        return error_response("STT_WORD_NOT_FOUND", "Word not found", 404)
    return jsonify({"removed": True, "custom": stt_keyterms.list_custom(account_id)})


# Deepgram grant endpoint URL — temporary client-side tokens.
_DEEPGRAM_GRANT_URL = "https://api.deepgram.com/v1/auth/grant"
# Default TTL for the mobile streaming token. The token only needs to be valid
# at WebSocket-connect time; a few minutes covers session start + a transparent
# reconnect. Deepgram caps at 3600s.
_GRANT_TTL_DEFAULT = 300


@stt_bp.route("/grant-token", methods=["POST"])
@require_auth_or_local
def grant_streaming_token():
    """Mint a short-lived Deepgram token for DIRECT client→Deepgram streaming.

    Why: the Socket.IO `/daemon` proxy (``stt_stream.py``) cannot carry the
    live audio WebSocket in prod — gunicorn's ``gthread`` worker doesn't
    support WS upgrades (HTTP 400), and continuous binary audio dies on the
    polling fallback (Deepgram saw ``bytes=0``). So the mobile connects
    DIRECTLY to ``wss://api.deepgram.com/v1/listen`` instead, authenticated
    by a temporary token this endpoint mints from the master key. The master
    ``DEEPGRAM_API_KEY`` never leaves the server; the client gets a JWT that
    expires in minutes (Deepgram ``/v1/auth/grant``).
    """
    account_id = _resolve_account_id_for_user()
    if account_id is None or account_id < 0:
        return error_response("STT_NO_ACCOUNT", "No associated account", 404)

    deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
    if not deepgram_key:
        return error_response("STT_UNAVAILABLE", "Streaming STT not configured", 503)

    payload = request.get_json(silent=True) or {}
    try:
        ttl = int(payload.get("ttl_seconds", _GRANT_TTL_DEFAULT))
    except (TypeError, ValueError):
        ttl = _GRANT_TTL_DEFAULT
    ttl = max(10, min(ttl, 3600))

    import requests  # lazy, matches _call_deepgram pattern

    try:
        resp = requests.post(
            _DEEPGRAM_GRANT_URL,
            headers={"Authorization": f"Token {deepgram_key}"},
            json={"ttl_seconds": ttl},
            timeout=8,
        )
    except requests.RequestException as exc:  # noqa: BLE001
        logger.warning("[stt-grant] Deepgram grant request failed: %s", exc)
        return error_response("STT_GRANT_FAILED", "Could not obtain streaming token", 502)

    if resp.status_code != 200:
        logger.warning("[stt-grant] Deepgram grant %s: %s", resp.status_code, resp.text[:200])
        return error_response("STT_GRANT_FAILED", "Could not obtain streaming token", 502)

    try:
        data = resp.json()
    except ValueError:
        return error_response("STT_GRANT_FAILED", "Malformed grant response", 502)

    # Deepgram returns {"access_token": "<jwt>", "expires_in": <seconds>}.
    token = data.get("access_token") or data.get("token")
    if not token:
        return error_response("STT_GRANT_FAILED", "Malformed grant response", 502)
    expires_in = data.get("expires_in", ttl)

    logger.info("[stt-grant] minted streaming token account=%s ttl=%ss", account_id, expires_in)
    return jsonify({"token": token, "expires_in": expires_in})
