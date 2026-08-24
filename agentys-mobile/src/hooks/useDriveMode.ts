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
 * State machine pour le mode conduite.
 *
 * États :
 *   idle → loading → speaking → choosing → listening
 *   → confirming_dictation → generating
 *   → asking_preview → asking_send → (send) → next email
 *   → reviewing (modification manuelle)
 *   → paused / completed / error
 *
 * Commandes vocales disponibles dans tous les modes :
 *   répondre / suivant / précédent / répéter / archiver / supprimer / pause / stop
 */

import { useState, useCallback, useReducer, useRef, useEffect } from "react";
import { Animated } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Haptics from "expo-haptics";
import {
  postVoiceMetrics,
} from "../services/api";
import { useVoiceDictation } from "./useVoiceDictation";
import { useAudioLevelEnvelope } from "./useAudioLevelEnvelope";
import { useVoiceRouter } from "./useVoiceRouter";
import { useDraftFlow } from "./useDraftFlow";
import { useDriveSession } from "./useDriveSession";
import { useDriveVoiceIO } from "./useDriveVoiceIO";
import { useStreamingStt } from "./useStreamingStt";
import { useDeepgramDirect } from "./useDeepgramDirect";
import { useTts } from "./useTts";
import { useEarcons } from "./useEarcons";
import { useWatchdog } from "./useWatchdog";
import { registerErrorEarcon, unregisterErrorEarcon, reportError } from "../lib/errors";
import { toast } from "../lib/toast";
import {
  driveReducer,
  bumpStat,
  setCoreFlag,
  driveTransition,
  INITIAL_DRIVE_CORE,
  type DriveAction,
  type DriveCore,
  type DriveEvent,
} from "./driveReducer";
import type { SpokenAck } from "../lib/driveCommands";
import { logEvent } from "../lib/eventLog";
import { PendingActionManager } from "../lib/pendingActions";
import { voiceMetrics } from "../lib/voiceMetrics";
import i18n from "../i18n";
import type { DriveState, ReplyMode, SpeakableEmail, Email, SessionStats, SessionMode } from "../types";

/** Helper for TTS strings inside this hook — always reads the current i18n
 *  language so switching language updates future prompts. */
const dt = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "drive", ...(opts ?? {}) }) as string;

// ---------------------------------------------------------------------------
// STT pipeline — Deepgram nova-3 via backend (cohérent avec la webapp).
//
// Avant : on utilisait `expo-speech-recognition` (Siri on-device sur iOS)
// avec un check `NativeModules.ExpoSpeechRecognition` qui était CASSÉ —
// la lib v3 s'enregistre via la nouvelle API `requireNativeModule` d'Expo
// et n'apparaît pas dans `NativeModules`. STT silencieusement non-fonctionnel.
//
// Maintenant : `useVoiceDictation` (expo-av + VAD) enregistre l'audio,
// puis `transcribeAudio` (POST /api/transcribe) appelle Deepgram nova-3
// côté backend (fallback OpenAI whisper-1). Latence ~500-1000ms post-silence,
// même chemin que la webapp et compose.tsx.
// ---------------------------------------------------------------------------

// Détection de commandes vocales : extraite vers src/lib/driveCommands.ts
// (#1124). Ré-exportée ici pour compat des imports existants (tests).
export { extractSendDisposition } from "../lib/driveCommands";

