import { describe, expect, it } from 'vitest'
import { detectOAuthErrorGuidance } from './oauthProblemGuidance'

describe('detectOAuthErrorGuidance', () => {
  it('detects Gmail missing OAuth scopes from raw Google errors', () => {
    const guidance = detectOAuthErrorGuidance(
      'HttpError 403 when requesting https://gmail.googleapis.com/gmail/v1/users/me/messages returned "Request had insufficient authentication scopes."',
    )

    expect(guidance).toEqual({
      provider: 'gmail',
      defaultProblem: 'missing_scopes',
    })
  })

  it('detects the callback loop error shown after an invalid OAuth return', () => {
    const guidance = detectOAuthErrorGuidance('Invalid OAuth result')

    expect(guidance?.defaultProblem).toBe('callback_loop')
  })

  it('leaves unrelated sync errors in the generic error UI', () => {
    expect(detectOAuthErrorGuidance('database is locked')).toBeNull()
  })
})
