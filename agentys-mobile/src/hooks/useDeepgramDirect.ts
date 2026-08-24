/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * useDeepgramDirect — STT temps réel en se connectant DIRECTEMENT à Deepgram
 * (wss://api.deepgram.com/v1/listen) depuis le mobile, sans passer par le proxy
 * Socket.IO /daemon.
 *
 * Pourquoi : le worker gunicorn `gthread` de prod ne supporte pas l'upgrade
 * WebSocket (HTTP 400) et l'audio binaire continu meurt sur le fallback polling
 * (Deepgram recevait `bytes=0`). En se connectant directement à Deepgram —
 * authentifié par un token court mint par le backend (`/api/stt/grant-token`,
 * via Deepgram `/v1/auth/grant`) — on contourne entièrement le runtime serveur
 * ET on gagne en latence (un hop de moins). C'est le pattern recommandé par
 * Deepgram pour les clients (browser/mobile).
 *
 * Implémente la MÊME interface que `useStreamingStt` (UseStreamingStt) pour être
 * un drop-in dans useDriveMode derrière un flag. La partie mic native
 * (AgentysAudio.startMicStream → frames PCM16 16 kHz) est inchangée — elle est
 * prouvée fonctionnelle ; seul le transport change (raw WS au lieu de Socket.IO).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import * as AgentysAudio from "../../modules/agentys-audio";
import { getDeepgramToken } from "../services/api";
import type {
  StreamingSttState,
  StreamingSessionOptions,
  StreamingListenOptions,
  StreamingListenResult,
  UseStreamingStt,
} from "./useStreamingStt";

const SAMPLE_RATE = 16000;
const MAX_SESSION_RESTARTS = 2;
/** Fenêtre pendant laquelle un final arrivé hors-listen est réutilisable
 *  (barge-in pendant la TTS : on ne perd jamais l'utterance qui coupe l'AI). */
const PREBUFFER_MS = 1500;
const DEFAULT_NO_VOICE_MS = 10_000;
const DEFAULT_MAX_UTTERANCE_MS = 60_000;
const DEEPGRAM_BASE = "wss://api.deepgram.com/v1/listen";

// ── base64 → octets (frames mic natives) ───────────────────────────────────
const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const B64_LOOKUP = (() => {
  const t = new Uint8Array(256);
  for (let i = 0; i < B64.length; i++) t[B64.charCodeAt(i)] = i;
  return t;
})();
function base64ToBytes(b64: string): Uint8Array {
  let clean = b64;
  const pad = clean.indexOf("=");
  if (pad !== -1) clean = clean.slice(0, pad);
  const len = clean.length;
  const bytes = new Uint8Array((len * 3) >> 2);
  let p = 0;
  for (let i = 0; i < len; i += 4) {
    const a = B64_LOOKUP[clean.charCodeAt(i)];
    const b = i + 1 < len ? B64_LOOKUP[clean.charCodeAt(i + 1)] : 0;
    const c = i + 2 < len ? B64_LOOKUP[clean.charCodeAt(i + 2)] : 0;
    const d = i + 3 < len ? B64_LOOKUP[clean.charCodeAt(i + 3)] : 0;
    bytes[p++] = (a << 2) | (b >> 4);
    if (i + 2 < len) bytes[p++] = ((b & 15) << 4) | (c >> 2);
    if (i + 3 < len) bytes[p++] = ((c & 3) << 6) | d;
  }
  return bytes.subarray(0, p);
}

interface ActiveListen {
  parts: string[];
  resolve: (r: StreamingListenResult) => void;
  onPartial?: (text: string) => void;
  noVoiceTimer: ReturnType<typeof setTimeout> | null;
  maxTimer: ReturnType<typeof setTimeout> | null;
}

function buildDeepgramUrl(lang?: string): string {
  const params = new URLSearchParams({
    model: "nova-3",
    encoding: "linear16",
    sample_rate: String(SAMPLE_RATE),
    channels: "1",
    interim_results: "true",
    endpointing: "300",
    utterance_end_ms: "1000",
    vad_events: "true",
    smart_format: "true",
  });
  if (lang) params.set("language", lang);
  return `${DEEPGRAM_BASE}?${params.toString()}`;
}

export function useDeepgramDirect(): UseStreamingStt {
  const [state, setState] = useState<StreamingSttState>("idle");

  const wsRef = useRef<WebSocket | null>(null);
  const sessionOpenRef = useRef(false);
  const sessionOptsRef = useRef<StreamingSessionOptions>({});
  const restartsRef = useRef(0);
  const micUnsubRef = useRef<(() => void) | null>(null);
  const listenRef = useRef<ActiveListen | null>(null);
  const preBufferRef = useRef<{ text: string; at: number } | null>(null);
  const keepAliveRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const finishListen = useCallback((result: StreamingListenResult) => {
    const active = listenRef.current;
    if (!active) return;
    listenRef.current = null;
    if (active.noVoiceTimer) clearTimeout(active.noVoiceTimer);
    if (active.maxTimer) clearTimeout(active.maxTimer);
    setState(sessionOpenRef.current ? "open" : "idle");
    active.resolve(result);
  }, []);

  const teardown = useCallback(() => {
    sessionOpenRef.current = false;
    AgentysAudio.stopMicStream();
    if (micUnsubRef.current) { micUnsubRef.current(); micUnsubRef.current = null; }
    if (keepAliveRef.current) { clearInterval(keepAliveRef.current); keepAliveRef.current = null; }
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      try { ws.send(JSON.stringify({ type: "CloseStream" })); } catch { /* dead */ }
      try { ws.close(); } catch { /* dead */ }
    }
    preBufferRef.current = null;
    finishListen({ kind: "cancelled" });
    setState("idle");
  }, [finishListen]);

  // ── Parse un message Deepgram → events listen ─────────────────────────────
  const handleMessage = useCallback((raw: string) => {
    let msg: any;
    try { msg = JSON.parse(raw); } catch { return; }
    const type = msg?.type;

    if (type === "SpeechStarted") {
      sessionOptsRef.current.onSpeechStart?.();
      return;
    }

    if (type === "UtteranceEnd") {
      const active = listenRef.current;
      if (active && active.parts.length > 0) {
        finishListen({ kind: "ok", text: active.parts.join(" ") });
      }
      return;
    }

    if (type === "Results") {
      const alt = msg?.channel?.alternatives?.[0];
      const text = (alt?.transcript || "").trim();
      const isFinal = !!msg?.is_final;
      const speechFinal = !!msg?.speech_final;
      const active = listenRef.current;

      if (!active) {
        // Final hors-listen (barge-in pendant la TTS) : pré-buffer court.
        if (text && (isFinal || speechFinal)) preBufferRef.current = { text, at: Date.now() };
        return;
      }
      if (text) {
        if (active.noVoiceTimer) { clearTimeout(active.noVoiceTimer); active.noVoiceTimer = null; }
        if (isFinal) {
          active.parts.push(text);
        } else {
          // Partiel live : preview = finals accumulés + partiel courant.
          active.onPartial?.([...active.parts, text].join(" "));
        }
      }
      // speech_final = l'endpointing sémantique de Deepgram dit « tour fini ».
      if (speechFinal && active.parts.length > 0) {
        finishListen({ kind: "ok", text: active.parts.join(" ") });
      }
    }
  }, [finishListen]);

  // ── Ouvre la connexion Deepgram (token + WS + mic) ────────────────────────
  const connectDeepgram = useCallback(async (): Promise<boolean> => {
    let token: string;
    try {
      const grant = await getDeepgramToken(300);
      token = grant.token;
    } catch (e: any) {
      console.warn("[dg-direct] token mint failed:", e?.message || e);
      return false;
    }

    const lang = sessionOptsRef.current.lang;
    const url = buildDeepgramUrl(lang);

    return new Promise<boolean>((resolve) => {
      let settled = false;
      const done = (ok: boolean) => { if (settled) return; settled = true; resolve(ok); };

      let ws: WebSocket;
      try {
        // Auth Deepgram côté client : sous-protocole `['token', <jwt>]`
        // (RN/browser ne peuvent pas poser de header sur un WebSocket).
        ws = new WebSocket(url, ["token", token]);
      } catch (e: any) {
        console.warn("[dg-direct] WS construct failed:", e?.message || e);
        done(false);
        return;
      }
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        // Mic natif → WS (frames PCM16 directement vers Deepgram).
        const micStarted = AgentysAudio.startMicStream(SAMPLE_RATE);
        if (!micStarted) {
          console.warn("[dg-direct] startMicStream returned false");
          try { ws.close(); } catch { /* */ }
          done(false);
          return;
        }
        micUnsubRef.current = AgentysAudio.addMicFrameListener((base64) => {
          const w = wsRef.current;
          if (!w || w.readyState !== 1 /* OPEN */ || !sessionOpenRef.current) return;
          const bytes = base64ToBytes(base64);
          if (bytes.byteLength === 0) return;
          try {
            // slice() d'un ArrayBuffer|SharedArrayBuffer renvoie le même type
            // union sous @types/node ; nos bytes viennent de base64 (jamais
            // shared) → cast sûr pour la signature de WebSocket.send.
            w.send(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer);
          } catch { /* socket fermé en course */ }
        });
        // KeepAlive Deepgram : évite la fermeture sur 10 s sans audio reçu.
        keepAliveRef.current = setInterval(() => {
          const w = wsRef.current;
          if (w && w.readyState === 1) { try { w.send(JSON.stringify({ type: "KeepAlive" })); } catch { /* */ } }
        }, 8000);
        done(true);
      };

      ws.onmessage = (ev: WebSocketMessageEvent) => {
        if (typeof ev.data === "string") handleMessage(ev.data);
      };

      ws.onerror = () => {
        console.warn("[dg-direct] WS error");
        if (!settled) done(false);
      };

      ws.onclose = () => {
        // Fermeture serveur (token expiré, inactivité, cap Deepgram). Si la
        // session est censée vivre, on relance en transparence (le mic natif
        // tourne toujours) avec un token frais.
        if (!sessionOpenRef.current) return;
        if (micUnsubRef.current) { micUnsubRef.current(); micUnsubRef.current = null; }
        if (keepAliveRef.current) { clearInterval(keepAliveRef.current); keepAliveRef.current = null; }
        if (restartsRef.current >= MAX_SESSION_RESTARTS) {
          const lost = sessionOptsRef.current.onSessionLost;
          sessionOpenRef.current = false;
          finishListen({ kind: "cancelled" });
          lost?.();
          return;
        }
        restartsRef.current += 1;
        connectDeepgram().then((ok) => {
          if (!ok) {
            const lost = sessionOptsRef.current.onSessionLost;
            sessionOpenRef.current = false;
            finishListen({ kind: "cancelled" });
            lost?.();
          } else {
            restartsRef.current = 0;
          }
        });
      };
    });
  }, [finishListen, handleMessage]);

  const openSession = useCallback(
    async (opts: StreamingSessionOptions = {}): Promise<boolean> => {
      if (!AgentysAudio.MIC_STREAM_AVAILABLE) return false;
      if (sessionOpenRef.current) return true;
      sessionOptsRef.current = opts;
      restartsRef.current = 0;
      setState("connecting");
      sessionOpenRef.current = true; // le mic doit pouvoir émettre dès onopen
      const ok = await connectDeepgram();
      if (!ok) {
        sessionOpenRef.current = false;
        setState("idle");
        return false;
      }
      setState("open");
      return true;
    },
    [connectDeepgram],
  );

  const closeSession = useCallback(() => {
    if (!sessionOpenRef.current && !wsRef.current) return;
    teardown();
  }, [teardown]);

  const listen = useCallback(
    (opts: StreamingListenOptions = {}): Promise<StreamingListenResult> => {
      if (!sessionOpenRef.current) return Promise.resolve({ kind: "error", error: "session_closed" });
      if (listenRef.current) finishListen({ kind: "cancelled" });

      // Un final arrivé juste avant (barge-in) est servi immédiatement.
      const pre = preBufferRef.current;
      if (pre && Date.now() - pre.at < PREBUFFER_MS) {
        preBufferRef.current = null;
        return Promise.resolve({ kind: "ok", text: pre.text });
      }
      preBufferRef.current = null;

      setState("listening");
      return new Promise<StreamingListenResult>((resolve) => {
        const active: ActiveListen = {
          parts: [],
          resolve,
          onPartial: opts.onPartial,
          noVoiceTimer: null,
          maxTimer: null,
        };
        active.noVoiceTimer = setTimeout(() => {
          if (active.parts.length === 0) finishListen({ kind: "no_voice" });
        }, opts.noVoiceTimeoutMs ?? DEFAULT_NO_VOICE_MS);
        active.maxTimer = setTimeout(() => {
          finishListen(active.parts.length > 0 ? { kind: "ok", text: active.parts.join(" ") } : { kind: "no_voice" });
        }, opts.maxDurationMs ?? DEFAULT_MAX_UTTERANCE_MS);
        listenRef.current = active;
      });
    },
    [finishListen],
  );

  const cancelListen = useCallback(() => {
    if (listenRef.current) finishListen({ kind: "cancelled" });
  }, [finishListen]);

  // Cleanup au démontage.
  useEffect(() => () => { teardown(); }, [teardown]);

  return {
    available: AgentysAudio.MIC_STREAM_AVAILABLE,
    state,
    openSession,
    closeSession,
    listen,
    cancelListen,
  };
}
