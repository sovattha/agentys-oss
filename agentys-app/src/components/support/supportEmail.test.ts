import { describe, it, expect } from 'vitest'
import { buildSupportEmail } from './supportEmail'

describe('buildSupportEmail', () => {
  const base = {
    accountEmail: 'jane@example.com',
    ticketRef: 'AG-12345',
    signature: 'Sent from Agentys',
  }

  it('builds a subject prefixed with [Support] and suffixed with the ticket ref', () => {
    const { subject } = buildSupportEmail({
      ...base,
      description: 'My emails are not loading anymore',
    })

    expect(subject.startsWith('[Support] ')).toBe(true)
    expect(subject.endsWith('- AG-12345')).toBe(true)
  })

  it('omits the reference suffix when no ticket ref is provided', () => {
    const { subject } = buildSupportEmail({
      ...base,
      ticketRef: '',
      description: 'My emails are not loading anymore',
    })

    expect(subject).toBe('[Support] My emails are not loading')
  })

  it('caps the subject description at ~30 chars without splitting words', () => {
    const longDescription = 'The synchronization with my outlook account keeps failing intermittently'
    const { subject } = buildSupportEmail({ ...base, description: longDescription })
    const middle = subject.replace(/^\[Support\] /, '').replace(/ - AG-12345$/, '')

    // Stays under the cap and never ends mid-word
    expect(middle.length).toBeLessThanOrEqual(30)
    expect(middle).not.toMatch(/\s$/)
    expect(longDescription.startsWith(middle)).toBe(true)
  })

  it('falls back to a single truncated word when the first token alone exceeds the cap', () => {
    const oneLongWord = 'antidisestablishmentarianism-is-not-loading'
    const { subject } = buildSupportEmail({ ...base, description: oneLongWord })
    const middle = subject.replace(/^\[Support\] /, '').replace(/ - AG-12345$/, '')

    expect(middle.length).toBeGreaterThan(0)
    expect(middle.length).toBeLessThanOrEqual(30)
    expect(oneLongWord.startsWith(middle)).toBe(true)
  })

  it('emits a body that is just the user description plus a one-line signature', () => {
    const { body } = buildSupportEmail({
      ...base,
      description: 'Drafts are not generating',
    })

    expect(body).toBe('Drafts are not generating\n\n—\nSent from Agentys · jane@example.com')
  })

  it('never leaks chatbot scaffolding into the body (regression: 2026-05-15 audit)', () => {
    const { body } = buildSupportEmail({
      ...base,
      description: 'Something broke',
    })

    // None of the previous French-only scaffolding tokens may appear.
    expect(body).not.toMatch(/Type\s*:\s*Support client/i)
    expect(body).not.toMatch(/Référence\s*:/i)
    expect(body).not.toMatch(/Contexte de la conversation/i)
    expect(body).not.toMatch(/Compte\s*:/i)
    expect(body).not.toMatch(/^Date\s*:/m)
  })

  it('does not echo conversation context (no bot-rule replies in the body)', () => {
    const description = 'Cannot log in'
    const { body } = buildSupportEmail({ ...base, description })

    // The body must contain the description and the signature, and nothing
    // that resembles a bot guidance bullet (the previous "- step" leak).
    expect(body.includes(description)).toBe(true)
    const bulletLines = body.split('\n').filter(line => /^-\s+/.test(line))
    expect(bulletLines).toHaveLength(0)
  })

  it('collapses runs of whitespace in the user input', () => {
    const { body, subject } = buildSupportEmail({
      ...base,
      description: '   Help me     please   ',
    })

    expect(body.startsWith('Help me please')).toBe(true)
    expect(subject).toContain('Help me please')
  })

  it('honors the localized signature line', () => {
    const { body } = buildSupportEmail({
      ...base,
      description: 'Issue',
      signature: 'Envoyé depuis Agentys',
    })

    expect(body.endsWith('Envoyé depuis Agentys · jane@example.com')).toBe(true)
  })
})
