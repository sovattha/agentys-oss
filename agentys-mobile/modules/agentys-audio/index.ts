/**
 * agentys-audio — module natif iOS pour contrôle AVAudioSession.
 *
 * Expose des APIs que `expo-av` ne propose pas :
 * - `forceSpeakerOutput(enable)` : `AVAudioSession.overrideOutputAudioPort(.speaker)`
 * - `setVoiceChatMode(enable)` : active l'AEC hardware (suppression de l'écho)
 * - `configureForVoiceChat()` : combo atomique (category playAndRecord +
 *   voiceChat mode + speaker override + activate). À appeler avant
 *   d'enregistrer pendant la TTS pour avoir barge-in vocal fiable.
 * - `configureForPlayback()` : reset vers config playback standard.
 *
 * Sur Android et web, toutes les fonctions retournent `false` (no-op).
 *
 * Usage :
 * ```ts
 * import * as AgentysAudio from "../../modules/agentys-audio";
 *
 * // Avant un speakAndListen :
 * await AgentysAudio.configureForVoiceChat();
 * // ... TTS + recording simultanés (barge-in clean)
 * await AgentysAudio.configureForPlayback();
 * ```
 */

import { Platform } from "react-native";
import { requireOptionalNativeModule } from "expo-modules-core";

interface MicFrameEvent {
  base64: string;
}

interface MicStreamErrorEvent {
  error: string;
}

interface AgentysAudioNative {
  forceSpeakerOutput(enable: boolean): boolean;
  setVoiceChatMode(enable: boolean): boolean;
  isSpeakerForced(): boolean;
  configureForVoiceChat(): boolean;
  configureForPlayback(): boolean;
  /** Absent d'un build natif antérieur à son ajout — passer par
   *  `deactivateSession()` (wrapper) qui teste sa présence. */
  deactivateSession(): boolean;
  debugLog(message: string): void;
  audioSessionSnapshot(): string;
  // Step 4 (streaming STT) — absents sur un build natif antérieur à leur
  // ajout : toujours tester MIC_STREAM_AVAILABLE avant d'appeler.
  startMicStream(sampleRate: number): boolean;
  stopMicStream(): boolean;
  addListener(
    eventName: "onMicFrame" | "onMicStreamError",
    listener: (event: MicFrameEvent | MicStreamErrorEvent) => void,
  ): { remove: () => void };
}

// `requireOptionalNativeModule` retourne null si le module n'est pas linké
// (Expo Go, ou un dev build sans la pré-compilation). Sur Android, on n'a
// pas implémenté le module — il sera donc null et toutes les APIs no-op.
const native = requireOptionalNativeModule<AgentysAudioNative>("AgentysAudio");

const IS_IOS = Platform.OS === "ios";

/**
 * Force la sortie audio vers le speaker (true) ou laisse iOS choisir (false).
 * Sur Android / Expo Go : no-op, retourne false.
 */
export function forceSpeakerOutput(enable: boolean): boolean {
  if (!IS_IOS || !native) return false;
  return native.forceSpeakerOutput(enable);
}

/**
 * Active (true) ou désactive (false) le mode voiceChat (AEC hardware iOS).
 * Sur Android / Expo Go : no-op, retourne false.
 */
export function setVoiceChatMode(enable: boolean): boolean {
  if (!IS_IOS || !native) return false;
  return native.setVoiceChatMode(enable);
}

/**
 * Renvoie true si la sortie audio courante inclut le speaker built-in.
 * Sur Android / Expo Go : retourne false.
 */
export function isSpeakerForced(): boolean {
  if (!IS_IOS || !native) return false;
  return native.isSpeakerForced();
}

/**
 * Configure la session pour le pattern speakAndListen (TTS + recording
 * simultanés sans écho). Combine setCategory(playAndRecord, voiceChat) +
 * overrideOutputAudioPort(speaker) + setActive(true).
 * Sur Android / Expo Go : no-op, retourne false.
 */
export function configureForVoiceChat(): boolean {
  if (!IS_IOS || !native) return false;
  return native.configureForVoiceChat();
}

