/**
 * eventLog — ring buffer structuré des événements de session.
 *
 * Phase 1 du chantier fondations (tech-spec-mobile-foundations-refactor §1.2).
 * Pourquoi : en Release, console.log est invisible et chaque bug device
 * coûtait un cycle rebuild-instrumenter-reproduire (~30 min). Ce buffer garde
 * les EVENT_LOG_CAPACITY derniers événements (transitions d'état, erreurs,
 * résultats STT, changements audio, appels API) en mémoire, exportables en
 * 2 taps depuis Réglages → Diagnostic. Le prochain bug = lire un dump.
 *
 * Module-level (pas de React) : appelable depuis n'importe quel code, y
 * compris les callbacks natifs et les fonctions hors composants. Best-effort
 * intégral — le logging ne doit JAMAIS casser le flux qu'il observe.
 */

export type EventKind = "transition" | "error" | "stt" | "audio" | "api" | "watchdog" | "tts";

export interface LoggedEvent {
  /** Epoch ms. */
  ts: number;
  kind: EventKind;
  data: Record<string, unknown>;
}

export const EVENT_LOG_CAPACITY = 500;

let buffer: LoggedEvent[] = [];

// Miroir os_log (feedback loop live 2026-07-28) : chaque événement du ring
// buffer part aussi en NSLog [drive-dbg] via le module natif — visible en
// direct par `devicectl --console` sans attendre un dump Diagnostic. Les
// listens/meters natifs y sont déjà ; avec ce miroir la trace câble raconte
// TOUT le dialogue (transitions, stt, tts, earcons). Lazy require : pas de
// cycle d'import, no-op silencieux si le module natif est absent (jest).
let nativeDebugLog: ((msg: string) => void) | null | undefined;

/** Enregistre un événement. Ne throw jamais (best-effort). */
export function logEvent(kind: EventKind, data: Record<string, unknown>): void {
  try {
    buffer.push({ ts: Date.now(), kind, data });
    if (nativeDebugLog === undefined) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const mod = require("../../modules/agentys-audio");
        nativeDebugLog = mod?.NATIVE_AVAILABLE ? mod.debugLog : null;
      } catch { nativeDebugLog = null; }
    }
    if (nativeDebugLog) {
      try { nativeDebugLog(`evt ${kind} ${JSON.stringify(data)}`); } catch { /* no-op légitime : miroir best-effort */ }
    }
    if (buffer.length > EVENT_LOG_CAPACITY) {
      buffer = buffer.slice(buffer.length - EVENT_LOG_CAPACITY);
    }
  } catch {
    // no-op légitime : le logging ne doit jamais casser le flux observé.
  }
}

/** Les N événements les plus récents, du plus ancien au plus récent. */
export function getRecentEvents(count: number): LoggedEvent[] {
  return buffer.slice(-count);
}

/** Dump JSON-lines chronologique (une ligne par événement), pour export. */
export function dumpEvents(): string {
  return buffer
    .map((e) => {
      try {
        return JSON.stringify(e);
      } catch {
        // Data non sérialisable (référence circulaire…) : on garde la trace
        // avec un marqueur plutôt que de perdre la ligne.
        return JSON.stringify({ ts: e.ts, kind: e.kind, data: "<non-serializable>" });
      }
    })
    .join("\n");
}

export function clearEvents(): void {
  buffer = [];
}
