"""
API TTS : proxy ElevenLabs avec cache MP3 sur disque.

Endpoints (tous protégés par le guard d'auth global) :
  - GET    /api/tts/voices                → liste des voix (premade + clonées)
  - POST   /api/tts/speak                 → synthétise → {audio_url, cached, chars}
  - GET    /api/tts/audio/<hash>.mp3      → sert le MP3 synthétisé
  - POST   /api/tts/clone                 → crée une voix clonée (multipart)
  - DELETE /api/tts/voices/<voice_id>     → supprime une voix clonée
"""

from __future__ import annotations

import logging
import re
import threading
import time

from flask import Blueprint, jsonify, request, send_file

from app.adapters.elevenlabs_adapter import ElevenLabsAdapter, ElevenLabsError
from app.api.utils.errors import error_response
from app.infrastructure.tts_cache import (
    TTS_CACHE_DIR,
    compute_hash,
    delete_voice_owner,
    get_cached,
    get_voice_owner,
    put,
    set_voice_owner,
)
from app.utils.tts_cleaner import clean_for_tts

logger = logging.getLogger(__name__)

tts_bp = Blueprint("tts", __name__)

# Limites d'input
_MAX_TEXT_CHARS = 2500
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MIME_PREFIX = ("audio/",)
_MAX_SAMPLE_BYTES = 11 * 1024 * 1024  # 11MB (limite ElevenLabs par fichier)
_MAX_SAMPLES = 5

# Cache mémoire pour la liste des voix (ElevenLabs /v1/voices est lent)
_voices_cache: dict = {"voices": None, "fetched_at": 0.0}
_voices_lock = threading.Lock()
_VOICES_TTL = 300  # 5 min

_DEFAULT_MODEL = "eleven_turbo_v2_5"


def _adapter() -> ElevenLabsAdapter:
    return ElevenLabsAdapter()


