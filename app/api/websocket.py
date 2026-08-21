# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
WebSocket pour push des événements daemon vers l'app Tauri.

Ce module expose un namespace /daemon qui permet à l'app Tauri
de recevoir les événements en temps réel (nouveaux emails, brouillons prêts, sync status).
"""

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

from flask_socketio import SocketIO

from app.daemon import DaemonEvent, EventEmitter

logger = logging.getLogger(__name__)

_socketio: Optional[SocketIO] = None

# ──────────────────────────────────────────────────────────────────────────
# Reconnect event buffer (per-room)
#
# When an event is emitted to a room that has no active subscriber (client is
# in the 1-5s reconnection window, or briefly disconnected), it would be
# silently dropped. This buffer stores up to _BUFFER_MAX_PER_ROOM events per
# room for _BUFFER_TTL_SECONDS, and `_flush_pending_for_room` drains them on
# (re)connect. Prevents the "UI stuck in draft generating…" symptom.
# ──────────────────────────────────────────────────────────────────────────
_BUFFER_MAX_PER_ROOM = 50
_BUFFER_TTL_SECONDS = 120.0
# Events that MUST NOT be buffered (cheap status signals that are safe to
# drop — not worth replaying).
_BUFFER_EVENT_DENYLIST = frozenset({
    "sync_progress", "connectivity_changed",
    # Bulk jobs: progress is high-frequency (≤1/s/job, but a long
    # reconnect window can still pile up dozens). Frontend resyncs the
    # whole list on reconnect via REST instead.
    "bulk_job_progress",
})
# Events we actively WANT to buffer (critical state transitions).
_BUFFER_EVENT_ALLOWLIST = frozenset({
    "draft_complete", "draft_ready", "draft_error",
    "critique_complete", "critique_error",
    "new_email", "email_archived", "email_deleted",
    "email_restored", "email_spam_changed",
    "followup_draft_ready",
    "daemon_event",
    # Onboarding: buffer waiting_for_sync + progress so a client that
    # reconnects mid-sync catches the latest counter without waiting on
    # HTTP polling fallback (which has a 2 min circuit-breaker).
    "onboarding:learning_started", "onboarding:waiting_for_sync",
    "onboarding:progress_updated",
    # Discovery stream — narrative findings (signature, top contact,
    # default tone, ...) surfaced one event per wow moment.
    "onboarding:discovery",
    "onboarding:learning_completed", "onboarding:insights_generated",
    # Bulk jobs: critical state transitions (everything but progress —
    # progress is in the denylist above).
    "bulk_job_enqueued", "bulk_job_status", "bulk_job_completed",
})

_pending_events: Dict[str, Deque[Tuple[float, str, Dict[str, Any]]]] = {}
_pending_lock = threading.Lock()

# Lifetime counter of successful emit_to_account calls. Sampled by the
# /api/_internal/ws-stats endpoint to spot pathologies (sudden zero =
# emission path silently broken; runaway growth = something is fanning
# out without backpressure). Issue #577 item 3.
_emit_counter: int = 0
_emit_counter_lock = threading.Lock()
# Audit R-010 (2026-04-27): rooms whose owner never reconnects accumulate
# in _pending_events forever (memory leak under churn). Sweep stale rooms
# opportunistically, not more often than every _GC_INTERVAL seconds.
_GC_INTERVAL = 600.0  # 10 min
_last_gc_at: float = 0.0


# ──────────────────────────────────────────────────────────────────────────
# Prompt cache warmup on connect (audit 2026-05-05)
#
# Anthropic's prompt cache TTL is 5 minutes. The first draft per session
# pays a cache-miss on the entire static system prefix (~1.5–2k tokens,
# +100–200ms TTFT). Firing one tiny dummy completion when the client
# connects warms the cache so the user's first real draft hits it.
#
# Default ON. Disable via WS_CACHE_WARMUP=false. Debounced per-room with
# TTL just under Anthropic's 5-min cache so we don't pay the cost every
# reconnect inside the same warm window.
# ──────────────────────────────────────────────────────────────────────────
_cache_warmup_lock = threading.Lock()
_cache_warmup_last_at: Dict[str, float] = {}
_CACHE_WARMUP_DEBOUNCE = 240.0  # 4 min — under Anthropic's 5-min TTL


def _cache_warmup_enabled() -> bool:
    return os.environ.get("WS_CACHE_WARMUP", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )


def _maybe_warm_prompt_cache(room: str) -> None:
    """Fire-and-forget warmup of the Drafter system-prefix cache.

    Best-effort. Any exception (LLM unavailable, KB not loadable, network
    error) is logged at DEBUG and swallowed — a failed warmup must never
    affect the WS connect handshake. Cost per warmup: ~$0.0015 (Haiku
    input cost on the static prefix); debounce keeps that bounded.
    """
    if not room or not _cache_warmup_enabled():
        return
    now = time.time()
    with _cache_warmup_lock:
        last = _cache_warmup_last_at.get(room, 0.0)
        if now - last < _CACHE_WARMUP_DEBOUNCE:
            return
        _cache_warmup_last_at[room] = now
        # Opportunistically GC stale entries (older than 1h) so the dict
        # doesn't grow unbounded under churn — same pattern as _pending_events.
        cutoff = now - 3600.0
        for k in [k for k, t in _cache_warmup_last_at.items() if t < cutoff]:
            _cache_warmup_last_at.pop(k, None)

    def _worker() -> None:
        try:
            from app.infrastructure.container import get_container
            from app.infrastructure.llm_attribution import llm_attribution
            from app.infrastructure.cost_manager import (
                reset_usage_context,
                set_usage_context,
            )
            from app.prompts import load_knowledge_base

            account_id = None
            user_id = None
            if "@" in room:
                try:
                    from app.db.database import get_db_session
                    from app.db.repositories.account_repository import AccountRepository

                    with get_db_session() as session:
                        account = AccountRepository(session).get_by_email(room)
                        if account is not None:
                            account_id = account.id
                            user_id = getattr(account, "user_id", None)
                except Exception:
                    account_id = None
                    user_id = None

            llm = get_container().llm_drafting
            kb = load_knowledge_base() or ""
            # Warm the same static prefix the drafter actually uses. The
            # ping-tag suffix keys this completion as a no-op for the LLM —
            # max_tokens=1 caps the output billing at one token.
            usage_tokens = set_usage_context(
                account_id=account_id,
                user_id=user_id,
                feature="ws_cache_warmup",
            )
            try:
                with llm_attribution(
                    "ws_cache_warmup",
                    account_id=account_id,
                    user_id=user_id,
                    feature="ws_cache_warmup",
                ):
                    llm.complete(
                        system=f"{kb}\n=== ws_cache_warmup ===",
                        user="ping",
                        max_tokens=1,
                    )
            finally:
                reset_usage_context(usage_tokens)
            logger.debug("WebSocket: prompt cache warmed for room=%s", room)
        except Exception as e:
            logger.debug("WebSocket: cache warmup failed for room=%s: %s", room, e)

    t = threading.Thread(
        target=_worker,
        daemon=True,
        name=f"ws-cache-warm-{room[:16]}",
    )
    t.start()


def _gc_pending_events_locked(now: float) -> int:
    """Drop rooms whose every event is older than 2× TTL. Caller holds lock."""
    stale: list[str] = []
    cutoff = now - (2 * _BUFFER_TTL_SECONDS)
    for room, buf in _pending_events.items():
        if not buf or buf[-1][0] < cutoff:
            stale.append(room)
    for room in stale:
        _pending_events.pop(room, None)
    if stale:
        logger.info("WS buffer GC: evicted %d stale rooms", len(stale))
    return len(stale)


def _buffer_event_if_needed(room: str, event: str, data: Dict[str, Any]) -> None:
    """Append an event to the per-room buffer, dropping oldest when full.

    Only buffer events that are (a) in the allowlist AND (b) not in the
    denylist. Called from `emit_to_account` when no client is currently in
    the target room.
    """
    if not room or event in _BUFFER_EVENT_DENYLIST:
        return
    if event not in _BUFFER_EVENT_ALLOWLIST:
        return
    now = time.time()
    global _last_gc_at
    with _pending_lock:
        buf = _pending_events.get(room)
        if buf is None:
            buf = deque(maxlen=_BUFFER_MAX_PER_ROOM)
            _pending_events[room] = buf
        buf.append((now, event, data))
        # R-010: opportunistic sweep for stale rooms (no reconnect ever).
        if now - _last_gc_at >= _GC_INTERVAL:
            _last_gc_at = now
            _gc_pending_events_locked(now)


def _flush_pending_for_room(room: str) -> int:
    """Deliver buffered events to a newly-connected room.

    Called from on_daemon_connect after join_room. Drops events older than
    TTL. Returns the number of events delivered.
    """
    if _socketio is None:
        return 0
    now = time.time()
    delivered = 0
    with _pending_lock:
        buf = _pending_events.pop(room, None)
    if not buf:
        return 0
    for ts, event, data in list(buf):
        if now - ts > _BUFFER_TTL_SECONDS:
            continue
        try:
            _socketio.emit(event, data, namespace="/daemon", to=room)
            delivered += 1
        except Exception as e:
            logger.debug("flush_pending: failed to emit %s to %s: %s", event, room, e)
    if delivered:
        logger.info("WS buffer: replayed %d events to room=%s after reconnect", delivered, room)
    return delivered


class WebSocketEventEmitter(EventEmitter):
    """
    Émetteur d'événements via WebSocket.

    Pousse les événements du daemon vers tous les clients connectés
    au namespace /daemon.
    """

    def __init__(self, socketio: Optional[SocketIO] = None):
        self._socketio = socketio

    def emit(self, event: DaemonEvent, room: str | None = None) -> None:
        """
        Émet un événement vers les clients WebSocket d'une room spécifique.

        Args:
            event: L'événement daemon à émettre.
            room: Room cible (email utilisateur). None = broadcast à tous.
        """
        if self._socketio is None:
            logger.warning("WebSocket emit appelé sans SocketIO configuré")
            return

        data = {
            "type": event.event_type.value,
            "email_id": event.email_id,
            "timestamp": event.timestamp,
            "payload": event.payload,
        }

        # Audit Cluster D (2026-05-17) B-03: previously this raised straight
        # up through the classifier loop. A mid-emit socket close (client
        # disconnect, eventlet socket closed, Redis publish layer down) would
        # then drop the in-flight email's labeling. Mirror the defensive
        # try/except used by `_flush_pending_for_room` so an emit failure is
        # observable but non-fatal.
        try:
            self._socketio.emit("daemon_event", data, namespace="/daemon", to=room)
        except Exception as exc:
            logger.warning(
                "WebSocket emit failed for %s (room=%s): %s",
                event.event_type.value, room, exc,
            )
            return
        logger.debug("WebSocket: événement %s émis (room=%s)", event.event_type.value, room)


def on_daemon_connect(auth: Any = None) -> None:
    """Handler appelé lors d'une connexion au namespace /daemon.

    Vérifie que la connexion vient de localhost (mode Tauri) ou a un JWT valide.
    Joint l'utilisateur à une room privée basée sur son email pour isoler les events.

    Audit P1-007 (2026-04-28): the JWT is read EXCLUSIVELY from the
    socket.io `auth` handshake payload (POST body). The legacy
    `request.args.get("token")` URL-query fallback has been removed —
    sending the bearer in the URL leaked it into every reverse-proxy /
    Sentry access log line for the entire session lifetime. Clients that
    still send the token via query string will be rejected and must
    update.

    Audit P1-014 (2026-04-28): if the client supplies an `account_id` in
    the auth handshake, verify it belongs to the JWT user before joining
    a room derived from that field. Without this check a valid JWT_A
    could pin its room to JWT_B's account_id and receive B's events.
    """
    from flask import request as flask_request
    from flask_socketio import disconnect, join_room
    from app.api.auth import _decode_jwt, is_trusted_loopback

    # P1-007: ONLY the socket.io auth payload — never the URL query.
    token = ""
    if isinstance(auth, dict):
        token = str(auth.get("token", "") or "")
    # If a token slipped through the URL query, log+reject (do not silently accept).
    if not token and flask_request.args.get("token"):
        logger.warning(
            "WebSocket: connexion rejetée — token reçu via query string "
            "(URL leaks à chaque ligne de log proxy). Le client doit "
            "envoyer le JWT dans le payload `auth` du handshake."
        )
        disconnect()
        return

    user_email = None
    if token:
        payload = _decode_jwt(token)
        if not payload:
            logger.warning("WebSocket: connexion rejetée — token invalide")
            disconnect()
            return
        user_email = payload.get("email")
    else:
        # No token — only allow loopback (Tauri desktop)
        if not is_trusted_loopback():
            logger.warning("WebSocket: connexion rejetée — pas de token et pas localhost")
            disconnect()
            return

    # Audit P1-014: client may supply account_id to join a per-account room.
    # Verify ownership before honoring it.
    requested_account_id = None
    if isinstance(auth, dict):
        raw_aid = auth.get("account_id")
        if raw_aid not in (None, ""):
            try:
                # mypy strict refuse `int(Any | None)` même après le
                # narrow `not in (None, "")` (le check ne touche pas le
                # type, seulement la valeur). `str(raw_aid)` neutralise
                # le None résiduel ; le try/except gère le ValueError.
                requested_account_id = int(str(raw_aid))
            except (TypeError, ValueError):
                logger.warning(
                    "WebSocket: connexion rejetée — account_id non entier dans l'auth payload"
                )
                disconnect()
                return

    if requested_account_id is not None and user_email:
        try:
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                repo = AccountRepository(session)
                acct = repo.get(requested_account_id)
                if acct is None or (acct.email or "").strip().lower() != user_email.strip().lower():
                    logger.warning(
                        "WebSocket: connexion rejetée — account_id=%s n'appartient pas à %s",
                        requested_account_id, user_email,
                    )
                    disconnect()
                    return
        except Exception as e:
            logger.warning(
                "WebSocket: ownership lookup failed for account_id=%s user=%s: %s",
                requested_account_id, user_email, e,
            )
            disconnect()
            return

    # Joindre la room privée de l'utilisateur pour isoler les events
    # En mode JWT : room = email de l'utilisateur
    # En mode loopback (Tauri) : room = SID unique de la connexion Socket.IO
    if user_email:
        room = user_email
    else:
        # Flask-SocketIO attaches `sid` dynamically on the request proxy;
        # it's not declared on Flask's Request type stub.
        room = f"local_{flask_request.sid}"  # type: ignore[attr-defined]
    join_room(room, namespace="/daemon")
    # Loopback clients (no JWT — Tauri desktop or browser dev on localhost)
    # would only sit in `local_<sid>` while `emit_to_account()` targets
    # `<account.email>`. Result: every account-scoped onboarding/sync/draft
    # event silently dropped. Resolve the active account's email and join
    # that room too so loopback clients receive the events meant for them.
    if not user_email:
        try:
            from app.multi_accounts import get_current_account
            current = get_current_account()
            if current and current.email:
                join_room(current.email, namespace="/daemon")
                logger.info(
                    "WebSocket: loopback client joined account room=%s (extra)",
                    current.email,
                )
        except Exception as e:
            logger.debug("loopback account-room join failed: %s", e)
    logger.info("WebSocket: client connecté au namespace /daemon (room=%s)", room)
    # Streaming STT : confie l'identité vérifiée au registre des streams — les
    # event handlers stt_stream_* n'ont plus accès au payload auth du handshake.
    # Pour le JWT, l'ownership P1-014 a déjà été vérifié plus haut. Pour le
    # loopback (Tauri desktop, user_email None), `requested_account_id` venait
    # du payload SANS vérification (sur main il était parsé puis inutilisé ;
    # ce handler en est le premier consommateur) — on ne l'honore donc QUE s'il
    # résout au compte courant local, sinon None (audit P2-A).
    try:
        from app.api.stt_stream import register_sid_identity
        stt_account_id = requested_account_id
        if not user_email and requested_account_id is not None:
            verified = False
            try:
                from app.multi_accounts import get_current_account
                current = get_current_account()
                if current and str(getattr(current, "id", "")) == str(requested_account_id):
                    verified = True
            except Exception as e:  # noqa: BLE001
                logger.debug("WebSocket: loopback account verify failed: %s", e)
            if not verified:
                stt_account_id = None
        register_sid_identity(
            flask_request.sid,  # type: ignore[attr-defined]
            user_email,
            stt_account_id,
        )
    except Exception as e:
        logger.debug("WebSocket: stt identity registration failed: %s", e)
    try:
        from app.batch_queue import touch_user_activity
        touch_user_activity()  # type: ignore[no-untyped-call]
    except Exception as e:
        # S-18 fix: log so a bad batch_queue deploy doesn't silently break
        # activity tracking on every Socket.IO connect.
        logger.debug("WebSocket: touch_user_activity failed on connect: %s", e)
    # Replay buffered events that arrived while the client was disconnected.
    try:
        _flush_pending_for_room(room)
    except Exception as e:
        logger.debug("flush_pending on connect failed for room=%s: %s", room, e)

    # Warm the Drafter prompt cache so the user's first real draft of this
    # session lands a cache hit instead of paying the full input-token bill
    # for the static system prefix (audit 2026-05-05).
    try:
        _maybe_warm_prompt_cache(room)
    except Exception as e:
        logger.debug("cache warmup on connect failed for room=%s: %s", room, e)


def on_daemon_disconnect() -> None:
    """Handler appelé lors d'une déconnexion du namespace /daemon."""
    logger.info("WebSocket: client déconnecté du namespace /daemon")
    # Streaming STT : ferme proprement le stream Deepgram du client parti
    # (sinon le reader thread attend l'inactivity timeout de 30 s).
    try:
        from flask import request as flask_request
        from app.api.stt_stream import cleanup_for_sid
        cleanup_for_sid(flask_request.sid)  # type: ignore[attr-defined]
    except Exception as e:
        logger.debug("WebSocket: stt stream cleanup failed: %s", e)


