/**
 * driveReducer — état central de la machine Drive Mode (#1124, étape 2).
 *
 * Remplace les useState éparpillés + refs miroirs de useDriveMode. Le hook
 * wrappe dispatch pour mettre à jour une ref UNIQUE de façon SYNCHRONE
 * (certains flux — enqueueEmail, handleVoiceInput — lisent l'état juste
 * après l'avoir écrit, avant le re-render React).
 *
 * Reducer PUR : aucune API, aucun timer — les effets restent dans le hook.
 */

import type { DriveState, ReplyMode, SpeakableEmail, Email , SessionStats } from "../types";

export interface DriveCore {
  state: DriveState;
  emails: Email[];
  currentIndex: number;
  currentEmail: SpeakableEmail | null;
  replyMode: ReplyMode | null;
  draftContent: string | null;
  draftId: string | null;
  /** P2.4 : buffer de dictée DANS le contexte machine (sérialisable, tracé
   *  avec les transitions) — plus une ref de coordination éparpillée. */
  dictationBuffer: string[];
  /** P2.4b : flags de coordination (ex-refs). Sémantique inchangée — mis à
   *  jour hors transitions via setCoreFlag, lus par coreRef.current.<flag>. */
  silenceNudged: boolean;
  voiceCaptureActive: boolean;
  idleListeningActive: boolean;
  streamingActive: boolean;
  /** P2.4c : compteurs de session (ex-sessionStatsRef). */
  sessionStats: SessionStats;
}

export const INITIAL_DRIVE_CORE: DriveCore = {
  state: "idle",
  emails: [],
  currentIndex: 0,
  currentEmail: null,
  replyMode: null,
  draftContent: null,
  draftId: null,
  dictationBuffer: [],
  silenceNudged: false,
  voiceCaptureActive: false,
  idleListeningActive: false,
  streamingActive: false,
  sessionStats: {
    started: 0, totalEmails: 0, replied: 0,
    approved: 0, skipped: 0, archived: 0, deleted: 0,
  },
};

export type DriveAction =
  /** Transition d'état de la machine vocale (idle/speaking/choosing/…). */
  | { type: "SET_STATE"; state: DriveState }
  /** Nouvelle liste de session (start/restore). Réinitialise l'index si fourni. */
  | { type: "SET_EMAILS"; emails: Email[]; index?: number }
  /** Navigation : index courant dans la liste. */
  | { type: "SET_INDEX"; index: number }
  /** Contenu speakable de l'email courant (null entre deux lectures). */
  | { type: "SET_CURRENT_EMAIL"; email: SpeakableEmail | null }
  /** Mode de réponse choisi (reply/reply_all/forward) ou null. */
  | { type: "SET_REPLY_MODE"; mode: ReplyMode | null }
  /** Draft généré/modifié/effacé — point unique (ex-updateDraft). */
  | { type: "SET_DRAFT"; content: string | null; id: string | null };

