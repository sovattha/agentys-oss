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

import { describe, it, expect, vi } from 'vitest'
import {
  getResponse,
  getWelcomeMessage,
  POPULAR_ARTICLE_IDS,
  ARTICLE_INDEX,
  type QuickAction,
} from './chatEngine'
import enSupport from '../../i18n/locales/en/support.json'
import frSupport from '../../i18n/locales/fr/support.json'
import esSupport from '../../i18n/locales/es/support.json'

const en = enSupport as Record<string, string>
const fr = frSupport as Record<string, string>
const es = esSupport as Record<string, string>

describe('getWelcomeMessage', () => {
  it('resolves every visible label through the provided t() function (regression: 2026-05-15 audit)', () => {
    const seen: string[] = []
    const t = (k: string) => {
      seen.push(k)
      return `«${k}»`
    }

    const { quickActions, text } = getWelcomeMessage(t)

    // The component owns the greeting text — getWelcomeMessage returns an
    // empty string so the older hardcoded "Bonjour ! Je suis…" leak is gone.
    expect(text).toBe('')

    // Every quick-action label must have come from t() — no hardcoded FR/EN.
    expect(quickActions).toBeDefined()
    expect(quickActions!.length).toBeGreaterThan(0)
    for (const qa of quickActions as QuickAction[]) {
      expect(qa.label.startsWith('«') && qa.label.endsWith('»')).toBe(true)
    }

    // Specific keys we expect to be wired up.
    expect(seen).toEqual(
      expect.arrayContaining([
        'welcome_card_drafts_label',
        'welcome_card_style_label',
        'welcome_card_productivity_label',
        'welcome_card_problem_label',
        'welcome_action_suggest',
        'welcome_action_bug',
      ]),
    )
  })

  it('does not contain any of the old hardcoded FR strings', () => {
    const t = (k: string) => `«${k}»`
    const { quickActions } = getWelcomeMessage(t)

    const labels = (quickActions || []).map(q => q.label).join('\n')

    expect(labels).not.toMatch(/Brouillons IA/)
    expect(labels).not.toMatch(/Style IA/)
    expect(labels).not.toMatch(/Productivité/)
    expect(labels).not.toMatch(/Un problème/)
    expect(labels).not.toMatch(/Suggérer une amélioration/)
    expect(labels).not.toMatch(/Signaler un bug/)
    expect(labels).not.toMatch(/Parcourir l'aide/)
  })

  it('exposes 4 primary actions + 2 secondary actions in deterministic order', () => {
    const t = vi.fn((k: string) => k)
    const { quickActions } = getWelcomeMessage(t)

    expect(quickActions).toHaveLength(6)

    // Primary slot order: drafts, style, productivity, problem
    expect(quickActions![0].action).toMatch(/brouillons/)
    expect(quickActions![1].action).toMatch(/style/)
    expect(quickActions![2].action).toMatch(/plus vite/)
    expect(quickActions![3].action).toMatch(/quelque chose ne marche pas/)

    // Secondary slot order: suggest (form), bug (form). "Browse help"
    // (navigate:help) was removed from the welcome footer — the FAQ stays
    // reachable via the Popular guides articles and the fallback response.
    expect(quickActions![4].action).toBe('form:feature')
    expect(quickActions![5].action).toBe('form:bug')
  })

  it('attaches an icon id to every welcome action', () => {
    const t = (k: string) => k
    const { quickActions } = getWelcomeMessage(t)

    for (const qa of quickActions || []) {
      expect(qa.icon, `missing icon for action "${qa.action}"`).toBeTruthy()
    }
  })
})

describe('POPULAR_ARTICLE_IDS', () => {
  it('caps at 3 entries for a calmer welcome hierarchy', () => {
    expect(POPULAR_ARTICLE_IDS).toHaveLength(3)
  })

  it('every popular id resolves to an entry in ARTICLE_INDEX', () => {
    for (const id of POPULAR_ARTICLE_IDS) {
      const match = ARTICLE_INDEX.find(a => a.id === id)
      expect(match, `unknown article id: ${id}`).toBeDefined()
    }
  })
})

// A representative sweep of queries hitting most rules. Used to assert the
// engine's i18n contract holds for every reachable response.
const SWEEP = [
  'bonjour', 'merci', 'où sont mes brouillons', 'les brouillons ne se génèrent pas',
  'mes emails ne chargent pas', 'je ne peux pas envoyer', "l'application est lente",
  'comment connecter mon compte', "je n'arrive pas à me connecter", 'comment ça marche',
  'quels sont les raccourcis', 'comment affiner un brouillon', 'les labels',
  'corriger un label', 'rechercher un email', 'paramètres', 'spam corbeille',
  'réponse automatique absence', 'nouveau message', 'suggestions rapides',
  'sécurité confidentialité', 'utiliser les actions rapides',
  'automatiser declencheur automatique', 'relances et suivis', 'dicter un email',
  'réunion invitation rsvp', 'abonnements payants', 'newsletters', 'fragments modèles',
  "annuler l'envoi", 'deep work concentration', 'thème sombre', 'bilan mensuel',
  'pièce jointe', 'reporter snooze', 'plusieurs comptes', 'prix tarif',
  "j'aimerais une fonctionnalité", 'bug crash', 'parler à un humain', 'zzqqxx nonsense',
]

describe('getResponse — i18n key contract (2026-05-22 localization)', () => {
  it('returns an i18n key for text that exists in all three locales', () => {
    for (const q of SWEEP) {
      const { text } = getResponse(q)
      // Rule/fallback text is always a key; the welcome path (empty) is the only
      // exception and is not reachable through getResponse.
      expect(text, `empty text for "${q}"`).toBeTruthy()
      expect(text, `text not a key for "${q}": ${text}`).toMatch(/^r_/)
      expect(en[text], `missing en[${text}]`).toBeTruthy()
      expect(fr[text], `missing fr[${text}]`).toBeTruthy()
      expect(es[text], `missing es[${text}]`).toBeTruthy()
    }
  })

  it('every chip label is an i18n key present in the English bundle', () => {
    for (const q of SWEEP) {
      const { quickActions } = getResponse(q)
      for (const qa of quickActions || []) {
        expect(en[qa.label], `chip label "${qa.label}" (from "${q}") missing in en`).toBeTruthy()
      }
    }
  })
})

describe('getResponse — multilingual routing (fr/en/es)', () => {
  const cases: Array<[string, string]> = [
    ['bonjour', 'r_greeting'],
    ['où sont mes brouillons', 'r_where_drafts'],
    ['where are my drafts', 'r_where_drafts'],
    ['¿dónde están mis borradores?', 'r_where_drafts'],
    ['les brouillons ne se génèrent pas', 'r_drafts_not_generating'],
    ['comment connecter mon compte', 'r_connect_account'],
    ['utiliser les actions rapides', 'r_quicksteps'],
    ['quick steps command palette', 'r_quicksteps'],
    ['automatiser declencheur automatique', 'r_quicksteps_auto'],
    ['relances et suivis', 'r_followups'],
    ['follow up reminder no reply', 'r_followups'],
    ['dicter un email', 'r_dictation'],
    ['dictate with my voice', 'r_dictation'],
    ['meeting invitation rsvp', 'r_calendar'],
    ['corriger un label', 'r_relabel'],
    ['corregir una etiqueta', 'r_relabel'],
  ]

  it.each(cases)('routes %j → %s', (query, expectedKey) => {
    expect(getResponse(query).text).toBe(expectedKey)
  })
})

describe('support locale parity', () => {
  it('en / fr / es share an identical key set', () => {
    const ek = Object.keys(en).sort()
    const fk = Object.keys(fr).sort()
    const sk = Object.keys(es).sort()
    expect(fk).toEqual(ek)
    expect(sk).toEqual(ek)
  })
})

describe('content accuracy guards (corrected facts must not regress)', () => {
  const allValues = [...Object.values(en), ...Object.values(fr), ...Object.values(es)]

  it('no help string mentions Docker (it is a desktop app)', () => {
    const offenders = allValues.filter(v => /docker/i.test(v))
    expect(offenders, offenders.join(' | ')).toHaveLength(0)
  })

  it('no help string narrates a "Critic agent" pipeline', () => {
    const offenders = allValues.filter(v => /\bcritic\b/i.test(v) || /agent\s+critic/i.test(v))
    expect(offenders, offenders.join(' | ')).toHaveLength(0)
  })

  it('drafts help states drafts are on-demand, not auto for every email', () => {
    expect(en.r_drafts_not_generating.toLowerCase()).toContain('on demand')
    expect(fr.r_drafts_not_generating.toLowerCase()).toContain('à la demande')
    // The old false promise must be gone.
    expect(en.r_where_drafts).not.toMatch(/automatically generates a draft (reply )?for every/i)
  })

  it('label help uses the real names (Action / Info / Noise|Bruit|Ruido)', () => {
    expect(en.r_labels).toContain('Action')
    expect(en.r_labels).toContain('Info')
    expect(en.r_labels).toContain('Noise')
    expect(fr.r_labels).toContain('Bruit')
    expect(es.r_labels).toContain('Ruido')
    // The previously-wrong taxonomy must not reappear.
    expect(en.r_labels).not.toMatch(/\bWaiting\b/)
    expect(en.r_labels).not.toMatch(/\bImportant\b/)
  })
})
