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
 * voiceMetrics — télémétrie voice-to-voice du Drive Mode.
 *
 * LA métrique qui décide si la conversation « parle comme un humain » :
 * turn_latency_ms = fin de parole utilisateur → premier son de l'AI.
 * Budget : < 1000 ms = personne ; > 2000 ms = serveur vocal des années 90.
 *
 * Mesures (durées et compteurs uniquement — JAMAIS de contenu, zéro PII) :
 *   - turn_latency_ms    : speech end → TTS audible
 *   - stt_latency_ms     : speech end → transcript dispo
 *   - tts_first_audio_ms : demande TTS → premier son
 *   - false_restarts     : re-listen sur no_voice/vide (friction silencieuse)
 *   - undo_cancels       : annulations pendant la fenêtre act-then-undo
 *   - barge_ins          : l'utilisateur a coupé l'AI (bon signe de fluidité)
 *   - command_misses     : parole entendue mais aucune action déclenchée
 *
 * Buffer en mémoire, flush batché vers POST /api/voice/metrics (fin de
 * session + toutes les 60 s). Échec réseau → on jette : la télémétrie ne
 * doit jamais coûter quoi que ce soit à l'UX.
 */

export type LatencyKind = "turn_latency_ms" | "stt_latency_ms" | "tts_first_audio_ms";
export type CounterKind = "false_restarts" | "undo_cancels" | "command_misses" | "barge_ins";

export interface MetricEvent {
  kind: LatencyKind | CounterKind;
  value_ms?: number;
  count?: number;
  state?: string;
}

const MAX_BUFFER = 200;
const FLUSH_INTERVAL_MS = 60_000;

type Sender = (events: MetricEvent[]) => Promise<void>;

export class VoiceMetricsCollector {
  private buffer: MetricEvent[] = [];
  private speechEndAt: number | null = null;
  private transcriptMarked = false;
  private turnMarked = false;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private sender: Sender | null = null;

  /** Injecte l'envoi réseau (services/api) — découplé pour les tests. */
  configure(sender: Sender): void {
    this.sender = sender;
  }

  /** L'utilisateur vient de finir de parler (le VAD/endpointing a résolu). */
  markUserSpeechEnd(): void {
    this.speechEndAt = Date.now();
    this.transcriptMarked = false;
    this.turnMarked = false;
  }

  /** Le transcript de cette prise de parole est disponible. */
  markTranscriptReady(state?: string): void {
    if (this.speechEndAt === null || this.transcriptMarked) return;
    this.transcriptMarked = true;
    this.push({ kind: "stt_latency_ms", value_ms: Date.now() - this.speechEndAt, state });
  }

  /** Le premier son de la réponse AI est audible. Clôt le tour courant. */
  markAiSpeakStart(state?: string): void {
    if (this.speechEndAt === null || this.turnMarked) return;
    this.turnMarked = true;
    this.push({ kind: "turn_latency_ms", value_ms: Date.now() - this.speechEndAt, state });
    this.speechEndAt = null;
  }

  counter(kind: CounterKind, state?: string): void {
    this.push({ kind, count: 1, state });
  }

  latency(kind: LatencyKind, valueMs: number, state?: string): void {
    if (!Number.isFinite(valueMs) || valueMs < 0) return;
    this.push({ kind, value_ms: Math.round(valueMs), state });
  }

  private push(event: MetricEvent): void {
    if (this.buffer.length >= MAX_BUFFER) this.buffer.shift();
    this.buffer.push(event);
  }

  pendingCount(): number {
    return this.buffer.length;
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0 || !this.sender) return;
    // Draine TOUT le buffer en lots de 50 (M-P3 : un flush mono-lot laissait
    // le reste coincé jusqu'à la session suivante).
    while (this.buffer.length > 0) {
      const batch = this.buffer.splice(0, 50);
      try {
        await this.sender(batch);
      } catch {
        // no-op légitime : télémétrie best-effort — jamais de retry, jamais de bruit UX
        return;
      }
    }
  }

  /** Démarre le flush périodique (session active). */
  startSession(): void {
    if (this.flushTimer) return;
    this.flushTimer = setInterval(() => {
      this.flush().catch(() => {}); // no-op légitime : télémétrie best-effort
    }, FLUSH_INTERVAL_MS);
  }

  /** Fin de session : flush final + arrêt du timer. */
  endSession(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    this.speechEndAt = null;
    this.flush().catch(() => {}); // no-op légitime : télémétrie best-effort
  }
}

export const voiceMetrics = new VoiceMetricsCollector();
