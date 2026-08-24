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
 * CategoryCard — carte de la home screen (variante « Triangle = viz »).
 *
 *   variant="big"    → carte ACTION pleine largeur, count 56pt, bordure teal
 *   variant="small"  → carte INFO / LES DEUX, count 32pt, bordure subtile
 *
 * count=null → skeleton pulsant (chargement)
 * disabled   → opacité réduite + non tappable
 */

import { useEffect, useRef } from "react";
import { Animated, Easing, Pressable, StyleSheet, Text, View } from "react-native";
import { theme } from "../theme";

interface Props {
  label: string;
  /** Détail affiché après « · » sur la carte big. Ignoré en small. */
  detail?: string;
  count: number | null;
  variant?: "big" | "small";
  disabled?: boolean;
  onPress: () => void;
}

const ACCENT_TEAL = "#3DE3C7";

function Skeleton({ big }: { big: boolean }) {
  const pulse = useRef(new Animated.Value(0.25)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 0.55,
          duration: 650,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 0.25,
          duration: 650,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <Animated.View
      style={[
        big ? styles.skeletonBig : styles.skeletonSmall,
        { opacity: pulse },
      ]}
    />
  );
}

export function CategoryCard({
  label,
  detail,
  count,
  variant = "big",
  disabled = false,
  onPress,
}: Props) {
  const isBig = variant === "big";
  const inactive = disabled || count === 0;

  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      style={({ pressed }) => [
        isBig ? styles.cardBig : styles.cardSmall,
        pressed && !inactive && styles.cardPressed,
        inactive && styles.cardDisabled,
      ]}
      accessibilityRole="button"
      accessibilityLabel={`${label} — ${count ?? "chargement"}`}
    >
      <Text
        style={isBig ? styles.labelBig : styles.labelSmall}
        numberOfLines={1}
      >
        {isBig && detail ? `${label} · ${detail}` : label}
      </Text>

      {count === null ? (
        <Skeleton big={isBig} />
      ) : (
        <Text style={isBig ? styles.countBig : styles.countSmall}>{count}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  cardBig: {
    backgroundColor: "rgba(22,24,28,0.72)",
    borderWidth: 1,
    borderColor: "rgba(61,227,199,0.5)",
    borderRadius: 18,
    paddingVertical: 22,
    paddingHorizontal: 20,
  },
  cardSmall: {
    flex: 1,
    backgroundColor: "rgba(22,24,28,0.72)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.05)",
    borderRadius: 18,
    paddingVertical: 16,
    paddingHorizontal: 14,
  },
  cardPressed: {
    opacity: 0.82,
    transform: [{ scale: 0.985 }],
  },
  cardDisabled: {
    opacity: 0.32,
  },

  labelBig: {
    fontSize: 10,
    fontFamily: theme.fonts.bodySemi,
    color: ACCENT_TEAL,
    letterSpacing: 2,
    textTransform: "uppercase",
  },
  labelSmall: {
    fontSize: 9,
    fontFamily: theme.fonts.bodySemi,
    color: theme.colors.textFaint,
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },

  countBig: {
    fontSize: 56,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
    letterSpacing: -1.5,
    lineHeight: 58,
    marginTop: 4,
  },
  countSmall: {
    fontSize: 32,
    fontFamily: theme.fonts.bodyMedium,
    color: "rgba(235,235,245,0.55)",
    letterSpacing: -0.5,
    lineHeight: 34,
    marginTop: 2,
  },

  skeletonBig: {
    width: 72,
    height: 52,
    borderRadius: 8,
    backgroundColor: `${ACCENT_TEAL}33`,
    marginTop: 6,
  },
  skeletonSmall: {
    width: 40,
    height: 28,
    borderRadius: 6,
    backgroundColor: "rgba(235,235,245,0.18)",
    marginTop: 4,
  },
});
