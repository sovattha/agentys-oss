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
 * Tests for human-readable error messages with solutions
 *
 * Story 7-7: Plain Language Error Messages
 * Tests AC1-AC6 requirements
 */

import { describe, it, expect } from 'vitest'
import {
  getErrorMessage,
  fromHttpStatus,
  fromNetworkError,
  fromApiError,
  isOnline,
  createOfflineError,
  ErrorCode,
  type HumanError,
} from '../services/errorMessages'

describe('errorMessages', () => {
  describe('getErrorMessage', () => {
    it('returns connection error message for network failures', () => {
      const result = getErrorMessage(ErrorCode.CONNECTION_FAILED)

      expect(result.title).toBe('Impossible de se connecter')
      expect(result.message).toContain('assistant')
      expect(result.solution).toBeTruthy()
      expect(result.severity).toBe('error')
    })

    it('returns authentication error for 401', () => {
      const result = getErrorMessage(ErrorCode.UNAUTHORIZED)

      expect(result.title).toBe('Authentification requise')
      expect(result.solution).toBeTruthy()
      expect(result.severity).toBe('warning')
    })

    it('returns email provider error for IMAP/SMTP failures', () => {
      const result = getErrorMessage(ErrorCode.EMAIL_PROVIDER_ERROR)

      expect(result.title.toLowerCase()).toContain('email')
      expect(result.solution).toBeTruthy()
      expect(result.severity).toBe('error')
    })

    it('returns LLM error message when AI is unavailable', () => {
      const result = getErrorMessage(ErrorCode.LLM_UNAVAILABLE)

      expect(result.title.toLowerCase()).toContain('ia')
      expect(result.solution).toBeTruthy()
      expect(result.severity).toBe('warning')
    })

    it('returns draft creation error', () => {
      const result = getErrorMessage(ErrorCode.DRAFT_CREATION_FAILED)

      expect(result.title.toLowerCase()).toContain('brouillon')
      expect(result.solution).toBeTruthy()
    })

    it('returns generic error for unknown codes', () => {
      const result = getErrorMessage('UNKNOWN_CODE' as ErrorCode)

      expect(result.title).toBe('Erreur inattendue')
      expect(result.severity).toBe('error')
    })

    it('includes original error message in technicalDetails', () => {
      const originalError = 'Connection refused to localhost:5000'
      const result = getErrorMessage(ErrorCode.CONNECTION_FAILED, originalError)

      expect(result.technicalDetails).toBe(originalError)
    })

    // AC1: All error messages have clear text, localized via i18n (errors:human.*)
    it('returns human-readable messages (AC1)', () => {
      const codes = [
        ErrorCode.NETWORK_OFFLINE,
        ErrorCode.AUTH_TOKEN_EXPIRED,
        ErrorCode.GMAIL_QUOTA_EXCEEDED,
        ErrorCode.DRAFT_GENERATION_FAILED,
        ErrorCode.SEND_FAILED,
      ]

      codes.forEach((code) => {
        const result = getErrorMessage(code)
        expect(result.title).toBeTruthy()
        expect(result.message).toBeTruthy()
        expect(result.severity).toBeTruthy()
      })
    })

    // AC2: Each error proposes a concrete action
    it('includes action for errors that support it (AC2)', () => {
      const codesWithActions = [
        ErrorCode.NETWORK_OFFLINE,
        ErrorCode.CONNECTION_FAILED,
        ErrorCode.AUTH_TOKEN_EXPIRED,
        ErrorCode.SYNC_RATE_LIMITED,
        ErrorCode.DRAFT_GENERATION_FAILED,
        ErrorCode.SEND_FAILED,
      ]

      codesWithActions.forEach((code) => {
        const result = getErrorMessage(code)
        expect(result.action).toBeDefined()
        expect(result.action?.label).toBeTruthy()
        expect(result.action?.type).toBeTruthy()
      })
    })

    // AC3: No technical jargon
    it('does not contain technical jargon (AC3)', () => {
      const allCodes = Object.values(ErrorCode)

      allCodes.forEach((code) => {
        const result = getErrorMessage(code)
        // Should not contain HTTP codes or technical terms in user-facing text
        expect(result.title).not.toMatch(/\b(HTTP|500|404|401|403|503)\b/)
        expect(result.message).not.toMatch(/\b(HTTP|stack trace|exception|null|undefined)\b/i)
      })
    })

    // AC4: Contextual errors
    it('provides contextual error messages (AC4)', () => {
      const networkOffline = getErrorMessage(ErrorCode.NETWORK_OFFLINE)
      expect(networkOffline.title).toBe('Pas de connexion Internet')

      const gmailQuota = getErrorMessage(ErrorCode.GMAIL_QUOTA_EXCEEDED)
      expect(gmailQuota.title).toContain('Gmail')

      const llmTimeout = getErrorMessage(ErrorCode.LLM_TIMEOUT)
      expect(llmTimeout.title.toLowerCase()).toContain('ia')
    })
  })

  describe('fromHttpStatus', () => {
    it('maps 401 to UNAUTHORIZED', () => {
      expect(fromHttpStatus(401)).toBe(ErrorCode.UNAUTHORIZED)
    })

    it('maps 403 to FORBIDDEN', () => {
      expect(fromHttpStatus(403)).toBe(ErrorCode.FORBIDDEN)
    })

    it('maps 404 to NOT_FOUND', () => {
      expect(fromHttpStatus(404)).toBe(ErrorCode.NOT_FOUND)
    })

    it('maps 408 to TIMEOUT', () => {
      expect(fromHttpStatus(408)).toBe(ErrorCode.TIMEOUT)
    })

    it('maps 429 to SYNC_RATE_LIMITED', () => {
      expect(fromHttpStatus(429)).toBe(ErrorCode.SYNC_RATE_LIMITED)
    })

    it('maps 500 to SERVER_ERROR', () => {
      expect(fromHttpStatus(500)).toBe(ErrorCode.SERVER_ERROR)
    })

    it('maps 502, 503, 504 to SERVICE_UNAVAILABLE', () => {
      expect(fromHttpStatus(502)).toBe(ErrorCode.SERVICE_UNAVAILABLE)
      expect(fromHttpStatus(503)).toBe(ErrorCode.SERVICE_UNAVAILABLE)
      expect(fromHttpStatus(504)).toBe(ErrorCode.SERVICE_UNAVAILABLE)
    })

    it('maps unknown status to UNKNOWN', () => {
      expect(fromHttpStatus(418)).toBe(ErrorCode.UNKNOWN)
    })
  })

  describe('fromNetworkError', () => {
    it('detects connection refused', () => {
      const error = new TypeError('Failed to fetch')
      expect(fromNetworkError(error)).toBe(ErrorCode.CONNECTION_FAILED)
    })

    it('detects timeout errors by name', () => {
      const error = new Error('Request timeout')
      error.name = 'AbortError'
      expect(fromNetworkError(error)).toBe(ErrorCode.TIMEOUT)
    })

    it('detects timeout errors by message', () => {
      const error = new Error('Request timed out')
      expect(fromNetworkError(error)).toBe(ErrorCode.TIMEOUT)
    })

    it('detects offline errors', () => {
      const error = new Error('Network offline')
      expect(fromNetworkError(error)).toBe(ErrorCode.NETWORK_OFFLINE)
    })

    it('detects DNS errors', () => {
      const error = new Error('Could not resolve hostname')
      expect(fromNetworkError(error)).toBe(ErrorCode.NETWORK_OFFLINE)
    })

    it('returns NETWORK_ERROR for other errors', () => {
      const error = new Error('Some network issue')
      expect(fromNetworkError(error)).toBe(ErrorCode.NETWORK_ERROR)
    })
  })

  describe('fromApiError', () => {
    it('handles TypeError as network error', () => {
      const error = new TypeError('Failed to fetch')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.CONNECTION_FAILED)
    })

    it('detects token expired errors', () => {
      const error = new Error('Token expired')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.AUTH_TOKEN_EXPIRED)
    })

    it('detects Gmail quota errors', () => {
      const error = new Error('Gmail quota exceeded')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.GMAIL_QUOTA_EXCEEDED)
    })

    it('detects Outlook quota errors', () => {
      const error = new Error('Microsoft rate limit exceeded')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.OUTLOOK_QUOTA_EXCEEDED)
    })

    it('detects LLM errors', () => {
      const error = new Error('Claude API error')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.LLM_UNAVAILABLE)
    })

    it('detects LLM timeout', () => {
      const error = new Error('Claude timeout')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.LLM_TIMEOUT)
    })

    it('uses context for draft errors', () => {
      const error = new Error('Some error')
      const result = fromApiError(error, 'draft')

      expect(result.code).toBe(ErrorCode.DRAFT_GENERATION_FAILED)
    })

    it('uses context for send errors', () => {
      const error = new Error('Some error')
      const result = fromApiError(error, 'send')

      expect(result.code).toBe(ErrorCode.SEND_FAILED)
    })

    it('detects invalid recipient', () => {
      const error = new Error('Invalid recipient address')
      const result = fromApiError(error, 'send')

      expect(result.code).toBe(ErrorCode.INVALID_RECIPIENT)
    })

    it('returns UNKNOWN for unrecognized errors', () => {
      const error = new Error('Some random error')
      const result = fromApiError(error)

      expect(result.code).toBe(ErrorCode.UNKNOWN)
    })
  })

  describe('isOnline', () => {
    it('returns boolean', () => {
      expect(typeof isOnline()).toBe('boolean')
    })
  })

  describe('createOfflineError', () => {
    it('creates NETWORK_OFFLINE error', () => {
      const result = createOfflineError()

      expect(result.code).toBe(ErrorCode.NETWORK_OFFLINE)
      expect(result.title).toBe('Pas de connexion Internet')
    })
  })

  describe('HumanError interface', () => {
    it('has all required fields', () => {
      const result: HumanError = getErrorMessage(ErrorCode.CONNECTION_FAILED)

      expect(result).toHaveProperty('code')
      expect(result).toHaveProperty('title')
      expect(result).toHaveProperty('message')
      expect(result).toHaveProperty('solution')
      expect(result).toHaveProperty('severity')
      expect(['error', 'warning', 'info']).toContain(result.severity)
    })

    // AC6: Action buttons when possible
    it('includes action with label and type (AC6)', () => {
      const result = getErrorMessage(ErrorCode.CONNECTION_FAILED)

      expect(result.action).toBeDefined()
      expect(result.action?.label).toBe('Réessayer la connexion')
      expect(result.action?.type).toBe('retry')
    })

    it('includes delayMinutes for wait actions', () => {
      const result = getErrorMessage(ErrorCode.SYNC_RATE_LIMITED)

      expect(result.action?.type).toBe('wait')
      expect(result.action?.delayMinutes).toBe(5)
    })
  })
})
