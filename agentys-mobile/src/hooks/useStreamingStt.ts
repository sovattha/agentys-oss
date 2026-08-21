/**
 * useStreamingStt — STT temps réel via le proxy Socket.IO backend → Deepgram
 * live (Step 4 voice-first).
 *
 * Remplace le cycle batch (record fichier → upload → /api/transcribe,
 * ~1,5-2 s de blanc) par un flux continu :
 *
 *   1. `openSession()` — UNE connexion Deepgram pour toute la session Drive :
 *      mic natif (AVAudioEngine, frames PCM16 16 kHz) → socket /daemon →
 *      Deepgram. Pas de coût de connexion par tour de parole.
 *   2. `listen()` — attend la PROCHAINE utterance : les partiels arrivent en
 *      <300 ms (feedback transcript live), la fin de tour est décidée par
 *      l'endpointing sémantique de Deepgram (speech_final / UtteranceEnd),
 *      plus aucun timer de silence fixe côté mobile.
 *   3. `onSpeechStart` (session) — signal barge-in : l'utilisateur a pris la
 *      parole, le caller coupe la TTS. Avec l'AEC de configureForVoiceChat(),
 *      l'écho TTS n'atteint jamais Deepgram.
 *
 * Un final qui arrive HORS listen() (barge-in pendant la lecture) est gardé
 * `PREBUFFER_MS` et servi au listen() suivant — l'utterance de l'utilisateur
 * qui coupe l'AI n'est jamais perdue.
 *
 * Indisponible (Expo Go, Android, vieux build natif, socket down) →
 * `available=false` / résultats `error` : le caller retombe sur le pipeline
 * batch useVoiceDictation existant. Zéro régression.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Socket } from "socket.io-client";
import * as AgentysAudio from "../../modules/agentys-audio";
import { connectSocket } from "../services/websocket";

export type StreamingSttState = "idle" | "connecting" | "open" | "listening";

export interface StreamingSessionOptions {
  /** Code langue ISO ("fr", "en"…). Absent → auto-détection Deepgram. */
  lang?: string;
  /** Barge-in : Deepgram a détecté un début de parole (~<300 ms). */
  onSpeechStart?: () => void;
  /** La session streaming est morte et n'a pas pu être relancée — le caller
   *  doit repasser en batch pour la suite. */
  onSessionLost?: () => void;
}

export interface StreamingListenOptions {
  /** Transcript partiel live (UI). */
  onPartial?: (text: string) => void;
  /** Aucun son de voix détecté au bout de ce délai → no_voice. Défaut 10 s. */
  noVoiceTimeoutMs?: number;
  /** Durée max d'une utterance. Défaut 60 s. */
  maxDurationMs?: number;
}

export type StreamingListenResult =
  | { kind: "ok"; text: string }
  | { kind: "no_voice" }
  | { kind: "cancelled" }
  | { kind: "error"; error: string };

export interface UseStreamingStt {
  /** Tap mic natif compilé dans ce build ? (précondition matérielle) */
  available: boolean;
  state: StreamingSttState;
  openSession: (opts?: StreamingSessionOptions) => Promise<boolean>;
  closeSession: () => void;
  listen: (opts?: StreamingListenOptions) => Promise<StreamingListenResult>;
  cancelListen: () => void;
}

/** Fenêtre pendant laquelle un final arrivé hors-listen est réutilisable. */
const PREBUFFER_MS = 1500;
/** Timeout du handshake stt_stream_start → stt_stream_ready.
 *  DOIT dépasser le pire cas serveur : `on_start` ouvre une connexion WebSocket
 *  vers Deepgram avec un timeout de 5 s (stt_stream.py:447) AVANT d'émettre
 *  `stt_stream_ready`, plus la résolution d'identité + le fetch keyterms DB.
 *  En local le connect Deepgram est instantané, mais depuis Railway il peut
 *  approcher les 5 s — un timeout client à 4 s abandonnait pile avant la
 *  réponse serveur (handshake "échoué" alors que le stream s'ouvrait), d'où la
 *  retombée batch permanente en prod. 12 s = 5 s Deepgram + marge réseau. */
const HANDSHAKE_TIMEOUT_MS = 12000;
/** Tentatives de relance transparente après un stt_stream_closed serveur. */
const MAX_SESSION_RESTARTS = 2;
const SAMPLE_RATE = 16000;

const B64_LOOKUP = (() => {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const lookup = new Uint8Array(128);
  for (let i = 0; i < chars.length; i++) lookup[chars.charCodeAt(i)] = i;
  return lookup;
})();

/**
 * Décode du base64 en Uint8Array sans dépendance (atob n'est pas garanti
 * sur toutes les versions d'Hermes). Pure + exportée pour les tests.
 */
