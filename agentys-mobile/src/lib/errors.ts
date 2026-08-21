/**
 * errors — politique « loud failure » du mobile Agentys.
 *
 * Phase 1 du chantier fondations (tech-spec-mobile-foundations-refactor §1.1).
 * Règle unique : AUCUNE erreur ne meurt en silence. Chaque catch route vers
 * reportError(), qui (a) trace dans le ring buffer (eventLog), (b) trace vers
 * os_log (visible en Release via NSLog), (c) décide d'une représentation
 * utilisateur selon le domaine, (d) relaiera vers Sentry quand il sera branché
 * (sink enregistrable).
 *
 * ═══ RÈGLE D'OR — JAMAIS DE DONNÉE FABRIQUÉE ═══
 * Ne JAMAIS inventer une valeur pour satisfaire un type ou « continuer quand
 * même » : le draft_id fabriqué `ws-${Date.now()}` a produit des POST
 * /pending-drafts/ws-…/validate → 404 silencieux → « l'envoi ne marche pas »
 * (retour device 2026-07-11). Si une valeur requise manque : reportError +
 * chemin d'échec EXPLICITE (return early, état d'erreur, toast) — pas de
 * placeholder plausible.
 *
 * ═══ CONVENTION no-op légitimes ═══
 * Deux formes acceptées sans reportError :
 *  1. `Haptics.*(...).catch(() => {})` — feedback haptique best-effort,
 *     échec sans conséquence fonctionnelle (pattern reconnu tel quel).
 *  2. un catch portant le commentaire « no-op légitime : <raison> » (rien à
 *     faire) ou « fallback légitime : <raison> » (valeur dégradée documentée)
 *     — toute autre exception avalée DOIT être justifiée ainsi.
 * Le critère de sortie Phase 1 : aucun catch muet hors ces deux formes.
 *
 * ⚠️ PIÈGE : lib.dom déclare un `reportError(e)` GLOBAL à 1 argument. Un
 * appel sans import compile (en 1-arg) mais part dans le void DOM au lieu
 * de ce module — TOUJOURS vérifier l'import lors d'une migration.
 *
 * Contexte des erreurs historiques que ce module aurait rendues visibles :
 * 99 catch muets recensés le 2026-07-15, tap fin-de-dictée en no-op invisible,
 * transcripts vides en boucle sans aucun signal utilisateur.
 */

import { toast } from "./toast";
import { logEvent } from "./eventLog";
import * as AgentysAudio from "../../modules/agentys-audio";

export type ErrorDomain = "audio" | "stt" | "api" | "state" | "tts" | "unknown";

export interface ErrorContext {
  domain: ErrorDomain;
  /** Opération en cours, ex. "transcribe", "createAsync", "approveDraft". */
  op: string;
  /** État drive courant si pertinent (pour corréler avec les transitions). */
  state?: string;
  extra?: Record<string, unknown>;
}

export type UserFacing = "toast" | "earcon" | "silent";

export interface ReportOptions {
  /** Représentation utilisateur. Défaut par domaine :
   *  api/stt/tts → toast ; audio/state → earcon ; unknown → silent. */
  userFacing?: UserFacing;
  /** Message du toast (défaut générique par domaine). */
  toastMessage?: string;
}

// Les earcons vivent dans un hook React (useEarcons) — un module plain ne
// peut pas les jouer directement. Le drive enregistre son player au mount.
let earconPlayer: ((name: "alert") => void) | null = null;

export function registerErrorEarcon(play: (name: "alert") => void): void {
  earconPlayer = play;
}

export function unregisterErrorEarcon(): void {
  earconPlayer = null;
}

// Sink additionnel (Sentry, étape 1.4) — enregistrable sans dépendance dure.
let externalSink: ((err: unknown, ctx: ErrorContext) => void) | null = null;

export function registerErrorSink(sink: (err: unknown, ctx: ErrorContext) => void): void {
  externalSink = sink;
}

const DEFAULT_USER_FACING: Record<ErrorDomain, UserFacing> = {
  api: "toast",
  stt: "toast",
  tts: "toast",
  audio: "earcon",
  state: "earcon",
  unknown: "silent",
};

const DEFAULT_TOAST: Record<ErrorDomain, string> = {
  api: "Problème réseau — réessaie",
  stt: "Je n'ai pas pu te transcrire — réessaie",
  tts: "Lecture vocale indisponible",
  audio: "Problème micro/audio",
  state: "Petit couac — réessaie",
  unknown: "Erreur inattendue",
};

function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  return String(err);
}

/**
 * Route une erreur : ring buffer + os_log + UI selon le domaine.
 * Ne throw JAMAIS — appelable depuis n'importe quel catch sans risque.
 */
export function reportError(err: unknown, ctx: ErrorContext, opts: ReportOptions = {}): void {
  try {
    const message = messageOf(err);

    logEvent("error", {
      domain: ctx.domain,
      op: ctx.op,
      ...(ctx.state ? { state: ctx.state } : {}),
      ...(ctx.extra ?? {}),
      message,
    });

    // os_log — seul canal visible en Release (console.log Hermes ne l'est pas).
    try {
      AgentysAudio.debugLog(`ERROR ${ctx.domain}/${ctx.op} ${ctx.state ?? ""} ${message}`);
    } catch { /* no-op légitime : module natif absent (Expo Go) */ }

    if (__DEV__) {
      console.warn(`[reportError] ${ctx.domain}/${ctx.op}:`, err);
    }

    try {
      externalSink?.(err, ctx);
    } catch { /* no-op légitime : un sink cassé ne doit pas masquer l'erreur d'origine */ }

    const facing = opts.userFacing ?? DEFAULT_USER_FACING[ctx.domain];
    if (facing === "toast") {
      toast.warning(opts.toastMessage ?? DEFAULT_TOAST[ctx.domain]);
    } else if (facing === "earcon") {
      try {
        earconPlayer?.("alert");
      } catch { /* no-op légitime : earcon best-effort */ }
    }
  } catch {
    // Dernier filet : le reporting lui-même ne casse jamais l'appelant.
  }
}
