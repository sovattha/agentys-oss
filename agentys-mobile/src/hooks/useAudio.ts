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
