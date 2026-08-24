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
 * Écran de connexion Agentys — V14 « Breathing triangle ».
 *
 *   - Fond noir profond `#0A0B0E` + halo radial teal→violet→magenta en haut
 *   - Zone héro centrée : BreathingTriangle 200×200 (rubans audio-réactifs)
 *     + wordmark « Agentys » + tagline « Vos emails en mains-libres »
 *   - Bas : deux boutons connecteurs Gmail / Outlook côte à côte
 *
 * L'animation est pilotée par le mic via `useMicLevel`. En l'absence de
 * permission, BreathingTriangle bascule sur l'enveloppe simulée "ai" de
 * ribbons-engine (animation temporelle pure, 5 s).
 */

import { useState } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";
import Svg, {
  Defs,
  Path,
  RadialGradient,
  Rect,
  Stop,
} from "react-native-svg";
import { startOAuth, type OAuthProvider } from "../src/services/auth";
import { theme } from "../src/theme";
import { BreathingTriangle } from "../src/components/BreathingTriangle";
import { useMicLevel } from "../src/hooks/useMicLevel";

const TRIANGLE_SIZE = 200;

function GmailEnvelope() {
  return (
    <Svg width={44} height={33} viewBox="0 0 36 27">
      <Path d="M3 3l15 11L33 3v20a2 2 0 01-2 2H5a2 2 0 01-2-2V3z" fill="#fff" />
      <Path d="M3 3l15 11L33 3H3z" fill="#EA4335" />
      <Path d="M3 3l15 11v13H5a2 2 0 01-2-2V3z" fill="#4285F4" />
      <Path d="M33 3L18 14v13h13a2 2 0 002-2V3z" fill="#34A853" />
      <Path d="M18 14l15-11h-3v11l-12 9-12-9V3H3l15 11z" fill="#FBBC04" />
    </Svg>
  );
}

function OutlookSquares() {
  return (
    <Svg width={38} height={38} viewBox="0 0 32 32">
      <Rect x={1}  y={1}  width={14} height={14} fill="#F25022" />
      <Rect x={17} y={1}  width={14} height={14} fill="#7FBA00" />
      <Rect x={1}  y={17} width={14} height={14} fill="#00A4EF" />
      <Rect x={17} y={17} width={14} height={14} fill="#FFB900" />
    </Svg>
  );
}

type ConnectorKind = "gmail" | "outlook";

function ConnectorButton({
  kind,
  loading,
  disabled,
  onPress,
}: {
  kind: ConnectorKind;
  loading: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  const { t } = useTranslation("auth");
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={
        kind === "gmail"
          ? t("signInWithGmail")
          : t("signInWithOutlook")
      }
      accessibilityState={{ disabled, busy: loading }}
      style={({ pressed }) => [
        styles.connector,
        pressed && styles.connectorPressed,
      ]}
    >
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        <Svg width="100%" height="100%">
          <Defs>
            <RadialGradient
              id={`${kind}-halo`}
              cx="50%"
              cy="28%"
              r="70%"
            >
              <Stop
                offset="0%"
                stopColor={kind === "gmail" ? "#EA4335" : "#0A84FF"}
                stopOpacity={0.22}
              />
              <Stop
                offset="55%"
                stopColor={kind === "gmail" ? "#EA4335" : "#0A84FF"}
                stopOpacity={0.05}
              />
              <Stop offset="100%" stopColor="#0A0B0E" stopOpacity={0} />
            </RadialGradient>
          </Defs>
          <Rect
            x="0"
            y="0"
            width="100%"
            height="100%"
            fill={`url(#${kind}-halo)`}
          />
        </Svg>
      </View>
      <View style={styles.connectorLogoDisc}>
        {loading ? (
          <ActivityIndicator
            size="small"
            color={kind === "gmail" ? "#EA4335" : "#0A84FF"}
          />
        ) : kind === "gmail" ? (
          <GmailEnvelope />
        ) : (
          <OutlookSquares />
        )}
      </View>
      <Text style={styles.connectorLabel}>
        {kind === "gmail" ? "Gmail" : "Outlook"}
      </Text>
    </Pressable>
  );
}