export function driveReducer(core: DriveCore, action: DriveAction): DriveCore {
  switch (action.type) {
    case "SET_STATE":
      return { ...core, state: action.state };
    case "SET_EMAILS":
      return {
        ...core,
        emails: action.emails,
        ...(action.index !== undefined ? { currentIndex: action.index } : {}),
      };
    case "SET_INDEX":
      return { ...core, currentIndex: action.index };
    case "SET_CURRENT_EMAIL":
      return { ...core, currentEmail: action.email };
    case "SET_REPLY_MODE":
      return { ...core, replyMode: action.mode };
    case "SET_DRAFT":
      return { ...core, draftContent: action.content, draftId: action.id };
    default:
      return core;
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Machine à états explicite (Phase 2 fondations §2.2)
//
// Pourquoi : les ~76 `setState("…")` éparpillés dans 6 hooks rendaient les
// transitions ÉMERGENTES — la course « transcript en vol » (2026-07-11) et le
// badge qui flashe sans action n'étaient possibles que parce que n'importe
// quel code pouvait poser n'importe quel état à n'importe quel moment.
// Ici : les transitions légales sont une TABLE. Un événement illégal dans un
// état ne s'exécute pas — il est signalé (le wrapper dispatch du hook fait le
// reportError, ce module reste PUR).
//
// Migration (§2.3) : les surfaces passent une à une de setState() à
// dispatchEvent() — SET_STATE reste disponible pendant la transition et sera
// retiré à la fin.
// ═══════════════════════════════════════════════════════════════════════════

export type DriveEvent =
  /** Démarrage de session (emails chargés par l'appelant). */
  | { type: "SESSION_START" }
  /** Navigation vers un email (next/previous/archive/delete → lecture). */
  | { type: "EMAIL_LOAD" }
  /** Speakable prêt → lecture TTS. */
  | { type: "EMAIL_LOADED" }
  /** Fin de lecture TTS. `next` module la cible (brouillon existant → asking_send). */
  | { type: "TTS_DONE"; next?: "choosing" | "asking_send" | "asking_preview" | "reviewing" }
  /** Prise de parole IA (lecture email/brouillon/annonce) → speaking. */
  | { type: "SPEAK" }
  /** « répondre / répondre à tous / transférer » accepté → dictée. */
  | { type: "REPLY_CHOSEN" }
  /** Fin de dictée (tap « c'est fini » ou silence) → confirmation. */
  | { type: "DICTATION_FINISHED" }
  /** Annulation de la réponse en cours → retour au menu. */
  | { type: "DICTATION_CANCELLED" }
  /** Lancement de la génération de brouillon. */
  | { type: "GENERATE" }
  /** Brouillon prêt. autoSend → fenêtre d'annulation, sinon proposition d'écoute. */
  | { type: "DRAFT_READY"; autoSend: boolean }
  /** Échec de génération. */
  | { type: "DRAFT_FAILED" }
  /** Envoi différé armé (act-then-undo). */
  | { type: "SEND_SCHEDULED" }
  /** Fenêtre d'annulation consommée (annulé) → retour interactif. */
  | { type: "SEND_CANCELLED" }
  /** Relecture du brouillon demandée. */
  | { type: "REVIEW" }
  /** Pause / reprise / fin de session / arrêt. */
  | { type: "PAUSE" }
  | { type: "RESUME" }
  | { type: "SESSION_END" }
  | { type: "RESET" }
  /** Erreur fatale de flux. */
  | { type: "FLOW_ERROR" }
  /** Récupération vers un état interactif (filet anti-impasse M-P1d). */
  | { type: "RECOVER"; to: "choosing" | "listening" | "asking_send" | "asking_preview" | "reviewing" };

/** Cible d'une transition — statique ou dérivée de l'événement. */
type Target = DriveState | ((core: DriveCore, ev: DriveEvent) => DriveState);

/** Table des transitions LÉGALES : tout couple absent est un rejet bruyant. */
export const DRIVE_TRANSITIONS: Partial<Record<DriveState, Partial<Record<DriveEvent["type"], Target>>>> = {
  idle: {
    SESSION_START: "loading",
    /** startSession ne pose pas d'état : c'est readEmailAtIndex qui ouvre. */
    EMAIL_LOAD: "loading",
    /** reset() depuis idle (stopIdleSTT, gardes) — idempotent. */
    RESET: "idle",
  },
  loading: {
    /** next/previous enchaînés pendant un chargement — self-loop. */
    EMAIL_LOAD: "loading",
    EMAIL_LOADED: "speaking",
    SESSION_END: "completed",
    FLOW_ERROR: "error",
    RESET: "idle",
  },
  speaking: {
    TTS_DONE: (_c, ev) => (ev.type === "TTS_DONE" && ev.next) || "choosing",
    SPEAK: "speaking",
    SEND_SCHEDULED: "undo_window",
    REVIEW: "reviewing",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
    REPLY_CHOSEN: "listening",
    EMAIL_LOAD: "loading",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
  },
  choosing: {
    SPEAK: "speaking",
    REPLY_CHOSEN: "listening",
    EMAIL_LOAD: "loading",
    GENERATE: "generating",
    SEND_SCHEDULED: "undo_window",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
  listening: {
    SPEAK: "speaking",
    DICTATION_FINISHED: "confirming_dictation",
    DICTATION_CANCELLED: "choosing",
    GENERATE: "generating",
    EMAIL_LOAD: "loading",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
  confirming_dictation: {
    SPEAK: "speaking",
    GENERATE: "generating",
    SEND_SCHEDULED: "undo_window",
    DICTATION_CANCELLED: "choosing",
    /** Contenu supplémentaire dicté → retour en dictée. */
    REPLY_CHOSEN: "listening",
    EMAIL_LOAD: "loading",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
  },
  generating: {
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
    /** Flux réel (surface 3) : sans autoSend le brouillon est LU (auto-read
     *  F5) — speaking, puis TTS_DONE{asking_send}. asking_preview reste le
     *  chemin des brouillons PRÉ-existants (lecture email). */
    DRAFT_READY: (_c, ev) => (ev.type === "DRAFT_READY" && ev.autoSend ? "undo_window" : "speaking"),
    /** applyModify : brouillon modifié → relecture/validation. */
    REVIEW: "reviewing",
    SPEAK: "speaking",
    SEND_SCHEDULED: "undo_window",
    DRAFT_FAILED: "error",
    DICTATION_CANCELLED: "choosing",
    RESET: "idle",
    SESSION_END: "completed",
  },
  asking_preview: {
    SPEAK: "speaking",
    TTS_DONE: (_c, ev) => (ev.type === "TTS_DONE" && ev.next) || "asking_send",
    SEND_SCHEDULED: "undo_window",
    EMAIL_LOAD: "loading",
    REPLY_CHOSEN: "listening",
    DICTATION_CANCELLED: "choosing",
    REVIEW: "reviewing",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
  asking_send: {
    SPEAK: "speaking",
    SEND_SCHEDULED: "undo_window",
    REVIEW: "reviewing",
    REPLY_CHOSEN: "listening",
    DICTATION_CANCELLED: "choosing",
    EMAIL_LOAD: "loading",
    TTS_DONE: (_c, ev) => (ev.type === "TTS_DONE" && ev.next) || "asking_send",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
  reviewing: {
    SPEAK: "speaking",
    REVIEW: "reviewing",
    GENERATE: "generating",
    SEND_SCHEDULED: "undo_window",
    REPLY_CHOSEN: "listening",
    DICTATION_CANCELLED: "choosing",
    EMAIL_LOAD: "loading",
    SESSION_END: "completed",
    PAUSE: "paused",
    RESET: "idle",
    FLOW_ERROR: "error",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
  undo_window: {
    /** Annulation d'envoi : l'utilisateur récupère le BROUILLON (reviewing),
     *  pas le menu — surface 3, flux cancelPendingSend réel. */
    SEND_CANCELLED: "reviewing",
    EMAIL_LOAD: "loading",
    SESSION_END: "completed",
    RESET: "idle",
    FLOW_ERROR: "error",
  },
  paused: {
    RESUME: "loading",
    /** resumeSession passe par readEmailAtIndex — équivalent RESUME. */
    EMAIL_LOAD: "loading",
    RESET: "idle",
    SESSION_END: "completed",
  },
  completed: {
    SESSION_START: "loading",
    RESET: "idle",
  },
  error: {
    SESSION_START: "loading",
    EMAIL_LOAD: "loading",
    RESET: "idle",
    RECOVER: (_c, ev) => (ev.type === "RECOVER" ? ev.to : "choosing"),
  },
};

export interface TransitionOutcome {
  core: DriveCore;
  /** false ⇔ événement illégal dans cet état — le wrapper du hook signale. */
  accepted: boolean;
  /** P2.5 : accusé visuel (badge « ✓ commande »). Présent UNIQUEMENT si la
   *  transition est acceptée ET qu'un label a été fourni — une commande
   *  reconnue mais rejetée par la machine ne flashe jamais. */
  feedback?: { flash: string };
}

/** Applique un événement selon la table. PUR — le rejet est signalé par
 *  l'appelant (dispatch wrapper → reportError), jamais exécuté par défaut. */
export function driveTransition(core: DriveCore, event: DriveEvent, flash?: string): TransitionOutcome {
  const target = DRIVE_TRANSITIONS[core.state]?.[event.type];
  if (target === undefined) {
    return { core, accepted: false };
  }
  const nextState = typeof target === "function" ? target(core, event) : target;
  return {
    core: { ...core, state: nextState },
    accepted: true,
    ...(flash ? { feedback: { flash } } : {}),
  };
}

// ── P2.4 : mutateurs purs du contexte (hors transitions d'état) ─────────────
// Les sites appellent `coreRef.current = pushDictation(coreRef.current, t)` :
// même sémantique qu'avant (les transitions ne touchent PAS au buffer), mais
// le contenu vit dans le core → visible dans les dumps et les logs.

export function pushDictation(core: DriveCore, text: string): DriveCore {
  return { ...core, dictationBuffer: [...core.dictationBuffer, text] };
}

export function clearDictation(core: DriveCore): DriveCore {
  return core.dictationBuffer.length === 0 ? core : { ...core, dictationBuffer: [] };
}

export type CoreFlag = "silenceNudged" | "voiceCaptureActive" | "idleListeningActive" | "streamingActive";

export function setCoreFlag(core: DriveCore, flag: CoreFlag, value: boolean): DriveCore {
  return core[flag] === value ? core : { ...core, [flag]: value };
}

export type StatCounter = Exclude<keyof SessionStats, "started">;

/** Incrémente (delta ±1 typiquement) un compteur de session. */
export function bumpStat(core: DriveCore, stat: StatCounter, delta: number = 1): DriveCore {
  return { ...core, sessionStats: { ...core.sessionStats, [stat]: core.sessionStats[stat] + delta } };
}

export function resetStats(core: DriveCore, totalEmails: number, startedAt: number): DriveCore {
  return { ...core, sessionStats: {
    started: startedAt, totalEmails, replied: 0,
    approved: 0, skipped: 0, archived: 0, deleted: 0,
  } };
}
