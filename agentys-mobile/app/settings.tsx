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

﻿/**
 * Écran Réglages standalone — accessible depuis le Drive Screen via le bouton ⚙.
 */

import { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Alert,
  ScrollView,
  Switch,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";
import { useAuth } from "../src/hooks/useAuth";
import { useVoiceSettings } from "../src/hooks/useVoiceSettings";
import { useLanguage } from "../src/hooks/useLanguageSync";
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from "../src/i18n";
import { VoicePicker } from "../src/components/VoicePicker";
import { VoiceCloneModal } from "../src/components/VoiceCloneModal";
import { theme } from "../src/theme";
import { API_URL } from "../src/config";
import { Audio } from "expo-av";
import {
  EARCON_STYLES,
  getEarconSource,
  getEarconStyle,
  setEarconStyle,
  loadEarconStyle,
  type EarconStyle,
} from "../src/hooks/useEarcons";

const ACCENT_OPTIONS: Record<SupportedLanguage, Array<{ code: string; tKey: string }>> = {
  fr: [
    { code: "fr-FR", tKey: "settings:accent_fr-FR" },
    { code: "fr-CA", tKey: "settings:accent_fr-CA" },
  ],
  en: [
    { code: "en-US", tKey: "settings:accent_en-US" },
    { code: "en-GB", tKey: "settings:accent_en-GB" },
    { code: "en-AU", tKey: "settings:accent_en-AU" },
  ],
};

const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: "English",
  fr: "Français",
};

