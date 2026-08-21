/**
 * useAudioLevelEnvelope — niveau audio 0..1 pour l'aurora réactive (#1124).
 *
 * Extrait de useDriveMode (étape 3) : sous-système autonome.
 * - `audioLevel` : Animated.Value alimentée par `dictation.onLevel` quand
 *   l'utilisateur parle, et par une enveloppe SIMULÉE quand la TTS lit
 *   (base respirée + oscillation syllabique + bursts d'emphase rares).
 * - `pushAudioLevel` : écrit une valeur smoothed (useNativeDriver-safe).
 * - `startTtsEnvelope`/`stopTtsEnvelope` : cycle de vie de l'enveloppe
 *   simulée (10 Hz — assez smooth, léger en CPU).
 */

import { useCallback, useEffect, useRef } from "react";
import { Animated } from "react-native";

export interface AudioLevelEnvelope {
  audioLevel: Animated.Value;
  pushAudioLevel: (target: number, duration?: number) => void;
  startTtsEnvelope: () => void;
  stopTtsEnvelope: () => void;
}

export function useAudioLevelEnvelope(): AudioLevelEnvelope {
  const audioLevel = useRef(new Animated.Value(0)).current;
  const envelopeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const envelopePhaseRef = useRef(0);

  const pushAudioLevel = useCallback((target: number, duration = 100) => {
    Animated.timing(audioLevel, {
      toValue: Math.max(0, Math.min(1, target)),
      duration,
      useNativeDriver: true,
    }).start();
  }, [audioLevel]);

  const startTtsEnvelope = useCallback(() => {
    if (envelopeTimerRef.current) return;
    envelopePhaseRef.current = 0;
    pushAudioLevel(0.35, 200);
    envelopeTimerRef.current = setInterval(() => {
      // Signal composite : base 0.4 + oscillation syllabique 0.2 + burst rare 0.3
      envelopePhaseRef.current += 0.18;
      const syllabic    = Math.sin(envelopePhaseRef.current) * 0.18;
      const subOscil    = Math.sin(envelopePhaseRef.current * 2.3) * 0.08;
      const burst       = Math.random() < 0.12 ? 0.25 : 0;
      const lowVariance = (Math.random() - 0.5) * 0.05;
      const level = 0.42 + syllabic + subOscil + burst + lowVariance;
      pushAudioLevel(level, 120);
    }, 100);
  }, [pushAudioLevel]);

  const stopTtsEnvelope = useCallback(() => {
    if (envelopeTimerRef.current) {
      clearInterval(envelopeTimerRef.current);
      envelopeTimerRef.current = null;
    }
    pushAudioLevel(0, 500);
  }, [pushAudioLevel]);

  // Filet de sécurité : jamais de setInterval qui survit au unmount.
  useEffect(() => {
    return () => {
      if (envelopeTimerRef.current) clearInterval(envelopeTimerRef.current);
    };
  }, []);

  return { audioLevel, pushAudioLevel, startTtsEnvelope, stopTtsEnvelope };
}
