/**
 * useDriveSession — cycle de vie de la session Drive Mode (#1124 étape 3).
 *
 * Couvre : lecture d'un email (readEmailAtIndex + prefetch TTS/speakable),
 * navigation (next/previous/chooseReply), persistance/restauration
 * (persistSession, dismissResume), démarrage (startSession + briefing +
 * session streaming), arrêts (reset bruyant, stopWithFarewell silencieux),
 * reprise (resumeSession), enqueue live WebSocket, idle STT avec auto-stop
 * batterie, et les gardes AppState (#1122) / auth perdue (#1121).
 *
 * Extrait verbatim de useDriveMode — ctx aux noms identiques, corps
 * inchangé (diff de comportement nul).
 */

import { useCallback, useEffect, type Dispatch, type SetStateAction, type MutableRefObject } from "react";
import { AppState } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Haptics from "expo-haptics";
import i18n from "../i18n";
import { voiceMetrics } from "../lib/voiceMetrics";
import { reportError } from "../lib/errors";
import { getEmailSpeakable, getPendingDraftByEmail } from "../services/api";
import { subscribeAuthChange } from "../services/auth";
import * as AgentysAudio from "../../modules/agentys-audio";
import type { PendingActionManager } from "../lib/pendingActions";
import type { SpokenAck } from "../lib/driveCommands";
import type { UseTtsResult } from "./useTts";
import type { UseStreamingStt } from "./useStreamingStt";
import type { DriveCore, DriveEvent } from "./driveReducer";
import { pushDictation, clearDictation, setCoreFlag, bumpStat, resetStats } from "./driveReducer";
import type {
  DriveState, ReplyMode, SpeakableEmail, Email, SessionStats, SessionMode,
} from "../types";

const dt = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "drive", ...(opts ?? {}) }) as string;

export interface DriveSessionCtx {
  coreRef: MutableRefObject<DriveCore>;
  /** §2.3 : chemin de transition par la machine (rejet bruyant + trace). */
  dispatchEvent: (e: DriveEvent) => boolean;
  setEmails: (e: Email[]) => void;
  setCurrentIndex: (i: number) => void;
  setCurrentEmail: (e: SpeakableEmail | null) => void;
  setReplyMode: (m: ReplyMode | null) => void;
  setError: Dispatch<SetStateAction<string | null>>;
  setTranscript: Dispatch<SetStateAction<string>>;
  setSessionStats: Dispatch<SetStateAction<SessionStats | null>>;
  setPendingResume: Dispatch<SetStateAction<{ emailCount: number; currentIndex: number } | null>>;
  setQueuedCount: Dispatch<SetStateAction<number>>;
  setIdleListening: Dispatch<SetStateAction<boolean>>;
  updateDraft: (content: string | null, id: string | null) => void;

  speak: (text: string, onDone?: () => void) => void;
  speakAndListen: (text: string, onDone?: () => void) => void;
  startListening: () => void;
  stopListening: () => void;
  /** Clôt la capture en cours en CONSERVANT l'audio (→ transcript). */
  flushListening: () => boolean;
  stopTts: () => Promise<void>;
  playEarcon: (name: "turn" | "tick" | "done" | "alert") => void;

  streamingStt: UseStreamingStt;
  ttsHook: UseTtsResult;
  safeTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearSilenceTimer: () => void;

  clearDictationTimerRef: MutableRefObject<() => void>;
  pendingActionsRef: MutableRefObject<PendingActionManager>;
  /** Accusé parlé en attente — normalement préfixé au prochain énoncé par
   *  `speak`, mais la fin de session doit le dire seule (plus rien ne suit). */
  spokenAckRef: MutableRefObject<SpokenAck | null>;
  undoTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  agentHistoryRef: MutableRefObject<Array<{ role: "user" | "assistant"; content: string }>>;
  pendingAnnouncementsRef: MutableRefObject<string[]>;
  prefetchedIdsRef: MutableRefObject<Set<string>>;
  speakableCacheRef: MutableRefObject<Map<string, SpeakableEmail>>;
  idleTimeoutRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  idleModeCallbackRef: MutableRefObject<((mode: SessionMode) => void) | null>;
  timersRef: MutableRefObject<ReturnType<typeof setTimeout>[]>;

