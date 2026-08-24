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
 * Modal de clonage de voix ElevenLabs (Instant Voice Cloning).
 *
 * Flux :
 *   1. L'utilisateur entre un nom
 *   2. Il enregistre au moins 10 s (recommandé 30 s+) via le micro
 *   3. Il peut ré-enregistrer autant de fois qu'il veut avant d'uploader
 *   4. Upload → POST /api/tts/clone → la voix apparaît dans la liste
 */

import { useEffect, useRef, useState } from "react";
import {
  Modal,
  View,
  Text,
  Pressable,
  TextInput,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";
import { useAudio } from "../hooks/useAudio";
import { theme } from "../theme";
import type { VoiceSettings } from "../hooks/useVoiceSettings";

const MIN_DURATION_S = 10;
const RECOMMENDED_S = 30;

interface Props {
  visible: boolean;
  onClose: () => void;
  voice: VoiceSettings;
}

export function VoiceCloneModal({ visible, onClose, voice }: Props) {
  const insets = useSafeAreaInsets();
  const audio = useAudio();
  const { t } = useTranslation(["voice", "common", "compose"]);
  const [name, setName] = useState("");
  const [duration, setDuration] = useState(0); // seconds
  const [sampleUri, setSampleUri] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (!visible) {
      // Reset à l'ouverture suivante
      setName("");
      setDuration(0);
      setSampleUri(null);
      setUploading(false);
      if (tickRef.current) {
        clearInterval(tickRef.current);
        tickRef.current = null;
      }
    }
  }, [visible]);

  const startRec = async () => {
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    setSampleUri(null);
    setDuration(0);
    await audio.startRecording();
    startedAtRef.current = Date.now();
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = setInterval(() => {
      if (startedAtRef.current) {
        setDuration(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 500);
  };

  const stopRec = async () => {
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    const uri = await audio.stopRecording();
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    startedAtRef.current = null;
    if (uri) setSampleUri(uri);
  };

  const canUpload =
    !!sampleUri && duration >= MIN_DURATION_S && name.trim().length > 0 && !uploading;

  const handleUpload = async () => {
    if (!sampleUri) return;
    setUploading(true);
    try {
      await voice.cloneVoice(name.trim(), [sampleUri]);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert(
        t("voice:clone.successTitle"),
        t("voice:clone.successMessage", { name: name.trim() }),
        [{ text: t("common:ok"), onPress: onClose }],
      );
    } catch (err: any) {
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      Alert.alert(
        t("voice:clone.failureTitle"),
        err?.message || t("voice:clone.failureUnknown"),
      );
    } finally {
      setUploading(false);
    }
  };

  const isRecording = audio.audioState === "recording";
  const progressPct = Math.min(100, (duration / RECOMMENDED_S) * 100);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={[styles.wrapper, { paddingTop: insets.top }]}>
        <View style={styles.header}>
          <Pressable
            onPress={onClose}
            style={styles.backBtn}
            accessibilityRole="button"
            accessibilityLabel={t("common:back")}
          >
            <Ionicons name="chevron-back" size={24} color={theme.colors.textPrimary} />
            <Text style={styles.backText}>{t("common:back")}</Text>
          </Pressable>
          <Text style={styles.headerTitle}>{t("voice:clone.title")}</Text>
          <View style={styles.headerSpacer} />
        </View>

        <View style={styles.content}>
          <Text style={styles.sectionLabel}>{t("voice:clone.nameLabel")}</Text>
          <TextInput
            style={styles.input}
            accessibilityLabel={t("voice:clone.nameLabel")}
            placeholder={t("compose:cloneNamePlaceholder")}
            placeholderTextColor={theme.colors.textMuted}
            value={name}
            onChangeText={setName}
            maxLength={40}
            editable={!uploading}
          />

          <Text style={[styles.sectionLabel, { marginTop: 24 }]}>{t("voice:clone.audioLabel")}</Text>
          <Text style={styles.helper}>
            {t("voice:clone.audioHelper", { min: MIN_DURATION_S, rec: RECOMMENDED_S })}
          </Text>

          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${progressPct}%` }]} />
          </View>

          <View style={styles.timerRow}>
            <Text style={styles.timer}>
              {String(Math.floor(duration / 60)).padStart(2, "0")}:
              {String(duration % 60).padStart(2, "0")}
            </Text>
            <Text style={styles.timerHint}>
              {duration < MIN_DURATION_S
                ? t("voice:clone.minDuration", { min: MIN_DURATION_S })
                : duration < RECOMMENDED_S
                  ? t("voice:clone.okDuration", { rec: RECOMMENDED_S })
                  : t("voice:clone.optimalQuality")}
            </Text>
          </View>

          <View style={styles.recRow}>
            {!isRecording ? (
              <Pressable
                style={[styles.recBtn, uploading && styles.disabled]}
                onPress={startRec}
                disabled={uploading}
                accessibilityRole="button"
                accessibilityLabel={sampleUri ? t("voice:clone.recordRedo") : t("voice:clone.recordStart")}
                accessibilityState={{ disabled: uploading }}
              >
                <Ionicons
                  name="mic"
                  size={28}
                  color={uploading ? theme.colors.textMuted : theme.colors.bg}
                />
                <Text style={styles.recBtnText}>
                  {sampleUri ? t("voice:clone.recordRedo") : t("voice:clone.recordStart")}
                </Text>
              </Pressable>
            ) : (
              <Pressable
                style={[styles.recBtn, styles.recBtnStop]}
                onPress={stopRec}
                accessibilityRole="button"
                accessibilityLabel={t("voice:clone.recordStop")}
              >
                <Ionicons name="stop" size={28} color={theme.colors.textPrimary} />
                <Text style={[styles.recBtnText, { color: theme.colors.textPrimary }]}>
                  {t("voice:clone.recordStop")}
                </Text>
              </Pressable>
            )}
          </View>

          {sampleUri && !isRecording && (
            <Text style={styles.okBadge}>
              <Ionicons name="checkmark-circle" size={14} color={theme.colors.green} />
              {"  "}{t("voice:clone.sampleReady", { duration })}
            </Text>
          )}

          <Pressable
            style={[styles.uploadBtn, !canUpload && styles.disabled]}
            onPress={handleUpload}
            disabled={!canUpload}
            accessibilityRole="button"
            accessibilityLabel={t("voice:clone.submit")}
            accessibilityState={{ disabled: !canUpload, busy: uploading }}
          >
            {uploading ? (
              <>
                <ActivityIndicator color={theme.colors.bg} />
                <Text style={styles.uploadText}>{t("voice:clone.submitting")}</Text>
              </>
            ) : (
              <>
                <Ionicons name="cloud-upload-outline" size={18} color={theme.colors.bg} />
                <Text style={styles.uploadText}>{t("voice:clone.submit")}</Text>
              </>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrapper: { flex: 1, backgroundColor: theme.colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  backBtn: { flexDirection: "row", alignItems: "center", gap: 2, width: 88 },
  backText: { fontSize: 16, fontFamily: theme.fonts.body, color: theme.colors.textPrimary },
  headerTitle: {
    flex: 1,
    fontSize: 14,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
    textAlign: "center",
    letterSpacing: 2,
  },
  headerSpacer: { width: 88 },
  content: { padding: 24, gap: 8 },
  sectionLabel: {
    fontSize: 10,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    letterSpacing: 2,
    marginBottom: 8,
  },
  input: {
    backgroundColor: theme.colors.surface,
    color: theme.colors.textPrimary,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 15,
    fontFamily: theme.fonts.body,
  },
  helper: {
    fontSize: 12,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    marginBottom: 12,
    lineHeight: 17,
  },
  progressTrack: {
    height: 6,
    backgroundColor: theme.colors.surfaceHigh,
    borderRadius: 3,
    overflow: "hidden",
    marginTop: 4,
  },
  progressFill: {
    height: "100%",
    backgroundColor: theme.colors.cyan,
  },
  timerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    marginTop: 6,
  },
  timer: {
    fontSize: 28,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
  },
  timerHint: {
    fontSize: 11,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    letterSpacing: 1,
  },
  recRow: { alignItems: "center", marginTop: 16 },
  recBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: theme.colors.cyan,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: theme.radius.md,
  },
  recBtnStop: {
    backgroundColor: theme.colors.red,
  },
  recBtnText: {
    fontSize: 14,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.bg,
  },
  okBadge: {
    fontSize: 12,
    fontFamily: theme.fonts.bodyMedium,
    color: theme.colors.green,
    textAlign: "center",
    marginTop: 12,
  },
  uploadBtn: {
    marginTop: 28,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.colors.cyan,
    paddingVertical: 14,
    borderRadius: theme.radius.md,
  },
  uploadText: {
    fontSize: 14,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.bg,
  },
  disabled: {
    opacity: 0.4,
  },
});