/**
 * Reset la session vers la config playback standard (speaker, pas de mic).
 * À appeler quand on quitte un mode où l'enregistrement n'est plus actif.
 * Sur Android / Expo Go : no-op, retourne false.
 */
export function configureForPlayback(): boolean {
  if (!IS_IOS || !native) return false;
  return native.configureForPlayback();
}

/**
 * Rend l'AVAudioSession au système avec `.notifyOthersOnDeactivation` : c'est
 * ce qui autorise la musique interrompue au début de session (Spotify, Apple
 * Music, podcast…) à reprendre. À appeler à la FIN d'une session Drive, une
 * fois la TTS arrêtée.
 *
 * Indispensable parce qu'`expo-av` ne désactive plus jamais la session
 * (expo/expo#15873) : sans ce call, l'autre app reste interrompue.
 * Sur Android / Expo Go / build natif antérieur : no-op, retourne false.
 */
export function deactivateSession(): boolean {
  if (!IS_IOS || !native || typeof native.deactivateSession !== "function") return false;
  try {
    return native.deactivateSession();
  } catch {
    return false;
  }
}

/** Trace visible dans os_log en Release (console.log Hermes ne l'est pas).
 *  No-op sans module natif. Tag : [drive-dbg]. */
export function debugLog(message: string): void {
  if (!IS_IOS || !native) return;
  try { native.debugLog(message); } catch { /* no-op */ }
}

/** Snapshot AVAudioSession (category/mode/routes/gain) — "" sans natif. */
export function audioSessionSnapshot(): string {
  if (!IS_IOS || !native) return "";
  try { return native.audioSessionSnapshot(); } catch { return ""; }
}

/**
 * Renvoie true si le module natif est disponible (dev build avec ce module
 * compilé). Permet aux callers de tomber proprement en fallback sur
 * expo-av seul si le module n'est pas linké.
 */
export const NATIVE_AVAILABLE: boolean = IS_IOS && native !== null;

/**
 * Step 4 — tap mic AVAudioEngine dispo ? Distinct de NATIVE_AVAILABLE : un
 * dev build compilé AVANT l'ajout de startMicStream a le module sans cette
 * fonction. Les callers (useStreamingStt) doivent fallback batch si false.
 */
export const MIC_STREAM_AVAILABLE: boolean =
  NATIVE_AVAILABLE && typeof (native as AgentysAudioNative | null)?.startMicStream === "function";

/**
 * Démarre le streaming mic natif : frames PCM16 mono à `sampleRate` Hz
 * émises via l'event onMicFrame (payload base64). Retourne false si le
 * module/la fonction est absent ou si l'engine ne démarre pas.
 */
export function startMicStream(sampleRate = 16000): boolean {
  if (!MIC_STREAM_AVAILABLE || !native) return false;
  try {
    return native.startMicStream(sampleRate);
  } catch {
    return false;
  }
}

/** Coupe le streaming mic natif. Idempotent, no-op si indisponible. */
export function stopMicStream(): boolean {
  if (!MIC_STREAM_AVAILABLE || !native) return false;
  try {
    return native.stopMicStream();
  } catch {
    return false;
  }
}

/**
 * S'abonne aux frames mic (base64 de PCM16 mono). Retourne une fonction de
 * désabonnement (no-op si module absent).
 */
export function addMicFrameListener(listener: (base64: string) => void): () => void {
  if (!MIC_STREAM_AVAILABLE || !native) return () => {};
  const sub = native.addListener("onMicFrame", (event) => {
    const frame = event as MicFrameEvent;
    if (frame?.base64) listener(frame.base64);
  });
  return () => sub.remove();
}

/** S'abonne aux erreurs du stream mic natif. */
export function addMicStreamErrorListener(listener: (error: string) => void): () => void {
  if (!MIC_STREAM_AVAILABLE || !native) return () => {};
  const sub = native.addListener("onMicStreamError", (event) => {
    const err = event as MicStreamErrorEvent;
    listener(err?.error || "unknown");
  });
  return () => sub.remove();
}