export default function SettingsScreen() {
  const { logout } = useAuth();
  const router = useRouter();
  const voice = useVoiceSettings();
  const insets = useSafeAreaInsets();
  const { t } = useTranslation(["settings", "auth", "common"]);
  const { language, setLanguage } = useLanguage();
  const [showVoiceList, setShowVoiceList] = useState(false);
  const [showCloneModal, setShowCloneModal] = useState(false);
  const [showLangList, setShowLangList] = useState(false);
  const [showAccentList, setShowAccentList] = useState(false);

  const selectedVoiceName = voice.selectedVoice
    ? voice.availableVoices.find((v) => v.voice_id === voice.selectedVoice)?.name
      || voice.selectedVoice
    : t("settings:voiceNone");

  const handleLogout = async () => {
    Alert.alert(t("auth:logoutTitle"), t("auth:logoutMessage"), [
      { text: t("common:cancel"), style: "cancel" },
      {
        text: t("auth:logoutConfirm"),
        style: "destructive",
        onPress: async () => {
          await logout();
          router.replace("/login");
        },
      },
    ]);
  };

  const handleLanguagePick = async (lang: SupportedLanguage) => {
    await Haptics.selectionAsync();
    await setLanguage(lang);
    setShowLangList(false);
  };

  const RATE_STEPS = [0.5, 0.75, 1.0, 1.25, 1.5];
  const DELAY_STEPS = [1, 2, 3, 5];

  // ── Bips (earcons) : style persisté + préversion au tap ──────────────────
  const [earconStyle, setEarconStyleState] = useState<EarconStyle>(getEarconStyle());
  const earconPreviewRef = useRef<Audio.Sound | null>(null);
  useEffect(() => {
    loadEarconStyle().then(setEarconStyleState).catch(() => {}); // no-op légitime : style par défaut si pref illisible
    return () => {
      earconPreviewRef.current?.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
    };
  }, []);
  const handleEarconPick = async (style: EarconStyle) => {
    await Haptics.selectionAsync();
    setEarconStyle(style);           // module-level : effet immédiat en drive
    setEarconStyleState(style);
    // Préversion : joue le « à toi » de la famille choisie.
    try {
      await earconPreviewRef.current?.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
      const { sound } = await Audio.Sound.createAsync(getEarconSource("turn", style), {
        shouldPlay: true,
        volume: 0.9,
      });
      earconPreviewRef.current = sound;
    } catch { /* préversion best-effort */ }
  };

  return (
    <View style={[styles.wrapper, { paddingTop: insets.top }]}>
      {/* Header avec retour */}
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
        <Text style={styles.headerTitle}>{t("settings:title")}</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 32 }]}
      >
        {/* ── Section Langue ── */}
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:languageSection")}</Text>
        </View>

        <Pressable
          style={styles.row}
          onPress={() => setShowLangList((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel={t("settings:language")}
          accessibilityValue={{ text: LANGUAGE_LABELS[language] }}
          accessibilityState={{ expanded: showLangList }}
        >
          <Text style={styles.rowLabel}>{t("settings:language")}</Text>
          <View style={styles.rowRight}>
            <Text style={styles.rowValue} numberOfLines={1}>{LANGUAGE_LABELS[language]}</Text>
            <Ionicons
              name={showLangList ? "chevron-down" : "chevron-forward"}
              size={16}
              color={theme.colors.textMuted}
            />
          </View>
        </Pressable>

        {showLangList && (
          <View style={{ marginTop: 8, gap: 6 }}>
            {SUPPORTED_LANGUAGES.map((lang) => {
              const active = language === lang;
              return (
                <Pressable
                  key={lang}
                  style={[styles.voiceItem, active && styles.voiceItemSelected]}
                  onPress={() => handleLanguagePick(lang)}
                  accessibilityRole="button"
                  accessibilityLabel={LANGUAGE_LABELS[lang]}
                  accessibilityState={{ selected: active }}
                >
                  <Text
                    style={[
                      styles.voiceItemText,
                      active && styles.voiceItemTextSelected,
                    ]}
                  >
                    {LANGUAGE_LABELS[lang]}
                  </Text>
                  {active && (
                    <Ionicons
                      name="checkmark"
                      size={18}
                      color={theme.colors.primary}
                    />
                  )}
                </Pressable>
              );
            })}
            <Text style={styles.rowSub}>{t("settings:languageHint")}</Text>
          </View>
        )}

        {/* ── Section Accent ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:accentSection")}</Text>
        </View>

        <Pressable
          style={styles.row}
          onPress={() => setShowAccentList((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel={t("settings:accentSection")}
          accessibilityValue={{ text: voice.ttsAccent ? t(`settings:accent_${voice.ttsAccent}`) : "–" }}
          accessibilityState={{ expanded: showAccentList }}
        >
          <Text style={styles.rowLabel}>{t("settings:accentSection")}</Text>
          <View style={styles.rowRight}>
            <Text style={styles.rowValue} numberOfLines={1}>
              {voice.ttsAccent ? t(`settings:accent_${voice.ttsAccent}`) : "–"}
            </Text>
            <Ionicons
              name={showAccentList ? "chevron-down" : "chevron-forward"}
              size={16}
              color={theme.colors.textMuted}
            />
          </View>
        </Pressable>

        {showAccentList && (
          <View style={{ marginTop: 8, gap: 6 }}>
            {(ACCENT_OPTIONS[language] ?? []).map(({ code, tKey }) => {
              const active = voice.ttsAccent === code;
              return (
                <Pressable
                  key={code}
                  style={[styles.voiceItem, active && styles.voiceItemSelected]}
                  onPress={async () => {
                    await Haptics.selectionAsync();
                    await voice.setTtsAccent(active ? undefined : code);
                    setShowAccentList(false);
                  }}
                  accessibilityRole="button"
                  accessibilityLabel={t(tKey)}
                  accessibilityState={{ selected: active }}
                >
                  <Text style={[styles.voiceItemText, active && styles.voiceItemTextSelected]}>
                    {t(tKey)}
                  </Text>
                  {active && <Ionicons name="checkmark" size={18} color={theme.colors.primary} />}
                </Pressable>
              );
            })}
            <Text style={styles.rowSub}>{t("settings:accentHint")}</Text>
          </View>
        )}

        {/* ── Section Voix ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:voiceSection")}</Text>
        </View>

        <Pressable
          style={styles.row}
          onPress={() => setShowVoiceList((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel={t("settings:voiceSelected")}
          accessibilityValue={{ text: selectedVoiceName }}
          accessibilityState={{ expanded: showVoiceList }}
        >
          <Text style={styles.rowLabel}>{t("settings:voiceSelected")}</Text>
          <View style={styles.rowRight}>
            <Text style={styles.rowValue} numberOfLines={1}>{selectedVoiceName}</Text>
            <Ionicons
              name={showVoiceList ? "chevron-down" : "chevron-forward"}
              size={16}
              color={theme.colors.textMuted}
            />
          </View>
        </Pressable>

        {showVoiceList && (
          <View style={{ marginTop: 8 }}>
            <VoicePicker voice={voice} onOpenClone={() => setShowCloneModal(true)} />
          </View>
        )}

        <VoiceCloneModal
          visible={showCloneModal}
          onClose={() => setShowCloneModal(false)}
          voice={voice}
        />

        {/* ── Vitesse ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:speedSection")}</Text>
        </View>
        <View style={styles.segmentRow}>
          {RATE_STEPS.map((r) => (
            <Pressable
              key={r}
              style={[styles.segment, Math.abs(voice.speechRate - r) < 0.01 && styles.segmentActive]}
              onPress={async () => {
                await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                voice.setSpeechRate(r);
              }}
              accessibilityRole="button"
              accessibilityLabel={`${r}×`}
              accessibilityState={{ selected: Math.abs(voice.speechRate - r) < 0.01 }}
            >
              <Text style={[styles.segmentText, Math.abs(voice.speechRate - r) < 0.01 && styles.segmentTextActive]}>
                {r}×
              </Text>
            </Pressable>
          ))}
        </View>

        {/* ── Auto-avancement ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:autoAdvanceSection")}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.rowLabel}>{t("settings:autoAdvance")}</Text>
          <Switch
            value={voice.autoAdvance}
            onValueChange={voice.setAutoAdvance}
            accessibilityLabel={t("settings:autoAdvance")}
            trackColor={{ true: theme.colors.primary }}
            thumbColor={theme.colors.textPrimary}
          />
        </View>

        {voice.autoAdvance && (
          <>
            <Text style={styles.rowSub}>{t("settings:autoAdvanceDelay")}</Text>
            <View style={styles.segmentRow}>
              {DELAY_STEPS.map((d) => (
                <Pressable
                  key={d}
                  style={[styles.segment, voice.autoAdvanceDelay === d && styles.segmentActive]}
                  onPress={async () => {
                    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                    voice.setAutoAdvanceDelay(d);
                  }}
                  accessibilityRole="button"
                  accessibilityLabel={`${d}s`}
                  accessibilityState={{ selected: voice.autoAdvanceDelay === d }}
                >
                  <Text style={[styles.segmentText, voice.autoAdvanceDelay === d && styles.segmentTextActive]}>
                    {d}s
                  </Text>
                </Pressable>
              ))}
            </View>
          </>
        )}

        {/* ── Bips (earcons) ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:earconSection")}</Text>
        </View>
        <Text style={styles.rowSub}>{t("settings:earconHint")}</Text>
        <View style={styles.segmentRow}>
          {EARCON_STYLES.map((s) => (
            <Pressable
              key={s}
              style={[styles.segment, earconStyle === s && styles.segmentActive]}
              onPress={() => handleEarconPick(s)}
              accessibilityRole="button"
              accessibilityLabel={t(`settings:earconStyle.${s}`)}
              accessibilityState={{ selected: earconStyle === s }}
            >
              <Text style={[styles.segmentText, earconStyle === s && styles.segmentTextActive]}>
                {t(`settings:earconStyle.${s}`)}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* ── Aide ── */}
        <View style={[styles.sectionTitleRow, { marginTop: 28 }]}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:helpSection")}</Text>
        </View>
        <Pressable
          style={styles.row}
          onPress={async () => {
            await Haptics.selectionAsync();
            router.push("/guide");
          }}
          accessibilityRole="button"
          accessibilityLabel={t("settings:guideRow")}
        >
          <Text style={styles.rowLabel}>{t("settings:guideRow")}</Text>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} />
        </Pressable>
        <Pressable
          style={styles.row}
          onPress={async () => {
            await Haptics.selectionAsync();
            router.push("/diagnostic");
          }}
          accessibilityRole="button"
          accessibilityLabel={t("settings:diagnosticRow")}
        >
          <Text style={styles.rowLabel}>{t("settings:diagnosticRow")}</Text>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.textMuted} />
        </Pressable>

        {/* ── Compte ── */}
        <View style={styles.divider} />
        <View style={styles.sectionTitleRow}>
          <View style={styles.sectionTitleBar} />
          <Text style={styles.sectionTitle}>{t("settings:accountSection")}</Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.rowLabel}>{t("settings:apiServer")}</Text>
          <View style={styles.rowRight}>
            <Text style={styles.rowValue} numberOfLines={1}>{API_URL}</Text>
          </View>
        </View>
        <Pressable
          style={styles.logoutButton}
          onPress={handleLogout}
          accessibilityRole="button"
          accessibilityLabel={t("auth:logoutButton")}
        >
          <Text style={styles.logoutText}>{t("auth:logoutButton")}</Text>
        </Pressable>

        <View style={styles.divider} />
        <Text style={styles.version}>{t("settings:version")}</Text>
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
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  backBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    width: 88,
  },
  backText: {
    fontSize: 16,
    fontFamily: theme.fonts.body,
    color: theme.colors.textPrimary,
  },
  headerTitle: {
    flex: 1,
    fontSize: 14,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
    textAlign: "center",
    letterSpacing: 2,
  },
  headerSpacer: {
    width: 88,
  },
  scroll: {
    flex: 1,
  },
  content: {
    padding: 24,
  },
  sectionTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 12,
  },
  sectionTitleBar: {
    width: 2,
    height: 14,
    backgroundColor: theme.colors.primary,
    borderRadius: 1,
  },
  sectionTitle: {
    fontSize: 10,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    letterSpacing: 2,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginBottom: 8,
    minHeight: 52,
  },
  rowRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    flex: 1,
    justifyContent: "flex-end",
  },
  rowLabel: {
    fontSize: 15,
    fontFamily: theme.fonts.body,
    color: theme.colors.textPrimary,
    flex: 1,
  },
  rowValue: {
    fontSize: 13,
    fontFamily: theme.fonts.body,
    color: theme.colors.textSecondary,
    maxWidth: 160,
    textAlign: "right",
  },
  rowSub: {
    fontSize: 13,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    marginBottom: 8,
    marginTop: 4,
  },
  voiceItem: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: theme.radius.md,
    marginBottom: 4,
    backgroundColor: theme.colors.surface,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  voiceItemSelected: {
    borderColor: theme.colors.primary,
    backgroundColor: `${theme.colors.primary}18`,
  },
  voiceItemText: {
    fontSize: 14,
    fontFamily: theme.fonts.body,
    color: theme.colors.textSecondary,
    flex: 1,
  },
  voiceItemTextSelected: {
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.primary,
  },
  previewBtn: {
    padding: 8,
  },
  voiceItemLang: {
    fontSize: 11,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    marginTop: 2,
  },
  segmentRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 8,
  },
  segment: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
    alignItems: "center",
  },
  segmentActive: {
    borderColor: theme.colors.primary,
    backgroundColor: `${theme.colors.primary}18`,
  },
  segmentText: {
    fontSize: 13,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
  },
  segmentTextActive: {
    color: theme.colors.primary,
    fontFamily: theme.fonts.bodyBold,
  },
  divider: {
    height: 1,
    backgroundColor: theme.colors.border,
    marginVertical: 24,
  },
  logoutButton: {
    borderRadius: theme.radius.md,
    padding: 14,
    alignItems: "center",
    borderWidth: 1,
    borderColor: `${theme.colors.red}40`,
  },
  logoutText: {
    color: theme.colors.red,
    fontSize: 13,
    fontFamily: theme.fonts.body,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  version: {
    fontSize: 11,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    textAlign: "center",
    letterSpacing: 0.5,
  },
});
