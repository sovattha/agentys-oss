import type { Email } from '../types/email'

type ThreadLookupEmail = Pick<Email, 'id' | 'conversation_id'>

export function getEmailThreadEmails(emails: Email[], selectedEmail: ThreadLookupEmail): Email[] {
  if (selectedEmail.conversation_id) {
    return emails.filter((email) => email.conversation_id === selectedEmail.conversation_id)
  }

  const matchingEmail = emails.find((email) => email.id === selectedEmail.id)
  return matchingEmail ? [matchingEmail] : []
}

export function getUnreadThreadEmailsOnOpen(emails: Email[], selectedEmail: ThreadLookupEmail): Email[] {
  return getEmailThreadEmails(emails, selectedEmail).filter((email) => email.is_read === false)
}

export function markEmailThreadReadInList(emails: Email[], selectedEmail: ThreadLookupEmail): Email[] {
  const threadIds = new Set(getEmailThreadEmails(emails, selectedEmail).map((email) => email.id))
  if (threadIds.size === 0) {
    threadIds.add(selectedEmail.id)
  }

  let changed = false
  const nextEmails = emails.map((email) => {
    if (!threadIds.has(email.id) || email.is_read === true) {
      return email
    }
    changed = true
    return { ...email, is_read: true }
  })

  return changed ? nextEmails : emails
}
