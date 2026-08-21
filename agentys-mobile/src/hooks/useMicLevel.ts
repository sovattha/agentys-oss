/**
 * useMicLevel — ouvre le mic et expose son niveau normalisé (0..1) via un
 * Animated.Value. Retourne null si la permission est refusée ou si l'API audio
 * n'est pas disponible — le caller peut alors basculer sur une animation
 * temporelle.
 *
 * Conçu pour piloter les visualisations (BreathingTriangle, VoiceVisualizer)
 * en passant le résultat comme `externalLevel` à `useAudioBands`.
 */

import { useEffect, useRef, useState } from "react";
import { Animated } from "react-native";
import { Audio } from "expo-av";
import { AMBIENT_MIC_AUDIO_MODE } from "../lib/audioMode";

export function useMicLevel(): Animated.Value | null {
  const [granted, setGranted] = useState<boolean | null>(null);
  const levelRef = useRef(new Animated.Value(0));
  const recRef = useRef<Audio.Recording | null>(null);

  useEffect(() => {
    let cancelled = false;
    const level = levelRef.current;

    (async () => {
      try {
        const perm = await Audio.requestPermissionsAsync();
        if (!perm.granted) {
          if (!cancelled) setGranted(false);
          return;
        }
        await Audio.setAudioModeAsync(AMBIENT_MIC_AUDIO_MODE);

        const { recording } = await Audio.Recording.createAsync(
          {
            ...Audio.RecordingOptionsPresets.LOW_QUALITY,
            isMeteringEnabled: true,
          },
          (status) => {
            if (!status.isRecording) return;
            const db = typeof status.metering === "number" ? status.metering : -60;
            // -60 dB ≈ silence ambiant, 0 dB ≈ saturé
            const norm = Math.max(0, Math.min(1, (db + 60) / 60));
            level.setValue(norm);
          },
          80,
        );

        if (cancelled) {
          await recording.stopAndUnloadAsync().catch(() => {}); // no-op légitime : recorder déjà mort
          return;
        }
        recRef.current = recording;
        setGranted(true);
      } catch {
        if (!cancelled) setGranted(false);
      }
    })();

    return () => {
      cancelled = true;
      recRef.current?.stopAndUnloadAsync().catch(() => {}); // no-op légitime : recorder déjà mort
      recRef.current = null;
    };
  }, []);

  return granted === true ? levelRef.current : null;
}