  fullDuplexReads: boolean;
  streamingSttEnabled: boolean;
  idleSttTimeoutMs: number;
}

export function useDriveSession(ctx: DriveSessionCtx) {
  const {
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
  } = ctx;
  void FULL_DUPLEX_READS; void STREAMING_STT; void IDLE_STT_TIMEOUT_MS;

  // ── Lecture email → asking_preview ou choosing ───────────────────────────
  const readEmailAtIndex = useCallback(async (index: number, emailListArg: Email[]) => {
    const queued = pendingAnnouncementsRef.current;
    if (queued.length > 0) {
      pendingAnnouncementsRef.current = [];
      setQueuedCount(0);
      const msg = queued.length === 1
        ? `Nouveau mail de ${queued[0]}. Je l'ajoute à la suite.`
        : `${queued.length} nouveaux mails reçus. Je les ajoute à la suite.`;
      await new Promise<void>((resolve) => speak(msg, resolve));
    }

    const emailList = coreRef.current.emails.length > emailListArg.length ? coreRef.current.emails : emailListArg;

    if (index >= emailList.length) {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
      safeTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy), 200);
      safeTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy), 400);
      // Session terminée : exécute les actions différées (le résumé les
      // affiche comme faites) + flush la télémétrie du tour final.
      pendingActionsRef.current.flushAll().catch((e) =>
      reportError(e, { domain: "api", op: "flushPendingActions.sessionEnd" }, { userFacing: "silent" }));
      voiceMetrics.endSession();
      // Session finie : on rend la session audio pour que la musique de
      // l'utilisateur reprenne SANS attendre qu'il tape « Terminer » sur le
      // résumé — au volant, il ne le fera pas. Le résumé ne parle pas.
      AgentysAudio.deactivateSession();
      setSessionStats({ ...coreRef.current.sessionStats });
      dispatchEvent({ type: "SESSION_END" });
      // Dernier email : aucune lecture ne suivra pour porter l'accusé en
      // préfixe (« Supprimé. De Marc… »). On le dit seul, sinon l'utilisateur
      // vient de supprimer son dernier mail et n'entend qu'un earcon.
      const finalAck = spokenAckRef.current;
      spokenAckRef.current = null;
      if (finalAck) speak(finalAck.label);
      return;
    }
    // Audit TTS 2026-04-28 : haptic Error suffit pour signaler "déjà au début".
    // Le visualizer ne change pas + buzz d'erreur = signal univoque sans 700ms TTS.
    if (index < 0) { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {}); return; }

    const email = emailList[index];
    dispatchEvent({ type: "EMAIL_LOAD" });
    setError(null);
    updateDraft(null, null);
    setReplyMode(null);

    try {
      // M-P2f : réutilise le speakable mémorisé (prefetch) si dispo — MÊME
      // texte → cache TTS serveur en hit + zéro appel Haiku redondant.
      const cachedSpeakable = speakableCacheRef.current.get(email.id);
      const [speakable, existingDraft] = await Promise.all([
        cachedSpeakable
          ? Promise.resolve(cachedSpeakable)
          : getEmailSpeakable(email.id, true).then((sp) => {
              if (sp?.speakable_text) speakableCacheRef.current.set(email.id, sp);
              return sp;
            }),
        getPendingDraftByEmail(email.id),
      ]);
      setCurrentEmail(speakable);
      dispatchEvent({ type: "EMAIL_LOADED" });
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);

      // Prefetch de l'email N+1 pendant la lecture du N : on mémorise le
      // speakable EXACT (cache client) PUIS on warm le cache TTS serveur avec
      // ce même texte → le speak() du prochain mail est un cache hit garanti.
      // Fire-and-forget, dedupé par id.
      const nextEmail = emailList[index + 1];
      if (nextEmail && !prefetchedIdsRef.current.has(nextEmail.id)) {
        prefetchedIdsRef.current.add(nextEmail.id);
        getEmailSpeakable(nextEmail.id, true)
          .then((sp) => {
            if (sp?.speakable_text) {
              speakableCacheRef.current.set(nextEmail.id, sp);
              ttsHook.prefetch(sp.speakable_text).catch(() => {}); // no-op légitime : warm cache best-effort
            }
          })
          .catch(() => {
            // échec silencieux : on retire de la liste pour pouvoir re-essayer
            prefetchedIdsRef.current.delete(nextEmail.id);
          });
      }

      if (existingDraft?.draft_body) {
        const draftBody  = existingDraft.draft_body;
        const draftIdVal = existingDraft.id || existingDraft.draft_id;
        // Lecture email avec barge-in (si module natif) — l'user peut dire
        // "suivant"/"archiver"/etc avant la fin pour couper l'AI.
        // F5 — Si un brouillon pré-existe, on l'enchaîne directement après
        // la lecture du mail au lieu de demander "tu veux l'écouter ?".
        speakAndListen(speakable.speakable_text, () => {
          updateDraft(draftBody, draftIdVal);
          dispatchEvent({ type: "SPEAK" });
          // Brève intro + lecture du draft, puis earcon "à toi" (plus de
          // "J'envoie ?" parlé). FULL_DUPLEX_READS → lecture interruptible.
          const draftIntro = dt("tts.draftExistsShort", { defaultValue: "Brouillon existant :" });
          const readDraft = FULL_DUPLEX_READS ? speakAndListen : speak;
          readDraft(`${draftIntro} ${draftBody}`, () => {
            // « J'envoie ? » parlé d'office : le earcon seul ne signale pas
            // le point de décision (design audio 2026-07-30).
            speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), () => {
              dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
              playEarcon("turn");
              startListening();
            });
          });
        });
      } else {
        speakAndListen(speakable.speakable_text, () => {
          dispatchEvent({ type: "TTS_DONE", next: "choosing" });
          // #1134 : earcon « à toi » explicite en fin de lecture — le silence
          // seul ne signale pas le tour de parole (spec utilisateur).
          playEarcon("turn");
          startListening();
        });
      }
    } catch (err: any) {
      setError(err.message);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      speak(dt("tts.errorTryAgain"), () => {
        dispatchEvent({ type: "RECOVER", to: "choosing" });
        setError(null);
        startListening();
      });
      dispatchEvent({ type: "FLOW_ERROR" });
    }
  }, [speak, speakAndListen, startListening, updateDraft, safeTimeout]);

  // ── Navigation ───────────────────────────────────────────────────────────
  // Persist session en SecureStore pour la bannière "Reprendre ?" au boot.
  // IMPORTANT : iOS Keychain warn au-dessus de 2 KB/entrée. Une liste de 100+
  // IDs d'emails × ~30 chars dépasse la limite → warning en boucle.
  // Solution : on n'a besoin QUE de (emailCount, currentIndex) pour afficher
  // la bannière — `resumeSession` utilise coreRef.current.emails (mémoire vive),
  // pas le storage. On garde donc un payload minimal de <100 bytes.
  const persistSession = useCallback((index: number, emailList: Email[]) => {
    const data = JSON.stringify({
      emailCount:   emailList.length,
      currentIndex: index,
      timestamp:    Date.now(),
    });
    SecureStore.setItemAsync("drive_session", data).catch((e) =>
      reportError(e, { domain: "unknown", op: "persistSession" }, { userFacing: "silent" }));
  }, []);

  const next = useCallback(() => {
    stopListening();
    stopTts();
    clearDictationTimerRef.current();
    coreRef.current = clearDictation(coreRef.current);
    if (coreRef.current.state === "choosing" || coreRef.current.state === "speaking") {
      coreRef.current = bumpStat(coreRef.current, "skipped");
    }
    const newIndex = coreRef.current.currentIndex + 1;
    setCurrentIndex(newIndex);
    persistSession(newIndex, coreRef.current.emails);
    readEmailAtIndex(newIndex, coreRef.current.emails);
  }, [stopListening, stopTts, readEmailAtIndex, persistSession]);

  const previous = useCallback(() => {
    stopListening();
    stopTts();
    clearDictationTimerRef.current();
    coreRef.current = clearDictation(coreRef.current);
    const newIndex = coreRef.current.currentIndex - 1;
    if (newIndex < 0) { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {}); startListening(); return; }
    setCurrentIndex(newIndex);
    readEmailAtIndex(newIndex, coreRef.current.emails);
  }, [stopListening, stopTts, speak, startListening, readEmailAtIndex]);

  // ── Choix de réponse → dictée ─────────────────────────────────────────────
  const chooseReply = useCallback((mode: ReplyMode) => {
    setReplyMode(mode);
    stopListening();
    clearDictationTimerRef.current();
    coreRef.current = clearDictation(coreRef.current);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    dispatchEvent({ type: "REPLY_CHOSEN" });
    if (mode === "forward") {
      // Le transfert pose une vraie question (le destinataire) — TTS requis.
      speak(dt("tts.forwardPrompt"), () => startListening());
    } else {
      // Design audio 2026-07-30 : earcon = signal de tour, parole = signal de
      // vocabulaire. L'entrée en dictée change le vocabulaire attendu
      // (commandes → contenu libre) → consigne parlée courte, puis earcon.
      // Phrase fixe : cachée par le TTS après la première lecture.
      speak(dt("tts.listening", { defaultValue: "J'écoute." }), () => {
        playEarcon("turn");
        startListening();
      });
    }
  }, [stopListening, speak, playEarcon, startListening]);

  // Fin de dictée par TAP (retour device) : au lieu d'attendre le timer de
  // silence (3s), l'utilisateur touche l'écran pour signaler « c'est fini ».
  // Même transition que le timer : confirming_dictation + earcon « à toi »,
  // où il peut dire « envoyer », « oui » (rédige) ou continuer à dicter.
  const finishDictation = useCallback(() => {
    if (coreRef.current.state !== "listening") return;
    if (coreRef.current.dictationBuffer.length === 0) {
      // Rien dans le buffer : soit la capture est ENCORE OUVERTE (retour
      // device 2026-07-13 : bruit ambiant > seuil VAD → la capture ne se
      // fermait jamais, le tap tombait ici en vibration d'erreur muette),
      // soit vraiment aucun son. flush() clôt la capture en GARDANT
      // l'audio : la parole en vol part en transcription et reviendra
      // remplir le buffer (~1 s). Feedback haptique léger = « bien reçu ».
      const flushed = flushListening();
      Haptics.impactAsync(
        flushed ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light,
      ).catch(() => {}); // no-op légitime : best-effort
      if (!flushed) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {}); // no-op légitime : best-effort
      }
      return;
    }
    stopListening();
    clearDictationTimerRef.current();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {}); // no-op légitime : best-effort
    dispatchEvent({ type: "DICTATION_FINISHED" });
    // Device 2026-07-29 (3e session bloquée ici) : le earcon seul ne dit PAS
    // ce qui est attendu — l'utilisateur reste face à un silence et abandonne
    // (RESET). Un « Je rédige ? » parlé (court) donne le vocabulaire de
    // sortie : oui (rédige) / envoyer (rédige + envoie) / continuer à dicter.
    speak(dt("tts.confirmAfterTap", { defaultValue: "Je rédige ?" }), () => {
      playEarcon("turn");
      startListening();
    });
  }, [stopListening, speak, playEarcon, startListening]);



  // ── Démarrage de session ─────────────────────────────────────────────────
  const startSession = useCallback(async (emailList: Email[], mode: SessionMode = "mixed") => {
    // Step 2 — ouvre UNE session voiceChat (AEC + speaker forcé) pour toute la
    // session, plutôt que de basculer la category à chaque listen/speak.
    // No-op si flag off ou module natif absent (Expo Go).
    if (FULL_DUPLEX_READS) AgentysAudio.configureForVoiceChat();

    // Step 4 — ouvre la session streaming Deepgram (une connexion pour toute
    // la session). Échec → le flag streamingActive reste false, pipeline batch.
    if (STREAMING_STT && streamingStt.available) {
      AgentysAudio.configureForVoiceChat(); // AEC obligatoire : le mic stream tourne pendant la TTS
      const lang = (i18n.language || "").split(/[-_]/)[0] || undefined;
      const opened = await streamingStt.openSession({
        lang,
        onSpeechStart: () => {
          // Barge-in sémantique : l'utilisateur parle pendant la TTS.
          if (ttsHook.state === "speaking") {
            voiceMetrics.counter("barge_ins", coreRef.current.state);
            playEarcon("tick");
            ttsHook.stop().catch(() => {}); // no-op légitime : déjà à l'arrêt
          }
        },
        onSessionLost: () => {
          coreRef.current = setCoreFlag(coreRef.current, "streamingActive", false);
          console.warn("[drive-stt] streaming session lost — fallback batch");
        },
      });
      coreRef.current = setCoreFlag(coreRef.current, "streamingActive", opened);
      console.log("[drive-stt] streaming session:", opened ? "OPEN" : "unavailable → batch");
    }

    voiceMetrics.startSession();
    // Un accusé orphelin de la session précédente ne doit pas se coller au
    // « 5 emails. C'est parti. » de celle-ci.
    spokenAckRef.current = null;
    agentHistoryRef.current = [];
    setEmails(emailList);
    setCurrentIndex(0);
    coreRef.current = resetStats(coreRef.current, emailList.length, Date.now());
    setSessionStats(null);
    persistSession(0, emailList);

    const count = emailList.length;
    const kickKey = mode === "actions" ? "tts.startActions"
                  : mode === "infos"   ? "tts.startInfos"
                  :                      "tts.startMixed";
    speak(dt(kickKey, { count }), () => readEmailAtIndex(0, emailList));
  }, [speak, readEmailAtIndex, persistSession, streamingStt, ttsHook, playEarcon]);
  // ── Reset ────────────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    stopListening();
    stopTts();
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
    clearDictationTimerRef.current();
    coreRef.current = clearDictation(coreRef.current);
    clearSilenceTimer();
    if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
    // Act-then-undo : la fin de session EXÉCUTE immédiatement les actions
    // différées — l'utilisateur les croit faites, on ne les perd pas.
    pendingActionsRef.current.flushAll().catch((e) =>
      reportError(e, { domain: "api", op: "flushPendingActions" }, { userFacing: "silent" }));
    // Step 4 — ferme la session streaming Deepgram + flush la télémétrie.
    coreRef.current = setCoreFlag(coreRef.current, "streamingActive", false);
    streamingStt.closeSession();
    voiceMetrics.endSession();
    spokenAckRef.current = null;
    agentHistoryRef.current = [];
    prefetchedIdsRef.current.clear();
    speakableCacheRef.current.clear();
    // Step 2 — rend la session audio au mode Playback standard (no-op si flag off).
    if (FULL_DUPLEX_READS) AgentysAudio.configureForPlayback();
    // Libère l'AVAudioSession → la musique interrompue au démarrage reprend.
    AgentysAudio.deactivateSession();
    if (idleTimeoutRef.current) { clearTimeout(idleTimeoutRef.current); idleTimeoutRef.current = null; }
    idleModeCallbackRef.current  = null;
    coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", false);
    setIdleListening(false);
    dispatchEvent({ type: "RESET" });
    setCurrentEmail(null);
    updateDraft(null, null);
    setReplyMode(null);
    setError(null);
    setEmails([]);
    setCurrentIndex(0);
    setTranscript("");
    setSessionStats(null);
    setPendingResume(null);
    SecureStore.deleteItemAsync("drive_session").catch((e) =>
      reportError(e, { domain: "unknown", op: "clearPersistedSession" }, { userFacing: "silent" }));
  }, [stopListening, stopTts, clearSilenceTimer, updateDraft, streamingStt]);

  const dismissResume = useCallback(() => {
    setPendingResume(null);
    SecureStore.deleteItemAsync("drive_session").catch((e) =>
      reportError(e, { domain: "unknown", op: "clearPersistedSession" }, { userFacing: "silent" }));
  }, []);

  // ── Stop silencieux ──────────────────────────────────────────────────────
  // Utilisé quand l'utilisateur coupe volontairement (stop, back à l'email 1).
  // Retour home propre et silencieux. La session est sauvegardée pour reprise.
  const stopWithFarewell = useCallback(() => {
    stopListening();
    stopTts(); // coupe toute TTS en cours (pas de « Session en pause » qui traîne)
    clearDictationTimerRef.current();
    coreRef.current = clearDictation(coreRef.current);
    clearSilenceTimer();
    if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
    // Mêmes filets que reset : actions différées exécutées, streaming fermé.
    pendingActionsRef.current.flushAll().catch((e) =>
      reportError(e, { domain: "api", op: "flushPendingActions" }, { userFacing: "silent" }));
    coreRef.current = setCoreFlag(coreRef.current, "streamingActive", false);
    streamingStt.closeSession();
    voiceMetrics.endSession();
    spokenAckRef.current = null;
    agentHistoryRef.current = [];
    if (FULL_DUPLEX_READS) AgentysAudio.configureForPlayback();
    // Libère l'AVAudioSession → la musique interrompue au démarrage reprend.
    AgentysAudio.deactivateSession();
    if (idleTimeoutRef.current) { clearTimeout(idleTimeoutRef.current); idleTimeoutRef.current = null; }
    idleModeCallbackRef.current  = null;
    coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", false);

    // Retour au home silencieux — l'utilisateur a explicitement demandé d'arrêter,
    // pas besoin de lui confirmer vocalement (perçu comme fatiguant).
    const remaining = coreRef.current.emails.length - coreRef.current.currentIndex;

    // Transition immédiate vers le home — pas de TTS.
    setIdleListening(false);
    dispatchEvent({ type: "RESET" });
    setCurrentEmail(null);
    updateDraft(null, null);
    setReplyMode(null);
    setError(null);
    setTranscript("");
    setSessionStats(null);

    // Déclenche le banner "Reprendre" si des emails restent.
    if (remaining > 0) {
      setPendingResume({
        emailCount: coreRef.current.emails.length,
        currentIndex: coreRef.current.currentIndex,
      });
    } else {
      // Tout traité : on peut nettoyer la persistance.
      SecureStore.deleteItemAsync("drive_session").catch((e) =>
      reportError(e, { domain: "unknown", op: "clearPersistedSession" }, { userFacing: "silent" }));
    }
  }, [stopListening, stopTts, clearSilenceTimer, updateDraft, streamingStt]);

  // ── Passage en arrière-plan pendant une écoute (#1122) ──────────────────
  // Le micro se coupe proprement ; le TTS, lui, continue écran verrouillé
  // (staysActiveInBackground: true, cf. src/lib/audioMode.ts).
  useEffect(() => {
    const sub = AppState.addEventListener("change", (next) => {
      if (next !== "active") stopListening();
    });
    return () => sub.remove();
  }, [stopListening]);

  // ── Auth perdue en pleine session (#1121) ────────────────────────────────
  // Le token n'est purgé qu'après confirmation (probe /api/auth/me côté api.ts),
  // donc si on arrive ici c'est une vraie expiration. On suspend proprement
  // (stopWithFarewell garde le banner « Reprendre » + persistance) et on
  // prévient vocalement — un retour silencieux au login en conduite est
  // incompréhensible pour l'utilisateur.
  useEffect(() => {
    return subscribeAuthChange((hasToken) => {
      if (hasToken || coreRef.current.state === "idle") return;
      stopWithFarewell();
      speak(dt("tts.sessionExpiredAuth"));
    });
  }, [stopWithFarewell, speak]);

  // ── Idle STT helpers (avec auto-stop batterie) ───────────────────────────
  const clearIdleTimeout = useCallback(() => {
    if (idleTimeoutRef.current) {
      clearTimeout(idleTimeoutRef.current);
      idleTimeoutRef.current = null;
    }
  }, []);

  const startIdleSTT = useCallback((onMode: (mode: SessionMode) => void) => {
    // Le STT Fireworks (via expo-av + backend) est toujours disponible
    // dans un dev build avec micro autorisé — pas de gating client-side.
    idleModeCallbackRef.current  = onMode;
    coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", true);
    setIdleListening(true);
    startListening();

    // Timeout batterie : arrêt silencieux après 30s sans commande reconnue.
    // L'utilisateur peut re-déclencher en pull-to-refresh ou en tapant une carte.
    clearIdleTimeout();
    idleTimeoutRef.current = setTimeout(() => {
      if (coreRef.current.idleListeningActive) {
        idleModeCallbackRef.current  = null;
        coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", false);
        setIdleListening(false);
        stopListening();
      }
    }, IDLE_STT_TIMEOUT_MS);
  }, [startListening, stopListening, clearIdleTimeout]);

  const stopIdleSTT = useCallback(() => {
    // #1134 (racine « pas à moi de parler ») : ne couper l'écoute QUE si l'idle
    // STT tournait vraiment. `app/index.tsx` appelle stopIdleSTT dans un
    // useEffect([drive.state]) qui re-fire à CHAQUE transition d'état — dont le
    // passage en "choosing"/"speaking" du tour de parole. Sans ce garde,
    // stopListening() y annulait le listen (idle OU session, `dictation` est
    // partagé) qu'on venait d'ouvrir → micro mort, barge-in vocal cassé.
    const wasActive = coreRef.current.idleListeningActive;
    clearIdleTimeout();
    idleModeCallbackRef.current  = null;
    coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", false);
    setIdleListening(false);
    if (wasActive) stopListening();
  }, [stopListening, clearIdleTimeout]);

  // ── Reprise après pause ──────────────────────────────────────────────────
  const resumeSession = useCallback(() => {
    if (coreRef.current.state !== "paused") return;
    coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
    setError(null);
    const list = coreRef.current.emails;
    const idx  = coreRef.current.currentIndex;
    if (list.length === 0 || idx >= list.length) { dispatchEvent({ type: "SESSION_END" }); return; }
    // Audit TTS 2026-04-28 : skip "Je reprends." (~700ms) — l'user vient
    // de dire "reprends" ou de tap, il sait. Heavy haptic + lecture immédiate
    // de l'email courant = signal de reprise univoque.
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {}); // no-op légitime : best-effort
    readEmailAtIndex(idx, list);
  }, [readEmailAtIndex]);

  // ── Enqueue email live (WebSocket) ───────────────────────────────────────
  const enqueueEmail = useCallback((email: Email) => {
    if (coreRef.current.emails.some((e) => e.id === email.id)) return;
    const updated = [...coreRef.current.emails, email];
    setEmails(updated);
    pendingAnnouncementsRef.current.push(email.sender_name || dt("tts.unknownSender"));
    setQueuedCount(pendingAnnouncementsRef.current.length);
    coreRef.current = { ...coreRef.current, sessionStats: { ...coreRef.current.sessionStats, totalEmails: updated.length } };
    if (coreRef.current.state === "completed") {
      readEmailAtIndex(coreRef.current.currentIndex, updated);
    }
  }, [readEmailAtIndex]);

  return {
    readEmailAtIndex, persistSession, next, previous, chooseReply, finishDictation,
    startSession, reset, dismissResume, stopWithFarewell,
    startIdleSTT, stopIdleSTT, resumeSession, enqueueEmail,
  };
}