def init_socketio(app: Any) -> SocketIO:
    """
    Initialise SocketIO avec l'application Flask.

    Args:
        app: L'application Flask.

    Returns:
        L'instance SocketIO configurée.
    """
    global _socketio

    # Flask-SocketIO bypasses Flask-CORS, so keep these defaults aligned with
    # app.api.app. If Railway loses API_CORS_ORIGINS, prod Socket.IO must still
    # accept the public frontend origins instead of failing as a fake CORS bug.
    ws_cors = os.environ.get("API_CORS_ORIGINS")
    if ws_cors:
        ws_cors_origins = [o.strip() for o in ws_cors.split(",") if o.strip()]
    else:
        ws_cors_origins = [
            "http://127.0.0.1:1420", "http://localhost:1420",
            "http://[::1]:1420", "tauri://localhost",
            "https://tauri.localhost",
            "https://app.agentys.io",
            "https://agentys.io",
            "https://www.agentys.io",
        ]

    # Async backend is controlled by AGENTYS_ASYNC_MODE (set in run_api.py).
    # "threading" stays the production default: it avoids eventlet/gevent
    # monkey-patching while still supporting WebSocket transport through the
    # simple-websocket dependency.
    _async_mode = (os.environ.get("AGENTYS_ASYNC_MODE") or "threading").strip().lower()
    if _async_mode not in ("threading", "eventlet", "gevent"):
        _async_mode = "threading"

    # Heartbeat tuning. Un onglet desktop occulté / minimisé voit ses timers JS
    # throttlés par Chromium/WebView2 (~1 tick/min), donc il peut rater le pong
    # engine.io. Les defaults (interval 25s / timeout 20s ≈ drop à ~45s) sont
    # trop agressifs → drops WS intempestifs + churn de reconnexion + updates
    # temps réel figées au retour. Un timeout de 60s tolère un client brièvement
    # occulté avant d'abandonner. Tunable par env (diagnostic stabilité 2026-06-24).
    def _ping_env(name: str, default: int) -> int:
        try:
            return int((os.environ.get(name) or "").strip() or default)
        except ValueError:
            return default

    _socketio_kwargs: Dict[str, Any] = {
        "cors_allowed_origins": ws_cors_origins,
        "async_mode": _async_mode,
        "ping_interval": _ping_env("SOCKETIO_PING_INTERVAL", 25),
        "ping_timeout": _ping_env("SOCKETIO_PING_TIMEOUT", 60),
    }
    try:
        from app.infrastructure.redis_config import get_redis_url

        _message_queue_url = (
            os.environ.get("SOCKETIO_MESSAGE_QUEUE_URL", "").strip()
            or (
                get_redis_url()
                if os.environ.get("DRAFT_QUEUE_BACKEND", "").strip().lower() == "redis"
                else ""
            )
        )
        if _message_queue_url:
            _socketio_kwargs["message_queue"] = _message_queue_url
    except Exception as exc:
        logger.warning("SocketIO Redis message queue disabled: %s", exc)

    _socketio = SocketIO(app, **_socketio_kwargs)

    _socketio.on_event("connect", on_daemon_connect, namespace="/daemon")
    _socketio.on_event("disconnect", on_daemon_disconnect, namespace="/daemon")

    # Streaming STT (mobile voice-first) — events stt_stream_* sur /daemon.
    try:
        from app.api.stt_stream import register_stt_stream_handlers
        register_stt_stream_handlers(_socketio)
    except Exception as exc:
        logger.warning("Streaming STT handlers non enregistrés: %s", exc)

    logger.info(
        "SocketIO initialisé avec namespace /daemon (async_mode=%s, message_queue=%s)",
        _async_mode,
        bool(_socketio_kwargs.get("message_queue")),
    )
    return _socketio


