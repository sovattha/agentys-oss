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
 * i18n setup for the mobile app.
 *
 * Source of truth for language :
 *   1. Backend `preferred_language` on the user's account (set via the web app)
 *   2. SecureStore cache (last value synced from backend — avoids FR/EN flash on cold start)
 *   3. Default: 'en' (matches CLAUDE.md policy — English when no info available)
 *
 * The device locale is intentionally NOT used as a fallback. The web app is the
 * source of truth ; if the user hasn't set anything, we default to English.
 */

import i18n, { type InitOptions } from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enInbox from "./locales/en/inbox.json";
import enCompose from "./locales/en/compose.json";
import enDrive from "./locales/en/drive.json";
import enSession from "./locales/en/session.json";
import enSettings from "./locales/en/settings.json";
import enVoice from "./locales/en/voice.json";
import enGuide from "./locales/en/guide.json";

import frCommon from "./locales/fr/common.json";
import frAuth from "./locales/fr/auth.json";
import frInbox from "./locales/fr/inbox.json";
import frCompose from "./locales/fr/compose.json";
import frDrive from "./locales/fr/drive.json";
import frSession from "./locales/fr/session.json";
import frSettings from "./locales/fr/settings.json";
import frVoice from "./locales/fr/voice.json";
import frGuide from "./locales/fr/guide.json";

export const SUPPORTED_LANGUAGES = ["en", "fr"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];
export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

export const NAMESPACES = [
  "common",
  "auth",
  "inbox",
  "compose",
  "drive",
  "session",
  "settings",
  "voice",
  "guide",
] as const;

const resources = {
  en: {
    common: enCommon,
    auth: enAuth,
    inbox: enInbox,
    compose: enCompose,
    drive: enDrive,
    session: enSession,
    settings: enSettings,
    voice: enVoice,
    guide: enGuide,
  },
  fr: {
    common: frCommon,
    auth: frAuth,
    inbox: frInbox,
    compose: frCompose,
    drive: frDrive,
    session: frSession,
    settings: frSettings,
    voice: frVoice,
    guide: frGuide,
  },
} as const;

const initOptions: InitOptions = {
  resources,
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  defaultNS: "common",
  ns: NAMESPACES as unknown as string[],
  interpolation: { escapeValue: false },
  returnNull: false,
  compatibilityJSON: "v4",
};

let initialized = false;

export function initI18n(initialLanguage?: SupportedLanguage): typeof i18n {
  if (initialized) {
    if (initialLanguage && i18n.language !== initialLanguage) {
      void i18n.changeLanguage(initialLanguage);
    }
    return i18n;
  }
  const lng = normalizeLanguage(initialLanguage);
  void i18n.use(initReactI18next).init({ ...initOptions, lng });
  initialized = true;
  return i18n;
}

/** Coerce any string into a supported language, defaulting to `en`. */
export function normalizeLanguage(raw?: string | null): SupportedLanguage {
  if (!raw) return DEFAULT_LANGUAGE;
  const head = raw.trim().toLowerCase().split(/[-_]/)[0];
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(head)
    ? (head as SupportedLanguage)
    : DEFAULT_LANGUAGE;
}

export async function setLanguage(lang: SupportedLanguage): Promise<void> {
  if (!initialized) initI18n(lang);
  if (i18n.language !== lang) await i18n.changeLanguage(lang);
}

export { i18n };
export default i18n;