export interface DriveMode {
  state:              DriveState;
  replyMode:          ReplyMode | null;
  currentEmail:       SpeakableEmail | null;
  emails:             Email[];
  currentIndex:       number;
  draftContent:       string | null;
  error:              string | null;
  isListening:        boolean;
  /** True pendant la ~1s de transcription backend (VAD terminé, transcript pas encore là). */
  isTranscribing:     boolean;
  transcript:         string;
  commandRecognized:  string | null;
  sessionStats:       SessionStats | null;
  queuedCount:        number;
  /** Temps écoulé en ms depuis le début de la génération de brouillon
   *  (mis à jour ~toutes les 1.5s via le polling). 0 quand pas en générant.
   *  Affiché dans la StatusPill pour rassurer l'user que le système avance. */
  generatingElapsedMs: number;
  pendingResume:      { emailCount: number; currentIndex: number } | null;
  startSession:       (emails: Email[], mode?: SessionMode) => Promise<void>;
  resumeSession:      () => void;
  enqueueEmail:       (email: Email) => void;
  next:               () => void;
  previous:           () => void;
  chooseReply:        (mode: ReplyMode) => void;
  /** Fin de dictée par tap : passe en confirming_dictation (earcon « à toi »)
   *  sans attendre le timer de silence. No-op si le buffer est vide. */
  finishDictation:    () => void;
  /** Approve contextuel : lit le draft si asking_preview, draft si confirming, envoie sinon. */
  approveContextual:  () => Promise<void>;
  approveDraftAndNext: () => Promise<void>;
  rejectAndRelisten:  () => void;
  archiveAndNext:     () => Promise<void>;
  deleteAndNext:      () => Promise<void>;
  reset:              () => void;
  dismissResume:      () => void;
  /** STT disponible sur cet appareil (nécessite un dev build). */
  sttAvailable:       boolean;
  /** Écoute vocale en mode idle pour sélection du mode. */
  idleListening:      boolean;
  /** Démarre l'écoute idle : reconnaît "actions"/"infos"/"les deux" et appelle onMode. */
  startIdleSTT:       (onMode: (mode: SessionMode) => void) => void;
  /** Arrête l'écoute idle. */
  stopIdleSTT:        () => void;
  /** Reset avec annonce brève « Session interrompue ». Non bloquant : la voix
   *  survit à la transition vers le home (pas d'agressivité UX). */
  stopWithFarewell:   () => void;
  /** Niveau audio normalisé 0..1 — alimenté par STT volumechange quand
   *  l'utilisateur parle, et par une enveloppe simulée quand TTS lit.
   *  Utilisé par VoiceVisualizer pour animer les rubans en temps réel. */
  audioLevel:         Animated.Value;
  /** État du TTS en cours — utilisé pour activer le tap-to-interrupt sur le player. */
  ttsState:           "idle" | "loading" | "speaking" | "paused" | "error";
  /** Tap pendant lecture : stop TTS + ouvre le mic pour commande vocale.
   *  Fallback manuel du barge-in vocal natif. No-op si rien ne joue. */
  interruptAndListen: () => Promise<void>;
  /** Nombre d'actions différées encore annulables (archive/delete/envoi).
   *  > 0 → afficher le chip « Annuler » (escape hatch sans STT). */
  pendingActionCount: number;
  /** Annule la dernière action différée (tap du chip). Latency-proof. */
  undoLastAction: () => void;
  /** true ⇔ aucun progrès depuis 12 s dans un état actif — bandeau visible. */
  watchdogStalled: boolean;
  /** Tap du bandeau de gel : relance l'écoute. */
  retryFromStall: () => void;
}

// F6 — 3000 → 4000ms : tolère mieux les pauses naturelles dans une phrase
// dictée ("dis-lui que je serai... [pause de réflexion] ...là à 15h"). User
// peut toujours dire "c'est tout" pour finaliser plus tôt.
const DICTATION_SILENCE_MS = 4000;
const SILENCE_FIRST_MS     = 8000;
const SILENCE_SECOND_MS    = 8000;
/** Délai max sans activité vocale en mode idle avant d'arrêter l'écoute (économie batterie). */
const IDLE_STT_TIMEOUT_MS  = 30_000;

// Step 2 — Lectures full-duplex (barge-in vocal PENDANT la lecture d'un
// brouillon). GATED OFF jusqu'à la vérif device (Step 0) : les commentaires
// aux sites de lecture (wantsDraftRead/REPEAT/asking_preview) affirment encore
// le bug iOS PlayAndRecord = sortie écouteur (TTS inaudible). Une fois
// confirmé sur un vrai iPhone que configureForVoiceChat() garde le TTS FORT,
// passer ce flag à `true` (un seul interrupteur, réversible). OFF =
// comportement actuel exact, zéro régression.
const FULL_DUPLEX_READS = false;