def _truncate(text: str, limit: int = _MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    # couper sur la dernière ponctuation forte sous la limite
    head = text[:limit]
    for punct in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        idx = head.rfind(punct)
        if idx >= limit * 0.6:
            return head[: idx + 1] + " (…)"
    idx = head.rfind(" ")
    if idx >= limit * 0.6:
        return head[:idx] + " (…)"
    return head + " (…)"


def _serialize_voice(voice) -> dict:
    return {
        "voice_id": voice.voice_id,
        "name": voice.name,
        "category": voice.category,
        "preview_url": voice.preview_url,
        "labels": voice.labels,
        "language": voice.language,
    }


@tts_bp.route("/voices", methods=["GET"])
def list_voices():
    now = time.time()
    with _voices_lock:
        cached_at = _voices_cache["fetched_at"]
        if _voices_cache["voices"] is not None and now - cached_at < _VOICES_TTL:
            return jsonify({"voices": _voices_cache["voices"]})

    try:
        voices = _adapter().list_voices()
    except ElevenLabsError as exc:
        logger.warning("TTS list_voices: %s", exc)
        return jsonify({"error": str(exc)}), exc.status_code

    serialized = [_serialize_voice(v) for v in voices]
    with _voices_lock:
        _voices_cache["voices"] = serialized
        _voices_cache["fetched_at"] = now
    return jsonify({"voices": serialized})


_SUPPORTED_LANGUAGES = {"fr", "en", "de", "es", "it", "pt", "pl", "ja", "zh"}


@tts_bp.route("/speak", methods=["POST"])
def speak():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    voice_id = (payload.get("voice_id") or "").strip()
    model_id = (payload.get("model_id") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    # ISO 639-1 optionnel — si fourni, pin la langue pour ElevenLabs afin
    # d'éviter une mauvaise auto-détection (surtout sur phrases courtes).
    raw_lang = (payload.get("language_code") or "").strip().lower()
    language_code = raw_lang if raw_lang in _SUPPORTED_LANGUAGES else None
    clean = bool(payload.get("clean", True))

    if not text:
        return jsonify({"error": "text requis"}), 400
    if not voice_id:
        return jsonify({"error": "voice_id requis"}), 400

    if clean:
        text = clean_for_tts(text)
    text = _truncate(text)

    hash_ = compute_hash(text, voice_id, model_id, language_code=language_code)
    cached_path = get_cached(hash_)
    if cached_path is not None:
        return jsonify(
            {
                "audio_url": f"/api/tts/audio/{hash_}.mp3",
                "cached": True,
                "chars": len(text),
            }
        )

    try:
        mp3 = _adapter().synthesize(
            text, voice_id, model_id=model_id, language_code=language_code
        )
    except ElevenLabsError as exc:
        logger.warning("TTS synth: %s (voice=%s, chars=%d)", exc, voice_id, len(text))
        return jsonify({"error": str(exc)}), exc.status_code

    put(hash_, mp3, voice_id, model_id, chars=len(text))
    return jsonify(
        {
            "audio_url": f"/api/tts/audio/{hash_}.mp3",
            "cached": False,
            "chars": len(text),
        }
    )


@tts_bp.route("/audio/<path:hash_filename>", methods=["GET"])
def serve_audio(hash_filename: str):
    if not hash_filename.endswith(".mp3"):
        return jsonify({"error": "extension invalide"}), 400
    hash_ = hash_filename[:-4]
    if not _HASH_RE.match(hash_):
        return jsonify({"error": "hash invalide"}), 400
    path = get_cached(hash_)
    if path is None:
        return jsonify({"error": "audio introuvable"}), 404
    return send_file(str(path), mimetype="audio/mpeg", max_age=86400)


@tts_bp.route("/clone", methods=["POST"])
def clone_voice():
    # F-09 (audit issue #209, 2026-04-29) + F-03 (regression audit,
    # 2026-04-29): rate-limit /clone to prevent any one user from
    # draining the GLOBAL ElevenLabs voice slot pool. The original
    # F-09 keyed the bucket by endpoint name only — meaning the second
    # tenant to clone got 429 for 24h. Now key by (endpoint, user_id)
    # so each user has their own 2/day budget. Falls back to remote
    # IP for non-JWT loopback (Tauri desktop).
    from app.api.routes_helpers import _rate_limited
    from flask import g as _flask_g
    auth_user = getattr(_flask_g, "auth_user", None)
    user_key = (
        str(auth_user.get("id"))
        if auth_user and auth_user.get("id") is not None
        else (request.remote_addr or "unknown")
    )
    allowed, retry_after = _rate_limited(
        f"tts_clone:{user_key}", max_calls=2, window_seconds=86400,
    )
    if not allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": retry_after}), 429

    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    if not name:
        return jsonify({"error": "name requis"}), 400
    if len(name) > 100:
        return jsonify({"error": "name trop long (>100)"}), 400

    raw_files = request.files.getlist("files")
    if not raw_files:
        return error_response("TTS_FILES_REQUIRED", "At least one audio file required in 'files'", 400)
    if len(raw_files) > _MAX_SAMPLES:
        return error_response(
            "TTS_MAX_SAMPLES",
            f"Maximum {_MAX_SAMPLES} samples",
            400,
            context={"max": _MAX_SAMPLES},
        )

    samples: list[tuple[str, bytes, str]] = []
    total_bytes = 0
    for f in raw_files:
        mime = (f.content_type or "").lower()
        if not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIX):
            return error_response(
                "TTS_INVALID_MIME",
                f"Invalid MIME: {mime}",
                400,
                context={"mime": mime},
            )
        blob = f.read()
        if not blob:
            return error_response("TTS_EMPTY_FILE", "Empty file", 400)
        if len(blob) > _MAX_SAMPLE_BYTES:
            return error_response("TTS_SAMPLE_TOO_LARGE", "Sample too large (>11MB)", 400)
        total_bytes += len(blob)
        samples.append((f.filename or "sample.m4a", blob, mime))

    try:
        voice_id = _adapter().clone_voice(name, samples, description=description)
    except ElevenLabsError as exc:
        logger.warning("TTS clone: %s", exc)
        return jsonify({"error": str(exc)}), exc.status_code

    # F-02 (regression audit, 2026-04-29): persist voice → owner so that
    # /api/tts/voices/<id> DELETE can refuse cross-tenant deletes. Owner
    # is the authenticated JWT user when present; for loopback (Tauri
    # desktop, single-user) we record (-1, "loopback") as a sentinel so
    # later loopback DELETEs still succeed without a JWT but a remote
    # JWT caller cannot delete a voice that belongs to the desktop.
    if auth_user and auth_user.get("id") is not None:
        set_voice_owner(voice_id, int(auth_user["id"]), auth_user.get("email", ""))
    else:
        set_voice_owner(voice_id, -1, "loopback")

    # Invalider le cache mémoire des voix pour que la nouvelle apparaisse
    with _voices_lock:
        _voices_cache["voices"] = None
        _voices_cache["fetched_at"] = 0.0

    logger.info(
        "Voice cloned: name=%s voice_id=%s samples=%d bytes=%d",
        name,
        voice_id,
        len(samples),
        total_bytes,
    )
    return jsonify({"voice_id": voice_id, "name": name}), 201


@tts_bp.route("/voices/<voice_id>", methods=["DELETE"])
def delete_voice(voice_id: str):
    if not voice_id or not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", voice_id):
        return error_response("TTS_INVALID_VOICE_ID", "Invalid voice_id", 400)

    # F-02 (regression audit, 2026-04-29): refuse to delete voices not
    # owned by the JWT caller. ElevenLabs operates a single shared
    # tenant-wide pool — without this gate, any logged-in user could
    # destroy any other user's cloned voice.
    from flask import g as _flask_g
    auth_user = getattr(_flask_g, "auth_user", None)
    owner = get_voice_owner(voice_id)
    if owner is not None:
        owner_uid, owner_email = owner
        if auth_user and auth_user.get("id") is not None:
            if int(auth_user["id"]) != owner_uid:
                logger.warning(
                    "[F-02] cross-tenant DELETE refused: voice=%s owner_uid=%s caller_uid=%s",
                    voice_id, owner_uid, auth_user["id"],
                )
                return error_response("TTS_VOICE_NOT_OWNED", "Voice not owned by caller", 403)
        # If auth_user is None (loopback) and the voice was cloned by a
        # JWT user, refuse — desktop session shouldn't be able to delete
        # a JWT user's voice. Voices owned by loopback (-1) are deletable
        # from loopback as before.
        elif auth_user is None and owner_uid != -1:
            logger.warning(
                "[F-02] loopback DELETE refused for JWT-owned voice: voice=%s owner_uid=%s",
                voice_id, owner_uid,
            )
            return error_response("TTS_VOICE_NOT_OWNED", "Voice not owned by caller", 403)
    else:
        # owner is None → unknown voice (legacy clone before F-02, or a
        # premade ElevenLabs voice).
        #
        # Audit follow-up 2026-04-29 (P2 fail-closed): refuse DELETE on
        # unowned voices when called via JWT — a remote authenticated
        # user has no business deleting voices that the app didn't track.
        # Loopback callers (Tauri desktop, single-user) keep the legacy
        # path so the user can clean up old clones via their own client.
        # Premade voices fail at ElevenLabs anyway (404), so this just
        # returns a friendlier 403 first.
        if auth_user and auth_user.get("id") is not None:
            logger.warning(
                "[F-02] DELETE refused on unowned (legacy) voice: voice=%s caller_uid=%s",
                voice_id, auth_user["id"],
            )
            return jsonify({
                "error": "voice non suivie ou legacy — contactez le support",
            }), 403
        # Loopback: allow the delete to fall through to ElevenLabs.

    try:
        _adapter().delete_voice(voice_id)
    except ElevenLabsError as exc:
        logger.warning("TTS delete voice %s: %s", voice_id, exc)
        return jsonify({"error": str(exc)}), exc.status_code

    delete_voice_owner(voice_id)

    with _voices_lock:
        _voices_cache["voices"] = None
        _voices_cache["fetched_at"] = 0.0

    return ("", 204)


# Export pour le test client + visibilité du répertoire cache (debug)
__all__ = ["tts_bp", "TTS_CACHE_DIR"]