export function base64ToBytes(base64: string): Uint8Array {
  const clean = base64.replace(/[\r\n=]+/g, "");
  const len = clean.length;
  const bytes = new Uint8Array(Math.floor((len * 3) / 4));
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
  sawSpeech: boolean;
  resolve: (r: StreamingListenResult) => void;
  onPartial?: (text: string) => void;
  noVoiceTimer: ReturnType<typeof setTimeout> | null;
  maxTimer: ReturnType<typeof setTimeout> | null;
}

export function useStreamingStt(): UseStreamingStt {
  const [state, setState] = useState<StreamingSttState>("idle");

  const socketRef = useRef<Socket | null>(null);
  const sessionOpenRef = useRef(false);
  const sessionOptsRef = useRef<StreamingSessionOptions>({});
  const restartsRef = useRef(0);
  const micUnsubRef = useRef<(() => void) | null>(null);
  const listenRef = useRef<ActiveListen | null>(null);
  const preBufferRef = useRef<{ text: string; at: number } | null>(null);
  // Handlers socket enregistrés (pour off() propre au close).
  const handlersRef = useRef<Array<[string, (...args: any[]) => void]>>([]);

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
    if (micUnsubRef.current) {
      micUnsubRef.current();
      micUnsubRef.current = null;
    }
    const socket = socketRef.current;
    if (socket) {
      for (const [event, handler] of handlersRef.current) {
        socket.off(event, handler);
      }
      handlersRef.current = [];
      try {
        socket.emit("stt_stream_stop", {});
      } catch {
        // socket déjà mort — peu importe
      }
    }
    socketRef.current = null;
    preBufferRef.current = null;
    finishListen({ kind: "cancelled" });
    setState("idle");
  }, [finishListen]);

  /** Handshake stt_stream_start → ready/error sur un socket déjà câblé. */
  const startStream = useCallback((socket: Socket): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      let settled = false;
      const settle = (ok: boolean) => {
        if (settled) return;
        settled = true;
        socket.off("stt_stream_ready", onReady);
        socket.off("stt_stream_error", onError);
        resolve(ok);
      };
      const onReady = () => settle(true);
      const onError = (err: any) => {
        console.log("[stt-diag] prod stt_stream_error:", JSON.stringify(err));
        settle(false);
      };
      socket.on("stt_stream_ready", onReady);
      socket.on("stt_stream_error", onError);
      socket.emit("stt_stream_start", {
        lang: sessionOptsRef.current.lang,
        sample_rate: SAMPLE_RATE,
      });
      setTimeout(() => settle(false), HANDSHAKE_TIMEOUT_MS);
    });
  }, []);

  const openSession = useCallback(
    async (opts: StreamingSessionOptions = {}): Promise<boolean> => {
      if (!AgentysAudio.MIC_STREAM_AVAILABLE) return false;
      if (sessionOpenRef.current) return true;
      sessionOptsRef.current = opts;
      restartsRef.current = 0;
      setState("connecting");

      let socket: Socket;
      try {
        socket = await connectSocket();
      } catch (e: any) {
        console.log("[stt-diag] connectSocket FAILED:", e?.message || String(e));
        setState("idle");
        return false;
      }
      console.log("[stt-diag] socket connected → starting handshake");
      socketRef.current = socket;

      // ── Câblage des events de transcription ────────────────────────────
      const onPartial = (data: { text?: string }) => {
        const active = listenRef.current;
        const text = (data?.text || "").trim();
        if (!active || !text) return;
        active.sawSpeech = true;
        if (active.noVoiceTimer) {
          clearTimeout(active.noVoiceTimer);
          active.noVoiceTimer = null;
        }
        const preview = [...active.parts, text].join(" ");
        active.onPartial?.(preview);
      };

      const onFinal = (data: { text?: string; speech_final?: boolean }) => {
        const text = (data?.text || "").trim();
        const active = listenRef.current;
        if (!active) {
          // Final hors-listen (barge-in pendant la TTS) : pré-buffer court.
          if (text) preBufferRef.current = { text, at: Date.now() };
          return;
        }
        if (text) {
          active.sawSpeech = true;
          if (active.noVoiceTimer) {
            clearTimeout(active.noVoiceTimer);
            active.noVoiceTimer = null;
          }
          active.parts.push(text);
        }
        // speech_final = l'endpointing sémantique dit « le tour est fini ».
        if (data?.speech_final && active.parts.length > 0) {
          finishListen({ kind: "ok", text: active.parts.join(" ") });
        }
      };

      const onUtteranceEnd = () => {
        const active = listenRef.current;
        if (active && active.parts.length > 0) {
          finishListen({ kind: "ok", text: active.parts.join(" ") });
        }
      };

      const onSpeechStarted = () => {
        sessionOptsRef.current.onSpeechStart?.();
        const active = listenRef.current;
        if (active) active.sawSpeech = true;
      };

      const onClosed = async () => {
        // Le serveur a fermé (cap 5 min, inactivité, Deepgram down). Si la
        // session est censée vivre, on relance en transparence — le mic
        // natif tourne toujours, seul le tronçon socket↔Deepgram se rouvre.
        if (!sessionOpenRef.current) return;
        if (restartsRef.current >= MAX_SESSION_RESTARTS) {
          const lost = sessionOptsRef.current.onSessionLost;
          teardown();
          lost?.();
          return;
        }
        restartsRef.current += 1;
        const ok = socketRef.current ? await startStream(socketRef.current) : false;
        if (!ok) {
          const lost = sessionOptsRef.current.onSessionLost;
          teardown();
          lost?.();
        } else {
          // Relance réussie → on remet le budget à zéro, sinon le cap serveur
          // de 5 min épuiserait MAX_SESSION_RESTARTS sur une longue session
          // pourtant saine (M-P2g).
          restartsRef.current = 0;
        }
      };

      const wired: Array<[string, (...args: any[]) => void]> = [
        ["stt_partial", onPartial],
        ["stt_final", onFinal],
        ["stt_utterance_end", onUtteranceEnd],
        ["stt_speech_started", onSpeechStarted],
        ["stt_stream_closed", onClosed],
      ];
      for (const [event, handler] of wired) socket.on(event, handler);
      handlersRef.current = wired;

      const ok = await startStream(socket);
      if (!ok) {
        console.log("[stt-diag] startStream handshake FAILED — no stt_stream_ready within timeout (prod handler missing / DEEPGRAM key / error?)");
        for (const [event, handler] of wired) socket.off(event, handler);
        handlersRef.current = [];
        socketRef.current = null;
        setState("idle");
        return false;
      }
      console.log("[stt-diag] handshake OK → starting native mic stream");

      // ── Mic natif → socket ──────────────────────────────────────────────
      const micStarted = AgentysAudio.startMicStream(SAMPLE_RATE);
      if (!micStarted) {
        console.log("[stt-diag] startMicStream returned false at runtime (mic perm / engine start?)");
        socket.emit("stt_stream_stop", {});
        for (const [event, handler] of wired) socket.off(event, handler);
        handlersRef.current = [];
        socketRef.current = null;
        setState("idle");
        return false;
      }
      let _micFrames = 0;
      micUnsubRef.current = AgentysAudio.addMicFrameListener((base64) => {
        const s = socketRef.current;
        if (!s || !sessionOpenRef.current) return;
        const bytes = base64ToBytes(base64);
        if (bytes.byteLength === 0) return;
        _micFrames++;
        if (_micFrames === 1 || _micFrames % 25 === 0) {
          const tn = (s as unknown as { io?: { engine?: { transport?: { name?: string } } } })?.io?.engine?.transport?.name;
          console.log("[stt-diag] mic frames emitted=" + _micFrames + " bytes/frame=" + bytes.byteLength + " transport=" + (tn || "?"));
        }
        s.emit(
          "stt_stream_chunk",
          bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
        );
      });

      sessionOpenRef.current = true;
      setState("open");
      return true;
    },
    [finishListen, startStream, teardown],
  );

  const closeSession = useCallback(() => {
    teardown();
  }, [teardown]);

  const listen = useCallback(
    (opts: StreamingListenOptions = {}): Promise<StreamingListenResult> => {
      if (!sessionOpenRef.current) {
        return Promise.resolve({ kind: "error", error: "session_not_open" });
      }
      // Un listen écrase le précédent (même politique que useVoiceDictation).
      finishListen({ kind: "cancelled" });

      // Barge-in capturé juste avant ce listen ? Servi immédiatement.
      const pre = preBufferRef.current;
      if (pre && Date.now() - pre.at < PREBUFFER_MS) {
        preBufferRef.current = null;
        return Promise.resolve({ kind: "ok", text: pre.text });
      }
      preBufferRef.current = null;

      const { onPartial, noVoiceTimeoutMs = 10_000, maxDurationMs = 60_000 } = opts;

      return new Promise<StreamingListenResult>((resolve) => {
        const active: ActiveListen = {
          parts: [],
          sawSpeech: false,
          resolve,
          onPartial,
          noVoiceTimer: null,
          maxTimer: null,
        };
        active.noVoiceTimer = setTimeout(() => {
          if (listenRef.current === active && !active.sawSpeech) {
            finishListen({ kind: "no_voice" });
          }
        }, noVoiceTimeoutMs);
        active.maxTimer = setTimeout(() => {
          if (listenRef.current !== active) return;
          if (active.parts.length > 0) {
            finishListen({ kind: "ok", text: active.parts.join(" ") });
          } else {
            finishListen({ kind: "no_voice" });
          }
        }, maxDurationMs);
        listenRef.current = active;
        setState("listening");
      });
    },
    [finishListen],
  );

  const cancelListen = useCallback(() => {
    finishListen({ kind: "cancelled" });
  }, [finishListen]);

  // Cleanup au démontage du hook (sortie de l'écran Drive).
  useEffect(() => {
    return () => {
      teardown();
    };
  }, [teardown]);

  return {
    available: AgentysAudio.MIC_STREAM_AVAILABLE,
    state,
    openSession,
    closeSession,
    listen,
    cancelListen,
  };
}
