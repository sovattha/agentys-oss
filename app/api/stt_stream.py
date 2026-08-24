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
Streaming STT — proxy Socket.IO ↔ Deepgram live (Step 4 voice-first mobile).

Remplace le pipeline batch (record → upload fichier → /api/transcribe,
~1,5-2 s de blanc après chaque prise de parole) par un flux temps réel :
le mobile pousse des frames PCM16 16 kHz sur le socket /daemon existant,
le serveur les relaie vers le WebSocket live Deepgram (nova-3) et renvoie
les transcripts partiels/finals au fil de l'eau. L'endpointing sémantique
de Deepgram remplace les timers de silence fixes (400/1200/4000 ms) côté
mobile, et `SpeechStarted` donne le signal barge-in en <300 ms.

Protocole (namespace /daemon, après auth connect existante) :

  client → serveur
    stt_stream_start {lang?, sample_rate?, endpointing_ms?, utterance_end_ms?}
    stt_stream_chunk <bytes PCM16 mono>        (≤ 32 KB par frame)
    stt_stream_stop  {}

  serveur → client (room = sid)
    stt_stream_ready    {stream_id}
    stt_speech_started  {}                      ← barge-in instantané
    stt_partial         {text}                  ← transcript interim
    stt_final           {text, speech_final}    ← segment final (endpointing)
    stt_utterance_end   {}                      ← fin d'utterance sémantique
    stt_stream_closed   {reason}
    stt_stream_error    {error, code}           ← code "unavailable" → fallback batch

Garde-fous : 1 stream par connexion, cap par compte et global, durée max,
inactivité, frames bornées. Usage facturable loggé en DictationUsageLogRow
(durée audio réelle = bytes / (sample_rate × 2)), même table que /transcribe.

Scalabilité (audit 2026-05-29) : registry in-process → valide UNIQUEMENT en
single-instance (comme les 6 schedulers). À l'horizontal scaling, les streams
sont sticky par connexion Socket.IO donc le proxy lui-même tient, mais le cap
par compte devient per-instance — à migrer vers Redis avec le reste.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Limites ──────────────────────────────────────────────────────────────────
MAX_STREAM_SECONDS = 300          # durée wall-clock max d'un stream
MAX_CHUNK_BYTES = 32 * 1024       # une frame PCM16 16 kHz de 100 ms ≈ 3,2 KB
MAX_STREAMS_PER_ACCOUNT = 2       # tolère un overlap pendant une reconnexion
MAX_STREAMS_GLOBAL = 50
INACTIVITY_TIMEOUT_SECONDS = 30   # pas de chunk depuis 30 s → close

_VALID_SAMPLE_RATES = {8000, 16000, 24000, 44100, 48000}
_VALID_LANGS = {
    "fr", "en", "es", "de", "it", "pt", "nl", "ja", "ko", "zh", "hi", "ru",
    "pl", "sv", "da", "no", "fi", "tr", "uk", "cs", "ro", "hu", "el",
}

_DEEPGRAM_LIVE_URL = "wss://api.deepgram.com/v1/listen"


# Deepgram live n'a PAS d'auto-détection de langue (contrairement au batch).
# Sans paramètre `language`, le modèle décode en anglais → charabia pour un
# francophone, sans erreur nulle part. On envoie donc TOUJOURS un `language` :
# la langue du device si connue, sinon "multi" (nova-3 streaming multilingue).
_KEYTERM_BUDGET_CHARS = 400  # < cap ~500 tokens Deepgram (marge de sécurité)