def get_socketio() -> Optional[SocketIO]:
    """
    Retourne l'instance SocketIO globale.

    Returns:
        L'instance SocketIO ou None si non initialisée.
    """
    return _socketio


def get_websocket_emitter() -> WebSocketEventEmitter:
    """
    Factory pour obtenir un émetteur WebSocket configuré.

    Returns:
        Un WebSocketEventEmitter connecté au SocketIO global.
    """
    return WebSocketEventEmitter(socketio=get_socketio())


# Audit 2026-04-25 (HIGH-Iso-1 / sub-report 02 H-1): the helpers below that
# still rely on `_resolve_ws_room()` work fine from request-handler threads
# but silently DROP from background workers (no Flask request context). The
# `emit_*` callers in app/api/ have been migrated to pass account_id where
# the call site has it. Helpers in this file (emit_draft_*, emit_critique_*,
# emit_orchestration_*, emit_learning_*) accept optional `account_id=` to
# keep the change diff small. Callers that have account_id MUST pass it.
def _resolve_ws_room() -> str | None:
    """Resolve the WebSocket room for the current user.

    Returns the user email from Flask g.auth_user (set by JWT auth guard),
    or None when no per-user room can be determined (callers MUST then
    skip the emit or fall through to per-account scoping via
    `emit_to_account`).

    ISO-06 / S-01 fix (2026-04-24): the previous implementation returned
    the literal string `"localhost"` for any loopback request without a
    JWT. Every loopback-connected Socket.IO client joined room
    `local_<sid>` on connect (cf. `on_daemon_connect`), so emitting to
    `to="localhost"` actually delivered nothing to the per-sid rooms but
    DID broadcast to whatever happened to subscribe to `"localhost"` —
    which in practice was every emitter that didn't have a JWT in
    context. Net effect: cross-user blast of new_email, draft_complete,
    email_archived, orchestration_*, etc.

    The right answer in 2026 is to use `emit_to_account` for any
    account-scoped event (it resolves the room from the account's email),
    and to skip the emit when no scope is available rather than silently
    broadcast.
    """
    try:
        from flask import has_request_context, g
        if has_request_context():
            auth_user = getattr(g, 'auth_user', None)
            if auth_user and auth_user.get("email"):
                return str(auth_user["email"])
    except Exception:
        pass
    # No JWT in request context, or outside any request → caller must
    # decide (most callers should switch to `emit_to_account`).
    return None


# account_id -> (room_email, monotonic_ts). The account_id→email mapping is
# stable for an account's lifetime, but a streaming draft resolves the room
# once PER chunk (emit_draft_chunk → emit_to_account), i.e. 80-250 SQLite
# reads for a single draft. Memoize successful lookups with a short TTL so a
# burst of chunks costs one DB read. Throughput win (interleaved worker time),
# not perceived TTFT. (reply-latency quick win, 2026-06-23.)
_ROOM_CACHE_TTL_S = 300.0
_room_cache: Dict[int, Tuple[str, float]] = {}
_room_cache_lock = threading.Lock()


def _clear_room_cache() -> None:
    """Drop the memoized account_id→room map. For tests that remap an
    account_id to a different email within one process."""
    with _room_cache_lock:
        _room_cache.clear()


def _resolve_room_for_account(account_id: int | None) -> str | None:
    """Résout la room WebSocket d'un account_id donné.

    Cherche l'email du compte dans la DB et retourne-le comme room.
    Utile pour les événements déclenchés depuis un worker background
    (sync, daemon, recap) qui n'ont pas de contexte request mais savent
    quel compte ils traitent.

    Mémoïsé (TTL court) : un draft streamé appelle cette fonction une fois
    par chunk, donc sans cache c'est 80-250 lectures SQLite par brouillon.
    Seuls les résultats positifs sont cachés ; un échec transitoire (DB
    indispo) renvoie None sans empoisonner le cache et sera re-tenté.

    Returns:
        L'email du compte (room privée), ou None si compte inconnu
        (dans ce cas l'appelant DOIT s'abstenir d'émettre plutôt que
        de broadcaster à tous).
    """
    if not account_id or account_id <= 0:
        return None
    cached = _room_cache.get(account_id)
    if cached is not None and (time.monotonic() - cached[1]) < _ROOM_CACHE_TTL_S:
        return cached[0]
    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository
        with get_db_session() as session:
            repo = AccountRepository(session)
            acct = repo.get(account_id)
            if acct and getattr(acct, "email", None):
                with _room_cache_lock:
                    _room_cache[account_id] = (acct.email, time.monotonic())
                return acct.email
    except Exception as e:
        # Log at warning: a failure here silently drops every account-scoped
        # WS event (onboarding, sync, drafts), so it must be visible in prod.
        logger.warning("room lookup failed for account_id=%s: %s", account_id, e)
    return None


def emit_to_account(event: str, data: Dict[str, Any], account_id: int | None) -> bool:
    """Émet un événement WebSocket uniquement au compte ciblé.

    C'est le helper canonique pour TOUTE émission Socket.IO liée à une
    ressource account-scoped. Remplace les `socketio.emit(..., namespace=
    "/daemon")` nus qui broadcastaient à tous les clients connectés.

    Args:
        event: Nom de l'événement (ex. "new_email", "draft_ready").
        data: Payload JSON.
        account_id: Compte destinataire. Si None ou <= 0, l'émission est
            SILENCIEUSEMENT SKIPPÉE (safer default que broadcast).

    Returns:
        True si émis, False sinon (pas de socketio, pas de room, …).
    """
    socketio = get_socketio()
    if socketio is None:
        return False
    room = _resolve_room_for_account(account_id)
    if room is None:
        logger.debug(
            "emit_to_account: skip event=%s (no room for account_id=%s)",
            event, account_id,
        )
        return False
    socketio.emit(event, data, namespace="/daemon", to=room)
    # Also buffer critical events for replay after reconnect. All events in
    # _BUFFER_EVENT_ALLOWLIST are idempotent on the frontend (state updates
    # apply the same value on replay without introducing duplicates).
    _buffer_event_if_needed(room, event, data)
    _increment_emit_counter()
    return True


