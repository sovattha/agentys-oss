/**
 * Hook STT (enregistrement) — reste de l'ancien useAudio après la migration
 * vers ElevenLabs TTS.
 *
 * Le TTS est désormais géré par `useTts.ts`. Ici on ne conserve que
 * `startRecording` / `stopRecording` utilisés par :
 *   - AudioRecorder (réponse vocale)
 *   - VoiceCloneModal (échantillon pour le clonage)
 */

import { useCallback, useRef, useState } from "react";
import { PLAYBACK_AUDIO_MODE, RECORDING_AUDIO_MODE } from "../lib/audioMode";
import { Audio } from "expo-av";

export type AudioState = "idle" | "recording" | "stopped";

interface UseAudioResult {
  audioState: AudioState;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string | null>;
}

export function useAudio(): UseAudioResult {
  const [audioState, setAudioState] = useState<AudioState>("idle");
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = useCallback(async () => {
    try {
      await Audio.requestPermissionsAsync();
      await Audio.setAudioModeAsync(RECORDING_AUDIO_MODE);

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = recording;
      setAudioState("recording");
    } catch {
      setAudioState("idle");
    }
  }, []);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    const recording = recordingRef.current;
    if (!recording) return null;

    try {
      await recording.stopAndUnloadAsync();
      recordingRef.current = null;
      // Rebasculer en mode playback pour que le TTS redevienne audible après l'enregistrement
      await Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE);
      setAudioState("stopped");
      return recording.getURI() ?? null;
    } catch {
      setAudioState("idle");
      return null;
    }
  }, []);

  return { audioState, startRecording, stopRecording };
}
