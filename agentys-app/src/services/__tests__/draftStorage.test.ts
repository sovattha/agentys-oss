// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock currentAccountId BEFORE importing draftStorage so the subscribe call
// in draftStorage's module scope is already patched.
vi.mock('../../lib/currentAccountId', () => ({
  getCurrentAccountId: () => 1,
  isCurrentAccountLoaded: () => true,
  ensureCurrentAccountId: async () => 1,
  subscribeCurrentAccountId: (_cb: () => void) => () => {},
}))

import {
  saveComposeDraft,
  getSavedDrafts,
  getLatestComposeDraft,
  deleteAllSavedDrafts,
  hasContent,
} from '../draftStorage'

const STORAGE_KEY = 'agentys_saved_drafts:1'

describe('draftStorage — 7-day expiry (silent-failure fix, issue #312)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('garde un brouillon écrit il y a < 7 jours', () => {
    saveComposeDraft({
      to: 'alice@example.com',
      cc: '',
      bcc: '',
      subject: 'Hello',
      body: 'Contenu récent',
    })
    expect(getLatestComposeDraft()).toBeDefined()
    expect(getLatestComposeDraft()?.subject).toBe('Hello')
  })

  it('purge un brouillon > 7 jours sur getSavedDrafts', () => {
    // Injecter un brouillon vieux directement dans localStorage
    const old = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString()
    const fresh = new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString()
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { type: 'compose', id: 'old', to: '', cc: '', bcc: '', subject: 'Ancien', body: 'x', savedAt: old },
        { type: 'compose', id: 'new', to: '', cc: '', bcc: '', subject: 'Récent', body: 'y', savedAt: fresh },
      ]),
    )

    const remaining = getSavedDrafts()

    // Le draft > 7j doit avoir été purgé
    expect(remaining.some((d) => d.id === 'old')).toBe(false)
    // Le draft < 7j doit être conservé
    expect(remaining.some((d) => d.id === 'new')).toBe(true)
  })

  it('persiste la purge — le draft ancien ne réapparaît pas au lecture suivante', () => {
    const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString()
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { type: 'compose', id: 'tooOld', to: '', cc: '', bcc: '', subject: 'Antique', body: 'z', savedAt: old },
      ]),
    )

    getSavedDrafts() // premier appel déclenche la purge
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!) as Array<{ id: string }>
    expect(parsed.find((d) => d.id === 'tooOld')).toBeUndefined()
  })

  it('ne crash pas si savedAt est corrompu (date invalide)', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { type: 'compose', id: 'bad', to: '', cc: '', bcc: '', subject: '?', body: '?', savedAt: 'not-a-date' },
      ]),
    )
    expect(() => getSavedDrafts()).not.toThrow()
  })

  afterEach(() => {
    deleteAllSavedDrafts()
    localStorage.clear()
  })
})

// Helper pour pouvoir utiliser afterEach en haut
function afterEach(fn: () => void): void {

  ;(globalThis as any).afterEach?.(fn)
}

describe('draftStorage — recover drafts stranded by the async account-id race', () => {
  const NULL_KEY = 'agentys_saved_drafts:__none'
  const LEGACY_KEY = 'agentys_saved_drafts'

  beforeEach(() => {
    localStorage.clear()
  })

  const mkDraft = (id: string, subject: string, ageHours = 1) => ({
    type: 'compose' as const,
    id,
    to: '',
    cc: '',
    bcc: '',
    subject,
    body: 'x',
    savedAt: new Date(Date.now() - ageHours * 60 * 60 * 1000).toISOString(),
  })

  it('reclaims drafts written under the :__none fallback into the account key', () => {
    // Simulate a draft autosaved while the account id was still loading.
    localStorage.setItem(NULL_KEY, JSON.stringify([mkDraft('stranded', 'Hahaha')]))

    const drafts = getSavedDrafts()

    expect(drafts.some((d) => d.id === 'stranded')).toBe(true)
    // The stray key is consumed and the draft now lives under the real key.
    expect(localStorage.getItem(NULL_KEY)).toBeNull()
    const real = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') as Array<{ id: string }>
    expect(real.find((d) => d.id === 'stranded')).toBeDefined()
  })

  it('also migrates the pre-scoping legacy unscoped key', () => {
    localStorage.setItem(LEGACY_KEY, JSON.stringify([mkDraft('legacy', 'Sdfsdf')]))

    const drafts = getSavedDrafts()

    expect(drafts.some((d) => d.id === 'legacy')).toBe(true)
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull()
  })

  it('merges strays with existing account drafts, account entry wins on id clash', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([mkDraft('dup', 'Owned', 1)]))
    localStorage.setItem(NULL_KEY, JSON.stringify([
      { ...mkDraft('dup', 'Stray', 1), subject: 'Stray' },
      mkDraft('extra', 'Vérification suppression email'),
    ]))

    const drafts = getSavedDrafts()

    const dup = drafts.find((d) => d.id === 'dup') as { subject?: string } | undefined
    expect(dup?.subject).toBe('Owned')
    expect(drafts.some((d) => d.id === 'extra')).toBe(true)
  })

  it('does not resurrect expired strays (7-day TTL still applies)', () => {
    localStorage.setItem(NULL_KEY, JSON.stringify([mkDraft('old', 'Ancien', 8 * 24)]))

    const drafts = getSavedDrafts()

    expect(drafts.some((d) => d.id === 'old')).toBe(false)
  })

  afterEach(() => {
    localStorage.clear()
  })
})

describe('hasContent — HTML-wrapped empty body detection (R2-U-02 fix)', () => {
  it('retourne false pour body = "" (naïf)', () => {
    expect(hasContent({ body: '' })).toBe(false)
  })

  it('retourne false pour body = "<p></p>" (TipTap empty)', () => {
    expect(hasContent({ body: '<p></p>' })).toBe(false)
  })

  it('retourne false pour body = "<p><br></p>" (TipTap empty avec br)', () => {
    expect(hasContent({ body: '<p><br></p>' })).toBe(false)
  })

  it('retourne false pour body = "<p>&nbsp;</p>" (espace insécable only)', () => {
    expect(hasContent({ body: '<p>&nbsp;</p>' })).toBe(false)
  })

  it('retourne true pour body = "<p>Hello</p>"', () => {
    expect(hasContent({ body: '<p>Hello</p>' })).toBe(true)
  })

  it('retourne true si seul le subject est rempli', () => {
    expect(hasContent({ subject: 'Hi' })).toBe(true)
  })

  it('retourne true si seul le destinataire est rempli', () => {
    expect(hasContent({ to: 'alice@example.com' })).toBe(true)
  })
})
