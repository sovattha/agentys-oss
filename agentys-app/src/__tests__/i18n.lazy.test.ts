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
 * Regression tests for the lazy i18n backend (see src/i18n/index.ts).
 *
 * Background: production code splits each language into its own Vite chunk
 * (`locale-{fr,en}.js`) and the active language is preloaded via a
 * custom `BackendModule` that resolves a Vite glob. The risk surface this
 * suite guards:
 *
 *  1. The glob must match all (lang, ns) combinations the app declares.
 *  2. i18next must be able to drive the backend through init + changeLanguage.
 *  3. Fallback resolution must work when a key is absent from the active lang.
 *  4. A language not in SUPPORTED_LANGS must reject gracefully (no hang).
 *
 * Tests use `i18next.createInstance()` so we don't pollute the global
 * singleton that setup.ts pre-fills with eager resources for component tests.
 */
import { describe, it, expect } from 'vitest'
import i18next from 'i18next'
import { lazyBackend, NAMESPACES, SUPPORTED_LANGS } from '../i18n'

function freshInstance() {
  return i18next.createInstance()
}

describe('lazy i18n backend', () => {
  it('preloads the active language at init so first .t() returns translated text', async () => {
    const i18n = freshInstance()
    await i18n.use(lazyBackend).init({
      lng: 'en',
      fallbackLng: 'fr',
      ns: ['common'],
      defaultNS: 'common',
      initAsync: false,
      partialBundledLanguages: true,
    })

    // `accept` is a top-level key in common.json across supported langs with
    // distinct values per language. A non-loaded backend would return the
    // bare key; we assert we got a real string.
    const translated = i18n.t('accept')
    expect(translated).toBeTruthy()
    expect(translated).not.toBe('accept')
  })

  it('changeLanguage triggers backend read for the new language', async () => {
    const i18n = freshInstance()
    await i18n.use(lazyBackend).init({
      lng: 'fr',
      fallbackLng: 'fr',
      ns: ['common'],
      defaultNS: 'common',
      initAsync: false,
      partialBundledLanguages: true,
    })

    const fr = i18n.t('accept')
    expect(fr).toBeTruthy()
    expect(fr).toBe('Accepter')

    await i18n.changeLanguage('en')
    const en = i18n.t('accept')
    expect(en).toBeTruthy()
    expect(en).toBe('Accept')
    // EN and FR translations of `common.accept` should differ — if they
    // collide we'd have a coincidence we can revisit.
    expect(en).not.toBe(fr)
  })

  it('falls back to fallbackLng when active lang is missing a key', async () => {
    // `compose.no_project_prefix` exists in FR but is absent from EN (one of
    // the 4 documented coverage gaps). This is the gap that we currently
    // preload the FR fallback chunk to cover.
    const i18n = freshInstance()
    await i18n.use(lazyBackend).init({
      lng: 'en',
      fallbackLng: 'fr',
      ns: ['compose'],
      defaultNS: 'compose',
      initAsync: false,
      partialBundledLanguages: true,
    })

    const value = i18n.t('no_project_prefix')
    expect(value).toBeTruthy()
    expect(value).not.toBe('no_project_prefix')
  })

  it('the Vite glob covers every (lang, namespace) the app declares', async () => {
    // Catches the failure mode: someone adds a new namespace to NAMESPACES
    // (or new language to SUPPORTED_LANGS) but forgets the corresponding
    // JSON file. Without this test the lazy backend would silently log a
    // missing-key warning at runtime and only fail in browser QA.
    const localeLoaders = import.meta.glob('../i18n/locales/*/*.json')
    const present = new Set(Object.keys(localeLoaders).map(p => {
      const m = p.match(/locales\/([a-z]{2})\/(\w+)\.json$/)
      return m ? `${m[1]}/${m[2]}` : ''
    }))

    const missing: string[] = []
    for (const lng of SUPPORTED_LANGS) {
      for (const ns of NAMESPACES) {
        if (!present.has(`${lng}/${ns}`)) {
          missing.push(`${lng}/${ns}`)
        }
      }
    }
    expect(missing).toEqual([])
  })

  it('rejects unknown languages without hanging', async () => {
    // If `lng` is unsupported, the backend's read() callbacks with an Error.
    // i18next surfaces this as a failed namespace load but still resolves
    // init() (it just won't have resources for that lang). The fallback path
    // keeps the app usable.
    const i18n = freshInstance()
    await i18n.use(lazyBackend).init({
      lng: 'ja' as string, // not in SUPPORTED_LANGS
      fallbackLng: 'fr',
      ns: ['common'],
      defaultNS: 'common',
      initAsync: false,
      partialBundledLanguages: true,
    })

    // Fallback to FR keeps the app rendering a translated string instead of
    // the bare key.
    const value = i18n.t('accept')
    expect(value).toBeTruthy()
    expect(value).toBe('Accepter')
  })
})
