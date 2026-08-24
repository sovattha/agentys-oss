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
 * OnboardingTour — 3 cards swipables au premier launch.
 *
 * Audit UX 2026-04-28 : sans onboarding, un user fraîchement loggé ne sait
 * pas que (a) Drive lit + rédige, (b) il peut parler, (c) les gestes
 * existent. Le concept voice-first n'est PAS auto-évident.
 *
 * Affiché 1× après login. Persisté via SecureStore (`onboarding_seen_v1`).
 * Skip-able en haut-droite. Triangle change de teinte par card pour
 * démontrer la palette state-reactive (#10 dans l'audit UX).
 */

import { useRef, useState } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Animated,
  Dimensions,
  ScrollView,
  NativeSyntheticEvent,
  NativeScrollEvent,
} from "react-native";
import * as Haptics from "expo-haptics";
import * as SecureStore from "expo-secure-store";
import { useTranslation } from "react-i18next";
import { theme } from "../theme";
import { BreathingTriangle } from "./BreathingTriangle";

const { width: WIN_W } = Dimensions.get("window");

export const ONBOARDING_KEY = "onboarding_seen_v1";

interface Props {
  onDone: () => void;
}

interface Card {
  titleKey: string;
  bodyKey: string;
  /** Couleur d'accent du triangle (state-reactive teaser). */
  accentColor: string;
}

const CARDS: Card[] = [
  {
    titleKey: "onboarding.card1Title",
    bodyKey: "onboarding.card1Body",
    accentColor: "#3DE3C7", // teal — drive idle
  },
  {
    titleKey: "onboarding.card2Title",
    bodyKey: "onboarding.card2Body",
    accentColor: "#E879F9", // magenta — listening
  },
  {
    titleKey: "onboarding.card3Title",
    bodyKey: "onboarding.card3Body",
    accentColor: "#FBBF24", // amber — generating
  },
];

export function OnboardingTour({ onDone }: Props) {
  const { t } = useTranslation("inbox");
  const [page, setPage] = useState(0);
  const scrollRef = useRef<ScrollView>(null);

  const finish = () => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    SecureStore.setItemAsync(ONBOARDING_KEY, "true").catch(() => {}); // no-op légitime : cache best-effort
    onDone();
  };

  const goNext = () => {
    if (page < CARDS.length - 1) {
      const nextIdx = page + 1;
      Haptics.selectionAsync().catch(() => {});
      scrollRef.current?.scrollTo({ x: nextIdx * WIN_W, animated: true });
      setPage(nextIdx);
    } else {
      finish();
    }
  };

  const handleScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const idx = Math.round(e.nativeEvent.contentOffset.x / WIN_W);
    if (idx !== page) setPage(idx);
  };

  return (
    <View style={styles.container}>
      {/* Skip top-right */}
      <Pressable
        onPress={() => {
          Haptics.selectionAsync().catch(() => {});
          finish();
        }}
        style={styles.skip}
        hitSlop={12}
        accessibilityRole="button"
        accessibilityLabel={t("onboarding.skip", { defaultValue: "Passer l'introduction" })}
      >
        <Text style={styles.skipText}>{t("onboarding.skip", { defaultValue: "Passer" })}</Text>
      </Pressable>

      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={handleScroll}
        style={styles.scroll}
      >
        {CARDS.map((card, idx) => (
          <View key={idx} style={[styles.card, { width: WIN_W }]}>
            <View style={styles.triangleSlot}>
              <BreathingTriangle size={180} accentColor={card.accentColor} />
            </View>
            <View style={styles.textBlock}>
              <Text style={styles.title}>{t(card.titleKey)}</Text>
              <Text style={styles.body}>{t(card.bodyKey)}</Text>
            </View>
          </View>
        ))}
      </ScrollView>

      {/* Pagination dots */}
      <View style={styles.dots}>
        {CARDS.map((_, idx) => (
          <View
            key={idx}
            style={[styles.dot, idx === page && styles.dotActive]}
          />
        ))}
      </View>

      {/* CTA */}
      <Pressable
        style={({ pressed }) => [styles.cta, pressed && styles.ctaPressed]}
        onPress={goNext}
        accessibilityRole="button"
        accessibilityLabel={
          page < CARDS.length - 1
            ? t("onboarding.next", { defaultValue: "Suivant" })
            : t("onboarding.start", { defaultValue: "Commencer" })
        }
      >
        <Text style={styles.ctaText}>
          {page < CARDS.length - 1
            ? t("onboarding.next", { defaultValue: "Suivant" })
            : t("onboarding.start", { defaultValue: "Commencer" })}
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  skip: {
    position: "absolute",
    top: 60,
    right: 20,
    paddingHorizontal: 12,
    paddingVertical: 8,
    zIndex: 10,
  },
  skipText: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    color: theme.colors.textMuted,
    letterSpacing: 0.5,
  },
  scroll: {
    flex: 1,
  },
  card: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    paddingTop: 60,
    paddingBottom: 120,
  },
  triangleSlot: {
    width: 200,
    height: 200,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 48,
  },
  textBlock: {
    alignItems: "center",
    gap: 16,
    maxWidth: 320,
  },
  title: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 28,
    color: theme.colors.textPrimary,
    textAlign: "center",
    letterSpacing: -0.5,
    lineHeight: 32,
  },
  body: {
    fontFamily: theme.fonts.body,
    fontSize: 15,
    color: theme.colors.textSecondary,
    textAlign: "center",
    letterSpacing: 0.1,
    lineHeight: 22,
  },
  dots: {
    position: "absolute",
    bottom: 130,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "center",
    gap: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: `${theme.colors.textMuted}50`,
  },
  dotActive: {
    backgroundColor: theme.colors.cyan,
    width: 18,
  },
  cta: {
    position: "absolute",
    bottom: 56,
    left: 32,
    right: 32,
    paddingVertical: 18,
    borderRadius: 28,
    borderWidth: 1.5,
    borderColor: theme.colors.cyan,
    alignItems: "center",
    backgroundColor: `${theme.colors.cyan}10`,
  },
  ctaPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  ctaText: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 16,
    color: theme.colors.cyan,
    letterSpacing: 0.5,
  },
});