// Step 4 — STT streaming (Deepgram live via le proxy Socket.IO backend).
// GATED OFF jusqu'à la vérif device (Step 0) : exige un dev build avec le
// tap mic AVAudioEngine compilé (AgentysAudio.MIC_STREAM_AVAILABLE) ET la
// confirmation que configureForVoiceChat garde la TTS sur le speaker.
// ON = endpointing sémantique (plus de timers de silence), partiels live,
// barge-in <300 ms via SpeechStarted. OFF = pipeline batch actuel, zéro
// régression. Fallback batch automatique si la session streaming meurt.
const STREAMING_STT = false;

// Option C — quand le STT streaming est actif, se connecter DIRECTEMENT à
// Deepgram (useDeepgramDirect) au lieu de passer par le proxy Socket.IO /daemon
// (useStreamingStt). Le proxy ne peut PAS marcher en prod : worker gunicorn
// `gthread` sans support WebSocket → audio binaire `bytes=0`. La voie directe
// (token court mint par /api/stt/grant-token → WS direct vers Deepgram)
// contourne le runtime serveur et baisse la latence. Précond : endpoint
// /api/stt/grant-token déployé en prod.
const STREAMING_DIRECT_DEEPGRAM = true;



export function useDriveMode(): DriveMode {
  // État central de la machine (#1124 étape 2) : reducer pur + ref UNIQUE
  // synchronisée DANS le dispatch (pas en useEffect) — les flux vocaux
  // lisent l'état juste après l'avoir écrit, avant le re-render.
  const [core, dispatchCore] = useReducer(driveReducer, INITIAL_DRIVE_CORE);
  const coreRef = useRef<DriveCore>(core);
  const dispatch = useCallback((action: DriveAction) => {
    coreRef.current = driveReducer(coreRef.current, action);
    dispatchCore(action);
  }, []);

  // ── Machine à états explicite (§2.2) ─────────────────────────────────────
  // dispatchEvent : SEUL chemin de transition à terme (§2.3 migre les
  // setState un à un vers lui). Événement illégal → reportError + no-op —
  // jamais d'exécution par défaut (fin du badge qui flashe sans action).
  // Chaque transition acceptée est tracée dans le ring buffer.
  // P2.5 : label du badge « ✓ commande » posé par le routeur au parse, consommé
  // par la PREMIÈRE tentative de transition (acceptée OU rejetée) — le badge ne
  // flashe que si la machine accepte réellement l'événement.
  const pendingFlashRef = useRef<string | null>(null);
  // Pendant PARLÉ du badge (2026-08-05) : au volant l'écran n'est pas regardé,
  // donc l'accusé « compris et fait » doit s'entendre. Même règle que le flash
  // — un rejet de la machine ne doit RIEN annoncer. `spokenAckRef` est ensuite
  // consommé par le prochain `speak` du drive, qui le préfixe à son énoncé
  // (plutôt que de le dire à part : un speak isolé serait coupé net par la
  // lecture de l'email qui suit ~100 ms plus tard).
  const pendingAckRef = useRef<SpokenAck | null>(null);
  const spokenAckRef  = useRef<SpokenAck | null>(null);
  const dispatchEvent = useCallback((event: DriveEvent): boolean => {
    const from = coreRef.current.state;
    const flash = pendingFlashRef.current;
    const ack = pendingAckRef.current;
    pendingFlashRef.current = null; // consommation unique — un rejet ne flashe pas
    pendingAckRef.current = null;   // ni ne parle
    const outcome = driveTransition(coreRef.current, event, flash ?? undefined);
    if (!outcome.accepted) {
      reportError(new Error(`événement ${event.type} illégal en ${from}`), {
        domain: "state", op: "dispatchEvent", state: from,
        extra: { event: event.type },
      }, { userFacing: "silent" });
      return false;
    }
    coreRef.current = outcome.core;
    dispatchCore({ type: "SET_STATE", state: outcome.core.state });
    if (outcome.feedback) {
      setCommandRecognized(outcome.feedback.flash);
      timersRef.current.push(setTimeout(() => setCommandRecognized(null), 1000));
    }
    if (ack?.label) spokenAckRef.current = ack;
    // P2.4 : contexte compact avec chaque transition — un dump raconte la
    // session entière (position, taille du buffer de dictée, brouillon).
    logEvent("transition", {
      from, event: event.type, to: outcome.core.state,
      ctx: {
        idx: outcome.core.currentIndex,
        emails: outcome.core.emails.length,
        buf: outcome.core.dictationBuffer.length,
        draft: outcome.core.draftContent !== null,
      },
    });
    return true;
  }, []);
  const { state, replyMode, emails, currentIndex, currentEmail, draftContent } = core;
  // Shims setters : gardent les 60+ sites d'appel inchangés tout en routant
  // par le reducer (candidats à des actions sémantiques en étape 3).
  const setReplyMode    = useCallback((m: ReplyMode | null) => dispatch({ type: "SET_REPLY_MODE", mode: m }), [dispatch]);
  const setEmails       = useCallback((e: Email[]) => dispatch({ type: "SET_EMAILS", emails: e }), [dispatch]);
  const setCurrentIndex = useCallback((i: number) => dispatch({ type: "SET_INDEX", index: i }), [dispatch]);
  const setCurrentEmail = useCallback((e: SpeakableEmail | null) => dispatch({ type: "SET_CURRENT_EMAIL", email: e }), [dispatch]);

  const [error,             setError]            = useState<string | null>(null);
  const [isListening,       setIsListening]      = useState(false);
  const [isTranscribing,    setIsTranscribing]   = useState(false);
  const [transcript,        setTranscript]       = useState("");
  const [commandRecognized, setCommandRecognized] = useState<string | null>(null);
  const [sessionStats,      setSessionStats]     = useState<SessionStats | null>(null);
  const [pendingResume,     setPendingResume]    = useState<{ emailCount: number; currentIndex: number } | null>(null);
  const [queuedCount,       setQueuedCount]      = useState(0);
  const [idleListening,     setIdleListening]    = useState(false);
  // Compteur d'attente affiché dans la StatusPill pendant generating.
  // Permet à l'user de voir que le système travaille (vs. l'impression de blocage).
  const [generatingElapsedMs, setGeneratingElapsedMs] = useState(0);

  // Core refs
  const speechRateRef     = useRef(1.0);
  const timersRef         = useRef<ReturnType<typeof setTimeout>[]>([]);
  // Écran encore monté ? Purger `timersRef` au démontage ne suffit PAS : une
  // promesse en vol (`dictation.listen()`, un speak, un fetch) se résout APRÈS
  // le démontage et planifie alors un NOUVEAU timer, que le nettoyage a déjà
  // manqué. En prod ça ré-arme le micro 500 ms après qu'on ait quitté l'écran
  // drive ; en test ça fait tomber le worker Jest (environnement détruit).
  const isMountedRef      = useRef(true);

  // Prefetch dedup : on warm le cache TTS pour l'email N+1 pendant qu'on lit
  // l'email N. Stocké ici pour ne pas refetch si l'user revient en arrière.
  const prefetchedIdsRef         = useRef<Set<string>>(new Set());
  // Cache client du speakable par email id (M-P2f) : `/speakable?conversational`
  // refait un appel Haiku + un intro aléatoire à CHAQUE requête → le texte
  // prefetché ne serait JAMAIS égal au texte re-fetché sur next() (cache TTS
  // serveur keyé par hash = miss garanti, et double appel Haiku). On mémorise
  // donc le résultat exact pour le réutiliser à la lecture réelle.
  const speakableCacheRef        = useRef<Map<string, SpeakableEmail>>(new Map());

  // Dictation buffer + silence timer
  const dictationSilenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Nudge silence (choosing / reviewing states)
  const silenceTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Step 3 — timer de la fenêtre d'annulation (état undo_window).
  const undoTimerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Act-then-undo : actions différées annulables (archive/delete/send).
  const pendingActionsRef = useRef(new PendingActionManager());

  // M-P1c : true entre « la voix démarre » (onVoiceStart) et « le transcript
  // est traité » — le timer undo_window ne doit PAS envoyer pendant que
  // l'utilisateur est en train de dire « annule » (le STT batch a ~1-1,5 s de
  // latence après la fin de parole).

  // Compteur d'actions différées exposé à l'UI (chip « Annuler »). Miroir
  // réactif de pendingActionsRef.current.count() — mis à jour à chaque
  // schedule/cancel/flush via bumpPendingCount.
  const [pendingActionCount, setPendingActionCount] = useState(0);

  // Historique conversationnel glissant pour le voice agent (≤ 8 tours).
  const agentHistoryRef = useRef<Array<{ role: "user" | "assistant"; content: string }>>([]);

  // Queue des emails entrants pendant la session
  const pendingAnnouncementsRef = useRef<string[]>([]);

  // Idle STT — écoute avant session pour sélection du mode
  const idleModeCallbackRef    = useRef<((mode: SessionMode) => void) | null>(null);
  /** Auto-stop idle STT après IDLE_STT_TIMEOUT_MS sans activité (batterie). */
  const idleTimeoutRef         = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Niveau audio 0..1 pour l'aurora réactive (#1124 → hook dédié) ────────
  // Alimenté par `dictation.onLevel` (user parle) + enveloppe simulée (TTS parle).
  const { audioLevel, pushAudioLevel, startTtsEnvelope, stopTtsEnvelope } =
    useAudioLevelEnvelope();

  // Function refs (break circular deps)
  const resetRef              = useRef<() => void>(() => {});
  const resumeSessionRef      = useRef<() => void>(() => {});
  const nudgeOnSilenceRef     = useRef<() => void>(() => {});
  const armDictationSilenceRef = useRef<() => void>(() => {});
  const clearDictationTimerRef = useRef<() => void>(() => {});
  // Step 3 — enterUndoWindow référence approveDraftAndNext (défini plus bas) ;
  // on casse le cycle via ref, comme resetRef/resumeSessionRef.
  const enterUndoWindowRef    = useRef<() => void>(() => {});
  // Politique conservatrice undo_window (device 2026-07-28) : voix entendue
  // mais transcript vide pendant la fenêtre d'annulation → annuler l'envoi
  // (un « annule » raté par le STT batch laissait partir l'email).
  const cancelPendingSendRef  = useRef<() => void>(() => {});


  // La garde est DANS le callback, pas au moment de planifier : elle couvre
  // ainsi les deux fuites — le timer armé avant le démontage qui tombe après,
  // ET celui armé après par une promesse en retard. Signature inchangée.
  const safeTimeout = useCallback((fn: () => void, ms: number) => {
    const id = setTimeout(() => {
      if (!isMountedRef.current) return;
      fn();
    }, ms);
    timersRef.current.push(id);
    return id;
  }, []);

  // ── Silence timers (choosing/reviewing nudge) ────────────────────────────
  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const armSilenceTimer = useCallback((fn: () => void, ms: number) => {
    clearSilenceTimer();
    silenceTimerRef.current = setTimeout(() => {
      if (!isMountedRef.current) return;
      fn();
    }, ms);
  }, [clearSilenceTimer]);

  // Load voice prefs + restore session
  useEffect(() => {
    SecureStore.getItemAsync("voice_rate")
      .then((r) => { if (r) speechRateRef.current = parseFloat(r); })
      .catch(() => {}); // no-op légitime : restauration de session best-effort
    SecureStore.getItemAsync("drive_session")
      .then((raw) => {
        if (!raw) return;
        const data = JSON.parse(raw);
        const ageMinutes = (Date.now() - data.timestamp) / 60000;
        // Back-compat : anciennes sessions ont `emailIds.length`, nouvelles ont
        // `emailCount` direct (pas d'IDs persistés — trop lourd pour Keychain).
        const emailCount: number =
          typeof data.emailCount === "number"
            ? data.emailCount
            : data.emailIds?.length ?? 0;
        if (ageMinutes < 30 && emailCount > 0) {
          setPendingResume({ emailCount, currentIndex: data.currentIndex });
        } else {
          SecureStore.deleteItemAsync("drive_session").catch(() => {}); // no-op légitime : restauration de session best-effort
        }
      })
      .catch(() => {}); // no-op légitime : restauration de session best-effort
  }, []);

  // ── STT pipeline (VAD recorder + Fireworks via backend) ─────────────────
  // Pas d'event-loop : `dictation.listen()` retourne une Promise qui résout
  // après silence/timeout, on transcrit, on appelle handleVoiceInput, on
  // re-démarre. Auto-restart logique : voir `startListening` plus bas.
  const dictation = useVoiceDictation();
  // Step 4 — session streaming Deepgram (flag-gated, fallback batch intégré).
  // Les deux hooks sont appelés inconditionnellement (règles des hooks) mais
  // passifs jusqu'à openSession ; on sélectionne la voie directe (Deepgram) ou
  // proxy (Socket.IO) selon le flag. Voir STREAMING_DIRECT_DEEPGRAM.
  const streamingProxy = useStreamingStt();
  const streamingDirect = useDeepgramDirect();
  const streamingStt = STREAMING_DIRECT_DEEPGRAM ? streamingDirect : streamingProxy;
  // Ref pour casser le cycle startListening → handleVoiceInput → startListening.
  // handleVoiceInput est défini plus bas dans le fichier, on l'appelle via ce
  // ref depuis startListening qui le précède.
  const handleVoiceInputRef = useRef<(text: string) => void>(() => {});

  // Télémétrie voice-to-voice : branche l'envoi réseau une fois.
  useEffect(() => {
    voiceMetrics.configure(async (events) => {
      await postVoiceMetrics(events);
    });
  }, []);

  // Filet de démontage : des actions différées (archive/send) ne doivent pas
  // mourir avec le composant — l'utilisateur les croit déjà faites.
  // Branche aussi le compteur réactif (chip undo) sur le manager.
  useEffect(() => {
    const manager = pendingActionsRef.current;
    manager.setOnChange((count) => setPendingActionCount(count));
    return () => {
      manager.setOnChange(null);
      manager.flushAll().catch((e) => reportError(e, { domain: "api", op: "flushPendingActions.unmount" }, { userFacing: "silent" }));
    };
  }, []);

  // useTts est la source unique TTS : il force allowsRecording:false AVANT
  // chaque speak, garantissant que la sortie va au speaker.
  const ttsHook = useTts();

  // Earcons — canal non-verbal qui remplace les questions de protocole
  // ("J'envoie ?"…). `play` est stable (useCallback []), safe en deps.
  const { play: playEarcon } = useEarcons();

  // Loud failure (Phase 1 fondations) : reportError() peut jouer l'earcon
  // « alert » pour les erreurs audio/state — un module plain ne peut pas
  // appeler un hook, le drive enregistre donc son player au mount.
  useEffect(() => {
    registerErrorEarcon((name) => playEarcon(name));
    return () => unregisterErrorEarcon();
  }, [playEarcon]);

  // ── IO vocal (#1124 étape 3) — extrait vers useDriveVoiceIO ──────────────
  const {
    speak, stopTts, startListening, stopListening, flushListening,
    interruptAndListen,
    speakAndListen,
  } = useDriveVoiceIO({
    coreRef, dispatchEvent, setTranscript, setIsListening, setIsTranscribing,
    setCommandRecognized, spokenAckRef,
    ttsHook, dictation, streamingStt, playEarcon, pushAudioLevel,
    startTtsEnvelope, stopTtsEnvelope,
    safeTimeout, armSilenceTimer, clearSilenceTimer,
    nudgeOnSilenceRef, handleVoiceInputRef,
    pendingActionsRef, cancelPendingSendRef,
    streamingSttEnabled: STREAMING_STT,
    silenceFirstMs: SILENCE_FIRST_MS,
  });

  // ── Helper : setter draft avec sync ref ─────────────────────────────────
  const updateDraft = useCallback((content: string | null, id: string | null) => {
    dispatch({ type: "SET_DRAFT", content, id });
  }, [dispatch]);

  // ── Session & lifecycle (#1124 étape 3) — extrait vers useDriveSession ──
  const {
    next, previous, chooseReply, finishDictation,
    startSession, reset, dismissResume, stopWithFarewell,
    startIdleSTT, stopIdleSTT, resumeSession, enqueueEmail,
  } = useDriveSession({
    coreRef, dispatchEvent, spokenAckRef, setEmails, setCurrentIndex, setCurrentEmail,
    setReplyMode, setError, setTranscript, setSessionStats, setPendingResume,
    setQueuedCount, setIdleListening, updateDraft,
    speak, speakAndListen, startListening, stopListening, flushListening,
    stopTts, playEarcon,
    streamingStt, ttsHook, safeTimeout, clearSilenceTimer,
    clearDictationTimerRef,
    pendingActionsRef, undoTimerRef, agentHistoryRef,
    pendingAnnouncementsRef, prefetchedIdsRef, speakableCacheRef,
    idleTimeoutRef, idleModeCallbackRef, timersRef,
    fullDuplexReads: FULL_DUPLEX_READS,
    streamingSttEnabled: STREAMING_STT,
    idleSttTimeoutMs: IDLE_STT_TIMEOUT_MS,
  });



  // ── Flow draft (#1124 étape 3) — extrait vers useDraftFlow ──────────────
  const {
    cancelPendingSend, generateDraft, archiveAndNext, deleteAndNext,
    applyModify, approveDraftAndNext, approveContextual, rejectAndRelisten,
  } = useDraftFlow({
    coreRef, dispatchEvent, setError, setGeneratingElapsedMs, updateDraft,
    speak, speakAndListen, startListening, stopListening, stopTts, playEarcon,
    next, safeTimeout,
    pendingActionsRef, undoTimerRef,
    clearDictationTimerRef, enterUndoWindowRef,
    cancelPendingSendRef,
    fullDuplexReads: FULL_DUPLEX_READS,
  });


  // ── Routeur vocal (#1124 étape 3) — extrait vers useVoiceRouter ──────────
  // Placé ici car il capture des callbacks définis au-dessus (approve/reject).
  // reset/resumeSession, définis plus bas, passent par leurs function refs.
  const { handleVoiceInput } = useVoiceRouter({
    coreRef, dispatchEvent, setReplyMode, setError, pendingFlashRef, pendingAckRef,
    setIdleListening, updateDraft,
    speak, startListening, stopListening, stopTts,
    playEarcon,
    next, previous, chooseReply, generateDraft, applyModify,
    archiveAndNext, deleteAndNext, approveDraftAndNext, rejectAndRelisten,
    cancelPendingSend,
    resetRef, resumeSessionRef,
    agentHistoryRef, clearDictationTimerRef,
    armDictationSilenceRef, pendingActionsRef,
    undoTimerRef, idleModeCallbackRef,
    safeTimeout,
  });

  // Brancher le ref pour que startListening (défini plus haut) puisse
  // appeler handleVoiceInput sans dépendance circulaire dans useCallback.
  useEffect(() => {
    handleVoiceInputRef.current = handleVoiceInput;
  }, [handleVoiceInput]);

  // ── Wiring des refs après déclaration ───────────────────────────────────
  useEffect(() => { resetRef.current         = reset;         }, [reset]);
  useEffect(() => { resumeSessionRef.current = resumeSession; }, [resumeSession]);

  // Timer de dictée (brisé circulaire via ref)
  useEffect(() => {
    clearDictationTimerRef.current = () => {
      if (dictationSilenceTimerRef.current) {
        clearTimeout(dictationSilenceTimerRef.current);
        dictationSilenceTimerRef.current = null;
      }
    };
    armDictationSilenceRef.current = () => {
      clearDictationTimerRef.current();
      dictationSilenceTimerRef.current = setTimeout(() => {
        if (coreRef.current.state === "listening" && coreRef.current.dictationBuffer.length > 0) {
          stopListening();
          dispatchEvent({ type: "DICTATION_FINISHED" });
          // Earcon "à toi" au lieu du "Je rédige ?" parlé. La StatusPill
          // (visuel "Draft it?") reste le backstop.
          playEarcon("turn");
          startListening();
        }
      }, DICTATION_SILENCE_MS);
    };
  }, [speak, startListening, stopListening, playEarcon]);

  // Nudge silence (choosing / reviewing)
  useEffect(() => {
    nudgeOnSilenceRef.current = () => {
      const s = coreRef.current.state;
      if (s !== "choosing" && s !== "reviewing") return;
      if (!coreRef.current.silenceNudged) {
        coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", true);
        stopListening();
        const prompt = dt("tts.stillThere");
        speak(prompt, () => {
          startListening();
          armSilenceTimer(() => nudgeOnSilenceRef.current(), SILENCE_SECOND_MS);
        });
      } else {
        coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
        stopListening();
        dispatchEvent({ type: "PAUSE" });
        speak(dt("tts.pausingSession"), () => startListening());
      }
    };
  }, [speak, startListening, stopListening, armSilenceTimer]);

  useEffect(() => {
    isMountedRef.current = true; // remount (StrictMode) : on ré-arme la garde
    return () => {
      isMountedRef.current = false;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      // Le nudge de silence vivait hors de `timersRef` — il survivait donc au
      // démontage et parlait par-dessus l'écran suivant.
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
      // L'enveloppe TTS se nettoie dans useAudioLevelEnvelope (unmount).
    };
  }, []);

  // Watchdog UX (Phase 1 fondations §1.6) : après 12 s sans AUCUN progrès
  // (transition, transcript, écoute, TTS) dans un état actif, l'app l'AVOUE
  // au lieu de rester muette — bandeau « Je n'entends rien » dans DrivePlayer.
  // États exclus : attente légitime (idle/paused/completed/error), lecture
  // TTS potentiellement longue (speaking), génération (a son elapsed), et
  // undo_window (piloté par son propre timer d'envoi).
  const watchdogActive = !(
    state === "idle" || state === "paused" || state === "completed" ||
    state === "error" || state === "speaking" || state === "generating" ||
    state === "undo_window"
  );
  const { stalled: watchdogStalled, acknowledge: acknowledgeStall } = useWatchdog(
    watchdogActive,
    [state, transcript, isListening, isTranscribing, ttsHook.state],
    undefined,
    () => playEarcon("alert"),
  );
  const retryFromStall = useCallback(() => {
    acknowledgeStall();
    stopListening();
    startListening();
  }, [acknowledgeStall, stopListening, startListening]);

  // Chip « Annuler » (M-P1a) : escape hatch latency-proof (tap, pas de STT).
  // Annule la dernière action différée et recrédite la stat correspondante.
  const undoLastAction = useCallback(() => {
    const cancelled = pendingActionsRef.current.cancelLast();
    if (!cancelled) return;
    voiceMetrics.counter("undo_cancels", coreRef.current.state);
    if (cancelled.kind === "send") coreRef.current = bumpStat(coreRef.current, "approved", -1);
    else if (cancelled.kind === "archive") coreRef.current = bumpStat(coreRef.current, "archived", -1);
    else coreRef.current = bumpStat(coreRef.current, "deleted", -1);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {}); // no-op légitime : restauration de session best-effort
    playEarcon("tick");
    toast.info(
      cancelled.kind === "send" ? "Envoi annulé — brouillon conservé" :
      cancelled.kind === "archive" ? "Archivage annulé" : "Suppression annulée",
    );
  }, [playEarcon]);

  return {
    state, replyMode, currentEmail, emails, currentIndex,
    draftContent, error, isListening, isTranscribing, transcript,
    commandRecognized, sessionStats, queuedCount, pendingResume, generatingElapsedMs,
    startSession, resumeSession, enqueueEmail,
    next, previous, chooseReply, finishDictation,
    approveContextual, approveDraftAndNext, rejectAndRelisten,
    archiveAndNext, deleteAndNext,
    reset, dismissResume,
    sttAvailable: true,
    idleListening,
    startIdleSTT,
    stopIdleSTT,
    stopWithFarewell,
    audioLevel,
    ttsState: ttsHook.state,
    interruptAndListen,
    pendingActionCount,
    undoLastAction,
    watchdogStalled,
    retryFromStall,
  };
}
