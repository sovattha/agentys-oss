/**
 * EmptyState — affichage célébré de l'inbox zero (et autres "rien à faire").
 *
 * Audit UX 2026-04-28 : remplace le texte plat `t("noEmails")` par une
 * micro-célébration on-brand. Triangle ralenti (mode="loading" 8s) +
 * phrase variable (5 variantes random + une fortune-cookie pour le coup
 * de chance des inbox-zero stricts).
 *
 * Pourquoi : "inbox zero" est un MOMENT (rare, satisfaisant) — l'app doit
 * le célébrer un minimum. Coût : ~50 lignes. Gain : retour émotionnel +
 * mémorabilité (cf. Hey, Things 3).
 */

import { useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";
import { theme } from "../theme";
import { BreathingTriangle } from "./BreathingTriangle";

interface Props {
  /** "zero" : tout est traité (inbox zero clean). "category" : pas d'email
   *  dans cette catégorie spécifique mais d'autres existent. "session" : la
   *  session vient de se terminer sans plus rien à traiter. */
  variant?: "zero" | "category" | "session";
}

/** 5 variantes random pour `variant=zero`. La randomness est mémorisée par
 *  mount (useMemo []) pour ne pas changer au moindre re-render. */
const ZERO_KEYS = [
  "emptyZero1",
  "emptyZero2",
  "emptyZero3",
  "emptyZero4",
  "emptyZero5",
] as const;

export function EmptyState({ variant = "zero" }: Props) {
  const { t } = useTranslation("inbox");

  // Pick stable per mount — re-render ne change pas la copy.
  const messageKey = useMemo(() => {
    if (variant !== "zero") return `empty_${variant}`;
    return ZERO_KEYS[Math.floor(Math.random() * ZERO_KEYS.length)];
  }, [variant]);

  return (
    <View style={styles.container} accessibilityRole="text" accessibilityLabel={t(messageKey)}>
      <BreathingTriangle size={140} mode="loading" />
      <Text style={styles.title}>{t(messageKey)}</Text>
      {variant === "zero" ? (
        <Text style={styles.sub}>{t("emptyZeroSub", { defaultValue: "" })}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 32,
    paddingHorizontal: 24,
    gap: 24,
  },
  title: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 22,
    color: theme.colors.textPrimary,
    textAlign: "center",
    letterSpacing: -0.3,
    lineHeight: 28,
  },
  sub: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    color: theme.colors.textMuted,
    textAlign: "center",
    letterSpacing: 0.2,
    marginTop: -12,
  },
});
