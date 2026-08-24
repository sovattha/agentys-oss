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