export default function LoginScreen() {
  const [loadingProvider, setLoadingProvider] =
    useState<OAuthProvider | null>(null);
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const micLevel = useMicLevel();
  const { t } = useTranslation(["auth", "common"]);
  const loading = loadingProvider !== null;

  const handleOAuth = async (provider: OAuthProvider) => {
    setLoadingProvider(provider);
    try {
      const result = await startOAuth(provider);
      if (result.success) {
        router.replace("/");
      }
    } catch (err: any) {
      Alert.alert(
        t("common:error"),
        err.message || t("auth:connectError"),
      );
    } finally {
      setLoadingProvider(null);
    }
  };

  return (
    <View style={styles.container}>
      {/* ── Halo radial en haut ─────────────────────────────────────────── */}
      <View style={StyleSheet.absoluteFill} pointerEvents="none">
        <Svg width="100%" height="100%">
          <Defs>
            <RadialGradient id="bg-halo" cx="50%" cy="10%" r="70%">
              <Stop offset="0%"   stopColor="#3BC7B8" stopOpacity={0.08} />
              <Stop offset="40%"  stopColor="#8B5CF6" stopOpacity={0.05} />
              <Stop offset="100%" stopColor="#0A0B0E" stopOpacity={0} />
            </RadialGradient>
          </Defs>
          <Rect x="0" y="0" width="100%" height="100%" fill="url(#bg-halo)" />
        </Svg>
      </View>

      <KeyboardAvoidingView
        style={styles.kav}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <View
          style={[
            styles.content,
            {
              paddingTop: insets.top + 20,
              paddingBottom: insets.bottom + 180,
            },
          ]}
        >
          {/* ── Hero : triangle + titre + tagline ───────────────────────── */}
          <View style={styles.hero}>
            <View style={styles.triangleWrap}>
              <BreathingTriangle
                size={TRIANGLE_SIZE}
                externalLevel={micLevel ?? undefined}
              />
            </View>
            <View style={styles.titleBlock}>
              <Text style={styles.title}>Agentys</Text>
              <Text style={styles.tagline}>{t("auth:tagline")}</Text>
            </View>
          </View>

          {/* ── Bas : connecteurs OAuth ─────────────────────────────────── */}
          <View style={styles.connectorRow}>
            <ConnectorButton
              kind="gmail"
              loading={loadingProvider === "gmail"}
              disabled={loading}
              onPress={() => handleOAuth("gmail")}
            />
            <ConnectorButton
              kind="outlook"
              loading={loadingProvider === "outlook"}
              disabled={loading}
              onPress={() => handleOAuth("outlook")}
            />
          </View>
        </View>
      </KeyboardAvoidingView>

      {loading && (
        <View style={styles.loadingOverlay} pointerEvents="auto">
          <BreathingTriangle size={120} mode="loading" />
          <Text style={styles.loadingText}>{t("auth:connecting")}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0A0B0E",
  },
  kav: { flex: 1 },
  content: {
    flex: 1,
    paddingHorizontal: 18,
    justifyContent: "space-between",
  },

  /* ── Hero ── */
  hero: {
    flex: 1,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 40,
  },
  triangleWrap: {
    width: TRIANGLE_SIZE,
    height: TRIANGLE_SIZE,
    alignItems: "center",
    justifyContent: "center",
  },
  titleBlock: {
    alignItems: "center",
    marginTop: -24,
  },
  title: {
    fontSize: 40,
    fontFamily: theme.fonts.bodyBold,
    color: "#FFFFFF",
    letterSpacing: -0.8,
    lineHeight: 40,
  },
  tagline: {
    fontSize: 14,
    fontFamily: theme.fonts.body,
    color: "rgba(255,255,255,0.55)",
    marginTop: 8,
  },

  /* ── Connectors ── */
  connectorRow: {
    flexDirection: "row",
    gap: 12,
  },
  connector: {
    flex: 1,
    backgroundColor: "rgba(22,24,29,0.92)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.10)",
    borderRadius: 22,
    paddingVertical: 22,
    paddingHorizontal: 16,
    alignItems: "center",
    overflow: "hidden",
    position: "relative",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35,
    shadowRadius: 18,
    elevation: 6,
  },
  connectorPressed: {
    transform: [{ scale: 0.97 }],
    opacity: 0.88,
  },
  connectorLogoDisc: {
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  connectorLabel: {
    color: "#FFFFFF",
    fontSize: 16,
    fontFamily: theme.fonts.bodyMedium,
    letterSpacing: -0.1,
    marginTop: 12,
  },

  /* ── Loading overlay ── */
  loadingOverlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(8,8,10,0.75)",
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
  },
  loadingText: {
    color: theme.colors.textSecondary,
    fontFamily: theme.fonts.body,
    fontSize: 13,
    letterSpacing: 0.5,
  },
});
