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
 * Guide d'interaction — comment piloter Agentys (voix + toucher + bips).
 *
 * Créé quand les chips de mots d'action ont été retirés du DrivePlayer
 * (2026-07) : l'interaction est 100 % voix + gestes, ce guide est la
 * référence. Accessible depuis les réglages. Chaque bip est jouable au tap
 * (découverte active plutôt que description passive).
 */

import { useCallback, useRef } from "react";
import { View, Text, Pressable, StyleSheet, ScrollView } from "react-native";
import { Audio } from "expo-av";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";
import * as Haptics from "expo-haptics";
import { theme } from "../src/theme";
import { getEarconSource, type EarconName } from "../src/hooks/useEarcons";

const SPEAK_KEYS = [
  "reply", "replyAll", "forward", "next", "archive",
  "send", "cancel", "repeat", "stop",
] as const;
const TOUCH_KEYS = ["interrupt", "finish", "swipe", "logo", "undo"] as const;
const SOUND_KEYS: EarconName[] = ["turn", "tick", "done", "alert"];

export default function GuideScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { t } = useTranslation(["guide", "common"]);
  const previewRef = useRef<Audio.Sound | null>(null);

  // Joue le bip demandé (préversion) — un seul à la fois, best-effort.
  const playPreview = useCallback(async (name: EarconName) => {
    Haptics.selectionAsync().catch(() => {});
    try {
      await previewRef.current?.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
      const { sound } = await Audio.Sound.createAsync(getEarconSource(name), {
        shouldPlay: true,
        volume: 0.9,
      });
      previewRef.current = sound;
    } catch { /* asset indisponible — le tap reste silencieux */ }
  }, []);

  return (
    <View style={[styles.wrapper, { paddingTop: insets.top }]}>
      {/* Header avec retour (même pattern que settings) */}
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          style={styles.backBtn}
          accessibilityRole="button"
          accessibilityLabel={t("common:back")}
        >
          <Ionicons name="chevron-back" size={24} color={theme.colors.textPrimary} />
          <Text style={styles.backText}>{t("common:back")}</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{t("guide:title")}</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 32 }]}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.intro}>{t("guide:intro")}</Text>

        {/* ── Parler ── */}
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("guide:speakSection")}</Text>
        </View>
        <Text style={styles.sectionIntro}>{t("guide:speakIntro")}</Text>
        {SPEAK_KEYS.map((k) => (
          <View key={k} style={styles.row}>
            <Text style={styles.cmd}>{t(`guide:speak.${k}.cmd`)}</Text>
            <Text style={styles.desc}>{t(`guide:speak.${k}.desc`)}</Text>
          </View>
        ))}

        {/* ── Toucher ── */}
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("guide:touchSection")}</Text>
        </View>
        {TOUCH_KEYS.map((k) => (
          <View key={k} style={styles.row}>
            <Text style={styles.cmd}>{t(`guide:touch.${k}.gesture`)}</Text>
            <Text style={styles.desc}>{t(`guide:touch.${k}.desc`)}</Text>
          </View>
        ))}

        {/* ── Les bips (tap = écouter) ── */}
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("guide:soundsSection")}</Text>
        </View>
        <Text style={styles.sectionIntro}>{t("guide:soundsIntro")}</Text>
        {SOUND_KEYS.map((k) => (
          <Pressable
            key={k}
            style={({ pressed }) => [styles.soundRow, pressed && styles.soundRowPressed]}
            onPress={() => playPreview(k)}
            accessibilityRole="button"
            accessibilityLabel={t(`guide:sounds.${k}.name`)}
            accessibilityHint={t(`guide:sounds.${k}.desc`)}
          >
            <Ionicons name="volume-medium-outline" size={18} color={theme.colors.cyan} />
            <View style={styles.soundTextWrap}>
              <Text style={styles.cmd}>{t(`guide:sounds.${k}.name`)}</Text>
              <Text style={styles.desc}>{t(`guide:sounds.${k}.desc`)}</Text>
            </View>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  backBtn: {
    flexDirection: "row",
    alignItems: "center",
    padding: 4,
  },
  backText: {
    fontFamily: theme.fonts.body,
    fontSize: 15,
    color: theme.colors.textPrimary,
  },
  headerTitle: {
    flex: 1,
    textAlign: "center",
    fontFamily: theme.fonts.bodySemi,
    fontSize: 17,
    color: theme.colors.textPrimary,
  },
  headerSpacer: {
    width: 80,
  },
  scroll: {
    flex: 1,
  },
  content: {
    paddingHorizontal: 20,
  },
  intro: {
    fontFamily: theme.fonts.body,
    fontSize: 14,
    lineHeight: 21,
    color: theme.colors.textSecondary,
    marginTop: 8,
    marginBottom: 8,
  },
  sectionTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 28,
    marginBottom: 10,
  },
  sectionTitleBar: {
    width: 3,
    height: 14,
    borderRadius: 2,
    backgroundColor: theme.colors.cyan,
  },
  sectionTitle: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 13,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: theme.colors.textPrimary,
  },
  sectionIntro: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    color: theme.colors.textMuted,
    marginBottom: 10,
  },
  row: {
    marginBottom: 12,
  },
  cmd: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 15,
    color: theme.colors.cyan,
    marginBottom: 2,
  },
  desc: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    lineHeight: 19,
    color: theme.colors.textSecondary,
  },
  soundRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginBottom: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: `${theme.colors.cyan}22`,
    backgroundColor: `${theme.colors.cyan}08`,
  },
  soundRowPressed: {
    backgroundColor: `${theme.colors.cyan}18`,
  },
  soundTextWrap: {
    flex: 1,
  },
});