# ──────────────────────────────────────────────────────────────────────────
# Observability helpers (issue #577 item 3)
#
# These getters are sampled by /api/_internal/ws-stats. They MUST be cheap
# (locked snapshots, no I/O) — the sentinel polls daily but a slow snapshot
# would also slow down whatever holds these locks for write.
# ──────────────────────────────────────────────────────────────────────────


def _increment_emit_counter() -> None:
    """Bump the lifetime emit counter under a dedicated lock.

    Separate lock from `_pending_lock` so a long buffer GC sweep cannot
    block the emit fast path. Eventlet's monkey-patched `threading.Lock`
    is cooperative; the contention here is theoretical but cheap enough
    to keep correct.
    """
    global _emit_counter
    with _emit_counter_lock:
        _emit_counter += 1


def get_emit_count() -> int:
    """Snapshot of the lifetime emit counter."""
    with _emit_counter_lock:
        return _emit_counter


def get_pending_rooms_stats() -> Dict[str, Any]:
    """Snapshot of `_pending_events` for the /ws-stats endpoint.

    Returns: ``rooms_count`` (int), ``events_total`` (int) and
    ``ages_seconds`` (list[float]) — the age of the OLDEST event in
    each room's buffer, computed from `time.time()` minus the deque
    head's timestamp. The endpoint reduces ``ages_seconds`` to p50/p95.
    """
    with _pending_lock:
        snapshot = [
            (room, list(buf)) for room, buf in _pending_events.items()
        ]
    now = time.time()
    rooms_count = len(snapshot)
    events_total = sum(len(buf) for _, buf in snapshot)
    ages: list[float] = []
    for _, buf in snapshot:
        if buf:
            # `buf[0]` = oldest entry (deque is FIFO, append on right).
            oldest_ts = buf[0][0]
            ages.append(now - oldest_ts)
    return {
        "rooms_count": rooms_count,
        "events_total": events_total,
        "ages_seconds": ages,
    }


def get_cache_warmup_rooms_count() -> int:
    """Snapshot of the cache-warmup last-seen dict size."""
    with _cache_warmup_lock:
        return len(_cache_warmup_last_at)


def emit_to_account_or_room(
    event: str,
    data: Dict[str, Any],
    account_id: int | None,
    fallback_room: str = "",
) -> bool:
    """Like emit_to_account but falls back to fallback_room when account_id is invalid.

    BUG-G001 fix (2026-04-26): When account_id is -1 (sentinel) or None — e.g.
    because the DB lookup failed or the account isn't persisted yet — the WS room
    IS the user's email address. Background threads that have already captured
    _bg_user_email can pass it here so critical events (draft_ready, processing_error)
    reach the frontend instead of being silently dropped, which caused the "stuck on
    Generating…" symptom where the UI spun for 2+ minutes before the polling timeout.

    Args:
        event: Socket.IO event name.
        data: Payload dict.
        account_id: DB account id. Passed to emit_to_account first (fast path).
        fallback_room: User email string used as room when account_id resolution fails.

    Returns:
        True if the event was emitted via either path.
    """
    if emit_to_account(event, data, account_id):
        return True
    if not fallback_room:
        return False
    socketio = get_socketio()
    if socketio is None:
        return False
    socketio.emit(event, data, namespace="/daemon", to=fallback_room)
    _buffer_event_if_needed(fallback_room, event, data)
    _increment_emit_counter()
    logger.debug(
        "emit_to_account_or_room: fallback emitted event=%s to room=%s "
        "(account_id=%s was invalid/unresolved)",
        event, fallback_room, account_id,
    )
    return True


# ============================================================================
# Sync Event Emitters
# ============================================================================

def emit_sync_started(account_ids: List[int]) -> None:
    """
    Emit sync_started event when sync begins.

    S-08 fix (2026-04-24): the sync thread has no Flask request context,
    so the previous `_resolve_ws_room()` fallback returned None and the
    event was silently dropped (or before ISO-06 was a global broadcast).
    Now we fan-out one emission per account via `emit_to_account` so each
    user's tab receives only their own sync event.

    Args:
        account_ids: List of account IDs being synced.
    """
    if not account_ids:
        return
    for aid in account_ids:
        if aid is None or aid <= 0:
            continue
        emit_to_account(
            "sync_started",
            {"accounts": [aid], "account_id": aid},
            aid,
        )
    logger.debug("WebSocket: sync_started fan-out for %s accounts", len(account_ids))


def emit_sync_progress(account_id: int, status: str) -> None:
    """
    Emit sync_progress event for each account being processed.

    S-08 fix (2026-04-24): route per-account via emit_to_account. The sync
    thread always knows the account_id; broadcasting to all users for one
    user's progress was a leak.

    Args:
        account_id: Account being synced.
        status: Current status ("syncing", "success", "error").
    """
    if account_id is None or account_id <= 0:
        return
    emit_to_account(
        "sync_progress",
        {"account_id": account_id, "status": status},
        account_id,
    )
    logger.debug("WebSocket: sync_progress emitted for account %s: %s", account_id, status)


def emit_sync_complete(results: List[Dict[str, Any]], duration_ms: int) -> None:
    """
    Emit sync_complete event when sync finishes.

    Audit F-07 (2026-05-16): the previous implementation called
    ``_resolve_ws_room()``, which reads ``flask.g.auth_user`` and returns
    ``None`` outside request context. The sync loop runs in a background
    thread (daemon ``on_sync_complete_callback`` in ``run_api.py``), so
    every emission was silently skipped — frontend spinners stuck without
    a terminal event. Fan out per-account via ``emit_to_account`` (the
    same helper ``emit_sync_progress`` already uses) so each user's room
    receives only their own account's result.

    Args:
        results: List of sync results per account (each dict carries
            ``account_id``).
        duration_ms: Total sync duration in milliseconds.
    """
    if not results:
        return
    for r in results:
        aid = r.get("account_id")
        if not isinstance(aid, int) or aid <= 0:
            continue
        emit_to_account(
            "sync_complete",
            {
                "new_emails": r.get("new_emails_count", 0),
                "duration_ms": duration_ms,
                # Carry the full account dict so the FE keeps its existing
                # shape (`accounts: [...]`) — but only the matching row,
                # so a multi-tenant emission can't leak User B's
                # `new_emails_count` to User A.
                "accounts": [r],
            },
            aid,
        )


def emit_sync_error(account_id: int, error: str) -> None:
    """
    Emit sync_error event when sync fails for an account.

    Audit F-07 (2026-05-16): swapped from ``_resolve_ws_room()``
    (request-context-only) to ``emit_to_account`` so callbacks fired from
    background threads (daemon sync loop, ``sync_jobs.py`` worker pool)
    actually reach the user's room.

    Args:
        account_id: Account that failed.
        error: Error message.
    """
    if not isinstance(account_id, int) or account_id <= 0:
        return
    emit_to_account(
        "sync_error",
        {"account_id": account_id, "error": error},
        account_id,
    )


def emit_new_email(email_data: Dict[str, Any], account_id: int | None = None) -> None:
    """
    Emit new_email event for each newly synced email.

    S-08 fix (2026-04-24): the sync thread now forwards `account_id`
    (from `r.account_id` in the SyncResult) so the event lands in the
    right user's room. Without this, account A's new emails leaked to
    account B's open tab.

    Args:
        email_data: Dictionary with email info (email_id, sender, subject, snippet).
        account_id: Optional DB account id. When provided, emit_to_account
            is used; otherwise we fall back to _resolve_ws_room (request
            context only).
    """
    payload = {
        "type": "new_email",
        "email_id": email_data.get("email_id", ""),
        "timestamp": datetime.utcnow().isoformat(),
        "payload": {
            "sender": email_data.get("sender", ""),
            "sender_name": email_data.get("sender_name"),
            "subject": email_data.get("subject", ""),
            "received_at": email_data.get("received_at", ""),
            "is_read": email_data.get("is_read", False),
            "has_attachments": email_data.get("has_attachments", False),
            "conversation_id": email_data.get("conversation_id"),
            "body_preview": email_data.get("body_preview", email_data.get("snippet", "")),
            "snippet": email_data.get("snippet", ""),
            "account_id": account_id,
        },
    }

    if account_id is not None and account_id > 0:
        emit_to_account("daemon_event", payload, account_id)
        logger.info(
            "[WS] daemon_event new_email emitted: subject_len=%s (account_id=%s)",
            len(email_data.get("subject", "") or ""),
            account_id,
        )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "daemon_event",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            "[WS] daemon_event new_email emitted: subject_len=%s (room=%s)",
            len(email_data.get("subject", "") or ""),
            room,
        )


# ============================================================================
# Post-Send Event Emitters
# ============================================================================


