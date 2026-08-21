/**
 * PulsingDot — Petit point qui pulse doucement (breathe cyclique).
 * Utilisé dans le badge "En écoute" pour rendre la persistance visible
 * sans surcharger l'interface.
 */

import { useEffect, useRef } from "react";
import { Animated, Easing } from "react-native";

interface Props {
  color: string;
  size?: number;
  /** Période complète (up + down) en ms. Défaut 1600 (calme, non stressant). */
  period?: number;
}

export function PulsingDot({ color, size = 6, period = 1600 }: Props) {
  const opacity = useRef(new Animated.Value(0.45)).current;

  useEffect(() => {
    const half = period / 2;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: half,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.45,
          duration: half,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, period]);

  return (
    <Animated.View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: color,
        opacity,
      }}
    />
  );
}
