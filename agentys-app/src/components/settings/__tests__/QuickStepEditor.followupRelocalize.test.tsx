/**
 * Follow-up draft body — pristine relocalize (2026-06-23).
 *
 * The follow-up Quick Step body is seeded ONCE in the account's
 * `preferred_language` (DB default `'fr'`), so an English-UI user whose writing
 * language was never set saw a French template ("Bonjour … Cordialement,") that
 * never updated. `normalizeQuickStep` now relocalizes an UNTOUCHED seed to the
 * current UI language on load; an edited body is preserved.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
}))

import {
  normalizeQuickStep,
  relocalizePristineFollowupBody,
  FOLLOWUP_DRAFT_BODY_BY_LANG,
} from '../../../types/quickStep'

const FR = FOLLOWUP_DRAFT_BODY_BY_LANG.fr
const EN = FOLLOWUP_DRAFT_BODY_BY_LANG.en

beforeEach(() => {
  // followupDraftDefaultBody() reads this first — force the "English app".
  localStorage.setItem('agentys_language', 'en')
})

describe('relocalizePristineFollowupBody', () => {
  it('swaps an untouched French seed for the current (English) seed', () => {
    expect(relocalizePristineFollowupBody(FR)).toBe(EN)
  })

  it('leaves an already-current (English) seed unchanged', () => {
    expect(relocalizePristineFollowupBody(EN)).toBe(EN)
  })

  it('never touches a user-edited body', () => {
    const edited = '<div>Hey, just circling back. — Alex</div>'
    expect(relocalizePristineFollowupBody(edited)).toBe(edited)
  })

  it('leaves an empty body empty', () => {
    expect(relocalizePristineFollowupBody('')).toBe('')
  })
})

describe('normalizeQuickStep — follow-up body relocalize', () => {
  function followupStep(body: string) {
    return normalizeQuickStep({
      id: '22222222-2222-2222-2222-222222222222',
      name: 'Follow-up new thread',
      triggers: [{ type: 'is_new_thread', value: 'true' }],
      actions: [{ type: 'create_snoozed_followup_draft', payload: { body, delay_days: 7 } }],
      firesOn: 'sent',
    } as Parameters<typeof normalizeQuickStep>[0])
  }

  it('relocalizes a persisted French seed to English on load', () => {
    const step = followupStep(FR)
    const payload = step.actions[0].payload as { body: string; delay_days: number }
    expect(payload.body).toBe(EN)
    expect(payload.body).not.toContain('Bonjour')
    expect(payload.body).not.toContain('Prénom du destinataire')
    expect(payload.delay_days).toBe(7)
  })

  it('preserves an edited follow-up body', () => {
    const edited = '<div>Custom relance.</div>'
    const step = followupStep(edited)
    const payload = step.actions[0].payload as { body: string }
    expect(payload.body).toBe(edited)
  })
})
