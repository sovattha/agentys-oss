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
 * Écran Diagnostic — Réglages → Aide → Diagnostic.
 *
 * Phase 1 fondations (tech-spec-mobile-foundations-refactor §1.3) : expose le
 * ring buffer d'événements (eventLog) — transitions, erreurs, STT, audio —
 * avec export en 2 taps (share sheet). Remplace les cycles
 * « rebuild-instrumenter-reproduire » : l'utilisateur partage un dump, le
 * diagnostic se fait en le lisant.
 */

import { useCallback, useState } from "react";
import { View, Text, Pressable, StyleSheet, ScrollView, Share } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";
import * as Haptics from "expo-haptics";
import { theme } from "../src/theme";
import { getRecentEvents, dumpEvents, clearEvents, type LoggedEvent } from "../src/lib/eventLog";
import { reportError } from "../src/lib/errors";
import * as AgentysAudio from "../modules/agentys-audio";

const KIND_COLORS: Record<string, string> = {
  error: theme.colors.red,
  watchdog: theme.colors.amber,
  transition: theme.colors.cyan,
  stt: theme.colors.primaryLight,
  audio: theme.colors.textSecondary,
  api: theme.colors.textMuted,
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export default function DiagnosticScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { t } = useTranslation(["settings", "common"]);
  const [events, setEvents] = useState<LoggedEvent[]>(() => getRecentEvents(50).reverse());

  const refresh = useCallback(() => {
    setEvents(getRecentEvents(50).reverse());
  }, []);

  const handleShare = useCallback(async () => {
    Haptics.selectionAsync().catch(() => {});
    try {
      const header = [
        `Agentys — diagnostic ${new Date().toISOString()}`,
        `audioSession: ${AgentysAudio.audioSessionSnapshot() || "n/a"}`,
        "---",
      ].join("\n");
      await Share.share({ message: `${header}\n${dumpEvents()}` });
    } catch (e) {
      reportError(e, { domain: "unknown", op: "diagnosticShare" });
    }
  }, []);

  const handleClear = useCallback(() => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    clearEvents();
    refresh();
  }, [refresh]);

  return (
    <View style={[styles.wrapper, { paddingTop: insets.top }]}>
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
        <Text style={styles.headerTitle}>{t("settings:diagnosticRow")}</Text>
        <View style={styles.headerSpacer} />
      </View>

      {/* Actions */}
      <View style={styles.actions}>
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && styles.actionBtnPressed]}
          onPress={handleShare}
          accessibilityRole="button"
          accessibilityLabel={t("settings:diagnosticShare")}
        >
          <Ionicons name="share-outline" size={18} color={theme.colors.cyan} />
          <Text style={styles.actionText}>{t("settings:diagnosticShare")}</Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && styles.actionBtnPressed]}
          onPress={refresh}
          accessibilityRole="button"
          accessibilityLabel={t("settings:diagnosticRefresh")}
        >
          <Ionicons name="refresh-outline" size={18} color={theme.colors.cyan} />
          <Text style={styles.actionText}>{t("settings:diagnosticRefresh")}</Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && styles.actionBtnPressed]}
          onPress={handleClear}
          accessibilityRole="button"
          accessibilityLabel={t("settings:diagnosticClear")}
        >
          <Ionicons name="trash-outline" size={18} color={theme.colors.textMuted} />
          <Text style={[styles.actionText, { color: theme.colors.textMuted }]}>
            {t("settings:diagnosticClear")}
          </Text>
        </Pressable>
      </View>

      {/* Événements (50 derniers, plus récent en haut) */}
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 24 }]}
        showsVerticalScrollIndicator={false}
      >
        {events.length === 0 ? (
          <Text style={styles.empty}>{t("settings:diagnosticEmpty")}</Text>
        ) : (
          events.map((e, i) => (
            <View key={`${e.ts}-${i}`} style={styles.row}>
              <View style={styles.rowHead}>
                <Text style={[styles.kind, { color: KIND_COLORS[e.kind] ?? theme.colors.textMuted }]}>
                  {e.kind.toUpperCase()}
                </Text>
                <Text style={styles.time}>{formatTime(e.ts)}</Text>
              </View>
              <Text style={styles.data} numberOfLines={3}>
                {JSON.stringify(e.data)}
              </Text>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { flex: 1, backgroundColor: theme.colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  backBtn: { flexDirection: "row", alignItems: "center", padding: 4 },
  backText: { fontFamily: theme.fonts.body, fontSize: 15, color: theme.colors.textPrimary },
  headerTitle: {
    flex: 1,
    textAlign: "center",
    fontFamily: theme.fonts.bodySemi,
    fontSize: 17,
    color: theme.colors.textPrimary,
  },
  headerSpacer: { width: 80 },
  actions: {
    flexDirection: "row",
    gap: 10,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: `${theme.colors.cyan}30`,
    backgroundColor: `${theme.colors.cyan}08`,
  },
  actionBtnPressed: { backgroundColor: `${theme.colors.cyan}18` },
  actionText: { fontFamily: theme.fonts.bodyMedium, fontSize: 12, color: theme.colors.cyan },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 20 },
  empty: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    color: theme.colors.textMuted,
    textAlign: "center",
    marginTop: 40,
  },
  row: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.06)",
  },
  rowHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: 2 },
  kind: { fontFamily: theme.fonts.bodySemi, fontSize: 11, letterSpacing: 1 },
  time: { fontFamily: theme.fonts.body, fontSize: 11, color: theme.colors.textDim },
  data: { fontFamily: theme.fonts.body, fontSize: 12, color: theme.colors.textSecondary, lineHeight: 17 },
});
