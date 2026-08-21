/**
 * fakeSttPipeline — harnais d'injection de fautes STT (Phase 2 fondations §2.1).
 *
 * Remplace le pipeline capture→transcription réel (useVoiceDictation +
 * transcribeAudio) par un pipeline SCRIPTABLE : chaque tour d'écoute consomme
 * un `ScriptedTurn` (transcript, vide, no_voice, erreur, gel), avec latences
 * configurables — l'outil qui reproduit EN JEST les courses et pannes qui
 * coûtaient un build device par hypothèse :
 *   - transcript en vol qui rebascule confirming→listening (bug 2026-07-11)
 *   - homophone « Envoyé. » (bug 2026-07-12)
 *   - boucle de transcripts vides (bug 2026-07-13/16)
 *
 * Usage dans un test :
 *   jest.mock("../../src/hooks/useVoiceDictation", () =>
 *     require("../support/fakeSttPipeline").fakeDictationModule());
 *   // + brancher fakeTranscribe sur le mock de services/api.transcribeAudio
 *   scriptStt([
 *     { kind: "ok", transcript: "Répondre." },
 *     { kind: "ok", transcript: "je confirme pour demain" },
 *     { kind: "ok", transcript: "Envoyé.", transcribeMs: 400 },
 *   ]);
 */

import type { ListenOptions, ListenResult, UseVoiceDictation } from "../../src/hooks/useVoiceDictation";

export type ScriptedTurn =
  | { kind: "ok"; transcript: string; listenMs?: number; transcribeMs?: number }
  | { kind: "no_voice"; listenMs?: number }
  | { kind: "cancelled"; listenMs?: number }
  | { kind: "error"; error: string; listenMs?: number }
  /** La capture ne se résout JAMAIS (recorder gelé) — seuls cancel()/flush()
   *  la terminent. Reproduit la classe « mic figé » de #1134. */
  | { kind: "hang" };

const DEFAULT_LISTEN_MS = 15;
const DEFAULT_TRANSCRIBE_MS = 15;

let queue: ScriptedTurn[] = [];
let uriSeq = 0;
const transcriptByUri = new Map<string, { text: string; delayMs: number }>();

/** Journal des tours consommés — pour les assertions d'ordre. */
export const consumedTurns: ScriptedTurn[] = [];

/** (Re)programme le scénario. À appeler en début de test. */
export function scriptStt(turns: ScriptedTurn[]): void {
  queue = [...turns];
  consumedTurns.length = 0;
  transcriptByUri.clear();
  uriSeq = 0;
}

/** Tours non consommés (assertion de fin de test). */
export function remainingTurns(): number {
  return queue.length;
}

/** Teardown : vide le script et résout toute capture en vol (cancelled).
 *  À appeler en afterEach — sans ça, les promesses en vol résolvent APRÈS
 *  le démontage de l'environnement jest (crash Animated undefined). */
export function drainStt(): void {
  queue = [];
  const finish = currentFinish;
  currentFinish = null;
  currentTurn = null;
  finish?.({ kind: "cancelled" });
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// État de la capture en cours (single-flight, comme le vrai recorder).
let currentFinish: ((r: ListenResult) => void) | null = null;
let currentTurn: ScriptedTurn | null = null;

function registerUri(text: string, delayMs: number): string {
  const uri = `fake-stt://${++uriSeq}`;
  transcriptByUri.set(uri, { text, delayMs });
  return uri;
}

/** Implémentation scriptée de UseVoiceDictation. */
export function makeFakeDictation(): UseVoiceDictation {
  return {
    state: "idle",
    listen: async (_opts?: ListenOptions): Promise<ListenResult> => {
      // Single-flight comme le vrai recorder : un listen() pendant qu'un
      // autre est en vol annule le précédent (cleanup du hook réel).
      if (currentFinish) {
        const prev = currentFinish;
        currentFinish = null;
        currentTurn = null;
        prev({ kind: "cancelled" });
      }
      const turn = queue.shift();
      if (!turn) {
        // Script épuisé : no_voice lent — n'alimente plus la machine mais ne
        // gèle pas la Promise (le drive re-listen tranquillement).
        await sleep(50);
        return { kind: "no_voice" };
      }
      consumedTurns.push(turn);
      currentTurn = turn;

      if (turn.kind === "hang") {
        return new Promise<ListenResult>((resolve) => {
          currentFinish = resolve;
        });
      }

      const listenMs = turn.listenMs ?? DEFAULT_LISTEN_MS;
      const result = await new Promise<ListenResult>((resolve) => {
        currentFinish = resolve;
        setTimeout(() => {
          if (currentFinish !== resolve) return; // cancel/flush a déjà tranché
          currentFinish = null;
          if (turn.kind === "ok") {
            resolve({ kind: "ok", uri: registerUri(turn.transcript, turn.transcribeMs ?? DEFAULT_TRANSCRIBE_MS) });
          } else if (turn.kind === "no_voice") {
            resolve({ kind: "no_voice" });
          } else if (turn.kind === "cancelled") {
            resolve({ kind: "cancelled" });
          } else {
            resolve({ kind: "error", error: (turn as { error: string }).error });
          }
        }, listenMs);
      });
      currentTurn = null;
      return result;
    },
    cancel: async () => {
      const finish = currentFinish;
      currentFinish = null;
      currentTurn = null;
      finish?.({ kind: "cancelled" });
    },
    flush: () => {
      const finish = currentFinish;
      if (!finish) return false;
      currentFinish = null;
      const turn = currentTurn;
      currentTurn = null;
      // flush conserve l'audio : si le tour portait un transcript, il part
      // en transcription ; sinon la capture n'avait rien → cancelled.
      if (turn && turn.kind === "ok") {
        finish({ kind: "ok", uri: registerUri(turn.transcript, turn.transcribeMs ?? DEFAULT_TRANSCRIBE_MS) });
      } else {
        finish({ kind: "cancelled" });
      }
      return true;
    },
  };
}

/** Factory pour jest.mock du module useVoiceDictation. */
export function fakeDictationModule() {
  return { useVoiceDictation: () => makeFakeDictation() };
}

/** Remplaçant scripté de services/api.transcribeAudio. */
export async function fakeTranscribe(uri: string): Promise<{ text: string }> {
  const entry = transcriptByUri.get(uri);
  if (!entry) return { text: "" };
  await sleep(entry.delayMs);
  return { text: entry.text };
}
