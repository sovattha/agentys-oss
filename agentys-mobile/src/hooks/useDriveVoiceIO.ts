/**
 * useDriveVoiceIO — couche entrée/sortie vocale du Drive Mode (#1124 étape 3).
 *
 * Couvre : speak/stopTts (enveloppe aurora synchronisée sur l'état TTS),
 * startListening (pipeline batch VAD→transcribe + chemin streaming Deepgram),
 * stopListening, interruptAndListen (tap-to-interrupt) et speakAndListen
 * (barge-in full-duplex : TTS + mic AEC en parallèle).
 *
 * Extrait verbatim de useDriveMode — ctx aux noms identiques, corps
 * inchangé (diff de comportement nul).
 */

import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction, type MutableRefObject } from "react";
import { AppState } from "react-native";
import * as Haptics from "expo-haptics";
import i18n from "../i18n";
import { toast } from "../lib/toast";
import { voiceMetrics } from "../lib/voiceMetrics";
import { transcribeAudio } from "../services/api";
import * as AgentysAudio from "../../modules/agentys-audio";
import { logEvent } from "../lib/eventLog";
import { reportError } from "../lib/errors";
import { UNDO_RE, detectCommand, detectTailCommand, applySpokenAck } from "../lib/driveCommands";
import type { SpokenAck } from "../lib/driveCommands";
import type { PendingActionManager } from "../lib/pendingActions";
import type { UseTtsResult } from "./useTts";
import type { UseVoiceDictation } from "./useVoiceDictation";
import type { UseStreamingStt } from "./useStreamingStt";
import type { DriveCore, DriveEvent } from "./driveReducer";
import { setCoreFlag } from "./driveReducer";
import type { DriveState } from "../types";

const dt = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "drive", ...(opts ?? {}) }) as string;

export interface DriveVoiceIOCtx {
  coreRef: MutableRefObject<DriveCore>;
  /** §2.3 : SEUL chemin de transition (surface migrée le 2026-07-28). */
  dispatchEvent: (e: DriveEvent) => boolean;
  setTranscript: Dispatch<SetStateAction<string>>;
  setIsListening: Dispatch<SetStateAction<boolean>>;
  setIsTranscribing: Dispatch<SetStateAction<boolean>>;
  setCommandRecognized: Dispatch<SetStateAction<string | null>>;
  /** Accusé parlé confirmé par la machine, à préfixer au prochain énoncé. */
  spokenAckRef: MutableRefObject<SpokenAck | null>;

  ttsHook: UseTtsResult;
  dictation: UseVoiceDictation;
  streamingStt: UseStreamingStt;
  playEarcon: (name: "turn" | "tick" | "done" | "alert") => void;
  pushAudioLevel: (target: number, duration?: number) => void;
  startTtsEnvelope: () => void;
  stopTtsEnvelope: () => void;

  safeTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  armSilenceTimer: (fn: () => void, ms: number) => void;
  clearSilenceTimer: () => void;

  nudgeOnSilenceRef: MutableRefObject<() => void>;
  handleVoiceInputRef: MutableRefObject<(text: string) => void>;
  /** Annulation d'un envoi différé — câblé par useDriveMode (cycle cassé par ref). */
  cancelPendingSendRef: MutableRefObject<() => void>;
  pendingActionsRef: MutableRefObject<PendingActionManager>;

  streamingSttEnabled: boolean;
  silenceFirstMs: number;
}

