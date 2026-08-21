/**
 * useVoiceDictation — dictée mains-libres avec VAD.
 *
 * Ouvre le mic, surveille le niveau audio (metering dB exposé par expo-av),
 * auto-stoppe quand :
 *   - un silence durable (`silenceMs`) suit une période de voix détectée, OU
 *   - la durée max (`maxDurationMs`) est atteinte, OU
 *   - aucune voix détectée après `noVoiceTimeoutMs` (→ `no_voice`).
 *
 * Renvoie l'URI du fichier audio pour transcription, ou un kind d'erreur.
 *
 * Pour un feedback visuel temps réel (ribbons réactifs), passer `onLevel`
 * — appelé ~12×/s avec une valeur 0..1 dérivée du metering dB.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { PLAYBACK_AUDIO_MODE, RECORDING_AUDIO_MODE } from "../lib/audioMode";
import { Audio } from "expo-av";
import * as AgentysAudio from "../../modules/agentys-audio";
import { logEvent } from "../lib/eventLog";
import { reportError } from "../lib/errors";
import { createFloorTracker } from "../lib/vadFloor";

// Plafond d'attente du teardown d'un recording avant de résoudre le listen
// (#1134). Cas normal : stopAndUnloadAsync finit en ~100-150ms ; ce plafond
// n'est qu'un filet si l'unload natif se bloque (jamais observé), pour ne pas
// geler le tour de parole indéfiniment.
const CLEANUP_MAX_MS = 1500;

// Debounce VAD (device 2026-07-16) : frames consécutifs au-dessus du seuil
// requis pour déclarer la voix (~240 ms à 12.5 Hz). Un pic isolé (craquement,
// tap écran) ne démarre plus de capture.
const VOICE_DEBOUNCE_FRAMES = 3;
// Temps voisé cumulé minimal pour qu'une capture fermée par le VAD soit
// uploadée. En-dessous : transitoire → no_voice. « Oui » ≈ 300-500 ms.
const MIN_VOICED_MS = 250;
// Plancher glissant du VAD (device 2026-08-03) — voir src/lib/vadFloor.ts.
const FLOOR_WINDOW_FRAMES = 50; // ~4 s à 12.5 Hz (période status ~80 ms)
const FLOOR_MARGIN_DB = 7;
// Plancher de la DERNIÈRE écoute, partagé entre toutes les instances du hook :
// sert de seuil dès la première frame de l'écoute suivante (« mesurer
// l'ambiant AVANT d'ouvrir le micro » — en voiture, la voix se détecte
// par-dessus le bruit de route mémorisé). TTL court : l'environnement change.
let ambientSeed: { db: number; at: number } | null = null;
const AMBIENT_SEED_TTL_MS = 5 * 60_000;

export type VoiceState = "idle" | "listening" | "capturing";

export interface ListenOptions {
  /** Durée de silence après la voix avant auto-stop. Défaut 1800ms. */
  silenceMs?: number;
  /** Durée totale max. Défaut 30000ms. */
  maxDurationMs?: number;
  /** Durée min de voix avant que silenceMs soit appliqué. Défaut 300ms. */
  minSpeechMs?: number;
  /** Seuil dB au-dessus duquel on considère qu'il y a de la voix. Défaut -42. */
  voiceThresholdDb?: number;
  /** Délai max sans aucune voix avant d'abandonner. Défaut 10000ms. */
  noVoiceTimeoutMs?: number;
  /** #1134 : fenêtre de grâce (ms) au début de l'écoute pendant laquelle la
   *  détection de voix est INHIBÉE — le temps que l'earcon « à toi » finisse
   *  et que l'AEC converge, sinon le VAD prend l'earcon pour la voix. Défaut 0. */
  graceMs?: number;
  /** #1134 : active la session voiceChat (AEC hardware). NÉCESSAIRE seulement
   *  pour le barge-in full-duplex (écoute PENDANT la TTS). Pour une écoute
   *  séquentielle (aucune TTS simultanée), l'AEC ne sert à rien et ÉCRASE le
   *  gain du micro (voix mesurée à ~-48 dB au lieu de ~-32) → VAD qui rate la
   *  voix. Passer `false` pour un gain micro normal. Défaut true (compat). */
  useVoiceChat?: boolean;
  /** Callback ~12×/s avec le niveau audio 0..1 (pour UI). */
  onLevel?: (level: number) => void;
  /** Callback appelé UNE fois quand la voix démarre (début de `capturing`).
   *  Utilisé pour déclencher un barge-in (stopper le TTS qui joue). */
  onVoiceStart?: () => void;
}