def build_deepgram_url(
    lang: Optional[str],
    sample_rate: int,
    endpointing_ms: int,
    utterance_end_ms: int,
    keyterms: Optional[list[str]] = None,
) -> str:
    """Construit l'URL live Deepgram. Pure → testable sans réseau."""
    params: list[tuple[str, str]] = [
        ("model", "nova-3"),
        ("encoding", "linear16"),
        ("sample_rate", str(sample_rate)),
        ("channels", "1"),
        ("interim_results", "true"),
        ("smart_format", "true"),
        ("vad_events", "true"),
        ("endpointing", str(endpointing_ms)),
        ("utterance_end_ms", str(utterance_end_ms)),
        ("language", lang if lang else "multi"),
    ]
    # Budget caractères pour rester sous le cap ~500 tokens de Deepgram —
    # sinon le handshake échoue et le streaming devient « unavailable » pile
    # pour les comptes au vocabulaire le plus riche (masqué par le fallback batch).
    budget = _KEYTERM_BUDGET_CHARS
    for term in (keyterms or [])[:50]:
        term = (term or "").strip()
        if term and len(term) <= budget:
            params.append(("keyterm", term))
            budget -= len(term)
    return f"{_DEEPGRAM_LIVE_URL}?{urllib.parse.urlencode(params)}"


def parse_deepgram_message(raw: str) -> list[tuple[str, dict]]:
    """Convertit un message JSON Deepgram live en events Socket.IO.

    Retourne [(event_name, payload), …] — liste vide si le message ne
    concerne pas le client (Metadata, transcript vide non-final…).
    Pure → testable sans réseau.
    """
    try:
        msg = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(msg, dict):
        return []

    msg_type = msg.get("type")
    if msg_type == "SpeechStarted":
        return [("stt_speech_started", {})]
    if msg_type == "UtteranceEnd":
        return [("stt_utterance_end", {})]
    if msg_type != "Results":
        return []

    try:
        alt = msg["channel"]["alternatives"][0]
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(alt, dict):
        return []
    text = (alt.get("transcript") or "").strip()
    is_final = bool(msg.get("is_final"))
    speech_final = bool(msg.get("speech_final"))

    if not text:
        # Les interim vides sont du bruit ; un final vide peut quand même
        # porter speech_final=true (fin de segment silencieux) — on le
        # propage pour que le mobile résolve son tour.
        if is_final and speech_final:
            return [("stt_final", {"text": "", "speech_final": True})]
        return []

    if is_final:
        return [("stt_final", {"text": text, "speech_final": speech_final})]
    return [("stt_partial", {"text": text})]


# ─────────────────────────────────────────────────────────────────────────────
# Registry des streams actifs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StreamState:
    sid: str
    account_id: Optional[int]
    user_id: Optional[int]
    sample_rate: int
    dg_ws: Any = None
    reader: Optional[threading.Thread] = None
    started_at: float = field(default_factory=time.monotonic)
    last_chunk_at: float = field(default_factory=time.monotonic)
    bytes_received: int = 0
    oversize_warned: bool = False
    closed: threading.Event = field(default_factory=threading.Event)

    @property
    def audio_seconds(self) -> int:
        """Durée audio réelle reçue (PCM16 mono → 2 octets/échantillon)."""
        if self.sample_rate <= 0:
            return 0
        return int(self.bytes_received / (self.sample_rate * 2))


class StreamRegistry:
    """Registre thread-safe des streams + application des caps."""

    def __init__(self) -> None:
        self._streams: dict[str, StreamState] = {}
        self._lock = threading.Lock()

    def try_reserve(self, stream: StreamState) -> tuple[bool, str]:
        """Vérifie les caps ET insère le stream sous UN SEUL verrou (atomique).

        Audit P2-TOCTOU : `can_open` puis `add` en deux acquisitions de verrou
        laissait deux `stt_stream_start` concurrents passer le check global/
        par-compte avant que l'un ait `add`. La réservation atomique ferme la
        fenêtre — la place est prise AVANT de composer Deepgram (5 s) ; sur
        échec de connexion, l'appelant fait `remove(sid)` pour la libérer.
        """
        with self._lock:
            if stream.sid in self._streams:
                return False, "already_streaming"
            if len(self._streams) >= MAX_STREAMS_GLOBAL:
                return False, "server_busy"
            if stream.account_id is not None:
                per_account = sum(
                    1 for s in self._streams.values() if s.account_id == stream.account_id
                )
                if per_account >= MAX_STREAMS_PER_ACCOUNT:
                    return False, "account_limit"
            self._streams[stream.sid] = stream
            return True, ""

    def get(self, sid: str) -> Optional[StreamState]:
        with self._lock:
            return self._streams.get(sid)

    def remove(self, sid: str) -> Optional[StreamState]:
        with self._lock:
            return self._streams.pop(sid, None)

    def count(self) -> int:
        with self._lock:
            return len(self._streams)


