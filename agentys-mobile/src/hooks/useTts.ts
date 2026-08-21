/**
 * Hook TTS ElevenLabs — remplace l'ancien `useAudio.speak()` / expo-speech.
 *
 * Flux :
 *   1. `speak(text)` → POST /api/tts/speak → retourne un audio_url
 *   2. On télécharge le MP3 via expo-av `Audio.Sound.createAsync({uri, headers})`
 *   3. Playback, onDone callback, cleanup automatique
 *
 * Textes longs (> ~200 chars) : pipeline « chunké » — le texte est découpé
 * aux frontières de phrases (lib/ttsChunks), le 1er chunk court est
 * synthétisé seul (audio en ~400-700 ms au lieu de 1,5-3 s), et pendant
 * qu'un chunk joue, le suivant se synthétise en parallèle. stop/pause/
 * resume/toggle agissent sur le chunk courant et la chaîne s'interrompt
 * proprement via le callId monotone.
 *
 * `prefetch(text)` warme le cache serveur pour un email à venir (Drive
 * Mode) — il passe par le MÊME découpage pour que les hashes de cache
 * correspondent au speak() réel.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { PLAYBACK_AUDIO_MODE } from "../lib/audioMode";
import { reportError } from "../lib/errors";
import { Audio, AVPlaybackStatus } from "expo-av";
import * as SecureStore from "expo-secure-store";
import { speak as speakBackend, audioAuthHeaders, ensureVoiceId } from "../services/tts";
import { splitIntoTtsChunks } from "../lib/ttsChunks";
import { spellFrenchNumbers } from "../lib/frenchNumbers";
import i18n from "../i18n";
import * as AgentysAudio from "../../modules/agentys-audio";
import { logEvent } from "../lib/eventLog";

export type TtsState = "idle" | "loading" | "speaking" | "paused" | "error";

export interface SpeakOptions {
  /** Si true, useTts NE FORCE PAS `allowsRecordingIOS: false` avant le speak.
   *  À utiliser quand le caller a déjà configuré une session voiceChat
   *  (Phase 2 barge-in) — on ne veut pas casser cette config. Défaut false. */
  preserveAudioMode?: boolean;
  voiceIdOverride?: string;
}

export interface UseTtsResult {
  state: TtsState;
  error: string | null;
  speak: (text: string, onDone?: () => void, opts?: SpeakOptions | string) => Promise<void>;
  stop: () => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  toggle: () => Promise<void>;
  prefetch: (text: string, voiceIdOverride?: string) => Promise<void>;
}

// Filet de secours de fin de lecture (#1134). En build Release sur device,
// l'event `didJustFinish` d'expo-av n'est pas fiable (même cause que le revert
// expo-audio) : sans lui, la promesse de lecture ne se résout jamais et le tour
// de parole reste bloqué. On sonde donc l'état par REQUÊTE directe
// (`getStatusAsync`, fiable là où la livraison d'events ne l'est pas).
const TTS_POLL_INTERVAL_MS = 250;
// Tolérance : position/durée MP3 ne coïncident pas toujours au millimètre.
const TTS_END_EPSILON_MS = 400;

async function getStoredRate(): Promise<number> {
  try {
    const raw = await SecureStore.getItemAsync("voice_rate");
    if (!raw) return 1.0;
    const v = parseFloat(raw);
    return Number.isFinite(v) ? v : 1.0;
  } catch {
    // fallback légitime : vitesse par défaut 1.0 si la pref est illisible
    return 1.0;
  }
}

