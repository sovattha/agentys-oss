/**
 * SpeakerChip — indicateur « qui parle maintenant ? ».
 * Pill : avatar (disque + anneau pulsant) + nom + sublabel + 3 dots animés.
 *
 *   - user  → accent teal,    label « You »      + glyphe « Y »
 *   - ai    → accent magenta, label « Agentys »  + glyphe « ✦ »
 *   - idle  → chip masquée par le parent (ne rien afficher)
 *
 * Couleurs alignées sur les extrêmes du gradient du VoiceVisualizer.
 */

import { useEffect, useRef } from "react";
import { View, Text, Animated, StyleSheet, Easing, Platform } from "react-native";
import { theme } from "../theme";
import type { SpeakerMode } from "./VoiceVisualizer";

interface Props {
  mode: SpeakerMode;
  /** Nom affiché en mode ai (défaut « Agentys »). */
  aiName?: string;
  /** Surcharge le nom en mode user (défaut « You »). */
  userName?: string;
  /** Surcharge le glyphe en mode user (défaut « Y »). */
  userGlyph?: string;
  /** Surcharge le sublabel actif (défaut « SPEAKING »). */
  activeSublabel?: string;
  /** Sublabel affiché en mode idle (défaut « TAP TO TALK »). */
  idleSublabel?: string;
  /** Label affiché en mode idle (défaut « Écoute »). */
  idleLabel?: string;
  /** Glyphe affiché en mode idle (défaut « · »). */
  idleGlyph?: string;
  /** Disque foncé avec glyphe blanc au lieu du disque rempli d'accent. */
  discStyle?: "filled" | "outlined";
  /** Override la couleur d'accent (sinon dérivée du mode). */
  accentOverride?: string;
}

const USER_ACCENT = "#3DE3C7"; // ~ oklch(78% 0.15 190)
const AI_ACCENT   = "#E85FC2"; // ~ oklch(72% 0.25 340)
const IDLE_ACCENT = "#7c7f86";

function accentFor(mode: SpeakerMode): string {
  return mode === "user" ? USER_ACCENT : mode === "ai" ? AI_ACCENT : IDLE_ACCENT;
}

export function SpeakerChip({
  mode,
  aiName = "Agentys",
  userName = "You",
  userGlyph = "Y",
  activeSublabel = "SPEAKING",
  idleSublabel = "TAP TO TALK",
  idleLabel = "Écoute",
  idleGlyph = "·",
  discStyle = "filled",
  accentOverride,
}: Props) {
  const accent = accentOverride ?? accentFor(mode);
  const isActive = mode === "user" || mode === "ai";

  const label =
    mode === "user" ? userName : mode === "ai" ? aiName : idleLabel;
  const sublabel = isActive ? activeSublabel : idleSublabel;
  const glyph = mode === "user" ? userGlyph : mode === "ai" ? "✦" : idleGlyph;

  // Anneau pulse : scale 1 → 1.8 + opacity 1 → 0, loop 1.6 s ease-out
  const ring = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!isActive) {
      ring.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.timing(ring, {
        toValue: 1,
        duration: 1600,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => {
      loop.stop();
      ring.setValue(0);
    };
  }, [isActive, ring]);

  const ringScale = ring.interpolate({ inputRange: [0, 1], outputRange: [1, 1.8] });
  const ringOpacity = ring.interpolate({ inputRange: [0, 1], outputRange: [1, 0] });

  // 3 dots staggered — bounce 1.2 s ease-in-out, offsets 0 / 180 / 360 ms
  const dot0 = useRef(new Animated.Value(0)).current;
  const dot1 = useRef(new Animated.Value(0)).current;
  const dot2 = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!isActive) return;
    const makeLoop = (v: Animated.Value, delay: number) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(delay),
          Animated.timing(v, {
            toValue: 1,
            duration: 600,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.timing(v, {
            toValue: 0,
            duration: 600,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
        ]),
      );
    const l0 = makeLoop(dot0, 0);
    const l1 = makeLoop(dot1, 180);
    const l2 = makeLoop(dot2, 360);
    l0.start();
    l1.start();
    l2.start();
    return () => {
      l0.stop();
      l1.stop();
      l2.stop();
    };
  }, [isActive, dot0, dot1, dot2]);

  const dotAnim = (v: Animated.Value) => ({
    opacity: v.interpolate({ inputRange: [0, 1], outputRange: [0.3, 1] }),
    transform: [
      {
        translateY: v.interpolate({
          inputRange: [0, 1],
          outputRange: [0, -1.5],
        }),
      },
    ],
  });

  return (
    <View
      style={[
        styles.chip,
        isActive && {
          shadowColor: accent,
          shadowOpacity: Platform.OS === "ios" ? 0.35 : 0,
          shadowRadius: 18,
          shadowOffset: { width: 0, height: 0 },
        },
      ]}
    >
      {/* Avatar 28 × 28 : anneau pulsant + disque coloré + glyphe blanc */}
      <View style={styles.avatar}>
        {isActive && (
          <Animated.View
            style={[
              styles.ring,
              {
                borderColor: accent,
                opacity: ringOpacity,
                transform: [{ scale: ringScale }],
              },
            ]}
          />
        )}
        <View
          style={[
            styles.disc,
            discStyle === "filled"
              ? { backgroundColor: accent }
              : { backgroundColor: "rgba(10,14,22,0.9)", borderWidth: 1.25, borderColor: accent },
          ]}
        >
          {discStyle === "filled" && <View style={styles.discHighlight} pointerEvents="none" />}
          <Text style={[styles.glyph, discStyle === "outlined" && { color: accent }]}>{glyph}</Text>
        </View>
      </View>

      {/* Bloc texte : nom + sublabel + 3 dots */}
      <View style={styles.textBlock}>
        <Text style={styles.name}>{label}</Text>
        <View style={styles.sublabelRow}>
          <Text style={styles.sublabel}>{sublabel}</Text>
          {isActive && (
            <View style={styles.dots}>
              <Animated.View
                style={[styles.dot, { backgroundColor: accent }, dotAnim(dot0)]}
              />
              <Animated.View
                style={[styles.dot, { backgroundColor: accent }, dotAnim(dot1)]}
              />
              <Animated.View
                style={[styles.dot, { backgroundColor: accent }, dotAnim(dot2)]}
              />
            </View>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingLeft: 8,
    paddingRight: 16,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.05)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.10)",
  },
  avatar: {
    width: 28,
    height: 28,
    alignItems: "center",
    justifyContent: "center",
  },
  ring: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderWidth: 1.5,
    borderRadius: 14,
  },
  disc: {
    width: 26,
    height: 26,
    borderRadius: 13,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  discHighlight: {
    position: "absolute",
    top: 2,
    left: 2,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "rgba(255,255,255,0.55)",
  },
  glyph: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "700",
    fontFamily: theme.fonts.bodyBold,
    includeFontPadding: false,
  },
  textBlock: {
    flexDirection: "column",
  },
  name: {
    fontSize: 19,
    fontWeight: "600",
    color: theme.colors.textPrimary,
    fontFamily: theme.fonts.bodySemi,
    letterSpacing: 0.1,
  },
  sublabelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    marginTop: 1,
  },
  sublabel: {
    fontSize: 13,
    color: "rgba(255,255,255,0.55)",
    fontFamily: theme.fonts.body,
    letterSpacing: 0.3,
    textTransform: "uppercase",
  },
  dots: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
  },
  dot: {
    width: 3,
    height: 3,
    borderRadius: 1.5,
  },
});