_registry = StreamRegistry()

# sid → (user_email, account_id) renseigné par on_daemon_connect : les event
# handlers Socket.IO n'ont plus accès au payload auth du handshake, donc le
# connect handler nous confie l'identité vérifiée (P1-007/P1-014 déjà passés).
_sid_identity: dict[str, tuple[Optional[str], Optional[int]]] = {}
_sid_identity_lock = threading.Lock()


def register_sid_identity(sid: str, user_email: Optional[str], account_id: Optional[int]) -> None:
    with _sid_identity_lock:
        _sid_identity[sid] = (user_email, account_id)


def _resolve_identity(sid: str) -> tuple[Optional[str], Optional[int]]:
    with _sid_identity_lock:
        return _sid_identity.get(sid, (None, None))


def _resolve_user_and_account(sid: str) -> tuple[Optional[int], Optional[int]]:
    """user_id + account_id pour la facturation. Best-effort, jamais bloquant."""
    user_email, account_id = _resolve_identity(sid)
    user_id: Optional[int] = None
    try:
        if account_id is None and user_email:
            from app.db.database import get_db_session
            from app.db.models import Account

            with get_db_session() as session:
                row = (
                    session.query(Account)
                    .filter(Account.email == user_email)
                    .first()
                )
                if row is not None:
                    account_id = int(row.id)
                    user_id = int(row.user_id) if row.user_id is not None else None
        elif account_id is not None:
            from app.db.database import get_db_session
            from app.db.models import Account

            with get_db_session() as session:
                row = session.get(Account, int(account_id))
                if row is not None and row.user_id is not None:
                    user_id = int(row.user_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[stt-stream] identity resolve failed for sid=%s: %s", sid, exc)
    return user_id, account_id


def _record_stream_usage(stream: StreamState) -> None:
    """Insert DictationUsageLogRow — même table que /api/transcribe, provider
    distinct pour séparer batch et streaming dans les agrégats de coût."""
    seconds = stream.audio_seconds
    if seconds <= 0:
        return
    try:
        from datetime import datetime, timezone

        from app.db.database import get_db_session
        from app.db.models import DictationUsageLogRow

        with get_db_session() as session:
            session.add(
                DictationUsageLogRow(
                    account_id=stream.account_id,
                    user_id=stream.user_id,
                    provider="deepgram_stream",
                    duration_seconds=seconds,
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("[stt-stream] usage log skipped: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Reader thread — Deepgram → client
# ─────────────────────────────────────────────────────────────────────────────


def _reader_loop(stream: StreamState, emit: Callable[[str, dict], None]) -> None:
    """Boucle de lecture du WS Deepgram. Tourne dans un thread dédié ;
    s'arrête sur close/erreur/durée max/inactivité."""
    reason = "closed"
    try:
        while not stream.closed.is_set():
            now = time.monotonic()
            if now - stream.started_at > MAX_STREAM_SECONDS:
                reason = "max_duration"
                break
            if now - stream.last_chunk_at > INACTIVITY_TIMEOUT_SECONDS:
                reason = "inactivity"
                break
            try:
                raw = stream.dg_ws.recv()
            except Exception:
                # timeout de socket (on a configuré un timeout court pour
                # pouvoir vérifier les caps) ou connexion fermée.
                if stream.closed.is_set():
                    break
                try:
                    if not stream.dg_ws.connected:
                        reason = "deepgram_closed"
                        break
                except Exception:
                    reason = "deepgram_closed"
                    break
                continue
            if raw is None:
                continue
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            for event, payload in parse_deepgram_message(raw):
                emit(event, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[stt-stream] reader crashed sid=%s: %s", stream.sid, exc)
        reason = "error"
    finally:
        stream.closed.set()
        try:
            stream.dg_ws.close()
        except Exception:  # noqa: BLE001
            pass
        _registry.remove(stream.sid)
        _record_stream_usage(stream)
        emit("stt_stream_closed", {"reason": reason})
        logger.info(
            "[stt-stream] closed sid=%s reason=%s audio=%ds bytes=%d",
            stream.sid, reason, stream.audio_seconds, stream.bytes_received,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Socket.IO handlers
# ─────────────────────────────────────────────────────────────────────────────


def _make_emitter(socketio: Any, sid: str) -> Callable[[str, dict], None]:
    def emit(event: str, payload: dict) -> None:
        try:
            socketio.emit(event, payload, room=sid, namespace="/daemon")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[stt-stream] emit %s failed sid=%s: %s", event, sid, exc)
    return emit


def _clamp_int(value: object, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def register_stt_stream_handlers(socketio: Any) -> None:
    """Branche les events stt_stream_* sur le namespace /daemon existant.
    Appelé par init_socketio() après l'enregistrement du connect handler."""

    def on_start(data: Any = None) -> None:
        from flask import request as flask_request

        sid: str = flask_request.sid  # type: ignore[attr-defined]
        emit = _make_emitter(socketio, sid)

        # Defense-in-depth : seul un sid passé par on_daemon_connect a une
        # identité enregistrée. Pas d'entrée = connexion non acceptée → refus.
        user_email, _ = _resolve_identity(sid)
        if sid not in _sid_identity:
            emit("stt_stream_error", {"error": "Non authentifié", "code": "unauthorized"})
            return

        deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
        if not deepgram_key:
            emit("stt_stream_error", {"error": "Streaming STT non configuré", "code": "unavailable"})
            return

        data = data if isinstance(data, dict) else {}
        lang = data.get("lang")
        lang = lang.lower() if isinstance(lang, str) and lang.lower() in _VALID_LANGS else None
        sample_rate = data.get("sample_rate")
        sample_rate = sample_rate if sample_rate in _VALID_SAMPLE_RATES else 16000
        endpointing_ms = _clamp_int(data.get("endpointing_ms"), 300, 100, 3000)
        utterance_end_ms = _clamp_int(data.get("utterance_end_ms"), 1000, 500, 6000)

        user_id, account_id = _resolve_user_and_account(sid)

        # Audit P1 — fail-open : une connexion JWT distante (user_email présent)
        # sans Account résolu (pré-OAuth) ouvrait quand même un stream, sautait
        # le cap par-compte et streamait de l'audio Deepgram non facturé →
        # DoS 50-slots + coût orphelin. On REFUSE. Le loopback (Tauri desktop,
        # user_email None, peer local de confiance) reste autorisé.
        if user_email and account_id is None:
            emit("stt_stream_error", {"error": "Compte non résolu", "code": "unauthorized"})
            return

        stream = StreamState(
            sid=sid,
            account_id=account_id,
            user_id=user_id,
            sample_rate=sample_rate,
        )
        # Réservation ATOMIQUE de la place AVANT de composer Deepgram (5 s).
        ok, deny_reason = _registry.try_reserve(stream)
        if not ok:
            emit("stt_stream_error", {"error": f"Stream refusé ({deny_reason})", "code": deny_reason})
            return

        keyterms: list[str] = []
        try:
            from app.services import stt_keyterms as _stt_kt
            keyterms = _stt_kt.get_keyterms_for_account(account_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[stt-stream] keyterms fetch failed: %s", exc)

        url = build_deepgram_url(lang, sample_rate, endpointing_ms, utterance_end_ms, keyterms)

        try:
            import websocket as _ws  # websocket-client

            dg_ws = _ws.create_connection(
                url,
                header=[f"Authorization: Token {deepgram_key}"],
                timeout=5,
            )
            # recv() timeout court pour que la boucle reader vérifie les caps
            # (durée max / inactivité) même quand Deepgram est silencieux.
            dg_ws.settimeout(2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[stt-stream] Deepgram connect failed: %s", exc)
            _registry.remove(sid)  # libère la place réservée
            emit("stt_stream_error", {"error": "Connexion Deepgram échouée", "code": "unavailable"})
            return

        stream.dg_ws = dg_ws

        reader = threading.Thread(
            target=_reader_loop,
            args=(stream, emit),
            name=f"stt-stream-{sid[:8]}",
            daemon=True,
        )
        stream.reader = reader
        try:
            reader.start()
        except RuntimeError as exc:  # thread exhaustion — ne pas fuiter la place
            logger.warning("[stt-stream] reader thread start failed sid=%s: %s", sid, exc)
            _registry.remove(sid)
            try:
                dg_ws.close()
            except Exception:  # noqa: BLE001
                pass
            emit("stt_stream_error", {"error": "Serveur saturé", "code": "server_busy"})
            return

        emit("stt_stream_ready", {"stream_id": sid})
        logger.info(
            "[stt-stream] open sid=%s account=%s lang=%s rate=%d active=%d",
            sid, account_id, lang or "multi", sample_rate, _registry.count(),
        )

    def on_chunk(data: Any = None) -> None:
        from flask import request as flask_request

        sid: str = flask_request.sid  # type: ignore[attr-defined]
        stream = _registry.get(sid)
        if stream is None or stream.closed.is_set():
            return
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            return
        if len(data) > MAX_CHUNK_BYTES:
            # Frame mal calibrée côté encodeur mobile : sans signal, le client
            # voit des transcripts troués sans comprendre pourquoi. On émet une
            # erreur one-shot (le client peut réduire sa taille de frame).
            if not stream.oversize_warned:
                stream.oversize_warned = True
                _make_emitter(socketio, sid)(
                    "stt_stream_error",
                    {"error": "Frame audio trop grande", "code": "chunk_too_large"},
                )
            return
        stream.last_chunk_at = time.monotonic()
        stream.bytes_received += len(data)
        try:
            stream.dg_ws.send_binary(bytes(data))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[stt-stream] forward failed sid=%s: %s", sid, exc)
            stream.closed.set()

    def on_stop(_data: Any = None) -> None:
        from flask import request as flask_request

        sid: str = flask_request.sid  # type: ignore[attr-defined]
        stream = _registry.get(sid)
        if stream is None:
            return
        # CloseStream demande à Deepgram de flush les derniers résultats puis
        # de fermer — le reader thread terminera proprement sur la fermeture.
        try:
            stream.dg_ws.send(json.dumps({"type": "CloseStream"}))
        except Exception:  # noqa: BLE001
            stream.closed.set()

    socketio.on_event("stt_stream_start", on_start, namespace="/daemon")
    socketio.on_event("stt_stream_chunk", on_chunk, namespace="/daemon")
    socketio.on_event("stt_stream_stop", on_stop, namespace="/daemon")


def cleanup_for_sid(sid: str) -> None:
    """Appelé par on_daemon_disconnect : ferme le stream du client déconnecté
    et oublie son identité."""
    with _sid_identity_lock:
        _sid_identity.pop(sid, None)
    stream = _registry.get(sid)
    if stream is not None:
        stream.closed.set()
        if stream.dg_ws is not None:
            try:
                stream.dg_ws.close()
            except Exception:  # noqa: BLE001
                pass
        # Si le reader thread n'a jamais démarré (échec start) ou est déjà mort,
        # son `finally` ne retirera pas l'entrée → fuite de place. On nettoie ici.
        reader = stream.reader
        if reader is None or not reader.is_alive():
            _registry.remove(sid)
