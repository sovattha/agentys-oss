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
 * ribbons-engine — moteur partagé pour la visualisation Ribbons d'Agentys.
 *
 *   - palette teal → violet → magenta (4 stops OKLCH → sRGB)
 *   - Catmull-Rom → Bezier smoothing
 *   - 32 bandes audio simulées (ou alimentées par un Animated.Value externe)
 *   - 6 configs de rubans (phase, freq, amp, thickness, skew, speed, hue, blur, op)
 *
 * Utilisé par :
 *   - VoiceVisualizer     — full bleed dans DrivePlayer, audioLevel fourni par le hook
 *   - BreathingTriangle   — clippé à l'intérieur d'un triangle (login + home)
 */

import { useEffect, useRef, useState } from "react";
import type { Animated } from "react-native";

export type SpeakerMode = "user" | "ai" | "idle";

// ── Palette teal → magenta (OKLCH → sRGB approx) ───────────────────────────
const GRADIENT_STOPS: Array<[number, number, number]> = [
  [0x3d, 0xd8, 0xbc], // oklch(75% 0.15 190) teal
  [0x3e, 0xae, 0xe6], // oklch(72% 0.20 240) cyan-violet
  [0x9d, 0x6e, 0xde], // oklch(68% 0.22 290) violet
  [0xe4, 0x55, 0xb7], // oklch(70% 0.25 340) magenta
];

export function sampleGradient(t: number): string {
  const clamped = Math.max(0, Math.min(0.9999, t));
  const scaled = clamped * (GRADIENT_STOPS.length - 1);
  const i = Math.floor(scaled);
  const f = scaled - i;
  const a = GRADIENT_STOPS[i];
  const b = GRADIENT_STOPS[i + 1] ?? a;
  const r = Math.round(a[0] + (b[0] - a[0]) * f);
  const g = Math.round(a[1] + (b[1] - a[1]) * f);
  const bl = Math.round(a[2] + (b[2] - a[2]) * f);
  return `rgb(${r},${g},${bl})`;
}

