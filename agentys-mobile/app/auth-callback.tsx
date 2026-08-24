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
 * Deep link handler pour agentys://auth-callback?token=X
 */

import { useEffect } from "react";
import { useRouter, useLocalSearchParams } from "expo-router";
import { View, Text, StyleSheet } from "react-native";
import { BreathingTriangle } from "../src/components/BreathingTriangle";
import { useTranslation } from "react-i18next";
import { verifyMagicToken } from "../src/services/auth";
import { useAuth } from "../src/hooks/useAuth";
import { theme } from "../src/theme";

// Magic-link tokens we mint server-side are URL-safe base64 strings under 512
// chars. Reject anything else before forwarding to /api/auth/verify (audit
// Codex 2026-04-25 [F-MOBILE-10]). This is a shape check only — the backend
// remains the authority on whether the token was actually issued.
const TOKEN_PATTERN = /^[A-Za-z0-9._\-]+$/;
const TOKEN_MAX_LEN = 512;

export default function AuthCallbackScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const { login } = useAuth();
  const router = useRouter();
  const { t } = useTranslation("auth");

  useEffect(() => {
    if (!token || typeof token !== "string") {
      router.replace("/login");
      return;
    }
    if (token.length > TOKEN_MAX_LEN || !TOKEN_PATTERN.test(token)) {
      router.replace("/login");
      return;
    }

    verifyMagicToken(token)
      .then((data) => login(data.access_token))
      .then(() => router.replace("/"))
      .catch(() => router.replace("/login"));
  }, [token]);

  return (
    <View style={styles.container}>
      <BreathingTriangle size={120} mode="loading" />
      <Text style={styles.text}>{t("connecting")}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: theme.colors.bg,
    gap: 16,
  },
  text: {
    fontSize: 13,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    letterSpacing: 0.5,
  },
});
