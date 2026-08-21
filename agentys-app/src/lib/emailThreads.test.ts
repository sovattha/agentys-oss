import { describe, expect, it } from 'vitest'
import { getUnreadThreadEmailsOnOpen, markEmailThreadReadInList } from './emailThreads'
import type { Email } from '../types/email'

function makeEmail(overrides: Partial<Email>): Email {
  return {
    id: 'email-id',
    sender: 'sender@example.com',
    subject: 'Subject',
    received_at: '2026-06-02T12:00:00Z',
    conversation_id: null,
    is_read: true,
    ...overrides,
  }
}

describe('email thread read state', () => {
  it('marks unread siblings in the same conversation when the opened row is already read', () => {
    const emails = [
      makeEmail({ id: 'latest', conversation_id: 'thread-1', is_read: true }),
      makeEmail({ id: 'older', conversation_id: 'thread-1', is_read: false }),
      makeEmail({ id: 'other-thread', conversation_id: 'thread-2', is_read: false }),
    ]

    const unreadThreadEmails = getUnreadThreadEmailsOnOpen(emails, emails[0])
    const nextEmails = markEmailThreadReadInList(emails, emails[0])

    expect(unreadThreadEmails.map((email) => email.id)).toEqual(['older'])
    expect(nextEmails.find((email) => email.id === 'latest')?.is_read).toBe(true)
    expect(nextEmails.find((email) => email.id === 'older')?.is_read).toBe(true)
    expect(nextEmails.find((email) => email.id === 'other-thread')?.is_read).toBe(false)
  })

  it('does not group standalone emails that have no conversation id', () => {
    const emails = [
      makeEmail({ id: 'selected', conversation_id: null, is_read: false }),
      makeEmail({ id: 'unrelated', conversation_id: null, is_read: false }),
    ]

    const nextEmails = markEmailThreadReadInList(emails, emails[0])

    expect(nextEmails.find((email) => email.id === 'selected')?.is_read).toBe(true)
    expect(nextEmails.find((email) => email.id === 'unrelated')?.is_read).toBe(false)
  })
})
