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
 * BreathingTriangle — signature visuelle de la home screen.
 *
 * Triangle équilatéral pointe-en-haut qui respire sur un cycle de 5s :
 *   - scale intérieur 0.42 ↔ 0.78 (cosinus pur)
 *   - triangle extérieur apparaît uniquement quand l'intérieur est au plus
 *     petit (smoothstep sur `max(0, -cos)`)
 *   - rubans teal→magenta clippés à l'intérieur du triangle central
 *
 * Animation JS-driven (~60fps) via useAudioBands. Pas d'audio externe ici :
 * l'enveloppe est simulée en mode "ai" (flow continu).
 *
 * Audit UX 2026-04-28 :
 *   - `mode="loading"` : cycle ralenti à 8s + opacity 0.6 → utilisable comme
 *     remplaçant on-brand des ActivityIndicator génériques.
 *   - `accentColor` : surcharge la palette teal (idle teal / listening magenta /
 *     generating amber / speaking cyan / error red) pour que le triangle reflète
 *     l'état drive courant. Cohérence visuelle avec STATE_COLORS de DrivePlayer.
 */

import { useMemo } from "react";
import type { Animated } from "react-native";
import Svg, {
  ClipPath,
  Defs,
  G,
  LinearGradient,
  Path,
  Polygon,
  Stop,
} from "react-native-svg";
import {
  RIBBON_CONFIGS,
  ribbonShape,
  sampleGradient,
  useAudioBands,
} from "./ribbons-engine";

export type TriangleMode = "default" | "loading";

interface Props {
  size?: number;
  /** Niveau audio externe (0..1) — si fourni, pilote l'enveloppe macro des rubans. */
  externalLevel?: Animated.Value;
  /** Mode d'animation. `loading` ralentit le cycle et désature pour servir de
   *  loading indicator on-brand (remplace ActivityIndicator). */
  mode?: TriangleMode;
  /** Couleur d'accent override (hex). Si fourni, remplace le teal par défaut.
   *  Utilisé par DrivePlayer pour refléter le state courant. */
  accentColor?: string;
}

const TEAL_STROKE = "#3DE3C7"; // ~ oklch(78% 0.14 195)
const TEAL_INNER  = "#45DCC2"; // ~ oklch(75% 0.15 190)

export function BreathingTriangle({ size = 180, externalLevel, mode = "default", accentColor }: Props) {
  const audio = useAudioBands("ai", externalLevel);
  const t = audio.time;

  // Audit UX 2026-04-28 : `loading` ralentit à 8s (vs 5s default) — un loading
  // state qui pulse doucement signale "patience" mieux qu'un cycle vif.
  const cycleDurationSec = mode === "loading" ? 8 : 5;
  const cycle = (((t / cycleDurationSec) % 1) + 1) % 1;
  const raw = Math.cos(cycle * Math.PI * 2);

  // Intérieur : respire entre 0.42 (petit) et 0.78 (grand)
  const innerScale = 0.6 + raw * 0.18;

  // Extérieur : apparaît seulement quand l'intérieur est au plus petit
  const outerShow = Math.max(0, -raw);
  const eased = outerShow * outerShow * (3 - 2 * outerShow); // smoothstep
  const outerScale = 0.56 + eased * 0.36;
  const outerOpacity = eased;

  const cx = size / 2;
  const cy = size / 2;

  const poly = (scale: number): Array<[number, number]> => {
    const r = (size / 2) * scale;
    return [0, 120, 240].map((rot) => {
      const rads = ((rot - 90) * Math.PI) / 180;
      return [cx + Math.cos(rads) * r, cy + Math.sin(rads) * r] as [number, number];
    });
  };

  const innerPts = poly(innerScale);
  const outerPts = poly(outerScale);

  const innerStr = innerPts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const outerStr = outerPts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");

  // 3 couches suffisent sur mobile (les 2 premières ont blur élevé → coûteux)
  const configs = useMemo(() => RIBBON_CONFIGS.slice(1, 4), []);
  const ribbonsCy = size * 0.55;

  // Audit UX 2026-04-28 : palette overridable par `accentColor` (state-reactive).
  // En mode `loading`, désature à 60% pour signaler "passif".
  const strokeOuter = accentColor ?? TEAL_STROKE;
  const strokeInner = accentColor ?? TEAL_INNER;
  const globalOpacity = mode === "loading" ? 0.6 : 1;

  return (
    <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} opacity={globalOpacity}>
      <Defs>
        <ClipPath id="bt-clip">
          <Polygon points={innerStr} />
        </ClipPath>
        {configs.map((c, i) => (
          <LinearGradient key={`g${i}`} id={`bt-g${i}`} x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0%" stopColor={sampleGradient(Math.max(0, c.hue - 0.15))} />
            <Stop offset="50%" stopColor={sampleGradient(c.hue)} />
            <Stop offset="100%" stopColor={sampleGradient(Math.min(1, c.hue + 0.25))} />
          </LinearGradient>
        ))}
      </Defs>

      {/* Triangle extérieur — halo qui pulse à la plus petite forme intérieure */}
      <Polygon
        points={outerStr}
        fill="none"
        stroke={strokeOuter}
        strokeWidth={2 + eased * 0.6}
        strokeLinejoin="round"
        opacity={outerOpacity * 0.95}
      />

      {/* Rubans clippés dans le triangle intérieur */}
      <G clipPath="url(#bt-clip)">
        {configs.map((c, i) => {
          const shape = ribbonShape(size, ribbonsCy, audio, c, 1.2, 1, 28);
          return (
            <Path
              key={`r${i}`}
              d={shape.d}
              fill={`url(#bt-g${i})`}
              opacity={c.op}
            />
          );
        })}
      </G>

      {/* Outline du triangle intérieur, nette */}
      <Polygon
        points={innerStr}
        fill="none"
        stroke={strokeInner}
        strokeWidth={2.5}
        strokeLinejoin="round"
      />
    </Svg>
  );
}