export type ListenResult =
  | { kind: "ok"; uri: string }
  | { kind: "no_voice" }
  | { kind: "cancelled" }
  | { kind: "error"; error: string };

export interface UseVoiceDictation {
  state: VoiceState;
  listen: (opts?: ListenOptions) => Promise<ListenResult>;
  cancel: () => Promise<void>;
  /** Clôt la capture en cours en CONSERVANT l'audio (résout kind "ok").
   *  Retourne true si une capture était active. */
  flush: () => boolean;
}

export function useVoiceDictation(): UseVoiceDictation {
  const [state, setState] = useState<VoiceState>("idle");
  const recRef = useRef<Audio.Recording | null>(null);
  const cancelRef = useRef(false);
  const finishRef = useRef<((r: ListenResult, src?: string) => void) | null>(null);
  // Génération du listen courant (device 2026-07-28) : un finish() tardif d'un
  // listen préempté ne doit JAMAIS toucher les refs partagées (recRef,
  // finishRef, state) — sinon il tue le recorder du listen suivant.
  const listenGenRef = useRef(0);

  // P3.3 — Pré-chauffe : demander permissions + initialiser l'audio mode
  // au mount du hook, AVANT le premier listen(). Évite que le premier appel
  // déclenche un dialog de permission + ~300ms de setup audio system pile
  // au moment où l'user attend que le mic s'ouvre.
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await Audio.requestPermissionsAsync();
        // Pre-config seulement si pas déjà en voiceChat (laissé par un
        // listen précédent) — évite le toggle inutile.
        if (mounted) {
          await Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE);
        }
      } catch {
        // no-op légitime : permissions refusées au pré-chauffage — le premier
        // listen() retournera une erreur explicite via son propre chemin.
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const cleanup = useCallback(async () => {
    const rec = recRef.current;
    recRef.current = null;
    if (rec) {
      try {
        await rec.stopAndUnloadAsync();
      } catch {
        // no-op légitime : recorder déjà unloadé/mort — l'état visé (aucun
        // recorder actif) est atteint quoi qu'il arrive.
      }
    }
    // P3.3 — Optimisation latence : si le module natif est dispo, on
    // GARDE la session voiceChat active entre les listens. Audio.Recording
    // .createAsync est ~200-400ms plus rapide quand l'AVAudioSession reste
    // configurée. Pas de fuite audio : la sortie speaker reste fonctionnelle
    // pour le prochain TTS (voiceChat mode = speaker forcé).
    // Sans le module natif, on doit reset la category pour que les TTS
    // suivantes ne partent pas dans l'écouteur.
    if (!AgentysAudio.NATIVE_AVAILABLE) {
      try {
        await Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE);
      } catch (e) {
        // Un reset playback raté laisse la session en PlayAndRecord → la
        // prochaine TTS peut partir dans l'écouteur (classe de bugs #1134).
        reportError(e, { domain: "audio", op: "cleanupSetPlaybackMode" }, { userFacing: "silent" });
      }
    }
  }, []);

  const listen = useCallback(
    async (opts: ListenOptions = {}): Promise<ListenResult> => {
      const {
        silenceMs = 1800,
        maxDurationMs = 30_000,
        minSpeechMs = 300,
        voiceThresholdDb = -42,
        noVoiceTimeoutMs = 10_000,
        graceMs = 0,
        useVoiceChat = true,
        onLevel,
        onVoiceStart,
      } = opts;

      // Préempter tout listen précédent en le FINISSANT (cancelled), pas en
      // se contentant d'unloader son recorder. cleanup() seul laissait ses
      // timers mur-horloge (Fix B) armés : ils tiraient PLUS TARD et leur
      // cleanup() tuait le recorder du listen COURANT → capture sourde
      // (voicedMs=0, fileDur=-1, « ça ne me donne pas la main », 2026-07-28).
      const gen = ++listenGenRef.current;
      const prevFinish = finishRef.current;
      if (prevFinish) {
        // Le finish préempté se voit périmé (gen a bougé) : il résout sa
        // Promise et clear ses timers SANS toucher aux refs partagées.
        await prevFinish({ kind: "cancelled" }, "preempted");
      }
      if (recRef.current) {
        // C'est le préempteur qui unloade le recorder résiduel.
        await cleanup();
      }
      cancelRef.current = false;

      // [drive-dbg] Trace os_log (Release) : contexte du listen + état de la
      // session audio AVANT createAsync — pour diagnostiquer les captures
      // muettes post-dictée (transcriptions vides en boucle, 2026-07).
      AgentysAudio.debugLog(
        `listen start thr=${opts.voiceThresholdDb ?? -42} grace=${opts.graceMs ?? 0} ` +
        `aec=${opts.useVoiceChat !== false} max=${opts.maxDurationMs ?? 15000} ` +
        `session{${AgentysAudio.audioSessionSnapshot()}}`,
      );

      return new Promise<ListenResult>(async (resolve) => {
        let finished = false;
        // Recalé après createAsync (le setup consomme ~400 ms qu'on ne veut pas
        // amputer de la fenêtre no_voice/max).
        let started = Date.now();
        let voiceStartAt: number | null = null;
        let lastVoiceAt: number | null = null;
        // [drive-dbg] échantillonnage du metering pour le diagnostic.
        let maxDb = -160;
        let lastDbLogAt = 0;
        // Seuil VAD adaptatif CONTINU (device 2026-07-13, refondu 2026-08-03) :
        // le seuil fixe -38/-42 dB est AU-DESSUS du bruit ambiant réel
        // (-25..-30 dB en voiture / pièce vivante) → « voix » en continu,
        // aucune fenêtre de silence. La v1 calibrait le plancher UNE fois
        // pendant graceMs puis le figeait — un instant calme (-34) dans un
        // ambiant réel à -26 refigait le seuil SOUS l'ambiant et la
        // fin-de-parole ne se déclenchait jamais (compose, « Alexandre »).
        // v2 : plancher = MIN GLISSANT des ~4 dernières secondes de frames
        // (les instants calmes expirent, un frame plus calme retombe
        // instantanément), seuil = plancher + 7 dB borné [cfg, -18],
        // recalculé à CHAQUE frame. Le plancher de l'écoute précédente
        // (seed, TTL 5 min) sert de filet tant que la fenêtre n'est pas
        // remplie — en voiture, la voix est détectable par-dessus le bruit
        // de route dès la première frame, même en parlant pendant la grâce.
        const floorTracker = createFloorTracker(FLOOR_WINDOW_FRAMES);
        const seed = ambientSeed !== null && Date.now() - ambientSeed.at < AMBIENT_SEED_TTL_MS
          ? ambientSeed.db : null;
        let floorFrames = 0;
        let effThresholdDb: number | null = seed === null
          ? null
          : Math.min(-18, Math.max(voiceThresholdDb, seed + FLOOR_MARGIN_DB));
        let graceLogged = false;
        // Debounce anti-pics + temps voisé cumulé (device 2026-07-16) —
        // voir le commentaire au point de détection dans onStatus.
        let consecVoicedFrames = 0;
        let voicedTotalMs = 0;
        // #1134 (boucle) : filets mur-horloge INDÉPENDANTS de onStatus — voir
        // plus bas. Déclarés ici pour être nettoyés dans finish().
        let noVoiceTimer: ReturnType<typeof setTimeout> | null = null;
        let maxTimer: ReturnType<typeof setTimeout> | null = null;

        const finish = async (result: ListenResult, src: string = "?") => {
          if (finished) return;
          finished = true;
          // Périmé = un listen plus récent a pris la main (préemption). On
          // résout et on clear SES timers, mais on ne touche NI recRef NI
          // finishRef NI state : ils appartiennent au listen courant.
          const stale = listenGenRef.current !== gen;
          // [drive-dbg] verdict : type + SOURCE de fermeture + durée réelle du
          // fichier (durationMillis du recorder AVANT unload) vs durée écoulée.
          // Un fichier dont la durée ≠ elapsed+setup révèle une capture
          // corrompue/chevauchée (piste « transcripts vides », 2026-07-13).
          let fileDurMs = -1;
          try {
            const st = await recRef.current?.getStatusAsync();
            fileDurMs = (st as any)?.durationMillis ?? -1;
          } catch { /* recorder déjà mort */ }
          AgentysAudio.debugLog(
            `listen finish kind=${result.kind} src=${src} elapsed=${Date.now() - started}ms ` +
            `fileDur=${fileDurMs}ms maxDb=${maxDb.toFixed(1)} voicedMs=${voicedTotalMs} ` +
            `voiceDetected=${voiceStartAt !== null}`,
          );
          logEvent("audio", {
            op: "listen_finish", kind: result.kind, src,
            elapsedMs: Date.now() - started, fileDurMs,
            maxDb: Number(maxDb.toFixed(1)), voicedMs: voicedTotalMs,
            // Seuil VAD effectif de CETTE capture — diagnostique les écoutes
            // sourdes (seuil poussé au plafond par une calibration polluée).
            thr: effThresholdDb === null ? null : Number(effThresholdDb.toFixed(1)),
            ...(stale ? { stale: true } : {}),
          });
          // Persiste le plancher mesuré pour l'écoute suivante (seed) — info
          // d'environnement, valable même si CE listen a été préempté.
          const floorNow = floorTracker.floor();
          if (floorNow !== null) ambientSeed = { db: floorNow, at: Date.now() };
          if (noVoiceTimer) clearTimeout(noVoiceTimer);
          if (maxTimer) clearTimeout(maxTimer);
          if (stale) {
            resolve(result);
            return;
          }
          finishRef.current = null;
          // #1134 : ATTENDRE le teardown du recording AVANT de résoudre. Sinon
          // le listen suivant (auto-restart / tour de parole) démarre un
          // nouveau `Audio.Recording` pendant que le précédent s'unload encore
          // → deux recorders se chevauchent → l'audio capturé est corrompu et
          // le backend rejette (422 bad_audio). `Promise.race` avec un plafond
          // borne le cas (jamais observé) où stopAndUnloadAsync hang.
          await Promise.race([
            cleanup(),
            new Promise<void>((r) => setTimeout(r, CLEANUP_MAX_MS)),
          ]);
          setState("idle");
          resolve(result);
        };
        finishRef.current = finish;

        const onStatus = (status: Audio.RecordingStatus) => {
          if (finished || !status.isRecording) return;

          if (cancelRef.current) {
            finish({ kind: "cancelled" }, "cancel-status");
            return;
          }

          const now = Date.now();
          const elapsed = now - started;
          const db = typeof status.metering === "number" ? status.metering : -160;
          // [drive-dbg] niveau micro ~1×/s : -160 constant = micro MUET (route
          // input morte) ; -45..-50 = gain écrasé (AEC) ; -30 = voix normale.
          if (db > maxDb) maxDb = db;
          if (now - lastDbLogAt > 1000) {
            lastDbLogAt = now;
            AgentysAudio.debugLog(`meter db=${db.toFixed(1)} elapsed=${elapsed}ms`);
          }
          // #1134 : FENÊTRE DE GRÂCE. Le micro s'ouvre pendant que l'earcon
          // « à toi » joue encore et avant que l'AEC hardware n'ait convergé →
          // le VAD prenait l'earcon (~-37 dB) pour la voix de l'utilisateur
          // (onVoiceStart à +94 ms → capture → finish immédiat → « pas le temps
          // de parler »). Pendant `graceMs`, on N'ARME PAS la détection de voix
          // (le niveau visuel reste mis à jour). L'utilisateur parle après
          // l'earcon, donc aucune perte.
          // Plancher glissant (v2, voir déclaration de floorTracker) : chaque
          // frame — grâce comprise — alimente le MIN fenêtré. Le MIN reste
          // insensible aux transitoires forts (earcon à -3..-8 dB, tap) : il
          // ne retient que le plus calme. Le seed de l'écoute précédente
          // participe tant que la fenêtre n'est pas pleine, puis expire.
          floorFrames += 1;
          const ringFloor = floorTracker.push(db);
          const floor = seed !== null && floorFrames < FLOOR_WINDOW_FRAMES
            ? Math.min(ringFloor, seed) : ringFloor;
          effThresholdDb = Math.min(-18, Math.max(voiceThresholdDb, floor + FLOOR_MARGIN_DB));
          if (!graceLogged && elapsed >= graceMs) {
            graceLogged = true;
            AgentysAudio.debugLog(
              `vad threshold eff=${effThresholdDb.toFixed(1)} ambientN=${floorFrames} ` +
              `cfg=${voiceThresholdDb} seed=${seed === null ? "-" : seed.toFixed(1)}`,
            );
          }
          const rawVoiced = elapsed >= graceMs && db > (effThresholdDb ?? voiceThresholdDb);
          // -60 dB ≈ silence ambiant, -10 dB ≈ voix forte
          const level = Math.max(0, Math.min(1, (db + 60) / 50));
          onLevel?.(level);

          // Debounce anti-pics (device 2026-07-16) : un frame isolé au-dessus
          // du seuil (craquement, souffle, TAP sur l'écran mesuré à -8 dB)
          // déclenchait une capture « valide » de 1-5 s de bruit → upload →
          // transcript vide → ~2 s de cycle mort qui avalait la commande de
          // l'utilisateur (« j'ai dû répéter »). La voix réelle (-9..-18 dB)
          // tient sans effort VOICE_DEBOUNCE_FRAMES frames consécutifs
          // (~240 ms à 12.5 Hz) ; un transitoire jamais.
          if (rawVoiced) {
            consecVoicedFrames += 1;
            voicedTotalMs += 80; // période nominale des status updates
          } else {
            consecVoicedFrames = 0;
          }
          const isVoice = rawVoiced && consecVoicedFrames >= VOICE_DEBOUNCE_FRAMES;

          if (isVoice) {
            lastVoiceAt = now;
            if (voiceStartAt === null) {
              voiceStartAt = now;
              setState("capturing");
              // Firé UNE fois : permet au caller de stopper le TTS (barge-in)
              try {
                onVoiceStart?.();
              } catch (e) {
                // Un callback appelant qui lève est un bug du caller — visible.
                reportError(e, { domain: "state", op: "onVoiceStart" }, { userFacing: "silent" });
              }
            }
          }

          const enoughSpeech =
            voiceStartAt !== null && now - voiceStartAt > minSpeechMs;
          const silentEnough =
            lastVoiceAt !== null && now - lastVoiceAt > silenceMs;

          if (elapsed > maxDurationMs || (enoughSpeech && silentEnough)) {
            // Gate temps-voisé (device 2026-07-16) : si le total de frames
            // voisés est trop court pour être un mot (< MIN_VOICED_MS), la
            // « voix » était un transitoire qui a passé le debounce de
            // justesse — no_voice au lieu d'uploader du bruit (économise
            // l'upload + le cycle mort de ~2 s). « Oui » ≈ 300-500 ms voisés.
            if (voicedTotalMs < MIN_VOICED_MS) {
              finish({ kind: "no_voice" }, "vad-short");
              return;
            }
            const uri = recRef.current?.getURI() ?? null;
            finish(uri ? { kind: "ok", uri } : { kind: "error", error: "no-uri" }, "vad");
            return;
          }

          if (voiceStartAt === null && elapsed > noVoiceTimeoutMs) {
            finish({ kind: "no_voice" }, "nv-status");
          }
        };

        try {
          await Audio.requestPermissionsAsync();
          await Audio.setAudioModeAsync(RECORDING_AUDIO_MODE);

          // #1134 : voiceChat (AEC) UNIQUEMENT si demandé (barge-in full-duplex).
          // En écoute séquentielle (useVoiceChat=false), on NE configure PAS
          // l'AEC — il écrase le gain du micro et fait rater la voix. La
          // category playAndRecord posée par setAudioModeAsync ci-dessus + le
          // forceSpeakerOutput ci-dessous suffisent pour un record propre au
          // speaker, avec un gain normal.
          if (AgentysAudio.NATIVE_AVAILABLE && useVoiceChat) {
            AgentysAudio.configureForVoiceChat();
          }

          // LOW_QUALITY (22kHz / 64 kbps AAC) au lieu de HIGH_QUALITY :
          // - Fichier ~2× plus petit → upload plus rapide vers /api/transcribe
          // - Whisper-v3-turbo n'a pas besoin de >22 kHz pour la voix humaine
          //   (les fréquences utiles sont ≤ 8 kHz, Nyquist ≥ 16 kHz suffit)
          // - Réduit la latence perçue de ~150-300ms par dictée sur 4G
          const { recording } = await Audio.Recording.createAsync(
            {
              ...Audio.RecordingOptionsPresets.LOW_QUALITY,
              isMeteringEnabled: true,
            },
            onStatus,
            80, // status updates ~12.5Hz
          );
          // #1134 (boucle) — Fix A : si un cancel()/annulation est survenu
          // PENDANT l'ouverture du recorder (~200-600 ms), ne PAS l'installer.
          // Sinon on laisse un `Audio.Recording` orphelin vivant → le listen
          // suivant lève « Only one Recording object can be prepared » →
          // {error} instantané → auto-restart 500 ms → recollision → boucle où
          // le mic ne capte jamais (oscillation « Agentys parle ↔ You »).
          if (finished || cancelRef.current) {
            try { await recording.stopAndUnloadAsync(); } catch { /* à peine créé */ }
            if (!finished) finish({ kind: "cancelled" }, "aborted-create");
            return;
          }
          recRef.current = recording;
          // Fix C : recaler l'horloge après le setup.
          started = Date.now();
          // #1134 (boucle) — Fix B : filets mur-horloge INDÉPENDANTS de
          // `onStatus`. Les échappatoires no_voice/maxDuration vivent sinon
          // toutes dans le gate `!status.isRecording` d'onStatus : si le
          // recorder n'émet jamais isRecording=true (vu en Release device), la
          // Promise ne se résout JAMAIS → mic gelé, tour figé. Ces timers
          // garantissent la terminaison. `finished` protège du double-finish.
          noVoiceTimer = setTimeout(() => {
            if (!finished && voiceStartAt === null) finish({ kind: "no_voice" }, "nv-timer");
          }, noVoiceTimeoutMs);
          maxTimer = setTimeout(() => {
            if (!finished) {
              const uri = recRef.current?.getURI() ?? null;
              finish(uri ? { kind: "ok", uri } : { kind: "no_voice" }, "max");
            }
          }, maxDurationMs);
          // Recording.createAsync re-set la category en interne (expo-av
          // prepareToRecord) — iOS EFFACE l'override speaker à chaque
          // setCategory. Sans cette ré-application, le TTS qui joue en
          // parallèle bascule sur l'écouteur oreille (volume minuscule) —
          // confirmé device iPhone 13 le 2026-07-02. forceSpeakerOutput ne
          // touche que la route (pas la category) : sûr pendant un recording.
          if (AgentysAudio.NATIVE_AVAILABLE) {
            AgentysAudio.forceSpeakerOutput(true);
          }
          setState("listening");
        } catch (err: any) {
          finish({ kind: "error", error: String(err?.message || err) }, "create-error");
        }
      });
    },
    [cleanup],
  );

  const cancel = useCallback(async () => {
    cancelRef.current = true;
    const finish = finishRef.current;
    if (finish) {
      finish({ kind: "cancelled" }, "cancel-fn");
    } else {
      await cleanup();
      setState("idle");
    }
  }, [cleanup]);

  /** Clôt la capture EN COURS en CONSERVANT l'audio (résout kind "ok"),
   *  contrairement à cancel() qui le jette. Utilisé par le tap « c'est
   *  fini » quand le VAD n'a pas encore fermé la capture (bruit ambiant
   *  au-dessus du seuil, pause de réflexion). No-op sans capture active. */
  const flush = useCallback(() => {
    const finish = finishRef.current;
    if (!finish) return false;
    const uri = recRef.current?.getURI() ?? null;
    finish(uri ? { kind: "ok", uri } : { kind: "cancelled" }, "flush");
    return true;
  }, []);

  return { state, listen, cancel, flush };
}
