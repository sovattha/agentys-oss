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
 * Logo Agentys — Double triangle S4 (outer ring + inner jewel).
 *
 * Rendu pure React Native (border trick) pour éviter la dépendance react-native-svg.
 * Cinq couches :
 *   1. Outer ring (grand triangle cyan)
 *   2. Hollow cutout (triangle bg-color = effet anneau)
 *   3. Inner jewel (petit triangle cyan plein)
 *   4. Inner highlight (triangle clair sur le tiers sup de l'inner)
 *   5. Specular (blanc subtil, apex inner)
 */

import { View } from "react-native";
import { theme } from "../theme";

interface Props {
  size?: number;
  bgColor?: string;
}

export function AgentysLogo({ size = 140, bgColor = theme.colors.bg }: Props) {
  const S = size / 120;
  const h = size * (110 / 120);

  /**
   * Crée le style d'un triangle pointe-haut via la technique des bordures RN.
   * Paramètres en coordonnées du viewBox original (120×110).
   *
   * Note: pour un triangle symétrique (apex centré entre leftX et rightX),
   * left = leftX * S (le bord gauche en pixels).
   */
  const tri = (
    leftVbX: number,
    apexVbY: number,
    baseVbY: number,
    rightVbX: number,
    color: string,
    opacity = 1,
  ) => {
    const halfW = ((rightVbX - leftVbX) / 2) * S;
    return {
      position: "absolute" as const,
      top: apexVbY * S,
      left: leftVbX * S,
      width: 0,
      height: 0,
      borderLeftWidth: halfW,
      borderRightWidth: halfW,
      borderBottomWidth: (baseVbY - apexVbY) * S,
      borderLeftColor: "transparent",
      borderRightColor: "transparent",
      borderBottomColor: color,
      opacity,
    };
  };

  return (
    <View style={{ width: size, height: h }}>
      {/* 1. Outer ring base — M60 6 L114 104 L6 104 */}
      <View style={tri(6, 6, 104, 114, "#22d3ee", 0.85)} />
      {/* 2. Hollow cutout — M60 22 L102 98 L18 98 (crée l'anneau) */}
      <View style={tri(18, 22, 98, 102, bgColor, 1)} />
      {/* 3. Inner jewel — optical center in hollow (more top gap, less bottom gap) */}
      <View style={tri(28, 36, 92, 92, "#22d3ee", 1)} />
    </View>
  );
}
