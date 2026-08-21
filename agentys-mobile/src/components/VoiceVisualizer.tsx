/**
 * VoiceVisualizer — 5 rubans fluides horizontaux, ancrés au bas de l'écran.
 * Port du design handoff « Voice Visualizer — Ribbons ».
 *
 *   - chaque ruban est un <Path> SVG recalculé à chaque frame (~60fps JS)
 *   - amplitude/épaisseur pilotées par 32 bandes simulées à partir du
 *     audioLevel temps réel (mic en user, envelope TTS en ai)
 *   - gradient teal→magenta, Gaussian blur sur les rubans arrière
 *
 * Logique math + audio mutualisée dans ribbons-engine.ts.
 */

import { useMemo, useRef } from "react";
import { View, StyleSheet, Animated } from "react-native";
import Svg, {
  Defs,
  LinearGradient,
  RadialGradient,
  Stop,
  Path,
  Rect,
  Circle,
  G,
} from "react-native-svg";
import {
  RIBBON_CONFIGS,
  type SpeakerMode,
  ribbonShape,
  sampleGradient,
  useAudioBands,
} from "./ribbons-engine";

export type { SpeakerMode } from "./ribbons-engine";

interface Props {
  mode: SpeakerMode;
  width: number;
  height: number;
  /** Y du centre des rubans. Défaut 78 % de la hauteur. */
  centerY?: number;
  /** Multiplicateur vitesse d'oscillation (défaut 1). */
  speed?: number;
  /** Multiplicateur amplitude/épaisseur (défaut 1). */
  intensity?: number;
  /** Nombre de rubans 3..6 (défaut 5). */
  count?: number;
  /** Niveau audio 0..1. Optionnel — fallback enveloppe simulée. */
  audioLevel?: Animated.Value;
}

export function VoiceVisualizer({
  mode,
  width,
  height,
  centerY,
  speed = 1,
  intensity = 1,
  count = 5,
  audioLevel,
}: Props) {
  const audio = useAudioBands(mode, audioLevel);
  const cy = centerY ?? height * 0.78;

  const configs = useMemo(() => RIBBON_CONFIGS.slice(0, count), [count]);

  // User = bursty → parle un peu plus vite
  const modeSpeed = mode === "user" ? 1.25 : 1;
  const effectiveSpeed = speed * modeSpeed;

  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.root]}>
      <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <Defs>
          {configs.map((c, i) => (
            <LinearGradient key={`g${i}`} id={`vv-g${i}`} x1="0" y1="0" x2="1" y2="0">
              <Stop offset="0%" stopColor={sampleGradient(Math.max(0, c.hue - 0.15))} />
              <Stop offset="50%" stopColor={sampleGradient(c.hue)} />
              <Stop offset="100%" stopColor={sampleGradient(Math.min(1, c.hue + 0.25))} />
            </LinearGradient>
          ))}
          <LinearGradient id="vv-sheen" x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0%" stopColor="#ffffff" stopOpacity="0" />
            <Stop offset="50%" stopColor="#ffffff" stopOpacity="0.55" />
            <Stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </LinearGradient>
          <RadialGradient id="vv-floor" cx="50%" cy="100%" rx="70%" ry="70%">
            <Stop offset="0%" stopColor="#a97cee" stopOpacity="0.32" />
            <Stop offset="60%" stopColor="#a97cee" stopOpacity="0.08" />
            <Stop offset="100%" stopColor="#a97cee" stopOpacity="0" />
          </RadialGradient>
        </Defs>

        {/* Nappe lumineuse au sol — suit les rubans */}
        <Rect
          x={0}
          y={Math.max(0, cy - height * 0.6)}
          width={width}
          height={height}
          fill="url(#vv-floor)"
        />

        {/* Rubans arrière → avant */}
        {configs.map((c, i) => {
          const shape = ribbonShape(width, cy, audio, c, effectiveSpeed, intensity, 28);
          return (
            <G key={`r${i}`} opacity={c.op}>
              <Path
                d={shape.d}
                fill={`url(#vv-g${i})`}
              />
              {c.blur <= 2 && (
                <Path
                  d={shape.topD}
                  stroke="url(#vv-sheen)"
                  strokeWidth={1.2}
                  fill="none"
                  opacity={0.75}
                />
              )}
            </G>
          );
        })}

        {/* Point spéculaire traversant le ruban de devant */}
        {configs.length > 0
          ? (() => {
              const front = configs[configs.length - 1];
              const tx = (((audio.time * 0.18) % 1) + 1) % 1;
              const x = tx * width;
              const env = Math.pow(Math.sin(tx * Math.PI), 0.7);
              const y =
                cy +
                Math.sin(
                  tx * Math.PI * front.freq +
                    audio.time * front.speed * effectiveSpeed +
                    front.phase,
                ) *
                  env *
                  (20 + audio.level * 90) *
                  front.ampMul *
                  intensity;
              return <Circle cx={x} cy={y} r={3.5} fill="#ffffff" opacity={0.85} />;
            })()
          : null}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    overflow: "visible",
    backgroundColor: "transparent",
  },
});
