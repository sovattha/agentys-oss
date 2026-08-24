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
 * useVoiceRouter — routeur vocal du Drive Mode (#1124 étape 3).
 *
 * Sommet du graphe : `handleVoiceInput` reçoit chaque transcript (keyword
 * matcher → tail-command → LLM voice agent en fallback) et route vers les
 * actions ; `executeAgentActions` rejoue la liste ordonnée d'actions du
 * backend /api/voice/agent sur les MÊMES handlers que le path keyword.
 *
 * Extrait verbatim de useDriveMode : le hook destructure un contexte aux
 * noms IDENTIQUES aux symboles d'origine — le corps n'a subi AUCUNE
 * modification (diff de comportement nul). reset/resumeSession arrivent via
 * leurs function refs (définis après le call site dans la façade).
 */

import { useCallback, useRef, type MutableRefObject } from "react";
import * as Haptics from "expo-haptics";
import i18n from "../i18n";
import { toast } from "../lib/toast";
import { voiceMetrics } from "../lib/voiceMetrics";
import { voiceAgent, type VoiceAgentAction } from "../services/api";
import type { PendingActionManager } from "../lib/pendingActions";
import type { DriveCore, DriveEvent } from "./driveReducer";
import { pushDictation, clearDictation, setCoreFlag, bumpStat } from "./driveReducer";
import type { DriveState, ReplyMode, SessionStats, SessionMode } from "../types";
import {
  UNDO_RE,
  detectCommand,
  isEndOfDictation,
  isSendUtterance,
  isCancelUtterance,
  extractSendDisposition,
  isSpokenAckCommand,
} from "../lib/driveCommands";
import type { SpokenAck } from "../lib/driveCommands";

/** Helper TTS — même définition que dans useDriveMode (ns drive). */
const dt = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "drive", ...(opts ?? {}) }) as string;

export interface VoiceRouterCtx {
  coreRef: MutableRefObject<DriveCore>;
  /** §2.3 : SEUL chemin de transition du routeur (rejet bruyant + trace).
   *  Surface migrée le 2026-07-18 — plus aucun setState ici. */
  dispatchEvent: (e: DriveEvent) => boolean;
  setReplyMode: (m: ReplyMode | null) => void;
  setError: (e: string | null) => void;
  /** P2.5 : label du badge « ✓ commande » — posé ici au parse, consommé par
   *  dispatchEvent qui ne flashe QUE si la transition est acceptée. */
  pendingFlashRef: MutableRefObject<string | null>;
  /** Pendant parlé du badge : accusé candidat, posé au parse et consommé par
   *  dispatchEvent. `at` sert de garde d'obsolescence — une commande qui ne
   *  déclenche aucune transition (ex. « précédent » sur le 1er email) ne doit
   *  pas faire parler l'app dix minutes plus tard. */
  pendingAckRef: MutableRefObject<SpokenAck | null>;
  setIdleListening: (v: boolean) => void;
  updateDraft: (content: string | null, id: string | null) => void;

  speak: (text: string, onDone?: () => void) => void;
  startListening: () => void;
  stopListening: () => void;
  stopTts: () => Promise<void>;
  playEarcon: (name: "turn" | "tick" | "done" | "alert") => void;

  next: () => void;
  previous: () => void;
  chooseReply: (mode: ReplyMode) => void;
  generateDraft: (text: string, opts?: { autoSend?: boolean }) => Promise<void>;
  applyModify: (instruction: string) => Promise<void>;
  archiveAndNext: () => Promise<void>;
  deleteAndNext: () => Promise<void>;
  approveDraftAndNext: () => Promise<void>;
  rejectAndRelisten: () => void;
  cancelPendingSend: () => void;

  resetRef: MutableRefObject<() => void>;
  resumeSessionRef: MutableRefObject<() => void>;

  agentHistoryRef: MutableRefObject<Array<{ role: "user" | "assistant"; content: string }>>;
  clearDictationTimerRef: MutableRefObject<() => void>;
  armDictationSilenceRef: MutableRefObject<() => void>;
  pendingActionsRef: MutableRefObject<PendingActionManager>;
  undoTimerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>;
  idleModeCallbackRef: MutableRefObject<((mode: SessionMode) => void) | null>;

  safeTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
}