export function useTts(): UseTtsResult {
  const [state, setState] = useState<TtsState>("idle");
  const [error, setError] = useState<string | null>(null);
  const soundRef = useRef<Audio.Sound | null>(null);
  // Token monotone pour ignorer les anciens callbacks après un nouveau speak()
  const callIdRef = useRef(0);
  const onDoneRef = useRef<(() => void) | null>(null);
  // Resolver du chunk en cours de lecture : stop() doit le réveiller pour
  // que la boucle chunkée sorte au lieu d'attendre un didJustFinish qui ne
  // viendra jamais (le Sound est unloadé).
  const chunkResolveRef = useRef<(() => void) | null>(null);
  // Pause inter-chunk (M-P2e) : pause() pendant le trou entre deux chunks
  // (soundRef null) doit STOPPER la chaîne, pas la laisser continuer. La
  // boucle attend `pauseWaiterRef` avant de jouer le chunk suivant.
  const pausedRef = useRef(false);
  const pauseWaiterRef = useRef<(() => void) | null>(null);

  const unloadCurrent = useCallback(async () => {
    const s = soundRef.current;
    soundRef.current = null;
    if (!s) return;
    try {
      await s.stopAsync().catch(() => {}); // no-op légitime : son déjà arrêté/libéré
      await s.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    // Mode audio : lecture même en silencieux iOS, pas d'enregistrement actif
    Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE).catch((e) =>
      reportError(e, { domain: "audio", op: "ttsMountSetPlaybackMode" }, { userFacing: "silent" }));
    return () => {
      unloadCurrent().catch(() => {}); // no-op légitime : son déjà arrêté/libéré
    };
  }, [unloadCurrent]);

  const speak = useCallback(
    async (text: string, onDone?: () => void, opts?: SpeakOptions | string) => {
      // Back-compat : ancien signature `speak(text, onDone, voiceIdOverride)`
      // où le 3e arg était une string (voice id direct).
      const normalizedOpts: SpeakOptions =
        typeof opts === "string" ? { voiceIdOverride: opts } :
        opts ?? {};
      const callId = ++callIdRef.current;
      onDoneRef.current = onDone ?? null;
      // Nouveau speak → on repart non-pausé (un pause/resume antérieur ne doit
      // pas geler la première lecture chunkée de ce nouvel énoncé).
      pausedRef.current = false;
      pauseWaiterRef.current?.();
      pauseWaiterRef.current = null;
      setError(null);
      setState("loading");

      await unloadCurrent();

      // FORCE le mode Playback AVANT chaque speak — SAUF si le caller a
      // demandé `preserveAudioMode: true` (Phase 2 voiceChat barge-in,
      // qui a déjà configuré la session via le module natif AgentysAudio).
      if (!normalizedOpts.preserveAudioMode) {
        try {
          await Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE);
          // Force le loudspeaker explicitement — iOS peut router vers l'écouteur
          // d'oreille via le capteur de proximité même en catégorie .playback.
          if (AgentysAudio.NATIVE_AVAILABLE) {
            AgentysAudio.forceSpeakerOutput(true);
          }
        } catch {
          // Si setAudioModeAsync throw (rare), on continue — le pire cas est
          // un volume sub-optimal, pas un crash.
        }
      }

      try {
        const voiceId = normalizedOpts.voiceIdOverride ?? (await ensureVoiceId());
        if (!voiceId) {
          throw new Error(i18n.t("voice:errors.noVoiceSelected") as string);
        }
        // Pin la langue côté ElevenLabs pour éviter la mauvaise auto-détection
        // sur phrases courtes (ex: "14 actions, 7 infos. On y va.").
        const baseLang = (i18n.language || "").split(/[-_]/)[0] || undefined;
        const storedAccent = await SecureStore.getItemAsync("voice_accent");
        // Accent stocké > fallback fr→fr-FR (ElevenLabs traite "fr" comme ambigu)
        const languageCode = storedAccent ?? (baseLang === "fr" ? "fr-FR" : baseLang);

        // #1134 : en français, écrire les nombres en lettres — ElevenLabs
        // normalise sinon « 66 » avec une détection anglaise (« sixty-six »)
        // même avec language_code=fr-FR, surtout en tête de phrase courte.
        const spokenText = (languageCode || "").startsWith("fr")
          ? spellFrenchNumbers(text)
          : text;

        // ── Pipeline chunké ──────────────────────────────────────────────
        // ≤ 1 chunk = chemin historique (une requête, un Sound). > 1 chunk =
        // on joue le 1er pendant que le 2e se synthétise, etc.
        const chunks = splitIntoTtsChunks(spokenText);
        if (chunks.length === 0) {
          throw new Error("empty text");
        }

        const [headers, rate] = await Promise.all([
          audioAuthHeaders(),
          getStoredRate(),
        ]);
        if (callId !== callIdRef.current) return; // superseded
        // Device 2026-08-04 (« tu m'as répondu en accéléré ») : trace le taux
        // de lecture réellement appliqué + le découpage + LE TEXTE (demande
        // Nathan : « logue ce qui est dit ») — indiagnosticable en Release
        // sans ça. Le ring buffer reçoit la même info (export Diagnostic).
        AgentysAudio.debugLog(
          `tts speak rate=${rate} chunks=${chunks.length} chars=${spokenText.length} ` +
          `text="${spokenText.slice(0, 100)}"`,
        );
        logEvent("tts", {
          src: "useTts", rate, chunks: chunks.length, text: spokenText.slice(0, 120),
        });

        /** Joue une URL et résout sur didJustFinish (ou stop/supersede).
         *  REJETTE si le chunk ne se charge pas (URL 404/expirée) — sinon un
         *  échec de chargement passait pour une lecture réussie silencieuse,
         *  et le Drive Mode avançait comme si l'email avait été lu (M-P2e). */
        const playOne = async (audioUrl: string): Promise<void> => {
          await unloadCurrent();
          if (callId !== callIdRef.current) return;
          await new Promise<void>((resolve, reject) => {
            let settled = false;
            // Sonde de fin de lecture (#1134) : filet si didJustFinish ne fire pas.
            let poll: ReturnType<typeof setInterval> | null = null;
            // Durée réelle de l'audio produit par ElevenLabs (device 2026-08-04
            // « réponse en accéléré ») : chars/durMs objectivent le débit de
            // synthèse — le rate client est déjà tracé au speak.
            let lastDurMs = -1;
            const clearPoll = () => {
              if (poll) {
                clearInterval(poll);
                poll = null;
              }
            };
            const settle = () => {
              if (settled) return;
              settled = true;
              clearPoll();
              if (chunkResolveRef.current === settle) chunkResolveRef.current = null;
              AgentysAudio.debugLog(`tts chunk done durMs=${lastDurMs}`);
              resolve();
            };
            chunkResolveRef.current = settle;
            Audio.Sound.createAsync(
              { uri: audioUrl, headers },
              { shouldPlay: true, rate, shouldCorrectPitch: true },
              (status: AVPlaybackStatus) => {
                if (!("isLoaded" in status) || !status.isLoaded) return;
                if (typeof status.durationMillis === "number") lastDurMs = status.durationMillis;
                if (status.didJustFinish) settle();
              },
            )
              .then(({ sound }) => {
                if (callId !== callIdRef.current) {
                  sound.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
                  settle();
                  return;
                }
                soundRef.current = sound;
                setState("speaking");
                // Fast-path = le callback didJustFinish ci-dessus. Ce poll est le
                // filet de secours : il interroge l'état par requête (fiable en
                // Release) et résout dès que la piste est finie. Respecte pause
                // (isPlaying=false mais position<durée → on ne settle pas).
                poll = setInterval(() => {
                  if (settled) {
                    clearPoll();
                    return;
                  }
                  sound
                    .getStatusAsync()
                    .then((st) => {
                      if (!("isLoaded" in st) || !st.isLoaded) return;
                      if (typeof st.durationMillis === "number") lastDurMs = st.durationMillis;
                      if (st.didJustFinish) {
                        settle();
                        return;
                      }
                      if (
                        !st.isPlaying &&
                        typeof st.durationMillis === "number" &&
                        st.durationMillis > 0 &&
                        st.positionMillis >= st.durationMillis - TTS_END_EPSILON_MS
                      ) {
                        settle();
                      }
                    })
                    .catch(() => {}); // no-op légitime : son déjà arrêté/libéré
                }, TTS_POLL_INTERVAL_MS);
              })
              .catch((err) => {
                if (settled) return;
                settled = true;
                if (chunkResolveRef.current === settle) chunkResolveRef.current = null;
                reject(err instanceof Error ? err : new Error("chunk load failed"));
              });
          });
        };

        const fetchChunk = (i: number) => {
          const p = speakBackend(chunks[i], voiceId, undefined, languageCode);
          // Évite un unhandledRejection si on abandonne ce fetch sur supersede.
          p.catch(() => {}); // no-op légitime : son déjà arrêté/libéré
          return p;
        };

        // Synthèse du chunk N+1 pendant la lecture du chunk N.
        let nextFetch = fetchChunk(0);
        for (let i = 0; i < chunks.length; i++) {
          const { audioUrl } = await nextFetch;
          if (callId !== callIdRef.current) return;
          if (i + 1 < chunks.length) nextFetch = fetchChunk(i + 1);
          // Pause inter-chunk : si l'utilisateur a mis en pause pendant le trou,
          // on attend la reprise AVANT de jouer le chunk suivant.
          if (pausedRef.current) {
            await new Promise<void>((resolve) => { pauseWaiterRef.current = resolve; });
            pauseWaiterRef.current = null;
            if (callId !== callIdRef.current) return;
          }
          await playOne(audioUrl);
          if (callId !== callIdRef.current) return;
        }

        // Fin naturelle du dernier chunk.
        setState("idle");
        // #1134 (boucle) : décharger le Sound AVANT de rendre la main. Sinon
        // `cb?.()` ouvre le micro (earcon + startListening) pendant que la
        // queue du dernier chunk draine encore → le mic capte la fin de la TTS
        // (faux barge-in / bruit → re-speak sans earcon). On draine d'abord.
        await unloadCurrent();
        const cb = onDoneRef.current;
        onDoneRef.current = null;
        cb?.();
      } catch (e: any) {
        if (callId !== callIdRef.current) return;
        setError(e?.message || "Erreur TTS");
        setState("error");
        const cb = onDoneRef.current;
        onDoneRef.current = null;
        // On appelle onDone même en erreur pour que Drive Mode continue
        cb?.();
      }
    },
    [unloadCurrent],
  );

  const stop = useCallback(async () => {
    callIdRef.current++; // invalide tout speak en cours
    onDoneRef.current = null;
    // Réveille la boucle chunkée si elle attend un didJustFinish — le Sound
    // va être unloadé, le callback ne viendra jamais. Idem pour le waiter de
    // pause inter-chunk (la boucle sort via le check callId).
    pausedRef.current = false;
    pauseWaiterRef.current?.();
    pauseWaiterRef.current = null;
    chunkResolveRef.current?.();
    chunkResolveRef.current = null;
    await unloadCurrent();
    setState("idle");
  }, [unloadCurrent]);

  const pause = useCallback(async () => {
    // Marque l'intention de pause AVANT tout : si on est dans le trou entre
    // deux chunks (soundRef null), la boucle attendra la reprise.
    pausedRef.current = true;
    const s = soundRef.current;
    if (s) {
      try {
        await s.pauseAsync();
      } catch (e) {
        reportError(e, { domain: "tts", op: "pause" }, { userFacing: "silent" });
      }
    }
    setState("paused");
  }, []);

  const resume = useCallback(async () => {
    pausedRef.current = false;
    // Débloque la boucle chunkée si elle attendait la reprise.
    pauseWaiterRef.current?.();
    pauseWaiterRef.current = null;
    const s = soundRef.current;
    if (s) {
      try {
        await s.playAsync();
      } catch (e) {
        reportError(e, { domain: "tts", op: "resume" }, { userFacing: "silent" });
      }
    }
    setState("speaking");
  }, []);

  const toggle = useCallback(async () => {
    const s = soundRef.current;
    if (!s) return;
    try {
      const status = await s.getStatusAsync();
      if (!("isLoaded" in status) || !status.isLoaded) return;
      if (status.isPlaying) {
        await s.pauseAsync();
        setState("paused");
      } else {
        await s.playAsync();
        setState("speaking");
      }
    } catch (e) {
      reportError(e, { domain: "tts", op: "togglePlayback" }, { userFacing: "silent" });
    }
  }, []);

  const prefetch = useCallback(
    async (text: string, voiceIdOverride?: string) => {
      try {
        const voiceId = voiceIdOverride ?? (await ensureVoiceId());
        if (!voiceId) return;
        const baseLang = (i18n.language || "").split(/[-_]/)[0] || undefined;
        const storedAccent = await SecureStore.getItemAsync("voice_accent");
        // Accent stocké > fallback fr→fr-FR (ElevenLabs traite "fr" comme ambigu)
        const languageCode = storedAccent ?? (baseLang === "fr" ? "fr-FR" : baseLang);
        // Fire-and-forget : on warm le cache serveur avec la bonne langue.
        // MÊME découpage + MÊME normalisation des nombres que speak() (#1134),
        // sinon le hash du cache serveur diffère et le prefetch ne sert à rien.
        // SÉQUENTIEL (et non Promise.all) : un prefetch parallèle de N chunks
        // peut saturer la concurrence ElevenLabs et faire échouer la lecture
        // live en cours (M-P2f). Le 1er chunk d'abord (time-to-audio), puis le
        // reste un par un.
        const spokenText = (languageCode || "").startsWith("fr")
          ? spellFrenchNumbers(text)
          : text;
        const chunks = splitIntoTtsChunks(spokenText);
        for (const c of chunks) {
          await speakBackend(c, voiceId, undefined, languageCode);
        }
      } catch {
        // no-op légitime : préchargement best-effort
      }
    },
    [],
  );

  return { state, error, speak, stop, pause, resume, toggle, prefetch };
}