export function useDriveVoiceIO(ctx: DriveVoiceIOCtx) {
  const {
    coreRef, dispatchEvent, setTranscript, setIsListening, setIsTranscribing,
    setCommandRecognized, spokenAckRef,
    ttsHook, dictation, streamingStt, playEarcon, pushAudioLevel,
    startTtsEnvelope, stopTtsEnvelope,
    safeTimeout, armSilenceTimer, clearSilenceTimer,
    nudgeOnSilenceRef, handleVoiceInputRef, cancelPendingSendRef,
    pendingActionsRef,
    streamingSttEnabled: STREAMING_STT,
    silenceFirstMs: SILENCE_FIRST_MS,
  } = ctx;
  void STREAMING_STT; void SILENCE_FIRST_MS;

  // ── TTS via useTts (source unique pour audio mode + playback) ────────────
  // Avant : TTS local dupliqué dans ce hook + useTts. Trois acteurs touchaient
  // setAudioModeAsync (useTts mount, useVoiceDictation listen/cleanup, et le
  // local speak qui ne le settait pas). Race conditions garanties.
  // Maintenant : useTts est la source unique. Il force `allowsRecordingIOS:
  // false` AVANT chaque speak, garantissant que la sortie va au speaker.
  /** Transcriptions vides CONSÉCUTIVES (voix captée, texte vide) — à 2, on
   *  l'avoue à voix haute au lieu de ré-écouter en silence (2026-08-04). */
  const emptyStreakRef = useRef(0);

  /** Consommation unique de l'accusé parlé posé par la machine à états.
   *  La règle (préfixe + péremption) est pure, cf. `applySpokenAck`. */
  const consumeSpokenAck = useCallback((text: string): string => {
    const ack = spokenAckRef.current;
    spokenAckRef.current = null;
    return applySpokenAck(text, ack, Date.now());
  }, [spokenAckRef]);

  const speak = useCallback((rawText: string, onDone?: () => void) => {
    const text = consumeSpokenAck(rawText);
    // Step 2 (say() unifié) : quand une session STT streaming est ouverte, le
    // tap mic natif (AVAudioEngine) tourne en continu. Un speak() qui force
    // `allowsRecordingIOS:false` reconfigurerait la session en playback et
    // TUERAIT le tap dès le 1er prompt parlé ("J'envoie ?") — sans fermeture
    // socket, la session streaming meurt en silence (pas de relance). En
    // passant `preserveAudioMode` tant que le streaming est actif, TOUS les
    // surfaces parlées (lectures, prompts, SAY, erreurs, nudges) qui passent
    // par ce helper préservent la config voiceChat. Hors streaming (batch) :
    // `coreRef.current.streamingActive === false` → comportement actuel exact, zéro
    // régression.
    // Les deux côtés du dialogue dans le ring buffer : sans ça, un dump
    // Diagnostic ne montre que ce que l'utilisateur dit, jamais ce que
    // l'app a répondu (demande utilisateur 2026-07-28).
    logEvent("tts", { state: coreRef.current.state, text: text.slice(0, 120) });
    ttsHook.speak(text, () => {
      // Tick haptique léger en fin de TTS : signal hands-free que c'est
      // au tour de l'user de parler. Light pour ne pas être agressant.
      Haptics.selectionAsync().catch(() => {});
      onDone?.();
    }, { preserveAudioMode: coreRef.current.streamingActive }).catch((err) => {
      console.warn("[drive-tts] speak failed:", err);
      // Toast déjà émis ci-dessous — trace structurée sans doubler l'UI.
      reportError(err, { domain: "tts", op: "speak" }, { userFacing: "silent" });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
      toast.warning("Lecture vocale indisponible — vérifie ta connexion");
      // Garantir que onDone fire même en erreur (sinon state machine bloqué).
      onDone?.();
    });
  }, [ttsHook, consumeSpokenAck]);

  const stopTts = useCallback(async () => {
    await ttsHook.stop();
  }, [ttsHook]);


  // L'envelope visualizer est piloté par l'état réel de useTts (réactif,
  // pas besoin de coordonner manuellement).
  useEffect(() => {
    if (ttsHook.state === "speaking") {
      // Premier son audible de la réponse AI → clôt le tour de parole
      // (turn_latency_ms = fin de parole user → maintenant).
      voiceMetrics.markAiSpeakStart(coreRef.current.state);
      startTtsEnvelope();
    } else {
      stopTtsEnvelope();
    }
  }, [ttsHook.state, startTtsEnvelope, stopTtsEnvelope]);

  // ── STT helpers ──────────────────────────────────────────────────────────
  /** Tune VAD options par état UI :
   *  - `listening` (dictée libre du brouillon) : silence long (1.8s), max 60s.
   *    On laisse de la marge pour les pauses naturelles dans une phrase.
   *  - autres états (commande/confirmation/idle) : silence court (700ms),
   *    max 6s. Les commandes sont des mots uniques ("supprimer", "suivant"),
   *    pas besoin d'attendre 1.5s après le mot pour finaliser.
   *
   *  La somme silenceMs + upload + Whisper inference représente la latence
   *  perçue par l'utilisateur entre la fin de sa parole et l'action. Avec
   *  700ms + ~200ms upload + ~700ms Whisper = ~1.6s perçus (vs 3s avant).
   */
  const startListening = useCallback(() => {
    // #1122 : jamais d'écoute micro en arrière-plan. Le TTS peut continuer
    // écran verrouillé (staysActiveInBackground), mais démarrer le micro
    // hors foreground est interdit (privacy + iOS le refuserait de toute façon).
    if (AppState.currentState !== "active") return;
    setTranscript("");
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setIsListening(true);

    const s = coreRef.current.state;
    if (s === "choosing" || s === "reviewing") {
      armSilenceTimer(() => nudgeOnSilenceRef.current(), SILENCE_FIRST_MS);
    }
    const isFreeDictation = s === "listening";

    // ── Step 4 : chemin streaming (Deepgram live) ────────────────────────
    // Endpointing sémantique : pas de timer de silence, le modèle décide de
    // la fin du tour. Les partiels alimentent le transcript live. En cas de
    // pépin sur CE tour (session morte entre-temps), on retombe sur le
    // pipeline batch ci-dessous au prochain startListening.
    if (STREAMING_STT && coreRef.current.streamingActive) {
      streamingStt
        .listen({
          onPartial: (preview) => setTranscript(preview),
          noVoiceTimeoutMs: 8_000,
          maxDurationMs: isFreeDictation ? 60_000 : 15_000,
        })
        .then((res) => {
          setIsListening(false);
          pushAudioLevel(0, 500);
          if (res.kind === "cancelled") return;
          if (res.kind === "ok" && res.text.trim().length > 0) {
            const clean = res.text.trim();
            // Streaming : le transcript arrive AVEC la fin de parole — les
            // deux marqueurs tombent au même instant (stt_latency ≈ 0).
            voiceMetrics.markUserSpeechEnd();
            voiceMetrics.markTranscriptReady(coreRef.current.state);
            setTranscript(clean);
            clearSilenceTimer();
            coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
            handleVoiceInputRef.current(clean);
            return;
          }
          // no_voice / error / texte vide → même politique de retry que le
          // batch : on ré-ouvre l'écoute sur les états qui attendent une voix.
          voiceMetrics.counter("false_restarts", coreRef.current.state);
          const cur = coreRef.current.state;
          if (
            (coreRef.current.idleListeningActive && cur === "idle") ||
            cur === "listening" || cur === "choosing" || cur === "reviewing" ||
            cur === "confirming_dictation" || cur === "asking_preview" || cur === "asking_send"
          ) {
            safeTimeout(() => startListening(), 400);
          }
        })
        .catch(() => {
          coreRef.current = setCoreFlag(coreRef.current, "voiceCaptureActive", false);
          setIsListening(false);
          pushAudioLevel(0, 500);
        });
      return;
    }
    const opts = {
      onLevel: (v: number) => pushAudioLevel(v, 100),
      // "Got it" tick dès que le mic entend la voix : feedback < 100ms qui
      // dit "je capture, arrête de parler" PENDANT le trou de ~1.5-2s du STT
      // batch (la cause principale des ré-élocutions qui collisionnent).
      onVoiceStart: () => {
        coreRef.current = setCoreFlag(coreRef.current, "voiceCaptureActive", true); // M-P1c : un transcript arrive
        playEarcon("tick");
      },
      // Threshold abaissé à -38 dB : sur iPhone en mode PlayAndRecord, la voix
      // utilisateur à distance normale est ≈ -32 dB ; -28 dB (l'ancien défaut
      // de useVoiceDictation = -42 mais fixé à -28 ici) la ratait.
      voiceThresholdDb: -38,
      // minSpeechMs: 150ms = sustained voice court suffit pour les commandes
      // mono-mot ("supprimer", "suivant"). Le default 300ms ajoutait du delay
      // inutile pour valider qu'il y a bien quelqu'un qui parle.
      minSpeechMs:      isFreeDictation ? 250 : 150,
      // silenceMs abaissé (1800→1200 dictée, 600→400 commandes) : marge encore
      // confortable, gain perçu -200 à -400 ms entre fin de parole et action.
      silenceMs:        isFreeDictation ? 1200 : 400,
      maxDurationMs:    isFreeDictation ? 60_000 : 6_000,
      noVoiceTimeoutMs: 5_000,
      // #1134 : ignore la détection de voix pendant les premières 600ms — le
      // micro s'ouvre pendant que l'earcon « à toi » joue et avant que l'AEC
      // n'ait convergé ; sans ça, l'earcon était pris pour la voix de l'user
      // (finish immédiat → « pas le temps de parler »). Mesuré device : earcon
      // capté jusqu'à ~+350ms, on garde de la marge.
      graceMs: 600,
      // #1134 : PAS d'AEC pour le tour de parole séquentiel — aucune TTS ne
      // joue en même temps, et l'AEC écrasait le gain du micro (voix à ~-48 dB
      // au lieu de ~-32) → le VAD ratait la voix. Gain normal sans AEC.
      useVoiceChat: false,
    };
    console.log("[drive-stt] startListening state:", s, "opts:", JSON.stringify({ silenceMs: opts.silenceMs, threshold: opts.voiceThresholdDb }));
    const t0 = Date.now();

    dictation
      .listen(opts)
      .then(async (res) => {
        coreRef.current = setCoreFlag(coreRef.current, "voiceCaptureActive", false); // M-P1c : capture terminée
        // L'utilisateur ou un stopListening() a annulé — silence radio.
        if (res.kind === "cancelled") {
          setIsListening(false);
          pushAudioLevel(0, 500);
          return;
        }
        // Pas de voix détectée OU erreur expo-av → auto-restart sur les
        // états qui dépendent d'une réponse vocale.
        if (res.kind === "no_voice" || res.kind === "error") {
          if (res.kind === "error") {
            console.warn("[drive-stt] dictation error:", res.error);
            // console.warn est invisible en Release — trace structurée en plus.
            reportError(res.error, { domain: "audio", op: "listen", state: coreRef.current.state }, { userFacing: "silent" });
          }
          setIsListening(false);
          pushAudioLevel(0, 500);
          voiceMetrics.counter("false_restarts", coreRef.current.state);
          const cur = coreRef.current.state;
          if (coreRef.current.idleListeningActive && cur === "idle") {
            safeTimeout(() => startListening(), 500);
            return;
          }
          if (
            cur === "listening" || cur === "choosing" || cur === "reviewing" ||
            cur === "confirming_dictation" || cur === "asking_preview" || cur === "asking_send"
          ) {
            safeTimeout(() => startListening(), 500);
          }
          return;
        }

        // res.kind === "ok" → on a un fichier audio, on transcrit côté backend.
        // Le VAD vient de résoudre = l'utilisateur a fini de parler.
        voiceMetrics.markUserSpeechEnd();
        // Mic fermé immédiatement (l'user a fini de parler) ; la transcription
        // backend (~1s) continue en tâche de fond — isTranscribing donne un
        // feedback visuel pendant ce gap invisible.
        setIsListening(false);
        setIsTranscribing(true);
        try {
          const tListen = Date.now() - t0;
          const tTranscribeStart = Date.now();
          const { text } = await transcribeAudio(res.uri, tListen);
          const tTranscribe = Date.now() - tTranscribeStart;
          voiceMetrics.markTranscriptReady(coreRef.current.state);
          const clean = (text || "").trim();
          console.log(
            `[drive-stt] transcript: ${JSON.stringify(clean)} state=${coreRef.current.state} listen=${tListen}ms transcribe=${tTranscribe}ms`
          );
          // [drive-dbg] miroir os_log (console.log invisible en Release).
          AgentysAudio.debugLog(
            `transcript len=${clean.length} state=${coreRef.current.state} listen=${tListen}ms text="${clean.slice(0, 60)}"`,
          );
          logEvent("stt", {
            len: clean.length,
            state: coreRef.current.state,
            listenMs: tListen,
            transcribeMs: tTranscribe,
            text: clean.slice(0, 60),
          });
          setIsTranscribing(false);
          setTranscript(clean);
          pushAudioLevel(0, 500);
          if (clean.length === 0) {
            // Whisper a rendu une chaîne vide (bruit ambiant uniquement).
            // Même politique de retry que `no_voice`.
            const cur = coreRef.current.state;
            if (cur === "undo_window") {
              // Voix ENTENDUE (capture ok du VAD) mais intranscriptible
              // pendant la fenêtre d'annulation d'un envoi IRRÉVERSIBLE :
              // toute parole vaut annulation, même ratée par le STT batch
              // (« annule » avalé → email parti, device 2026-07-28). Faux
              // positif bénin : l'utilisateur redit « envoyer ».
              cancelPendingSendRef.current();
              return;
            }
            if (coreRef.current.idleListeningActive && cur === "idle") {
              safeTimeout(() => startListening(), 500);
              return;
            }
            if (
              cur === "listening" || cur === "choosing" || cur === "reviewing" ||
              cur === "confirming_dictation" || cur === "asking_preview" || cur === "asking_send"
            ) {
              emptyStreakRef.current += 1;
              if (emptyStreakRef.current >= 2) {
                // Loud failure (device 2026-08-04) : 4 transcriptions vides
                // d'affilée en choosing — voix bien captée, texte vide,
                // ré-écoute MUETTE en boucle → l'utilisateur parlait dans le
                // vide et a abandonné (RESET). Après 2 vides consécutifs, on
                // l'AVOUE et on donne la parade avant de rouvrir le micro.
                emptyStreakRef.current = 0;
                speak(
                  dt("tts.transcriptFailed", {
                    defaultValue: "Je t'entends, mais je ne comprends pas. Reformule en une phrase.",
                  }),
                  () => startListening(),
                );
                return;
              }
              safeTimeout(() => startListening(), 500);
            }
            return;
          }
          // Reset du watchdog "silence prolongé" — l'utilisateur a parlé.
          emptyStreakRef.current = 0;
          clearSilenceTimer();
          coreRef.current = setCoreFlag(coreRef.current, "silenceNudged", false);
          handleVoiceInputRef.current(clean);
        } catch (err: any) {
          console.warn("[drive-stt] transcribe failed:", err?.message || err);
          setIsTranscribing(false);
          pushAudioLevel(0, 500);
          // Toast pour rendre l'erreur visible — sinon l'user voit juste un
          // mic qui se rouvre et s'imagine que le système est cassé.
          const msg = String(err?.message || err);
          if (msg.includes("Timeout") || msg.includes("trop longue")) {
            toast.warning("Transcription lente — réessaie");
          } else if (msg.includes("Unauthorized") || msg.includes("401")) {
            toast.error("Session expirée — reconnecte-toi");
          } else {
            toast.warning("Transcription échouée");
          }
          // Erreur transcription — on retente sans bloquer l'UX.
          safeTimeout(() => startListening(), 500);
        }
      })
      .catch((err) => {
        // dictation.listen() lui-même throw : très rare, mais on filet
        // de sécurité pour ne pas geler l'état "listening" indéfiniment.
        console.warn("[drive-stt] listen() rejected:", err?.message || err);
        reportError(err, { domain: "audio", op: "listenRejected", state: coreRef.current.state }, { userFacing: "silent" });
        // M-P1c (régression corrigée) : si onVoiceStart avait posé le flag de
        // capture avant le throw, il faut le libérer — sinon le timer
        // undo_window se redéclenche en boucle sans jamais envoyer ni annuler.
        coreRef.current = setCoreFlag(coreRef.current, "voiceCaptureActive", false);
        setIsListening(false);
        pushAudioLevel(0, 500);
      });
  }, [armSilenceTimer, clearSilenceTimer, dictation, streamingStt, pushAudioLevel, safeTimeout, playEarcon]);

  const stopListening = useCallback(() => {
    // Un cancel raté peut laisser un recorder orphelin (#1134 5e cause) —
    // loggé silencieusement : le ring buffer le corrèlera au prochain listen.
    dictation.cancel().catch((e) => reportError(e, { domain: "audio", op: "stopListening.cancel" }, { userFacing: "silent" }));
    streamingStt.cancelListen();
    setIsListening(false);
    clearSilenceTimer();
    pushAudioLevel(0, 500);
  }, [clearSilenceTimer, dictation, streamingStt, pushAudioLevel]);

  /** Clôt la capture en cours en CONSERVANT l'audio (→ transcript). Tap
   *  « c'est fini » pendant une capture encore ouverte (VAD pas fermé).
   *  Retourne true si une capture était active. */
  const flushListening = useCallback((): boolean => {
    return dictation.flush();
  }, [dictation]);

  /** Tap-to-interrupt : l'utilisateur tape pendant que l'AI parle pour
   *  reprendre la main vocalement. On stoppe le TTS, on transitionne vers un
   *  état qui accepte la commande vocale, puis on ouvre le mic.
   *
   *  Mirroir manuel du barge-in vocal natif (`speakAndListen`) — utile sur
   *  les builds sans module AgentysAudio (Expo Go) où l'AEC n'est pas dispo. */
  const interruptAndListen = useCallback(async () => {
    if (ttsHook.state !== "speaking" && ttsHook.state !== "paused") return;
    Haptics.selectionAsync().catch(() => {});
    await ttsHook.stop();
    // Si on était en "speaking" pur, l'onDone naturel ne fire plus → on bascule
    // explicitement en "choosing" pour que la logique d'auto-retry STT en
    // no_voice prenne le relais si l'user n'a rien dit. Les autres états
    // parlants (asking_preview, asking_send, confirming_*) sont déjà dans la
    // whitelist d'auto-retry, on ne les touche pas.
    if (coreRef.current.state === "speaking") {
      // Lecture interrompue = fin de TTS (sans next) → choosing, via la table.
      dispatchEvent({ type: "TTS_DONE" });
    }
    // #1134 : earcon « à toi » aussi sur le tap — même signal que la fin
    // naturelle, l'utilisateur sait DANS LES DEUX CAS que le mic est ouvert.
    playEarcon("turn");
    startListening();
  }, [ttsHook, startListening, playEarcon]);

  // ── Plus de speakAndListen ──────────────────────────────────────────────
  // Phase 1 (stabilisation) : on supprime le pattern TTS+listen parallèles.
  // Sur iOS, expo-av active PlayAndRecord pendant le listen → la sortie
  // Sound est routée vers l'écouteur (earpiece) au lieu du speaker, rendant
  // la TTS quasi inaudible. Sans accès natif à `defaultToSpeaker`, on ne
  // peut pas avoir de barge-in vocal fiable.
  //
  // Phase 2 : module natif AgentysAudio expose
  // AVAudioSession.overrideOutputAudioPort(.speaker) + Mode.voiceChat (AEC).
  // Si NATIVE_AVAILABLE, on peut faire du barge-in vocal proprement.
  // Sinon (Expo Go ou ancien build), fallback sur speak séquentiel.

  /** Lecture d'email SÉQUENTIELLE (#1134). Le pattern full-duplex (TTS + mic
   *  barge-in parallèle en voiceChat) a été abandonné : même avec l'AEC, le
   *  mic captait l'écho de la TTS → faux `onVoiceStart` → la lecture était
   *  coupée en plein milieu (« rend la main trop vite »). On lit désormais le
   *  mail en entier via `speak` ; le tour de parole (earcon « à toi » + micro)
   *  est déclenché par `onDone` à la VRAIE fin (fiable via la sonde
   *  getStatusAsync de useTts). Le barge-in par TAP (interruptAndListen) reste
   *  dispo pour couper manuellement. */
  const speakAndListen = useCallback(
    (text: string, onDone?: () => void) => {
      speak(text, onDone);
    },
    [speak]
  );

  return {
    speak, stopTts, startListening, stopListening, flushListening, interruptAndListen,
    speakAndListen,
  };
}