export function useVoiceRouter(ctx: VoiceRouterCtx): { handleVoiceInput: (text: string) => Promise<void> } {
  const {
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
  } = ctx;

  // Hint « J'envoie ? » émis une seule fois par cycle asking_send — remis à
  // zéro dès qu'une réponse reconnue aboutit (envoi ou relecture).
  const askSendHintedRef = useRef(false);

  // ── Exécuteur des actions du voice agent ─────────────────────────────────
  // Le backend /api/voice/agent renvoie une liste ordonnée d'actions
  // (intents composés : « archive ça et lis-moi le suivant »). On les rejoue
  // séquentiellement sur les MÊMES handlers que le path keyword.
  //
  // Subtilité : ARCHIVE/DELETE/APPROVE avancent déjà à l'email suivant
  // (« …AndNext ») — un NEXT immédiatement après est dédupliqué pour ne pas
  // sauter un email de plus que demandé.
  const executeAgentActions = useCallback(async (actions: VoiceAgentAction[]) => {
    const priorState = coreRef.current.state;

    // Rouvre le mic dans un état interactif sûr — filet anti-impasse (M-P1d).
    const recoverToListening = () => {
      const back =
        (["choosing", "asking_send", "asking_preview", "reviewing", "listening"] as const)
          .includes(priorState as never)
          ? (priorState as "choosing" | "asking_send" | "asking_preview" | "reviewing" | "listening")
          : "choosing";
      dispatchEvent({ type: "RECOVER", to: back });
      if (back === "asking_send") playEarcon("turn");
      startListening();
    };

    // M-P2b/c : on parle d'ABORD toutes les réponses SAY (concaténées), AVANT
    // les actions qui avancent — sinon archiveAndNext/next() couperaient la
    // réponse (et la Promise du speak resterait pendante). En Q&A pure (aucune
    // autre action), on revient à l'état interactif d'origine — y compris
    // `listening` pour ne PAS jeter une dictée en cours.
    const sayTexts = actions.filter((a) => a.type === "SAY").map((a) => (a as { text: string }).text);
    const rest = actions.filter((a) => a.type !== "SAY");

    if (sayTexts.length > 0) {
      for (const t of sayTexts) agentHistoryRef.current.push({ role: "assistant", content: t });
      if (agentHistoryRef.current.length > 8) {
        agentHistoryRef.current = agentHistoryRef.current.slice(-8);
      }
      stopListening();
      dispatchEvent({ type: "SPEAK" });
      await new Promise<void>((resolve) => speak(sayTexts.join(" "), resolve));
      if (rest.length === 0) {
        recoverToListening();
        return;
      }
    }

    let skipFollowingNext = false;
    let handled = false; // un branche a-t-elle avancé / rouvert le mic ?
    for (let i = 0; i < rest.length; i++) {
      const action = rest[i];

      if (action.type === "NEXT" && skipFollowingNext) {
        skipFollowingNext = false;
        continue;
      }
      skipFollowingNext = false;

      // Le chemin LLM (phrases libres : « passe au suivant », « jette-moi
      // ça ») exécute les MÊMES actions que le chemin mots-clés — il doit donc
      // les annoncer pareil, sinon l'accusé parlé dépendrait de la façon dont
      // l'utilisateur a formulé sa demande. Consommé par dispatchEvent comme
      // au parse : une action rejetée par la machine n'annonce rien.
      if (isSpokenAckCommand(action.type)) {
        pendingAckRef.current = {
          label: dt(`cmdAck.${action.type}`, { defaultValue: "" }),
          at: Date.now(),
        };
      }

      switch (action.type) {
        case "DRAFT_REPLY": {
          setReplyMode(action.reply_type);
          await generateDraft(action.content, { autoSend: action.auto_send });
          return; // generateDraft pilote la suite du flow (lecture, envoi…)
        }
        case "MODIFY": {
          await applyModify(action.instruction);
          return;
        }
        case "REPLY":     stopTts(); chooseReply("reply");     return;
        case "REPLY_ALL": stopTts(); chooseReply("reply_all"); return;
        case "FORWARD":   stopTts(); chooseReply("forward");   return;
        case "ARCHIVE":   stopTts(); await archiveAndNext();   skipFollowingNext = true; handled = true; break;
        case "DELETE":    stopTts(); await deleteAndNext();    skipFollowingNext = true; handled = true; break;
        case "APPROVE": {
          if (coreRef.current.draftContent) {
            stopTts();
            await approveDraftAndNext();
            skipFollowingNext = true;
            handled = true;
          }
          break; // sans draft : no-op → filet recoverToListening en sortie
        }
        case "REJECT": {
          if (coreRef.current.draftContent) { rejectAndRelisten(); return; }
          break;
        }
        case "NEXT":     stopTts(); next();     handled = true; break;
        case "PREVIOUS": stopTts(); previous(); handled = true; break;
        case "REPEAT":
        case "READ_DRAFT": {
          stopListening();
          stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
          if (coreRef.current.draftContent && action.type !== "REPEAT") {
            dispatchEvent({ type: "SPEAK" });
            await new Promise<void>((resolve) => speak(coreRef.current.draftContent!, resolve));
            await new Promise<void>((resolve) => speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), resolve));
            dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
            playEarcon("turn");
            startListening();
            return;
          }
          // REPEAT context-aware : draft chargé → draft, sinon email courant.
          const target = coreRef.current.draftContent ?? coreRef.current.currentEmail?.speakable_text;
          if (target) {
            const after = coreRef.current.draftContent ? ("asking_send" as const) : ("choosing" as const);
            dispatchEvent({ type: "SPEAK" });
            await new Promise<void>((resolve) => speak(target, resolve));
            if (after === "asking_send") {
              await new Promise<void>((resolve) => speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), resolve));
            }
            dispatchEvent({ type: "TTS_DONE", next: after });
            if (after === "asking_send") playEarcon("turn");
            startListening();
          } else {
            recoverToListening(); // rien à relire → ne pas rester muet
          }
          return;
        }
        case "READ_EMAIL": {
          const sp = coreRef.current.currentEmail;
          if (sp) {
            stopListening();
            stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
            dispatchEvent({ type: "SPEAK" });
            await new Promise<void>((resolve) => speak(sp.speakable_text, resolve));
            dispatchEvent({ type: "TTS_DONE", next: "choosing" });
            startListening();
          } else {
            recoverToListening();
          }
          return;
        }
        case "PAUSE": {
          stopListening();
          stopTts();
          clearDictationTimerRef.current();
          dispatchEvent({ type: "PAUSE" });
          coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
          speak(dt("tts.paused"), () => startListening());
          return;
        }
        case "RESUME": {
          if (coreRef.current.state === "paused") resumeSessionRef.current();
          else recoverToListening(); // déjà actif → rouvre le mic, pas de silence
          return;
        }
        case "STOP": resetRef.current(); return;
        case "CANCEL_REPLY": {
          stopListening();
          stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
          clearDictationTimerRef.current();
          coreRef.current = clearDictation(coreRef.current);
          updateDraft(null, null);
          setReplyMode(null);
          setError(null);
          toast.info("Réponse annulée");
          dispatchEvent({ type: "DICTATION_CANCELLED" });
          speak(dt("tts.replyCancelled", { defaultValue: "Réponse annulée. Que veux-tu faire ?" }), () => startListening());
          return;
        }
        default:
          break;
      }
    }
    // Filet M-P1d : aucune action n'a avancé ni rouvert le mic (APPROVE/REJECT
    // sans draft, action inconnue) → ne pas laisser l'utilisateur dans le
    // silence mic fermé.
    if (!handled) recoverToListening();
  }, [
    speak, startListening, stopListening, stopTts, chooseReply, next, previous,
    generateDraft, applyModify, archiveAndNext, deleteAndNext, updateDraft,
    playEarcon,
  ]);

  // ── Routeur vocal principal ──────────────────────────────────────────────
  const handleVoiceInput = useCallback(async (text: string) => {
    // 1) Keyword detector d'abord (sync, instantané, couvre 80% des cas).
    let cmd: ReturnType<typeof detectCommand> = detectCommand(text);
    const curState = coreRef.current.state;
    const lower    = text.toLowerCase().trim();

    // 1bis) Act-then-undo : une action différée (archive/delete/send) est
    //    encore annulable — « annule »/« undo » la récupère. Vérifié AVANT
    //    tout le reste : la fenêtre ne dure que quelques secondes.
    //    Gardes (M-P2a) : (a) PAS dans les états de dictée — « annule le
    //    rendez-vous » y est du CONTENU, pas une commande ; (b) PAS en
    //    undo_window — son bloc dédié gère l'envoi implicite (cancelPendingSend)
    //    et ne doit pas annuler par erreur une vieille action archive en file.
    const undoEligibleState =
      curState !== "listening" && curState !== "confirming_dictation" && curState !== "undo_window";
    if (undoEligibleState && pendingActionsRef.current.count() > 0 && UNDO_RE.test(lower)) {
      const cancelled = pendingActionsRef.current.cancelLast();
      if (cancelled) {
        voiceMetrics.counter("undo_cancels", curState);
        if (cancelled.kind === "send") coreRef.current = bumpStat(coreRef.current, "approved", -1);
        else if (cancelled.kind === "archive") coreRef.current = bumpStat(coreRef.current, "archived", -1);
        else coreRef.current = bumpStat(coreRef.current, "deleted", -1);
        stopListening();
        stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
        playEarcon("tick");
        toast.info(
          cancelled.kind === "send" ? "Envoi annulé — brouillon conservé" :
          cancelled.kind === "archive" ? "Archivage annulé" : "Suppression annulée",
        );
        dispatchEvent({ type: "RECOVER", to: "choosing" });
        speak(dt("tts.undone", { defaultValue: "Annulé." }), () => startListening());
        return;
      }
    }

    // 2) Si le keyword fail (cmd null ou free_text), fallback voice AGENT.
    //    Remplace l'ancien /voice/intent mono-action : intents composés
    //    (« archive ça et lis-moi le suivant »), dictée inline (« réponds-lui
    //    que ok pour jeudi et envoie »), questions sur l'email courant
    //    (« il proposait quelle heure ? » → réponse parlée).
    //    Exceptions : pas en idle (sélection de mode locale), et pas pour les
    //    LONGUES utterances en états de dictée (c'est du contenu, pas une
    //    commande — le buffer local s'en charge sans payer ~1 s de LLM).
    // M-P1b : en undo_window, on NE consulte PAS l'agent (4 s de LLM) — son
    // timer d'envoi (UNDO_WINDOW_MS) tournerait en parallèle et enverrait
    // l'email pendant l'appel, alors que l'utilisateur parle PRÉCISÉMENT pour
    // l'arrêter. Le bloc undo_window plus bas tranche immédiatement (toute
    // parole = annulation). Géré en sortant tôt si rien d'autre n'a matché.
    if (!cmd || cmd === "free_text") {
      const isDictationState = curState === "listening" || curState === "confirming_dictation";
      const wordCount = lower.split(/\s+/).length;
      const agentEligible =
        curState !== "idle" && curState !== "undo_window" && (!isDictationState || wordCount <= 5);
      if (agentEligible) {
        try {
          const agentResult = await Promise.race([
            voiceAgent(text, {
              state: curState,
              email_id: coreRef.current.currentEmail?.id,
              has_draft: !!coreRef.current.draftContent,
              draft_excerpt: coreRef.current.draftContent?.slice(0, 600) ?? undefined,
              history: agentHistoryRef.current.slice(-8),
            }),
            new Promise<never>((_, rej) =>
              setTimeout(() => rej(new Error("agent timeout")), 4000),
            ),
          ]);
          if (
            agentResult && agentResult.source === "llm" &&
            agentResult.confidence >= 0.6 && agentResult.actions.length > 0
          ) {
            console.log("[drive-agent] actions:", JSON.stringify(agentResult.actions), "conf", agentResult.confidence);
            agentHistoryRef.current.push({ role: "user", content: text.slice(0, 300) });
            if (agentHistoryRef.current.length > 8) agentHistoryRef.current.shift();
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
            await executeAgentActions(agentResult.actions);
            return;
          }
          if (agentResult && agentResult.source === "llm" && agentResult.actions.length === 0 &&
              !isDictationState) {
            // L'agent a compris « rien d'actionnable » (bruit, conversation
            // tierce) — friction silencieuse à mesurer. (undo_window déjà
            // exclu par agentEligible.)
            voiceMetrics.counter("command_misses", curState);
          }
        } catch (err: any) {
          console.log("[drive-agent] fallback skipped:", err?.message || err);
        }
      }
    }

    // Flash visuel — P2.5 : le badge n'est plus posé au parse mais par la
    // PREMIÈRE transition ACCEPTÉE que cette commande déclenche (dispatchEvent
    // consomme pendingFlashRef, un rejet l'invalide). Fini le « ça flashe mais
    // rien ne se passe ». Le haptique reste au parse : accusé « compris ».
    if (cmd && cmd !== "free_text") {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      pendingFlashRef.current = dt(`cmdLabel.${cmd}`, { defaultValue: cmd });
      // Accusé PARLÉ — même rail que le badge (posé au parse, consommé par la
      // première transition ACCEPTÉE) : au volant l'écran n'est pas regardé,
      // donc « compris » doit s'entendre, pas seulement clignoter.
      pendingAckRef.current = isSpokenAckCommand(cmd)
        ? { label: dt(`cmdAck.${cmd}`, { defaultValue: "" }), at: Date.now() }
        : null;
    }

    // ── Idle listening : sélection du mode avant session ──────────────────
    if (curState === "idle" && coreRef.current.idleListeningActive) {
      let mode: SessionMode | null = null;
      if (lower.includes("action")) mode = "actions";
      else if (lower.includes("info"))  mode = "infos";
      else if (lower.includes("tout") || lower.includes("tous") || lower.includes("deux")) mode = "mixed";
      if (mode && idleModeCallbackRef.current) {
        coreRef.current = setCoreFlag(coreRef.current, "idleListeningActive", false);
        setIdleListening(false);
        stopListening();
        const cb = idleModeCallbackRef.current;
        idleModeCallbackRef.current = null;
        cb(mode);
      }
      return;
    }

    // ── Step 3 : fenêtre d'annulation (envoi implicite "…et envoie") ──────
    // Un envoi différé est armé. Une confirmation explicite l'exécute tout
    // de suite ; TOUTE autre parole l'annule et garde le brouillon (reviewing).
    // Placé AVANT le fail-safe de relecture pour qu'aucun "lis-le" ne passe.
    if (curState === "undo_window") {
      const confirmNow =
        cmd === "APPROVE" || lower.startsWith("oui") || lower === "ok" || lower === "go" ||
        lower.includes("envoie") || lower.includes("envoyer") || lower.includes("send");
      if (confirmNow) {
        if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null; }
        await approveDraftAndNext();
        return;
      }
      cancelPendingSend();
      return;
    }

    // ── Lecture du draft (fail-safe global) ──────────────────────────────
    // Capture les variantes "lis le draft", "lis-le", "écoute le brouillon",
    // "read it", "play", "joue-le" peu importe l'état courant — du moment
    // qu'un draft est chargé en mémoire. Évite les frustrations où
    // l'utilisateur essaie d'entendre le draft depuis un état inattendu.
    const wantsDraftRead =
      coreRef.current.draftContent && coreRef.current.draftContent.trim().length > 0 && (
        /^(lis|lit|lisez|écoute|écoutez|joue|read|play)([\s\-,.!?]|$)/i.test(text.trim()) ||
        lower.includes(" le draft") ||
        lower.includes(" le brouillon") ||
        lower.includes("-le moi") ||
        lower.includes(" the draft") ||
        lower === "lis-le" || lower === "lis le" || lower === "lis-le moi" ||
        lower === "écoute" || lower === "écoute-le" || lower === "joue-le" ||
        lower === "read it" || lower === "read the draft" || lower === "play it"
      );
    if (wantsDraftRead) {
      console.log("[drive] wantsDraftRead matched in state:", curState, "transcript:", JSON.stringify(text));
      stopListening();
      stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
      // F4 fix : si l'user demande à entendre le draft depuis un état
      // "non-draft" (choosing typiquement, peu probable mais possible si
      // un draft est resté en mémoire d'un email précédent), on revient
      // à `choosing` après lecture — pas à asking_preview qui reposerait
      // une question redondante "tu veux l'écouter ?" et créerait une
      // boucle si l'user redit "lis-le".
      const stateAfter =
        curState === "asking_preview" ? ("asking_send" as const) :
        curState === "asking_send" ? ("asking_send" as const) :
        curState === "reviewing" ? ("reviewing" as const) :
        curState === "choosing" ? ("choosing" as const) :
        ("asking_preview" as const);
      dispatchEvent({ type: "SPEAK" });
      // IMPORTANT : utiliser `speak` (mode Playback → speaker fort) plutôt
      // que `speakAndListen` (mode PlayAndRecord → earpiece quiet sur iOS).
      // C'est la cause racine du bug "j'ai demandé à entendre le draft et
      // ça ne fonctionne pas" : la lecture via speakAndListen partait dans
      // l'écouteur téléphonique. Pas de barge-in possible ici, mais le user
      // peut tap sur les chips pour interrompre.
      speak(coreRef.current.draftContent!, () => {
        if (stateAfter === "asking_preview") {
          // Cible hors union TTS_DONE.next — filet RECOVER équivalent.
          dispatchEvent({ type: "RECOVER", to: "asking_preview" });
        } else {
          dispatchEvent({ type: "TTS_DONE", next: stateAfter });
        }
        if (stateAfter === "asking_send") {
          playEarcon("turn"); startListening(); // "à toi" (remplace le "J'envoie ?" parlé)
        } else {
          startListening();
        }
      });
      return;
    }

    // ── Commandes globales ─────────────────────────────────────────────────
    if (cmd === "STOP") { resetRef.current(); return; }

    // F7 — Annule la réponse en cours, retour à choosing sans fermer la
    // session. Pertinent dans tout state qui n'est pas idle/choosing/speaking
    // (où "annule" n'a pas de sens contextuel).
    // Device 2026-08-04 : « Annulé. » seul en relecture partait en texte
    // libre → REGÉNÉRATION du brouillon avec "Annulé" comme instruction. En
    // states de REVUE (brouillon existant, pas de dictée en cours), un
    // « annule » en énoncé entier est sans ambiguïté → même chemin que
    // CANCEL_REPLY. Les states de dictée restent exclus (prudence : « j'annule
    // mon vol » est du contenu).
    const bareCancelInReview =
      isCancelUtterance(text) &&
      (["reviewing", "asking_preview", "asking_send"] as DriveState[]).includes(curState);
    if (cmd === "CANCEL_REPLY" || bareCancelInReview) {
      const cancellableStates: DriveState[] = [
        "listening", "confirming_dictation", "generating",
        "asking_preview", "asking_send", "reviewing",
      ];
      if (cancellableStates.includes(curState)) {
        stopListening();
        stopTts().catch(() => {}); // no-op légitime : déjà à l'arrêt
        clearDictationTimerRef.current();
        coreRef.current = clearDictation(coreRef.current);
        updateDraft(null, null);
        setReplyMode(null);
        setError(null);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
        toast.info("Réponse annulée");
        dispatchEvent({ type: "DICTATION_CANCELLED" });
        speak(dt("tts.replyCancelled", { defaultValue: "Réponse annulée. Que veux-tu faire ?" }), () => startListening());
      }
      return;
    }

    if (cmd === "PAUSE") {
      stopListening();
      stopTts();
      clearDictationTimerRef.current();
      dispatchEvent({ type: "PAUSE" });
      coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
      speak(dt("tts.paused"), () => startListening());
      return;
    }

    if (cmd === "RESUME" && curState === "paused") { resumeSessionRef.current(); return; }

    // REPEAT — context-aware : si un draft est chargé (states post-génération),
    // on relit le draft, sinon l'email courant. Évite le bug "j'ai dit
    // 'réécoute' en attendant d'entendre le brouillon mais il m'a relu l'email".
    if (cmd === "REPEAT") {
      const draftStates: DriveState[] = ["asking_preview", "asking_send", "reviewing"];
      if (draftStates.includes(curState) && coreRef.current.draftContent) {
        stopListening();
        dispatchEvent({ type: "SPEAK" });
        // Plain `speak` (Playback → speaker fort) au lieu de `speakAndListen`
        // (PlayAndRecord → earpiece quiet sur iOS). Sans ça la relecture du
        // draft se faisait dans l'écouteur téléphonique, inaudible.
        speak(coreRef.current.draftContent, () => {
          if (curState === "asking_preview") {
            speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), () => {
              dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
              playEarcon("turn"); startListening();
            });
          } else {
            // Retour à l'état d'origine après relecture : self-loop — l'état
            // n'a pas bougé côté machine (SPEAK ne fut pas émis sur ce chemin).
            startListening();
          }
        });
        return;
      }
      const sp = coreRef.current.currentEmail;
      if (sp) {
        stopListening();
        dispatchEvent({ type: "SPEAK" });
        speak(sp.speakable_text, () => { dispatchEvent({ type: "TTS_DONE", next: "choosing" }); startListening(); });
      }
      return;
    }

    // ── Speaking : commandes interceptées via TTS clean ──────────────────
    // En Phase 1, le pattern speakAndListen est supprimé donc handleVoiceInput
    // n'est jamais appelé en state="speaking" depuis un parallel listen. Le
    // bloc reste (dead code logique) au cas où une commande arrive via tap UI
    // qui simule une commande pendant la lecture.
    if (curState === "speaking") {
      if (cmd === "REPLY")     { stopTts(); chooseReply("reply");     return; }
      if (cmd === "REPLY_ALL") { stopTts(); chooseReply("reply_all"); return; }
      if (cmd === "FORWARD")   { stopTts(); chooseReply("forward");   return; }
      if (cmd === "NEXT")      { stopTts(); next();                   return; }
      if (cmd === "PREVIOUS")  { stopTts(); previous();               return; }
      if (cmd === "ARCHIVE")   { stopTts(); await archiveAndNext();   return; }
      if (cmd === "DELETE")    { stopTts(); await deleteAndNext();    return; }
      // Draft-context : APPROVE/REJECT/MODIFY ne sont pertinents que pendant
      // la lecture d'un draft (pas la lecture d'un email entrant). On les
      // gate sur la présence d'un draft chargé en mémoire.
      if (coreRef.current.draftContent) {
        if (cmd === "APPROVE") {
          stopTts();
          await approveDraftAndNext();
          return;
        }
        if (cmd === "REJECT" || cmd === "MODIFY") {
          stopTts();
          dispatchEvent({ type: "REVIEW" });
          speak(`${dt("tts.hereIsDraft")} ${coreRef.current.draftContent ?? ""}`, () => startListening());
          return;
        }
      }
      // Autres (free_text, etc.) ignorés — on laisse la TTS finir.
      return;
    }

    // ── Choosing ──────────────────────────────────────────────────────────
    if (curState === "choosing") {
      if (cmd === "REPLY")     { chooseReply("reply");     return; }
      if (cmd === "REPLY_ALL") { chooseReply("reply_all"); return; }
      if (cmd === "FORWARD")   { chooseReply("forward");   return; }
      if (cmd === "NEXT")      { next();                   return; }
      if (cmd === "PREVIOUS")  { previous();               return; }
      if (cmd === "ARCHIVE")   { await archiveAndNext();   return; }
      if (cmd === "DELETE")    { await deleteAndNext();    return; }
      return;
    }

    // ── Listening : dictée ────────────────────────────────────────────────
    if (curState === "listening") {
      if (cmd === "NEXT") {
        coreRef.current = clearDictation(coreRef.current);
        clearDictationTimerRef.current();
        next();
        return;
      }
      if (cmd === "ARCHIVE") { coreRef.current = clearDictation(coreRef.current); clearDictationTimerRef.current(); await archiveAndNext(); return; }
      if (cmd === "DELETE")  { coreRef.current = clearDictation(coreRef.current); clearDictationTimerRef.current(); await deleteAndNext();  return; }

      // « envoyer » seul pendant la dictée → clôt + rédige + envoie.
      // Retour device 2026-07 : après le tap fin-de-dictée, la transcription
      // in-flight de la dernière phrase rebascule confirming_dictation →
      // listening (branche contenu). Le « envoyer » de l'utilisateur arrive
      // donc ICI — il flashait (cmd APPROVE reconnu) mais était ajouté au
      // buffer comme contenu. isSendUtterance : utterance entière = verbe
      // d'envoi, tolérant aux homophones FR (« Envoyé. », « J'envoie »…).
      if (isSendUtterance(text) && coreRef.current.dictationBuffer.length > 0) {
        const buffer = coreRef.current.dictationBuffer.join(". ");
        coreRef.current = clearDictation(coreRef.current);
        clearDictationTimerRef.current();
        await generateDraft(buffer, { autoSend: true });
        return;
      }
      // « …, envoyez. » : contenu + ordre d'envoi dans la MÊME utterance
      // (retour device 2026-07-28 — l'ordre était bufferisé comme contenu).
      // extractSendDisposition ne matche que le suffixe explicite (connecteur
      // ou ponctuation + verbe), donc pas de faux positif sur un corps qui
      // mentionne « envoyer » au milieu.
      {
        const disp = extractSendDisposition(text);
        if (disp.send) {
          coreRef.current = pushDictation(coreRef.current, disp.body);
          const buffer = coreRef.current.dictationBuffer.join(". ");
          coreRef.current = clearDictation(coreRef.current);
          clearDictationTimerRef.current();
          await generateDraft(buffer, { autoSend: true });
          return;
        }
      }

      if (text.trim().length > 0) {
        // Audit TTS 2026-04-28 : phrase de fin explicite ("voilà", "c'est tout")
        // → on enchaîne DIRECTEMENT sur generateDraft. Avant ce changement,
        // on transitionnait via `confirming_dictation` + TTS "Je rédige ?" +
        // ré-écoute → ~3-5s de friction inutile pour un signal d'intent qui
        // était déjà clair. L'user peut toujours annuler en disant "annule"
        // pendant la génération (CANCEL_REPLY est cancellable depuis
        // `generating`).
        //
        // Le state `confirming_dictation` reste utilisé par (a) la safety
        // cap des 3 turns max (path AI-driven, pas user-driven), et (b) le
        // tap chip "yesDraft" depuis l'UI.
        if (isEndOfDictation(text) && coreRef.current.dictationBuffer.length > 0) {
          const buffer = coreRef.current.dictationBuffer.join(". ");
          coreRef.current = clearDictation(coreRef.current);
          clearDictationTimerRef.current();
          await generateDraft(buffer);
          return;
        }
        // Contenu → accumuler + armer le timer 3s
        coreRef.current = pushDictation(coreRef.current, text.trim());
        armDictationSilenceRef.current();
      }
      return;
    }

    // ── Confirming dictation : "Je peux rédiger l'email ?" ───────────────
    if (curState === "confirming_dictation") {
      // FR + EN : on accepte la lecture naturelle des chips ("oui, rédige" /
      // "yes, draft it"). "yes" + "draft" couvrent la quasi-totalité des
      // formulations EN (yes / yep / yeah / yes draft it / draft it / go ahead).
      const isYes = lower.startsWith("oui") || lower.startsWith("ouais") ||
        lower.startsWith("yes") || lower.startsWith("yep") || lower.startsWith("yeah") ||
        lower === "ok" || lower === "okay" || lower === "go" ||
        ["rédige", "compose", "génère", "oui",
         "draft", "go ahead", "do it", "write it"].some((w) => lower.includes(w));
      const isRedo = lower.startsWith("non") || lower.startsWith("no ") || lower === "no" ||
        lower.includes("recommence") || lower.includes("efface") || lower.includes("annule") ||
        lower.includes("redo") || lower.includes("restart") || lower.includes("start over");
      // « envoyer » explicite : intention plus forte que le simple « oui »
      // (rédige puis relis) — on rédige ET on envoie directement. Chemin
      // naturel après le tap fin-de-dictée (retour device 2026-07).
      // isSendUtterance : l'utterance ENTIÈRE est le verbe d'envoi, tolérant
      // aux homophones FR (« Envoyé. », « J'envoie », « Envoi »…) — une
      // phrase longue mentionnant « envoie » reste de la dictée continuée.
      const isSend = isSendUtterance(text);

      if (isSend && coreRef.current.dictationBuffer.length > 0) {
        const buffer = coreRef.current.dictationBuffer.join(". ");
        coreRef.current = clearDictation(coreRef.current);
        clearDictationTimerRef.current();
        await generateDraft(buffer, { autoSend: true });
        return;
      }
      // Suffixe « …, envoyez. » dans la même utterance — même logique que la
      // branche listening (retour device 2026-07-28).
      {
        const disp = extractSendDisposition(text);
        if (disp.send) {
          coreRef.current = pushDictation(coreRef.current, disp.body);
          const buffer = coreRef.current.dictationBuffer.join(". ");
          coreRef.current = clearDictation(coreRef.current);
          clearDictationTimerRef.current();
          await generateDraft(buffer, { autoSend: true });
          return;
        }
      }
      if (isYes && coreRef.current.dictationBuffer.length > 0) {
        const buffer = coreRef.current.dictationBuffer.join(". ");
        coreRef.current = clearDictation(coreRef.current);
        clearDictationTimerRef.current();
        await generateDraft(buffer);
        return;
      }
      if (isRedo) {
        coreRef.current = clearDictation(coreRef.current);
        clearDictationTimerRef.current();
        dispatchEvent({ type: "REPLY_CHOSEN" });
        speak(dt("tts.okRedictate"), () => startListening());
        return;
      }
      // Contenu libre → ajouter au buffer, continuer la dictée.
      // Audit TTS 2026-04-28 : retiré le "Noté. Continuez." qui interrompait
      // l'user en pleine dictée (~1.2s perdues + cassait le rythme). Haptic
      // selection (click discret) suffit comme accusé de réception.
      if (lower.split(" ").length >= 2) {
        coreRef.current = pushDictation(coreRef.current, text.trim());
        clearDictationTimerRef.current();
        dispatchEvent({ type: "REPLY_CHOSEN" });
        Haptics.selectionAsync().catch(() => {});
        startListening();
        armDictationSilenceRef.current();
        return;
      }
      // Mot isolé non reconnu (« Répondre », bruit transcrit, « envoyer »
      // avec buffer vide…) : ne JAMAIS mourir en silence — sans ré-écoute,
      // l'app est figée jusqu'au watchdog (vu device 2026-07-28 :
      // « Répondre. » en confirming → 19 s de silence radio). On reste en
      // confirming et on rouvre le micro.
      startListening();
      return;
    }

    // ── Asking preview : "Tu veux l'écouter avant d'envoyer ?" ───────────
    if (curState === "asking_preview") {
      // Matchers très permissifs — l'utilisateur attend un OUI sous forme
      // affirmative ("oui"/"ok") OU un verbe d'écoute conjugué ("lis-le",
      // "écoute", "joue") OU sa traduction anglaise ("read", "play", "go").
      // `includes("lis")` couvre "lis", "lis-le", "lis-moi", "tu lis ça".
      // `includes("écout")` couvre "écouter", "écoute", "écoutez", "réécoute".
      const isYes  = lower.startsWith("oui") || lower.startsWith("ouais") ||
        lower === "ok" || lower === "okay" || lower === "yes" || lower === "yep" ||
        ["écout", "lire", "lis", "lit ", "lisez", "entend",
         "joue", "play", "read", "vas-y", "vas y", "go"].some((w) => lower.includes(w));
      const isSkip = lower.startsWith("non") || lower.includes("direct") ||
        lower.includes("passer") || lower.includes("skip") || cmd === "NEXT";

      if (isYes) {
        const body = coreRef.current.draftContent?.trim() ?? "";
        if (!body) {
          // Garde-fou : si on entre asking_preview SANS draft chargé, lire
          // une chaîne vide via TTS échoue silencieusement et le state machine
          // re-cycle sans rien. Préviens l'user et retombe en choosing.
          console.warn("[drive] asking_preview but draftContent (core) is empty — skipping read");
          speak(dt("tts.errorTryAgain"), () => {
            dispatchEvent({ type: "TTS_DONE", next: "choosing" });
            startListening();
          });
          return;
        }
        stopListening();
        dispatchEvent({ type: "SPEAK" });
        // `speak` (Playback mode, speaker fort) plutôt que `speakAndListen`
        // (PlayAndRecord, earpiece quiet) — voir wantsDraftRead pour détail.
        speak(body, () => {
          speak(dt("tts.shouldSend", { defaultValue: "J'envoie ?" }), () => {
            dispatchEvent({ type: "TTS_DONE", next: "asking_send" });
            playEarcon("turn"); startListening();
          });
        });
        return;
      }
      // Audit TTS 2026-04-28 : si l'user dit explicitement "envoie/envoyer/send",
      // on exécute directement — pas de double confirmation théâtrale via
      // asking_send ("J'envoie ?" alors que l'user vient de dire send).
      // `isSkip` ("non / passer") garde le re-prompt asking_send car
      // sémantiquement ambigu (user a dit non à l'écoute, pas oui à l'envoi).
      // « envoi »+« envoy » couvrent TOUTE la famille homophone [ɑ̃vwaje]
      // (envoie/envoi → « envoi », envoyer/envoyez/envoyé → « envoy »).
      if (lower.includes("envoi") || lower.includes("envoy") ||
          lower.includes("send") || cmd === "APPROVE") {
        stopListening();
        await approveDraftAndNext();
        return;
      }
      if (isSkip) {
        stopListening();
        dispatchEvent({ type: "RECOVER", to: "asking_send" });
        playEarcon("turn"); startListening(); // "à toi" (remplace le "J'envoie ?" parlé)
        return;
      }
      if (cmd === "REJECT") {
        dispatchEvent({ type: "REVIEW" });
        speak(`${dt("tts.hereIsDraft")} ${coreRef.current.draftContent ?? ""}`, () => startListening());
        return;
      }
      // Phrase non reconnue : ré-écouter, jamais mourir en silence.
      startListening();
      return;
    }

    // ── Asking send : "J'envoie ?" ────────────────────────────────────────
    if (curState === "asking_send") {
      // « envoi »+« envoy » = famille homophone complète (3e occurrence du
      // même trou : « Envoyez. » en réponse à « J'envoie ? » était raté).
      const isSend = lower.startsWith("oui") || lower === "ok" || lower === "go" ||
        ["envoi", "envoy", "valider", "valide", "approuver", "approuve", "send"].some((w) => lower.includes(w));
      const isCancel = lower.startsWith("non") ||
        ["modifier", "modifie", "refaire", "refais", "changer", "annule"].some((w) => lower.includes(w));

      if (isSend) { askSendHintedRef.current = false; await approveDraftAndNext(); return; }
      if (isCancel || cmd === "REJECT" || cmd === "MODIFY") {
        askSendHintedRef.current = false;
        dispatchEvent({ type: "REVIEW" });
        speak(`${dt("tts.hereIsDraft")} ${coreRef.current.draftContent ?? ""}`, () => startListening());
        return;
      }
      // Phrase non reconnue (« Répondre. », « Ok, merci. ») : trace live
      // 2026-07-28 — le return muet laissait ~15 s de vide par tentative
      // (seul un nudge de secours rouvrait le micro). Hint parlé UNE fois
      // pour donner le vocabulaire attendu, puis ré-écoute directe.
      if (!askSendHintedRef.current) {
        askSendHintedRef.current = true;
        speak(dt("tts.askSendHint", { defaultValue: "J'envoie ? Dis « envoyer », ou « modifier »." }), () => startListening());
      } else {
        startListening();
      }
      return;
    }

    // ── Reviewing : modification manuelle ────────────────────────────────
    if (curState === "reviewing") {
      if (cmd === "APPROVE") { await approveDraftAndNext(); return; }
      if (cmd === "REJECT")  { rejectAndRelisten();         return; }
      if (cmd === "NEXT")    { next();                      return; }
      if (cmd === "ARCHIVE") { await archiveAndNext();      return; }
      if (cmd === "DELETE")  { await deleteAndNext();       return; }
      if (cmd === "MODIFY") {
        // Path keyword local ("modifie …") — le path naturel MODIFY-avec-
        // instruction passe par executeAgentActions/applyModify, où l'agent
        // a déjà strippé le verbe proprement.
        const instruction = text
          .replace(/^(modifier|modifie|modifies|changer|change|modify|edit)\s*/i, "")
          .trim();
        if (instruction && coreRef.current.currentEmail) {
          await applyModify(instruction);
        }
        return;
      }
      // Texte libre → regénérer avec les nouvelles instructions
      if (cmd === "free_text") { await generateDraft(text); return; }
      // Cmd reconnu mais sans action en relecture (PAUSE, UNDO…) : ne JAMAIS
      // mourir en silence (device 2026-08-04 : 2e « Annulé » → 30 s de vide,
      // abandon). Vocabulaire parlé + ré-écoute.
      speak(dt("tts.reviewHint", { defaultValue: "Dis envoyer, modifier, ou annule pour abandonner la réponse." }), () => startListening());
      return;
    }
  }, [
    speak, startListening, stopListening, stopTts,
    chooseReply, next, previous, generateDraft,
    archiveAndNext, deleteAndNext, updateDraft, safeTimeout,
    cancelPendingSend, playEarcon, executeAgentActions, applyModify,
  ]);

  return { handleVoiceInput };
}
