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
 * Design system — Cortex (Cyan/Slate Command Center)
 * Utilisé dans tous les écrans Agentys Mobile.
 */

export const theme = {
  colors: {
    bg:           "#06080A",
    surface:      "#0d1117",
    surfaceHigh:  "#161b22",
    border:       "#1a2333",
    primary:      "#22d3ee",
    primaryLight: "#67e8f9",
    primaryDark:  "#0e7490",
    cyan:         "#22d3ee",
    green:        "#34d399",
    red:          "#ef4444",
    amber:        "#fbbf24",
    textPrimary:  "#F0FAFA",
    textSecondary:"#9ca3af",
    textMuted:    "#4a5568",
    textGray:     "#6b7280",
    textDim:      "#374151",
    surface3:     "#1c2330",
    borderLight:  "#243044",
    cyanGlow:     "rgba(34,211,238,0.12)",
    // Design-spec tokens (home screen)
    surface2:     "#141c25",
    borderBright: "rgba(120, 220, 240, 0.22)",
    textDimmed:   "rgba(230, 238, 246, 0.55)",
    textFaint:    "rgba(230, 238, 246, 0.32)",
    cyanSoft:     "#9ff3fb",
    cyanDeep:     "#0891b2",
  },
  fonts: {
    display:    "JetBrainsMono_700Bold",
    mono:       "JetBrainsMono_400Regular",
    monoMedium: "JetBrainsMono_500Medium",
    monoBold:   "JetBrainsMono_700Bold",
    body:       "InstrumentSans_400Regular",
    bodyMedium: "InstrumentSans_500Medium",
    bodySemi:   "InstrumentSans_600SemiBold",
    bodyBold:   "InstrumentSans_700Bold",
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
  },
  radius: {
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
    xxl: 28,
  },
  timing: {
    breathe:   2400,
    pulse:      800,
    pulseSlow: 1200,
    fade:       300,
    stagger:     55,
  },
} as const;

export type Theme = typeof theme;
