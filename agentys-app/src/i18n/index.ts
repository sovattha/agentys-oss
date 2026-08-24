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

import i18n, { type BackendModule, type ReadCallback } from 'i18next'
import { initReactI18next } from 'react-i18next'

// All app namespaces. Keep in sync with the locale folder contents.
export const NAMESPACES = [
  'common', 'inbox', 'drafts', 'compose', 'settings', 'search',
  'deepfocus', 'onboarding', 'agents', 'calendar', 'errors',
  'support', 'availability',
] as const

// User-facing UI languages. Keep this intentionally narrow: incomplete
// locales should not be auto-detected or shown in settings/onboarding.
export const SUPPORTED_LANGS = ['fr', 'en'] as const
type Lang = (typeof SUPPORTED_LANGS)[number]

// Vite glob: each JSON becomes a separately-chunked dynamic import. The
// `manualChunks` rule in vite.config.ts coalesces all of one language's
// namespaces into a single `locale-<lng>.js` chunk so we fetch 1 file per
// language switch instead of N=13.
type LocaleModule = { default: Record<string, unknown> }
const localeLoaders = import.meta.glob<LocaleModule>('./locales/*/*.json')

const loaderKey = (lng: string, ns: string) => `./locales/${lng}/${ns}.json`

// In-process i18next backend. i18next calls `read()` whenever it needs a
// (language, namespace) bundle that isn't already in memory. We resolve via
// the Vite glob, which lazy-loads the matching chunk on first miss and
// caches it for the rest of the session.
//
// Exported so the regression test (`i18n.lazy.test.ts`) can attach it to a
// fresh `i18next.createInstance()` and exercise the chunk-loading path
// without touching the global singleton (which setup.ts already pre-fills).
export const lazyBackend: BackendModule = {
  type: 'backend',
  init: () => { /* nothing to init */ },
  read: (language: string, namespace: string, callback: ReadCallback) => {
    const loader = localeLoaders[loaderKey(language, namespace)]
    if (!loader) {
      callback(new Error(`i18n: missing locale ${language}/${namespace}`), null)
      return
    }
    loader()
      .then(mod => callback(null, mod.default as Record<string, string>))
      .catch(err => callback(err instanceof Error ? err : new Error(String(err)), null))
  },
}

function detectBrowserLang(): Lang {
  if (typeof navigator === 'undefined') return 'fr'

  // Step 1: system regional setting via Intl. On macOS / Windows the OS-level
  // regional preference (fr-CA on a Quebec machine) flows through here even
  // when the browser's UI/Accept-Language list starts with English. We treat
  // this as the strongest signal of "what language does this human actually
  // operate in."
  let systemLocale = ''
  try {
    systemLocale = Intl.DateTimeFormat().resolvedOptions().locale || ''
  } catch { /* ignore */ }
  const systemShort = systemLocale.toLowerCase().slice(0, 2) as Lang
  if ((SUPPORTED_LANGS as readonly string[]).includes(systemShort)) {
    return systemShort
  }

  // Step 2: any French preference anywhere in the browser language list wins
  // over English. Rationale: Quebec users routinely have `en-US` first in
  // Chrome's Accept-Language list (Chrome's default) but want the app in
  // French. Without this bias the auto-detect kept landing on English.
  const browserCandidates = [
    ...(navigator.languages ?? []),
    navigator.language,
  ].filter(Boolean) as string[]
  if (browserCandidates.some(raw => raw.toLowerCase().startsWith('fr'))) {
    return 'fr'
  }

  // Step 3: first matching supported lang from the browser preferences.
  for (const raw of browserCandidates) {
    const short = raw.toLowerCase().slice(0, 2) as Lang
    if ((SUPPORTED_LANGS as readonly string[]).includes(short)) return short
  }
  return 'fr'
}

const storedLang = typeof localStorage !== 'undefined'
  ? localStorage.getItem('agentys_language')
  : null
const initialLang: Lang = (storedLang && (SUPPORTED_LANGS as readonly string[]).includes(storedLang))
  ? storedLang as Lang
  : detectBrowserLang()

// Boot-time preload. Awaited by main.tsx before React mounts so the first
// frame has the active language fully resolved (zero flash of keys). i18next
// loads both `lng` and `fallbackLng` if they differ — so a non-FR user pays
// 2 chunks at boot (their language + FR fallback). A FR user pays 1 chunk.
//
// `i18n.isInitialized` short-circuit covers two cases:
//   - Vitest setup.ts initializes i18n synchronously with bundled FR
//     resources; component test imports of this module must NOT re-init
//     (would wipe the test resources).
//   - Vite HMR re-running this module (e.g. dev edit) keeps the existing
//     instance; we re-trigger languageChanged below to repaint.
export const i18nReady: Promise<typeof i18n> = (async () => {
  if (i18n.isInitialized) return i18n

  await i18n
    .use(lazyBackend)
    .use(initReactI18next)
    .init({
      lng: initialLang,
      fallbackLng: 'fr',
      supportedLngs: SUPPORTED_LANGS as unknown as string[],
      ns: NAMESPACES as unknown as string[],
      defaultNS: 'common',
      interpolation: { escapeValue: false },
      // `initAsync: false` makes i18n.init() resolve only after the active
      // language's namespaces are read by the backend. Without this, init
      // resolves immediately and the first render flashes keys.
      initAsync: false,
      // Required so addResourceBundle (HMR re-run path) merges new keys into
      // backend-loaded languages instead of being ignored.
      partialBundledLanguages: true,
      // P3-21 (2026-05-17): explicit debug gate so we never ship the Locize
      // promo banner to production. i18next defaults to debug=true in
      // bundles where `process.env.NODE_ENV !== 'production'`, which Vite
      // dev builds satisfy but some prod chunkers leave ambiguous; pinning
      // to `import.meta.env.DEV` makes the production payload deterministic.
      debug: import.meta.env.DEV,
    })

  return i18n
})()

// BUG-U001 (2026-05-16): keep `<html lang="…">` in sync with the active
// i18n language. Screen readers (NVDA/JAWS/VoiceOver) read the document's
// lang attribute to pick a voice/pronunciation — without this, switching
// the UI to English left lang='fr' so French TTS was used to read English
// text. Also matters for SEO (crawlers honour lang) and CSS `:lang()`.
//
// Fires on every languageChanged event AND once at init so the first paint
// already has the right value. Guarded against SSR / test environments
// where `document` is undefined.
if (typeof document !== 'undefined') {
  const syncHtmlLang = (lng?: string) => {
    const code = (lng || i18n.language || 'fr').slice(0, 2)
    document.documentElement.setAttribute('lang', code)
  }
  i18n.on('languageChanged', syncHtmlLang)
  i18nReady.then(() => syncHtmlLang()).catch(() => { /* init already failed elsewhere */ })
}

// Vite HMR. With the previous static-import setup, editing a JSON file
// invalidated this module and the `else` branch re-applied bundles in place.
// With dynamic glob, JSON files are no longer direct deps of this module, so
// Vite falls back to a full page reload on JSON edits (~200 ms). The
// self-accept below keeps this module from full-reloading when ONLY it is
// edited (rare — the JSON files dominate edit frequency).
if (import.meta.hot) {
  import.meta.hot.accept()
}

export default i18n
