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
 * Greeting — Salutation dynamique avec prénom personnalisé.
 *
 * Audit UX 2026-04-28 : ajout du cache SecureStore — sans ce cache, on
 * voyait "Bonjour" → 200-400ms plus tard "Bonjour\nAlex" (pop-in désagréable
 * au cold start). Avec le cache, le nom apparaît instantanément (lecture
 * SecureStore ~10ms vs fetch HTTP 200-400ms), et un fetch en background
 * rafraîchit silencieusement si l'user a changé de compte.
 *
 * 4 plages horaires (matin/après-midi/soir/nuit) — la nuit (22-5h) est
 * fréquente chez les power users qui font leur inbox tard le soir.
 */

import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import * as SecureStore from "expo-secure-store";
import { useTranslation } from "react-i18next";
import { getUserName } from "../services/api";
import { theme } from "../theme";

const NAME_CACHE_KEY = "agentys_user_first_name";

type GreetingKey =
  | "greetingMorning"
  | "greetingAfternoon"
  | "greetingEvening"
  | "greetingNight";

function getGreetingKey(): GreetingKey {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return "greetingMorning";
  if (h >= 12 && h < 18) return "greetingAfternoon";
  if (h >= 18 && h < 22) return "greetingEvening";
  return "greetingNight";
}

export function Greeting() {
  const [name, setName] = useState<string | null>(null);
  const { t } = useTranslation("settings");

  useEffect(() => {
    let cancelled = false;
    // Path 1 (instant) : cache SecureStore — le prénom apparaît dès le 1er paint
    SecureStore.getItemAsync(NAME_CACHE_KEY)
      .then((cached) => {
        if (!cancelled && cached) setName(cached);
      })
      .catch(() => {}); // no-op légitime : prénom best-effort

    // Path 2 (background) : fetch via /api/accounts pour rafraîchir si changé
    getUserName()
      .then((n) => {
        if (cancelled) return;
        if (n) {
          setName(n);
          SecureStore.setItemAsync(NAME_CACHE_KEY, n).catch(() => {}); // no-op légitime : cache best-effort
        }
      })
      .catch(() => {}); // no-op légitime : prénom best-effort

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <View style={styles.wrap}>
      <Text style={styles.greeting}>{t(getGreetingKey())}</Text>
      {name ? <Text style={styles.name}>{name}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center",
    gap: 4,
  },
  greeting: {
    fontFamily: theme.fonts.body,
    fontSize: 16,
    color: theme.colors.textDimmed,
    letterSpacing: 0.2,
    textAlign: "center",
  },
  name: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 20,
    color: theme.colors.textPrimary,
    letterSpacing: 0.2,
    textAlign: "center",
  },
});