def emit_email_sent(
    email_id: str,
    account_id: int | None = None,
    is_reply: bool = False,
) -> None:
    """Emit `email_sent` after a successful send (compose or reply).

    Frontends listen to refresh the Sent folder and any open email-list views
    that may include the sent email. Mirrors `emit_email_archived` routing.
    """
    payload = {"email_id": email_id, "is_reply": is_reply}
    if account_id is not None and account_id > 0:
        emit_to_account("email_sent", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_sent", payload, namespace="/daemon", to=room)
        logger.debug("WebSocket: email_sent emitted for %s (room=%s)", email_id, room)


def emit_email_scheduled(
    scheduled_id: str,
    *,
    send_at: str,
    account_id: int | None = None,
) -> None:
    """Emit `email_scheduled` quand un envoi differe est cree.

    Le frontend ecoute pour rafraichir la vue "Programmes" et le compteur
    de la sidebar. Suit le pattern emit_email_archived (S-07) — l'appelant
    DOIT passer `account_id` capture dans le contexte requete.
    """
    payload = {"scheduled_id": scheduled_id, "send_at": send_at}
    if account_id is not None and account_id > 0:
        emit_to_account("email_scheduled", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_scheduled", payload, namespace="/daemon", to=room)


def emit_email_sent_scheduled(
    *,
    scheduled_id: str,
    sent_message_id: str,
    account_id: int | None = None,
) -> None:
    """Emit `email_sent_scheduled` quand le scheduler a livre un envoi differe.

    Bg thread oblige : `account_id` doit etre resolu avant l'envoi (cf.
    lecon 2026-04-24 sur emit-from-bg-thread).
    """
    payload = {
        "scheduled_id": scheduled_id,
        "sent_message_id": sent_message_id,
    }
    if account_id is not None and account_id > 0:
        emit_to_account("email_sent_scheduled", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_sent_scheduled", payload, namespace="/daemon", to=room)


def emit_email_schedule_canceled(
    scheduled_id: str,
    *,
    account_id: int | None = None,
) -> None:
    """Emit `email_schedule_canceled` apres annulation utilisateur."""
    payload = {"scheduled_id": scheduled_id}
    if account_id is not None and account_id > 0:
        emit_to_account("email_schedule_canceled", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_schedule_canceled", payload, namespace="/daemon", to=room)


def emit_email_schedule_updated(
    scheduled_id: str,
    *,
    send_at: str,
    account_id: int | None = None,
) -> None:
    """Emit `email_schedule_updated` quand l'utilisateur reprogramme."""
    payload = {"scheduled_id": scheduled_id, "send_at": send_at}
    if account_id is not None and account_id > 0:
        emit_to_account("email_schedule_updated", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_schedule_updated", payload, namespace="/daemon", to=room)


def emit_email_schedule_failed(
    scheduled_id: str,
    *,
    error: str,
    account_id: int | None = None,
) -> None:
    """Emit `email_schedule_failed` quand le scheduler n'a pas pu envoyer un email programmé.

    Le frontend doit écouter cet événement pour afficher une notification
    d'erreur et permettre à l'utilisateur de reprogrammer ou d'annuler.
    """
    payload = {"scheduled_id": scheduled_id, "error": error}
    if account_id is not None and account_id > 0:
        emit_to_account("email_schedule_failed", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("email_schedule_failed", payload, namespace="/daemon", to=room)


def emit_email_archived(email_id: str, account_id: int | None = None) -> None:
    """
    Emit email_archived event after background archive completes.

    This notifies the frontend to refresh the email list so the archived
    email disappears from the inbox.

    S-07 fix (2026-04-24): caller can pass `account_id` (resolved BEFORE
    thread.start() in request context) to route the event via
    `emit_to_account` — the bg thread itself has no Flask request context
    so `_resolve_ws_room()` would return None and previously fell through
    to broadcast.
    """
    if account_id is not None and account_id > 0:
        emit_to_account("email_archived", {"email_id": email_id}, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "email_archived",
            {"email_id": email_id},
            namespace="/daemon",
            to=room,
        )
        logger.debug("WebSocket: email_archived emitted for %s (room=%s)", email_id, room)


def emit_email_restored(email_id: str, account_id: int | None = None) -> None:
    """Emit email_restored event when an email is restored from trash or unarchived.

    S-07: see `emit_email_archived` — same per-account routing pattern.
    """
    if account_id is not None and account_id > 0:
        emit_to_account("email_restored", {"email_id": email_id}, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "email_restored",
            {"email_id": email_id},
            namespace="/daemon",
            to=room,
        )
        logger.debug("WebSocket: email_restored emitted for %s (room=%s)", email_id, room)


def emit_email_spam_changed(email_id: str, is_spam: bool, account_id: int | None = None) -> None:
    """Emit email_spam_changed event when an email is marked as spam or not-spam.

    S-07: see `emit_email_archived` — same per-account routing pattern.
    """
    if account_id is not None and account_id > 0:
        emit_to_account(
            "email_spam_changed",
            {"email_id": email_id, "is_spam": is_spam},
            account_id,
        )
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "email_spam_changed",
            {"email_id": email_id, "is_spam": is_spam},
            namespace="/daemon",
            to=room,
        )
        logger.debug("WebSocket: email_spam_changed emitted for %s (is_spam=%s, room=%s)", email_id, is_spam, room)


def emit_email_deleted(email_id: str, account_id: int | None = None) -> None:
    """Emit email_deleted event after an email is moved to trash.

    Frontend uses this to remove the email from list state incrementally,
    avoiding a full refetch of /api/emails.

    S-07: see `emit_email_archived` — same per-account routing pattern.
    """
    if account_id is not None and account_id > 0:
        emit_to_account("email_deleted", {"email_id": email_id}, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "email_deleted",
            {"email_id": email_id},
            namespace="/daemon",
            to=room,
        )
        logger.debug("WebSocket: email_deleted emitted for %s (room=%s)", email_id, room)


def emit_email_updated(email_id: str, updates: Dict[str, Any], account_id: int | None = None) -> None:
    """Emit email_updated event when an email field changes (is_read, labels...).

    Args:
        email_id: ID of the modified email.
        updates: Partial dict of fields that changed (e.g. {"is_read": True}).
                 Frontend merges these into its local state instead of refetching.
        account_id: Optional DB account id (S-07). When provided, routes via
                 emit_to_account (correct for bg threads with no request context).
    """
    if account_id is not None and account_id > 0:
        emit_to_account(
            "email_updated",
            {"email_id": email_id, "updates": updates},
            account_id,
        )
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "email_updated",
            {"email_id": email_id, "updates": updates},
            namespace="/daemon",
            to=room,
        )
        logger.debug("WebSocket: email_updated emitted for %s (keys=%s, room=%s)", email_id, list(updates.keys()), room)


# ============================================================================
# Connectivity Event Emitters
# ============================================================================

def emit_connectivity_changed(is_online: bool, account_id: int | None = None) -> None:
    """
    Emit connectivity_changed event when network status changes.

    S-12 fix (2026-04-24): when the connectivity change is per-account
    (e.g. OAuth refresh failure on a single mailbox), pass `account_id`
    so the banner only shows on that user's tab. The previous behavior
    was always-broadcast — account A's expired Outlook token made
    account B's tab flash "You are offline" even though their Gmail was
    fine. Keep the broadcast path for genuine backend-wide outages
    (no `account_id` provided).

    Args:
        is_online: True if online, False if offline.
        account_id: Optional DB account id for per-account routing.
    """
    if account_id is not None and account_id > 0:
        emit_to_account(
            "connectivity_changed",
            {"online": is_online, "account_id": account_id},
            account_id,
        )
        status = "online" if is_online else "offline"
        logger.info(
            f"WebSocket: connectivity_changed emitted: {status} (account_id={account_id})"
        )
        return
    socketio = get_socketio()
    if socketio:
        # True backend-wide outage — broadcast is intentional here.
        socketio.emit(
            "connectivity_changed",
            {"online": is_online},
            namespace="/daemon",
        )
        status = "online" if is_online else "offline"
        logger.info(f"WebSocket: connectivity_changed emitted: {status}")


def emit_back_online(account_id: int | None = None) -> None:
    """
    Emit back_online event when connectivity is restored.

    This is a convenience event to trigger queue processing and UI updates.

    S-12 fix: same per-account routing as `emit_connectivity_changed`.
    """
    if account_id is not None and account_id > 0:
        emit_to_account(
            "back_online",
            {"message": "Connection restored", "account_id": account_id},
            account_id,
        )
        logger.info(f"WebSocket: back_online emitted (account_id={account_id})")
        return
    socketio = get_socketio()
    if socketio:
        # Connectivity affects all users — no room scoping
        socketio.emit(
            "back_online",
            {"message": "Connection restored"},
            namespace="/daemon",
        )
        logger.info("WebSocket: back_online emitted")


# ============================================================================
# Action Queue Event Emitters
# ============================================================================

def emit_action_queued(
    action_id: int,
    action_type: str,
    email_id: str,
    account_id: int | None = None,
) -> None:
    """
    Emit action_queued event when an action is queued for offline processing.

    Audit 2026-04-25 (HIGH-Iso-1): account_id parameter so background-thread
    callers (which lack a request context) can route through emit_to_account
    instead of silently dropping the event.

    Args:
        action_id: ID of the queued action.
        action_type: Type of action (mark_read, etc.).
        email_id: Email the action applies to.
        account_id: DB account id for routing. None = best-effort
            request-context lookup.
    """
    payload = {
        "action_id": action_id,
        "action_type": action_type,
        "email_id": email_id,
    }
    if account_id is not None:
        emit_to_account("action_queued", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("action_queued", payload, namespace="/daemon", to=room)
        logger.debug("WebSocket: action_queued emitted: %s for %s (room=%s)", action_type, email_id, room)


def emit_action_processed(
    action_id: int,
    success: bool,
    error: Optional[str] = None,
    account_id: int | None = None,
) -> None:
    """
    Emit action_processed event when a queued action completes.

    Audit 2026-04-25 (HIGH-Iso-1): account_id parameter for bg-thread routing.
    """
    payload = {"action_id": action_id, "success": success, "error": error}
    if account_id is not None:
        emit_to_account("action_processed", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("action_processed", payload, namespace="/daemon", to=room)
        status = "success" if success else "failed"
        logger.debug("WebSocket: action_processed emitted: %s %s (room=%s)", action_id, status, room)


def emit_queue_processed(
    total: int,
    completed: int,
    failed: int,
    account_id: int | None = None,
) -> None:
    """
    Emit queue_processed event when the action queue finishes processing.

    Audit 2026-04-25 (HIGH-Iso-1): account_id for bg-thread routing.
    """
    payload = {"total": total, "completed": completed, "failed": failed}
    if account_id is not None:
        emit_to_account("queue_processed", payload, account_id)
        return
    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("queue_processed", payload, namespace="/daemon", to=room)
        logger.info(f"WebSocket: queue_processed emitted: {completed}/{total} completed (room={room})")


# ============================================================================
# Draft Streaming Event Emitters (Story 5-1)
# ============================================================================

def emit_draft_stage(
    email_id: str,
    stage: str,
    stage_index: int,
    total_stages: int,
    progress_percent: float,
    account_id: int | None = None,
) -> None:
    """
    Emit draft_stage event to inform the frontend of the current pipeline stage.

    FIX WS-003 (audit P1): the previous implementation only used
    `_resolve_ws_room()`, which always returns None when called from a
    background thread (no Flask request context). All SmartRouter
    streaming-pipeline progress events were silently dropped, leaving
    the ReplyComposer "generating…" spinner stuck forever for any draft
    that didn't go through the routes_emails.py background path.
    Callers that know which account they're serving now pass
    `account_id=` explicitly and routing goes via `emit_to_account`.

    Args:
        email_id: ID of the email being processed.
        stage: Stage key (classification, redaction, optimisation, finalisation).
        stage_index: 0-based index of the current stage.
        total_stages: Total number of stages.
        progress_percent: Approximate progress percentage.
        account_id: Optional DB account_id for explicit per-user routing
            (preferred when the caller is a background thread).
    """
    socketio = get_socketio()
    if not socketio:
        return
    payload = {
        "email_id": email_id,
        "stage": stage,
        "stage_index": stage_index,
        "total_stages": total_stages,
        "progress_percent": progress_percent,
    }
    if account_id is not None:
        if emit_to_account("draft_stage", payload, account_id):
            logger.debug(
                "WebSocket: draft_stage emitted to account=%s for email %s: %s (%s/%s, %s%%)",
                account_id, email_id, stage, stage_index + 1, total_stages, int(progress_percent),
            )
        return
    room = _resolve_ws_room()
    if room is None:
        return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
    socketio.emit("draft_stage", payload, namespace="/daemon", to=room)
    logger.debug(
        "WebSocket: draft_stage emitted for email %s: %s (%s/%s, %s%%)",
        email_id, stage, stage_index + 1, total_stages, int(progress_percent),
    )


def emit_draft_chunk(
    email_id: str,
    chunk: str,
    chunk_index: int,
    accumulated_text: str,
    progress_percent: float,
    is_final: bool = False,
    account_id: int | None = None,
) -> None:
    """
    Emit draft_chunk event during streaming draft generation.

    Sends only the new chunk text (delta) for incremental assembly on the client.
    Full accumulated_text is included only in the final chunk to save O(n^2) bandwidth.

    FIX WS-003 (audit P1): supports `account_id` for explicit per-user
    routing from background threads (see emit_draft_stage docstring).

    Args:
        email_id: ID of the email being responded to.
        chunk: The new text chunk generated (delta only).
        chunk_index: Index of this chunk (0-based).
        accumulated_text: Full text accumulated so far (sent only when is_final=True).
        progress_percent: Progress percentage (0-100).
        is_final: Whether this is the final chunk.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    socketio = get_socketio()
    if not socketio:
        return
    payload = {
        "email_id": email_id,
        "chunk": chunk,
        "chunk_index": chunk_index,
        "progress_percent": progress_percent,
        "is_final": is_final,
    }
    # Only send full accumulated text in the final payload (saves O(n^2) bandwidth)
    if is_final:
        payload["accumulated_text"] = accumulated_text

    if account_id is not None:
        if emit_to_account("draft_chunk", payload, account_id):
            logger.debug(
                "WebSocket: draft_chunk emitted to account=%s for email %s, chunk %s, progress %.1f%%",
                account_id, email_id, chunk_index, progress_percent,
            )
        return

    room = _resolve_ws_room()
    if room is None:
        return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
    socketio.emit("draft_chunk", payload, namespace="/daemon", to=room)
    logger.debug(
        "WebSocket: draft_chunk emitted for email %s, chunk %s, progress %.1f%%",
        email_id, chunk_index, progress_percent,
    )


def emit_draft_complete(
    email_id: str,
    draft_content: str,
    confidence: float,
    generation_time_ms: int,
    tokens_used: int,
    tone_detected: str = "professional",
    account_id: int | None = None,
    fallback_room: str = "",
    truncated: bool = False,
) -> None:
    """
    Emit draft_complete event when draft generation finishes.

    Args:
        email_id: ID of the email being responded to.
        draft_content: Full generated draft content.
        confidence: Confidence score (0-1).
        generation_time_ms: Generation duration in milliseconds.
        tokens_used: Total tokens used.
        tone_detected: Detected tone of the draft.
        account_id: Optional DB account_id. When passed (typically by a
            background thread that knows which account it is serving),
            the event is routed via `emit_to_account` so the correct
            per-user room receives it. S-09 fix: previously the bg
            thread inside `_process_in_background` emitted via
            `_resolve_ws_room` → None → `to=None` → namespace-wide
            broadcast (every other tab got the wrong draft body).
        fallback_room: BUG-G001 fix — user email used as room when
            account_id is -1/None (DB lookup failed). Prevents the
            draft_complete event from being silently dropped.
        truncated: F-03 (audit 2026-05-14) — set to True when the LLM
            stop_reason was `max_tokens`, meaning the streamed draft was
            cut at the token cap (a half-word body). The frontend keys
            off this flag to render a "réponse tronquée — réessayer"
            affordance instead of silently rendering the partial body.
            Default False preserves the pre-fix payload shape for all
            non-streaming-compose callers (reply path, draft_complete
            from `_process_in_background`, etc.).
    """
    payload = {
        "email_id": email_id,
        "draft": draft_content,
        "confidence": confidence,
        "generation_time_ms": generation_time_ms,
        "tokens_used": tokens_used,
        "tone_detected": tone_detected,
    }
    # F-03: only add the field when truthy so the payload shape stays
    # backward-compat for legacy WS subscribers that don't know about it.
    if truncated:
        payload["truncated"] = True
    if account_id is not None or fallback_room:
        # S-09 path: scope explicitly to the caller's account.
        # BUG-G001: use fallback_room when account_id resolution yielded -1.
        if emit_to_account_or_room("draft_complete", payload, account_id, fallback_room):
            logger.info(
                "WebSocket: draft_complete emitted to account=%s "
                "(email=%s, %d chars)",
                account_id, email_id, len(draft_content),
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("draft_complete", payload, namespace="/daemon", to=room)
        logger.info(
            f"WebSocket: draft_complete emitted for email {email_id}, "
            f"{len(draft_content)} chars in {generation_time_ms}ms"
        )


def emit_draft_revised(
    email_id: str,
    v1_draft: str,
    v2_draft: str,
    critique_summary: str = "",
    account_id: int | None = None,
) -> None:
    """Emit `draft_revised` when the critic produces a V2 that should
    optionally replace the V1 the user has already seen.

    Race-condition safety (2026-05-05):
        The legacy flow had `_emit_instant_draft` silently overwriting V1
        with V2 — if the user started editing V1 in the ~1.5s critic
        window, those edits got blown away. `draft_revised` is the
        non-destructive variant: the frontend receives BOTH versions and
        can render a "View improved version" toggle instead of mutating
        the editor in place.

    Wired only when `STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE` env flag
    is true. Default OFF — the legacy "V2 silently replaces V1" path
    keeps working unchanged for users on the old frontend that doesn't
    handle this event.

    Args:
        email_id: ID of the email being responded to.
        v1_draft: The originally-streamed draft (already shown to user).
        v2_draft: The critic-revised version.
        critique_summary: Optional one-line reason ("placeholder removed",
            "tone refined", etc.) for surfacing in the toggle UI.
        account_id: Per-user routing (same semantics as `emit_draft_complete`).
    """
    payload = {
        "email_id": email_id,
        "v1": v1_draft,
        "v2": v2_draft,
        "critique_summary": critique_summary,
    }
    if account_id is not None:
        if emit_to_account("draft_revised", payload, account_id):
            logger.info(
                "WebSocket: draft_revised emitted to account=%s "
                "(email=%s, V1=%d chars, V2=%d chars)",
                account_id, email_id, len(v1_draft), len(v2_draft),
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return
        socketio.emit("draft_revised", payload, namespace="/daemon", to=room)
        logger.info(
            f"WebSocket: draft_revised emitted for email {email_id}"
        )


def emit_draft_error(
    email_id: str,
    error: str,
    retry_count: int = 0,
    account_id: int | None = None,
) -> None:
    """Emit draft_error event when draft generation fails.

    Audit R-001 (2026-04-27): now accepts account_id so background-thread
    failures (offline resume, deep-focus batch, auto-followups) reach the
    user instead of being silently dropped by `_resolve_ws_room()` returning
    None outside a Flask request context. Mirrors emit_draft_complete.
    """
    payload = {
        "email_id": email_id,
        "error": error,
        "retry_count": retry_count,
    }
    if account_id is not None:
        if emit_to_account("draft_error", payload, account_id):
            logger.warning(
                "WebSocket: draft_error emitted to account=%s for email %s: %s",
                account_id, email_id, error,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("draft_error", payload, namespace="/daemon", to=room)
        logger.warning(f"WebSocket: draft_error emitted for email {email_id}: {error}")


# ============================================================================
# CRITIQUE EVENTS (Story 5-2)
# ============================================================================


def emit_critique_start(
    email_id: str,
    draft_id: str | None = None,
    account_id: int | None = None,
) -> None:
    """Emit critique_start event when critique evaluation begins.

    Audit R-002 (2026-04-27): account_id added for BG-thread routing.

    Audit 2026-05-06: include a user-facing ``phase_label`` so the front-end
    can display "Vérification de la qualité…" between draft_complete and
    critique_complete without having to localise the technical ``status``.
    Closes the silent 1–2s perception gap users see today.
    """
    payload = {
        "email_id": email_id,
        "draft_id": draft_id,
        "status": "evaluating",
        "phase_label": "Vérification de la qualité…",
        "phase_label_en": "Verifying quality…",
    }
    if account_id is not None:
        if emit_to_account("critique_start", payload, account_id):
            logger.info(
                "WebSocket: critique_start emitted to account=%s for email %s",
                account_id, email_id,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("critique_start", payload, namespace="/daemon", to=room)
        logger.info(f"WebSocket: critique_start emitted for email {email_id}")


def emit_critique_complete(
    email_id: str,
    decision: str,
    overall_score: int,
    scores: Dict[str, Any],
    suggestions: list[str],
    explanation: str,
    evaluation_time_ms: int,
    tokens_used: int,
    draft_id: str | None = None,
    tone_classification: Optional[Dict[str, Any]] = None,
    account_id: int | None = None,
) -> None:
    """
    Emit critique_complete event when critique evaluation finishes.

    Args:
        email_id: ID of the email being evaluated.
        decision: "valid" or "reject".
        overall_score: Overall quality score (0-100).
        scores: Dict with coherence, tone, completeness, errors scores.
        suggestions: List of improvement suggestions.
        explanation: Explanation for the decision.
        evaluation_time_ms: Evaluation duration in milliseconds.
        tokens_used: Total tokens used.
        draft_id: Optional draft ID being critiqued.
        tone_classification: Optional tone classification result (Story 5-5).
            Dict with classification, confidence, explanation, label, color.
    """
    data = {
        "email_id": email_id,
        "draft_id": draft_id,
        "decision": decision,
        "overall_score": overall_score,
        "scores": scores,
        "suggestions": suggestions,
        "explanation": explanation,
        "evaluation_time_ms": evaluation_time_ms,
        "tokens_used": tokens_used,
    }
    # Story 5-5: Ajouter la classification du ton si disponible
    if tone_classification is not None:
        data["tone"] = tone_classification
    tone_info = f", tone={tone_classification.get('classification', 'N/A')}" if tone_classification else ""

    # Audit R-002 (2026-04-27): route via account_id when caller provides
    # it (BG threads). Falls back to legacy request-context lookup.
    if account_id is not None:
        if emit_to_account("critique_complete", data, account_id):
            logger.info(
                "WebSocket: critique_complete emitted to account=%s "
                "for email %s, decision=%s, score=%s%s in %sms",
                account_id, email_id, decision, overall_score, tone_info,
                evaluation_time_ms,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("critique_complete", data, namespace="/daemon", to=room)
        logger.info(
            f"WebSocket: critique_complete emitted for email {email_id}, "
            f"decision={decision}, score={overall_score}{tone_info} in {evaluation_time_ms}ms"
        )


def emit_critique_error(
    email_id: str,
    error: str,
    retry_count: int = 0,
    draft_id: str | None = None,
    account_id: int | None = None,
) -> None:
    """Emit critique_error event when critique evaluation fails.

    Audit R-002 (2026-04-27): account_id added for BG-thread routing.
    Without it, a critic timeout in the orchestration pipeline left the
    UI spinner stuck because the error was dropped at _resolve_ws_room().
    """
    payload = {
        "email_id": email_id,
        "draft_id": draft_id,
        "error": error,
        "retry_count": retry_count,
    }
    if account_id is not None:
        if emit_to_account("critique_error", payload, account_id):
            logger.warning(
                "WebSocket: critique_error emitted to account=%s for email %s: %s",
                account_id, email_id, error,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit("critique_error", payload, namespace="/daemon", to=room)
        logger.warning(f"WebSocket: critique_error emitted for email {email_id}: {error}")


# ============================================================================
# ORCHESTRATION EVENTS (Story 5-3)
# ============================================================================


def emit_orchestration_start(
    email_id: str,
    max_iterations: int = 2,
    quality_threshold: int = 70,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_start event when Drafter/Critic pipeline begins.

    Args:
        email_id: ID of the email being processed.
        max_iterations: Maximum number of iterations configured.
        quality_threshold: Quality threshold for acceptance.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "max_iterations": max_iterations,
        "quality_threshold": quality_threshold,
        "status": "started",
    }
    if account_id is not None:
        if emit_to_account("orchestration_start", payload, account_id):
            logger.info(
                "WebSocket: orchestration_start emitted to account=%s for email %s "
                "(max_iterations=%s, threshold=%s)",
                account_id, email_id, max_iterations, quality_threshold,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_start",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            f"WebSocket: orchestration_start emitted for email {email_id} "
            f"(max_iterations={max_iterations}, threshold={quality_threshold})"
        )


def emit_orchestration_iteration_start(
    email_id: str,
    iteration_number: int,
    is_revision: bool = False,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_iteration_start event at the beginning of each iteration.

    Args:
        email_id: ID of the email being processed.
        iteration_number: Current iteration number (1-based).
        is_revision: True if this is a revision based on previous critique.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "iteration_number": iteration_number,
        "is_revision": is_revision,
        "status": "drafting" if not is_revision else "revising",
    }
    if account_id is not None:
        if emit_to_account("orchestration_iteration_start", payload, account_id):
            logger.info(
                "WebSocket: orchestration_iteration_start emitted to account=%s "
                "for email %s (iteration=%s, is_revision=%s)",
                account_id, email_id, iteration_number, is_revision,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_iteration_start",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            f"WebSocket: orchestration_iteration_start emitted for email {email_id} "
            f"(iteration={iteration_number}, is_revision={is_revision})"
        )


def emit_orchestration_iteration_complete(
    email_id: str,
    iteration_number: int,
    score: int,
    decision: str,
    duration_ms: int = 0,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_iteration_complete event at the end of each iteration.

    Args:
        email_id: ID of the email being processed.
        iteration_number: Current iteration number (1-based).
        score: Overall quality score from CriticAgent.
        decision: VALID or REJECT decision.
        duration_ms: Duration of the iteration in milliseconds.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "iteration_number": iteration_number,
        "score": score,
        "decision": decision,
        "duration_ms": duration_ms,
    }
    if account_id is not None:
        if emit_to_account("orchestration_iteration_complete", payload, account_id):
            logger.info(
                "WebSocket: orchestration_iteration_complete emitted to account=%s "
                "for email %s (iteration=%s, score=%s, decision=%s)",
                account_id, email_id, iteration_number, score, decision,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_iteration_complete",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            f"WebSocket: orchestration_iteration_complete emitted for email {email_id} "
            f"(iteration={iteration_number}, score={score}, decision={decision})"
        )


def emit_orchestration_complete(
    email_id: str,
    final_draft: str,
    final_score: int,
    total_iterations: int,
    total_duration_ms: int,
    was_validated: bool,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_complete event when pipeline finishes successfully.

    Args:
        email_id: ID of the email being processed.
        final_draft: Final draft content.
        final_score: Final quality score.
        total_iterations: Total number of iterations performed.
        total_duration_ms: Total duration in milliseconds.
        was_validated: True if final draft was validated by CriticAgent.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "draft": final_draft,
        "final_score": final_score,
        "total_iterations": total_iterations,
        "total_duration_ms": total_duration_ms,
        "was_validated": was_validated,
        "status": "completed",
    }
    if account_id is not None:
        if emit_to_account("orchestration_complete", payload, account_id):
            logger.info(
                "WebSocket: orchestration_complete emitted to account=%s for email %s "
                "(iterations=%s, score=%s, validated=%s, duration=%sms)",
                account_id, email_id, total_iterations, final_score,
                was_validated, total_duration_ms,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_complete",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            f"WebSocket: orchestration_complete emitted for email {email_id} "
            f"(iterations={total_iterations}, score={final_score}, "
            f"validated={was_validated}, duration={total_duration_ms}ms)"
        )


def emit_orchestration_timeout(
    email_id: str,
    best_draft: str | None,
    best_score: int,
    completed_iterations: int,
    total_duration_ms: int,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_timeout event when pipeline times out.

    Args:
        email_id: ID of the email being processed.
        best_draft: Best draft available (may be None).
        best_score: Best quality score achieved.
        completed_iterations: Number of completed iterations.
        total_duration_ms: Total duration before timeout.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "draft": best_draft,
        "best_score": best_score,
        "completed_iterations": completed_iterations,
        "total_duration_ms": total_duration_ms,
        "status": "timeout",
    }
    if account_id is not None:
        if emit_to_account("orchestration_timeout", payload, account_id):
            logger.warning(
                "WebSocket: orchestration_timeout emitted to account=%s for email %s "
                "(iterations=%s, best_score=%s, duration=%sms)",
                account_id, email_id, completed_iterations, best_score,
                total_duration_ms,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_timeout",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.warning(
            f"WebSocket: orchestration_timeout emitted for email {email_id} "
            f"(iterations={completed_iterations}, best_score={best_score}, "
            f"duration={total_duration_ms}ms)"
        )


def emit_orchestration_error(
    email_id: str,
    error: str,
    completed_iterations: int = 0,
    best_draft: str | None = None,
    best_score: int = 0,
    account_id: int | None = None,
) -> None:
    """
    Emit orchestration_error event when pipeline fails.

    Args:
        email_id: ID of the email being processed.
        error: Error message.
        completed_iterations: Number of completed iterations before failure.
        best_draft: Best draft available (may be None).
        best_score: Best quality score achieved before failure.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "error": error,
        "completed_iterations": completed_iterations,
        "draft": best_draft,
        "best_score": best_score,
        "status": "error",
    }
    if account_id is not None:
        if emit_to_account("orchestration_error", payload, account_id):
            logger.error(
                "WebSocket: orchestration_error emitted to account=%s for email %s: %s",
                account_id, email_id, error,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "orchestration_error",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.error(
            f"WebSocket: orchestration_error emitted for email {email_id}: {error}"
        )


# ============================================================================
# Learning Refresh Event Emitters
# ============================================================================


def emit_learning_correction_recorded(
    email_id: str,
    had_correction: bool,
    edit_ratio: float,
    account_id: int | None = None,
) -> None:
    """
    Emit learning:correction_recorded after post-send recording.

    Args:
        email_id: ID of the sent email.
        had_correction: True if the user edited the draft before sending.
        edit_ratio: Edit ratio (0.0 = unchanged, 1.0 = fully rewritten).
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "had_correction": had_correction,
        "edit_ratio": round(edit_ratio, 3),
    }
    if account_id is not None:
        if emit_to_account("learning:correction_recorded", payload, account_id):
            logger.debug(
                "WebSocket: learning:correction_recorded emitted to account=%s "
                "for %s (correction=%s, ratio=%.2f)",
                account_id, email_id, had_correction, edit_ratio,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "learning:correction_recorded",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.debug(
            "WebSocket: learning:correction_recorded emitted for %s (correction=%s, ratio=%.2f)",
            email_id, had_correction, edit_ratio,
        )


def emit_learning_label_corrected(
    email_id: str,
    old_label: str,
    new_label: str,
    account_id: int | None = None,
) -> None:
    """
    Emit learning:label_corrected after a user corrects a label.

    Args:
        email_id: ID of the email whose label was corrected.
        old_label: Label assigned by the AI.
        new_label: Label chosen by the user.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "email_id": email_id,
        "old_label": old_label,
        "new_label": new_label,
    }
    if account_id is not None:
        if emit_to_account("learning:label_corrected", payload, account_id):
            logger.debug(
                "WebSocket: learning:label_corrected emitted to account=%s "
                "for %s (%s -> %s)",
                account_id, email_id, old_label, new_label,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "learning:label_corrected",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.debug(
            "WebSocket: learning:label_corrected emitted for %s (%s -> %s)",
            email_id, old_label, new_label,
        )


def emit_learning_analysis_completed(
    patterns_count: int,
    new_adjustments: int,
    account_id: int | None = None,
) -> None:
    """
    Emit learning:analysis_completed after a light pattern analysis.

    Args:
        patterns_count: Number of patterns detected.
        new_adjustments: Number of new adjustments applied.
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "patterns_count": patterns_count,
        "new_adjustments": new_adjustments,
    }
    if account_id is not None:
        if emit_to_account("learning:analysis_completed", payload, account_id):
            logger.debug(
                "WebSocket: learning:analysis_completed emitted to account=%s "
                "(patterns=%s, adjustments=%s)",
                account_id, patterns_count, new_adjustments,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "learning:analysis_completed",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.debug(
            "WebSocket: learning:analysis_completed emitted (patterns=%s, adjustments=%s)",
            patterns_count, new_adjustments,
        )


def emit_learning_rule_extracted(
    rule_id: str,
    rule_text: str,
    category: str,
    account_id: int | None = None,
) -> None:
    """
    Emit learning:rule_extracted after a draft rule is extracted by LLM.

    Args:
        rule_id: ID of the new rule.
        rule_text: Human-readable rule text.
        category: Rule category (salutation, ton, etc.).
        account_id: Optional DB account_id for explicit per-user routing.
    """
    payload = {
        "rule_id": rule_id,
        "rule_text": rule_text,
        "category": category,
    }
    if account_id is not None:
        if emit_to_account("learning:rule_extracted", payload, account_id):
            logger.info(
                "WebSocket: learning:rule_extracted emitted to account=%s: %s (%s)",
                account_id, rule_text[:50], category,
            )
        return

    socketio = get_socketio()
    if socketio:
        room = _resolve_ws_room()
        if room is None:
            return  # ISO-06 / S-01: no per-user room → skip rather than broadcast
        socketio.emit(
            "learning:rule_extracted",
            payload,
            namespace="/daemon",
            to=room,
        )
        logger.info(
            f"WebSocket: learning:rule_extracted emitted: {rule_text[:50]} ({category})"
        )


def emit_learning_refresh_completed(
    account_id: int,
    refresh_type: str,
    summary: str,
) -> None:
    """
    Emit learning:refresh_completed after a KB refresh (incremental or deep).

    FIX WS-006 (audit P1): the LearningRefreshScheduler runs in a
    background thread with no request context, so `_resolve_ws_room()`
    always returned None and the event was permanently dropped. The
    function already takes `account_id` as the first parameter — we
    just need to actually USE it for routing instead of falling back to
    a request-context-dependent room lookup.

    Args:
        account_id: Account that was refreshed.
        refresh_type: "incremental" or "deep".
        summary: Human-readable summary of what changed.
    """
    socketio = get_socketio()
    if not socketio:
        return
    payload = {
        "account_id": account_id,
        "refresh_type": refresh_type,
        "summary": summary,
    }
    # account_id is required (positional) → always route via emit_to_account.
    # Only fall back to _resolve_ws_room if account_id is None (defensive,
    # shouldn't happen with current callers).
    if account_id is not None:
        if emit_to_account("learning:refresh_completed", payload, account_id):
            logger.info(
                f"WebSocket: learning:refresh_completed emitted to account={account_id} "
                f"(type={refresh_type})"
            )
        return
    room = _resolve_ws_room()
    if room is None:
        return
    socketio.emit("learning:refresh_completed", payload, namespace="/daemon", to=room)
    logger.info(
        f"WebSocket: learning:refresh_completed emitted for account {account_id} "
        f"(type={refresh_type})"
    )


# ============================================================================
# Auth Event Emitters
# ============================================================================

def emit_token_expired(account_id: str, email: str, provider: str) -> None:
    """
    Émet un événement auth:token_expired quand le refresh_token est révoqué
    (invalid_grant). Le frontend affiche un banner invitant à se reconnecter.
    """
    socketio = get_socketio()
    if socketio:
        # Émettre vers la room de l'utilisateur concerné (email fourni en paramètre)
        socketio.emit(
            "auth:token_expired",
            {"account_id": account_id, "email": email, "provider": provider},
            namespace="/daemon",
            to=email,
        )
        logger.warning(
            "WebSocket: auth:token_expired emitted for account %s (%s)",
            account_id, email
        )