// ── Catmull-Rom → cubic Bezier (chemin ouvert) ─────────────────────────────
export function smoothPath(points: Array<[number, number]>): string {
  if (points.length < 2) return "";
  let d = `M${points[0][0].toFixed(2)},${points[0][1].toFixed(2)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d +=
      `C${c1x.toFixed(2)},${c1y.toFixed(2)} ` +
      `${c2x.toFixed(2)},${c2y.toFixed(2)} ` +
      `${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}

// ── Config des 6 rubans (back → front) ─────────────────────────────────────
export type RibbonConfig = {
  phase: number;
  freq: number;
  ampMul: number;
  thickMul: number;
  skew: number;
  speed: number;
  hue: number;
  blur: number;
  op: number;
};

export const RIBBON_CONFIGS: RibbonConfig[] = [
  { phase: 0.0, freq: 2.2, ampMul: 1.15, thickMul: 1.9,  skew:  0.30, speed: 0.9, hue: 0.00, blur: 22, op: 0.28 },
  { phase: 1.3, freq: 3.0, ampMul: 0.95, thickMul: 1.3,  skew: -0.20, speed: 1.3, hue: 0.25, blur: 12, op: 0.45 },
  { phase: 2.6, freq: 2.6, ampMul: 1.05, thickMul: 0.9,  skew:  0.10, speed: 1.6, hue: 0.55, blur:  6, op: 0.65 },
  { phase: 3.8, freq: 3.8, ampMul: 0.75, thickMul: 0.65, skew: -0.35, speed: 2.0, hue: 0.80, blur:  2, op: 0.85 },
  { phase: 4.9, freq: 4.4, ampMul: 0.55, thickMul: 0.4,  skew:  0.20, speed: 2.4, hue: 1.00, blur:  0, op: 0.95 },
  { phase: 5.7, freq: 5.1, ampMul: 0.38, thickMul: 0.25, skew: -0.10, speed: 2.9, hue: 0.35, blur:  0, op: 0.90 },
];

// ── 1D value noise ─────────────────────────────────────────────────────────
function makeNoise(seed: number): (t: number) => number {
  const rand = (i: number) => {
    const x = Math.sin((i + seed) * 127.1) * 43758.5453;
    return x - Math.floor(x);
  };
  return (t: number) => {
    const i = Math.floor(t);
    const f = t - i;
    const s = f * f * (3 - 2 * f);
    return rand(i) * (1 - s) + rand(i + 1) * s;
  };
}

// ── Audio frame ────────────────────────────────────────────────────────────
export interface AudioFrame {
  level: number;
  bands: Float32Array;
  time: number;
}

/**
 * Hook qui produit un AudioFrame (level 0..1 + 32 bandes + time).
 *
 * Si `externalLevel` (Animated.Value) est fourni, le niveau macro suit sa
 * valeur courante (mic/TTS réels du DrivePlayer). Sinon, fallback sur une
 * enveloppe simulée selon `mode` — même comportement que audio-engine.jsx
 * du design handoff (user = bursty, ai = flow continu).
 */
export function useAudioBands(
  mode: SpeakerMode,
  externalLevel?: Animated.Value,
): AudioFrame {
  const [, tick] = useState(0);
  const ref = useRef<
    AudioFrame & {
      start: number;
      target: Float32Array;
      noises: Array<(t: number) => number>;
      external: number;
      hasExternal: boolean;
      burstUntil: number;
      pauseUntil: number;
    }
  >({
    start: Date.now(),
    level: 0,
    bands: new Float32Array(32),
    target: new Float32Array(32),
    noises: Array.from({ length: 34 }, (_, i) => makeNoise(i * 7.3 + 11)),
    external: 0,
    hasExternal: false,
    burstUntil: 0,
    pauseUntil: 0,
    time: 0,
  });

  useEffect(() => {
    if (!externalLevel) {
      ref.current.hasExternal = false;
      return;
    }
    ref.current.hasExternal = true;
    const id = externalLevel.addListener(({ value }) => {
      ref.current.external = value;
    });
    return () => externalLevel.removeListener(id);
  }, [externalLevel]);

  useEffect(() => {
    let raf = 0;
    let cancelled = false;
    const loop = () => {
      if (cancelled) return;
      const s = ref.current;
      const now = Date.now();
      const t = (now - s.start) / 1000;
      s.time = t;

      // Enveloppe macro : externe si branchée, sinon simulée selon le mode
      let macro: number;
      if (s.hasExternal) {
        macro = s.external;
      } else if (mode === "user") {
        if (now > s.burstUntil && now > s.pauseUntil) {
          if (Math.random() < 0.75) {
            s.burstUntil = now + 900 + Math.random() * 1200;
          } else {
            s.pauseUntil = now + 300 + Math.random() * 500;
          }
        }
        const inBurst = now < s.burstUntil;
        const inPause = now < s.pauseUntil;
        const baseLoud = inBurst
          ? 0.55 + 0.35 * s.noises[0](t * 8)
          : inPause
            ? 0.05
            : 0.2;
        const syl = 0.5 + 0.5 * Math.sin(t * 13 + s.noises[1](t * 2) * 6);
        macro = baseLoud * (0.5 + 0.5 * syl);
      } else {
        // mode "ai" ou "idle" — flow continu AI
        const slow = 0.45 + 0.35 * Math.sin(t * 0.8);
        const med = 0.5 + 0.5 * Math.sin(t * 2.3 + s.noises[2](t * 0.5) * 4);
        macro = slow * (0.6 + 0.4 * med);
      }

      s.level += (macro - s.level) * 0.18;

      for (let i = 0; i < 32; i++) {
        const n = s.noises[i];
        const freqWeight =
          mode === "user"
            ? Math.exp(-Math.pow((i - 7) / 10, 2)) * 1.2 + 0.3
            : Math.exp(-Math.pow((i - 14) / 14, 2)) * 1.0 + 0.4;
        const bandSpeed = mode === "user" ? 6 + i * 0.15 : 2 + i * 0.08;
        const v = n(t * bandSpeed) * freqWeight * (0.3 + s.level * 1.2);
        s.target[i] = Math.max(0, Math.min(1, v));
        const alpha = mode === "user" ? 0.35 : 0.22;
        s.bands[i] += (s.target[i] - s.bands[i]) * alpha;
      }

      tick((x) => (x + 1) % 1_000_000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [mode]);

  return ref.current;
}

// ── Ribbon shape builder ──────────────────────────────────────────────────
const DEFAULT_STEPS = 56;
const BAND_COUNT = 32;

export interface RibbonShape {
  d: string;
  topD: string;
}

export function ribbonShape(
  width: number,
  cy: number,
  audio: AudioFrame,
  cfg: RibbonConfig,
  globalSpeed: number,
  intensity: number,
  steps = DEFAULT_STEPS,
): RibbonShape {
  const top: Array<[number, number]> = [];
  const bot: Array<[number, number]> = [];
  for (let i = 0; i <= steps; i++) {
    const tx = i / steps;
    const x = tx * width;
    const env = Math.pow(Math.sin(tx * Math.PI), 0.7);
    const bIdx = Math.min(BAND_COUNT - 1, Math.floor(tx * BAND_COUNT));
    const b = audio.bands[bIdx] ?? 0;
    const baseY =
      cy +
      Math.sin(tx * Math.PI * cfg.freq + audio.time * cfg.speed * globalSpeed + cfg.phase) *
        env *
        (20 + audio.level * 90) *
        cfg.ampMul *
        intensity +
      Math.sin(
        tx * Math.PI * cfg.freq * 2.2 +
          audio.time * cfg.speed * globalSpeed * 1.6 +
          cfg.phase * 1.4,
      ) *
        env *
        (6 + audio.level * 30) *
        cfg.ampMul *
        0.55 *
        intensity +
      cfg.skew * (tx - 0.5) * 30;
    const thick =
      (6 + b * 34 + audio.level * 18) * cfg.thickMul * intensity * (0.5 + env * 0.7);
    top.push([x, baseY - thick]);
    bot.push([x, baseY + thick]);
  }
  const topD = smoothPath(top);
  const botRev = [...bot].reverse();
  const botD = smoothPath(botRev).replace(/^M/, "L");
  return { d: topD + botD + "Z", topD };
}
