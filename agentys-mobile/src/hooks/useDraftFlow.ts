/**
 * useDraftFlow — génération, modification, validation et annulation des
 * brouillons du Drive Mode (#1124 étape 3).
 *
 * Couvre : generateDraft (pipeline /process + WS race), applyModify,
 * archive/delete act-then-undo, approveDraftAndNext (envoi différé
 * annulable), enterUndoWindow, approveContextual, rejectAndRelisten,
 * cancelPendingSend.
 *
 * Extrait verbatim de useDriveMode — ctx aux noms identiques, corps
 * inchangé (diff de comportement nul).
 */

import { useCallback, useEffect, type MutableRefObject } from "react";
import * as Haptics from "expo-haptics";
import i18n from "../i18n";
import { toast } from "../lib/toast";
import { reportError } from "../lib/errors";
import {
  approveDraft,
  archiveEmail,
  deleteEmail as deleteEmailApi,
  generateProcessDraftFast,
  DraftSkippedError,
} from "../services/api";
import type { PendingActionManager } from "../lib/pendingActions";
import type { DriveCore, DriveEvent } from "./driveReducer";
import { bumpStat } from "./driveReducer";
import { pushDictation, clearDictation } from "./driveReducer";
import type { DriveState, SessionStats } from "../types";
import {
  UNDO_ACTION_MS,
  SEND_UNDO_MS,
  UNDO_WINDOW_MS,
  extractSendDisposition,
} from "../lib/driveCommands";
import * as SecureStore from "expo-secure-store";

const dt = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "drive", ...(opts ?? {}) }) as string;

export interface DraftFlowCtx {
  coreRef: MutableRefObject<DriveCore>;
  /** §2.3 : SEUL chemin de transition (surface migrée le 2026-07-28). */
  dispatchEvent: (e: DriveEvent) => boolean;
  setError: (e: string | null) => void;
  setGeneratingElapsedMs: (ms: number) => void;
  updateDraft: (content: string | null, id: string | null) => void;

  speak: (text: string, onDone?: () => void) => void;
  speakAndListen: (text: string, onDone?: () => void) => void;
  startListening: () => void;
  stopListening: () => void;
  stopTts: () => Promise<void>;
  playEarcon: (name: "turn" | "tick" | "done" | "alert") => void;

  next: () => void;
  safeTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;

  pendingActionsRef: MutableRefObject<PendingActionManager>;
  undoTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  clearDictationTimerRef: MutableRefObject<() => void>;
  enterUndoWindowRef: MutableRefObject<() => void>;
  cancelPendingSendRef: MutableRefObject<() => void>;

  fullDuplexReads: boolean;
}

export function useDraftFlow(ctx: DraftFlowCtx) {
  const {
    coreRef, dispatchEvent, setError, setGeneratingElapsedMs, updateDraft,
    speak, speakAndListen, startListening, stopListening, stopTts, playEarcon,
    next, safeTimeout,
    pendingActionsRef, undoTimerRef,
    clearDictationTimerRef, enterUndoWindowRef,
    cancelPendingSendRef,
    fullDuplexReads: FULL_DUPLEX_READS,
  } = ctx;
  void FULL_DUPLEX_READS;

  // ── Step 3 : annuler un envoi en attente (état undo_window) ───────────────
  // Coupe le timer d'envoi différé, GARDE le brouillon, et bascule en
  // `reviewing` pour que l'user puisse l'éditer / le refaire / l'envoyer.
  const cancelPendingSend = useCallback(() => {
    if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
    stopListening();
    stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
    toast.info("Envoi annulé");
    dispatchEvent({ type: "SEND_CANCELLED" });
    // Earcon "à toi" + mic ouvert : l'user reprend la main sur le brouillon.
    playEarcon("turn");
    startListening();
  }, [stopListening, stopTts, playEarcon, startListening]);

  // ── Génération du brouillon → asking_preview ─────────────────────────────
  // Utilise le pipeline complet `/api/emails/<id>/process` (Drafter + Critic)
  // pour la même qualité que le bouton Ctrl+G de la webapp. Réponse 202
  // immédiate, génération async, on poll `getPendingDraftByEmail` jusqu'à
  // récupérer le `draft_body`.
  // Le `[TRANSFERT]` prefix reste pour signaler l'intent forward au backend
  // (qui n'a pas de `reply_type:"forward"` officiel — le prefix transite via
  // les instructions et permet aux prompts de différencier).
  const generateDraft = useCallback(async (text: string, opts?: { autoSend?: boolean }) => {
    const emailId = coreRef.current.currentEmail?.id;
    if (!emailId) {
      // Trouvaille du harnais d'injection de fautes (§2.1) : ce return était
      // MUET — « je dis envoyer et rien ne se passe » sans aucune trace si
      // currentEmail est nul à cet instant (course email avancé / reset).
      reportError(new Error("generateDraft sans email courant"), {
        domain: "state", op: "generateDraft", state: coreRef.current.state,
      });
      return;
    }
    // Step 3 — si la dictée se termine par un verbe d'envoi explicite
    // ("…et envoie"), on le retire du corps et on mémorise l'intention
    // d'envoi auto (fenêtre d'annulation au lieu de "J'envoie ?").
    // Le voice agent peut aussi imposer l'intention via opts.autoSend
    // (DRAFT_REPLY{auto_send} — il a déjà strippé le verbe du contenu).
    const { body: extractedBody, send: autoSendDetected } = extractSendDisposition(text);
    const dictationBody = opts?.autoSend !== undefined ? text : extractedBody;
    const autoSend = opts?.autoSend ?? autoSendDetected;
    stopListening();
    clearDictationTimerRef.current();
    dispatchEvent({ type: "GENERATE" });
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    safeTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium), 100);

    const mode      = coreRef.current.replyMode || "reply";
    const prefix    = mode === "forward" ? "[TRANSFERT] " : "";
    const replyType: "reply" | "reply_all" = mode === "reply_all" ? "reply_all" : "reply";

    try {
      setGeneratingElapsedMs(0);
      const result = await generateProcessDraftFast(
        emailId,
        prefix + dictationBody,
        replyType,
        (elapsed) => setGeneratingElapsedMs(elapsed),
      );
      setGeneratingElapsedMs(0);
      updateDraft(result.content, result.draft_id);
      coreRef.current = bumpStat(coreRef.current, "replied");
      // F5 — Auto-read au lieu de demander "tu veux l'écouter ?". Le user
      // a dicté → il veut entendre le résultat (95% des cas). Économise
      // ~3s de prompt + réponse. Si on veut interrompre la lecture, le
      // chip "stop" reste accessible (Phase 1) ou barge-in vocal Phase 2.
      dispatchEvent({ type: "DRAFT_READY", autoSend: false });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      const readDraft = FULL_DUPLEX_READS ? speakAndListen : speak;
      readDraft(result.content, () => {
        if (autoSend) {
          // "…et envoie" : on agit (envoi différé) via la fenêtre
          // d'annulation, sans reposer la question parlée "J'envoie ?".
          enterUndoWindowRef.current();
        } else {
          // « J'envoie ? » parlé d'office (design audio 2026-07-30) : le
          // earcon seul ne signalait pas le point de décision — si l'user le
          // rate, il ne sait pas que le micro l'attend. Phrase fixe cachée
          // par le TTS. La StatusPill reste le backstop visuel "Send?".
          speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), () => {
            dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
            playEarcon("turn");
            startListening();
          });
        }
      });
    } catch (err: any) {
      setGeneratingElapsedMs(0);
      setError(err?.message ?? String(err));
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      // Skip path : le backend a explicitement décidé de ne PAS générer
      // (auto-sender, noise, "no reply needed"). Pas de retry — on revient
      // au choix d'action sur l'email courant avec un message clair, sans
      // re-déclencher la dictée.
      if (err instanceof DraftSkippedError) {
        const reasonMsg =
          err.reason === "no_reply_needed" ? "Cet email ne nécessite pas de réponse" :
          err.reason === "noise" ? "Email classé Bruit — pas de brouillon généré" :
          err.reason === "auto-sender" || err.reason === "auto-reply" ? "Expéditeur automatique — réponse impossible" :
          "Brouillon non généré (skip backend)";
        toast.warning(reasonMsg, 5000);
        speak(dt("tts.skipNoReply", { defaultValue: "Cet email ne demande pas de réponse, je passe au suivant." }), async () => {
          setError(null);
          await next();
        });
        dispatchEvent({ type: "SPEAK" });
        return;
      }
      // Toast explicite plutôt qu'un simple haptique — l'user doit savoir
      // pourquoi le brouillon n'arrive pas.
      const msg = String(err?.message || err);
      if (msg.includes("timeout") || msg.includes("trop longue")) {
        toast.error("Génération trop longue — réessaie ta dictée", 5000);
      } else if (msg.includes("Rate limit") || msg.includes("429")) {
        toast.warning("Trop de demandes — patiente quelques secondes", 5000);
      } else {
        toast.error("Brouillon non généré — vérifie ta connexion", 5000);
      }
      speak(dt("tts.errorTryAgain"), () => {
        dispatchEvent({ type: "RECOVER", to: "listening" });
        setError(null);
        startListening();
      });
      dispatchEvent({ type: "DRAFT_FAILED" });
    }
  }, [stopListening, speak, speakAndListen, startListening, updateDraft, safeTimeout, next, playEarcon]);

  // ── Archive / Supprimer ───────────────────────────────────────────────────
  // Audit TTS 2026-04-28 : skip TTS "Archivé"/"Supprimé" (~700ms chacun) en
  // faveur d'un haptic notification distinct. L'user vient juste d'agir, il
  // sait qu'il a agi — la confirmation parlée est de la politesse coûteuse.
  // Différenciation sémantique : Success (archive, neutre) vs Warning
  // (delete, destructif). Permet à l'user en voiture de reconnaître
  // l'action au seul ressenti.
  // Act-then-undo : l'earcon joue et la session avance IMMÉDIATEMENT (zéro
  // attente réseau dans le flow vocal) ; l'appel API part dans UNDO_ACTION_MS,
  // annulable à la voix (« annule ») via handleVoiceInput. Échec API différé →
  // earcon alert + haptic + toast (backstop visuel), stats recréditées.
  const archiveAndNext = useCallback(async () => {
    stopListening();
    const emailId = coreRef.current.currentEmail?.id;
    if (emailId) {
      coreRef.current = bumpStat(coreRef.current, "archived");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      playEarcon("tick"); // archive = neutre
      pendingActionsRef.current.schedule(
        "archive",
        emailId,
        UNDO_ACTION_MS,
        async () => { await archiveEmail(emailId); },
        (err: any) => {
          console.warn("[drive] archive failed:", err?.message || err);
          coreRef.current = bumpStat(coreRef.current, "archived", -1);
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
          playEarcon("alert");
          toast.warning("Archivage échoué — vérifie ta connexion");
        },
      );
    }
    safeTimeout(() => next(), 100);
  }, [stopListening, next, safeTimeout, playEarcon]);

  const deleteAndNext = useCallback(async () => {
    stopListening();
    const emailId = coreRef.current.currentEmail?.id;
    if (emailId) {
      coreRef.current = bumpStat(coreRef.current, "deleted");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
      playEarcon("alert"); // delete = destructif, ton sérieux
      pendingActionsRef.current.schedule(
        "delete",
        emailId,
        UNDO_ACTION_MS,
        async () => { await deleteEmailApi(emailId); },
        (err: any) => {
          console.warn("[drive] delete failed:", err?.message || err);
          coreRef.current = bumpStat(coreRef.current, "deleted", -1);
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
          playEarcon("alert");
          toast.warning("Suppression échouée — vérifie ta connexion");
        },
      );
    }
    safeTimeout(() => next(), 100);
  }, [stopListening, next, safeTimeout, playEarcon]);

  // ── Modification du brouillon (instruction libre) ────────────────────────
  // Utilisé par le path keyword (reviewing + MODIFY) ET par le voice agent
  // (action MODIFY{instruction}).
  const applyModify = useCallback(async (instruction: string) => {
    if (!instruction || !coreRef.current.currentEmail) return;
    stopListening();
    dispatchEvent({ type: "GENERATE" });
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    safeTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium), 100);
    try {
      const mode = coreRef.current.replyMode || "reply";
      const replyType: "reply" | "reply_all" = mode === "reply_all" ? "reply_all" : "reply";
      const result = await generateProcessDraftFast(coreRef.current.currentEmail.id, instruction, replyType);
      updateDraft(result.content, result.draft_id);
      dispatchEvent({ type: "REVIEW" });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      speak(result.content, () => startListening());
    } catch (err: any) {
      setError(err.message);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      speak(dt("tts.problemRetry"), () => {
        dispatchEvent({ type: "RECOVER", to: "listening" });
        setError(null);
        startListening();
      });
    }
  }, [stopListening, speak, startListening, updateDraft, safeTimeout]);
  // ── Approve + next ───────────────────────────────────────────────────────
  // Act-then-undo : l'envoi réel part dans SEND_UNDO_MS — « annule » pendant
  // la fenêtre récupère le brouillon même APRÈS l'earcon « done ». C'est
  // l'assurance la moins chère contre le pire scénario du mode mains-libres :
  // un email rédigé par l'AI, envoyé sans relecture, les yeux sur la route.
  //
  // F02 (HIGH, historique) : l'échec d'envoi ne doit JAMAIS être silencieux.
  // L'envoi étant désormais différé, on a déjà avancé quand l'API répond — le
  // « loud failure » passe par earcon alert + haptic Error + toast persistant
  // (le brouillon reste pending, récupérable dans Brouillons), plus le
  // recrédit des stats. Pas de TTS par-dessus la lecture de l'email suivant.
  const approveDraftAndNext = useCallback(async () => {
    stopListening();
    // Si un envoi différé (undo_window) était armé, son timer est désormais
    // consommé — on le neutralise pour éviter un double approve.
    if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
    const id = coreRef.current.draftId;
    if (id) {
      coreRef.current = bumpStat(coreRef.current, "approved");
      pendingActionsRef.current.schedule(
        "send",
        id,
        SEND_UNDO_MS,
        async () => { await approveDraft(id); },
        (err: any) => {
          console.warn("[useDriveMode] approveDraft failed:", err);
          coreRef.current = bumpStat(coreRef.current, "approved", -1);
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
          playEarcon("alert");
          toast.error("Envoi échoué — brouillon conservé dans Brouillons", 6000);
        },
      );
    }
    // Audit TTS 2026-04-28 : haptic combo Success+Heavy distinct (signature
    // unique reconnaissable au volant) au lieu du "Envoyé." parlé. L'user
    // vient de confirmer "envoie" à voix haute — il sait qu'il envoie.
    // Le delay configurable (auto_advance) reste en place pour qui veut
    // un break entre emails.
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
    playEarcon("done"); // accord "envoyé"
    const [advanceRaw, delayRaw] = await Promise.all([
      SecureStore.getItemAsync("voice_auto_advance"),
      SecureStore.getItemAsync("voice_auto_advance_delay"),
    ]);
    if (advanceRaw === "true") {
      const ms = parseInt(delayRaw || "2", 10) * 1000;
      safeTimeout(() => next(), ms);
    } else {
      next();
    }
  }, [stopListening, next, safeTimeout, playEarcon]);

  // ── Step 3 : fenêtre d'annulation après un envoi implicite ───────────────
  // L'user a dit "…et envoie" et on a lu le brouillon. On AGIT : envoi différé
  // de UNDO_WINDOW_MS, mic ouvert. Toute parole annule (cancelPendingSend) ;
  // sinon on approuve à l'expiration. Remplace la question parlée "J'envoie ?".
  const enterUndoWindow = useCallback(() => {
    dispatchEvent({ type: "SEND_SCHEDULED" });
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    playEarcon("tick"); // "noté, j'envoie" (le "done" se joue à l'envoi réel)
    // Annonce affirmative de l'action en cours (design audio 2026-07-30) —
    // toute parole pendant la fenêtre annule. Le micro s'ouvre après
    // l'annonce ; UNDO_WINDOW_MS est passé à 5 s pour compenser sa durée.
    speak(dt("tts.sendingNow", { defaultValue: "J'envoie." }), () => {
      // La fenêtre a pu être annulée (tap) pendant l'annonce — ne pas
      // ré-armer une écoute par-dessus celle du chemin d'annulation.
      if (coreRef.current.state !== "undo_window") return;
      startListening(); // capte un éventuel "annule"
    });
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    // M-P1c : à l'expiration, si l'utilisateur est EN TRAIN de parler (« annule »
    // dont le transcript n'est pas encore arrivé — le STT batch a ~1,5 s de
    // latence), on NE confirme pas : on attend que le transcript soit traité.
    // Le bloc undo_window (toute parole = cancelPendingSend) tranchera alors.
    // Borne dure (max 2 reports) : même si le flag de capture restait coincé,
    // on finit TOUJOURS par envoyer ou annuler — jamais d'état bloqué sans
    // recours (défense en profondeur après la régression du flag).
    let deferLeft = 2;
    const fire = () => {
      undoTimerRef.current = null;
      if (coreRef.current.state !== "undo_window") return;
      if (coreRef.current.voiceCaptureActive && deferLeft > 0) {
        deferLeft--;
        undoTimerRef.current = safeTimeout(fire, 1500); // laisse le transcript finir
        return;
      }
      approveDraftAndNext();
    };
    undoTimerRef.current = safeTimeout(fire, UNDO_WINDOW_MS);
  }, [playEarcon, speak, startListening, safeTimeout, approveDraftAndNext]);

  // Wire le ref pour generateDraft (défini plus haut) — casse le cycle.
  useEffect(() => { enterUndoWindowRef.current = enterUndoWindow; }, [enterUndoWindow]);
  useEffect(() => { cancelPendingSendRef.current = cancelPendingSend; }, [cancelPendingSend]);

  // ── Approve contextuel (boutons UI) ─────────────────────────────────────
  const approveContextual = useCallback(async () => {
    const s = coreRef.current.state;
    if (s === "asking_preview") {
      stopListening();
      dispatchEvent({ type: "SPEAK" });
      speak(coreRef.current.draftContent ?? "", () => {
        speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), () => {
          dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
          playEarcon("turn"); startListening();
        });
      });
      return;
    }
    if (s === "confirming_dictation" && coreRef.current.dictationBuffer.length > 0) {
      const buffer = coreRef.current.dictationBuffer.join(". ");
      coreRef.current = clearDictation(coreRef.current);
      clearDictationTimerRef.current();
      await generateDraft(buffer);
      return;
    }
    await approveDraftAndNext();
  }, [stopListening, speak, startListening, generateDraft, approveDraftAndNext]);

  const rejectAndRelisten = useCallback(() => {
    // Step 3 — pendant un envoi différé, "reject"/tap-undo = annuler l'envoi
    // et GARDER le brouillon (pas re-dicter de zéro).
    if (coreRef.current.state === "undo_window") { cancelPendingSend(); return; }
    coreRef.current = clearDictation(coreRef.current);
    clearDictationTimerRef.current();
    updateDraft(null, null);
    dispatchEvent({ type: "REPLY_CHOSEN" });
    speak(dt("tts.redictate"), () => startListening());
  }, [speak, startListening, updateDraft, cancelPendingSend]);

  return {
    cancelPendingSend, generateDraft, archiveAndNext, deleteAndNext,
    applyModify, approveDraftAndNext, approveContextual, rejectAndRelisten,
  };
}
