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

import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import {
  createDraftReminderService,
  type DraftReminderService,
  type PendingDraft,
  DEFAULT_REMINDER_DELAY_MS,
} from '../services/draftReminder'

describe('DraftReminderService', () => {
  let service: DraftReminderService
  let mockNotifyCallback: Mock<(draft: PendingDraft) => void>
  let now: number

  beforeEach(() => {
    vi.useFakeTimers()
    now = Date.now()
    vi.setSystemTime(now)
    mockNotifyCallback = vi.fn()
    service = createDraftReminderService({
      onReminder: mockNotifyCallback,
    })
  })

  afterEach(() => {
    service.stop()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('trackDraft', () => {
    it('ajoute un brouillon en attente', () => {
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      const pending = service.getPendingDrafts()
      expect(pending).toHaveLength(1)
      expect(pending[0].emailId).toBe('email-1')
      expect(pending[0].draftId).toBe('draft-1')
    })

    it('stocke le timestamp de creation', () => {
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      const pending = service.getPendingDrafts()
      expect(pending[0].createdAt).toBe(now)
    })

    it('ne duplique pas un brouillon existant', () => {
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      expect(service.getPendingDrafts()).toHaveLength(1)
    })
  })

  describe('untrackDraft', () => {
    it('retire un brouillon valide', () => {
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      service.untrackDraft('draft-1')

      expect(service.getPendingDrafts()).toHaveLength(0)
    })

    it('ne fait rien si le brouillon nexiste pas', () => {
      service.untrackDraft('non-existent')
      expect(service.getPendingDrafts()).toHaveLength(0)
    })
  })

  describe('checkReminders', () => {
    it('notifie pour brouillon en attente depuis X heures', () => {
      const twoHoursAgo = now - DEFAULT_REMINDER_DELAY_MS - 1000
      vi.setSystemTime(twoHoursAgo)

      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      vi.setSystemTime(now)
      service.checkReminders()

      expect(mockNotifyCallback).toHaveBeenCalledWith(
        expect.objectContaining({
          emailId: 'email-1',
          sender: 'client@example.com',
          draftId: 'draft-1',
        })
      )
    })

    it('ne notifie pas pour brouillon recent', () => {
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      service.checkReminders()

      expect(mockNotifyCallback).not.toHaveBeenCalled()
    })

    it('ne notifie quune fois par brouillon', () => {
      const twoHoursAgo = now - DEFAULT_REMINDER_DELAY_MS - 1000
      vi.setSystemTime(twoHoursAgo)

      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      vi.setSystemTime(now)
      service.checkReminders()
      service.checkReminders()

      expect(mockNotifyCallback).toHaveBeenCalledTimes(1)
    })

    it('notifie plusieurs brouillons en attente', () => {
      const twoHoursAgo = now - DEFAULT_REMINDER_DELAY_MS - 1000
      vi.setSystemTime(twoHoursAgo)

      service.trackDraft({
        emailId: 'email-1',
        sender: 'client1@example.com',
        draftId: 'draft-1',
      })
      service.trackDraft({
        emailId: 'email-2',
        sender: 'client2@example.com',
        draftId: 'draft-2',
      })

      vi.setSystemTime(now)
      service.checkReminders()

      expect(mockNotifyCallback).toHaveBeenCalledTimes(2)
    })
  })

  describe('start/stop', () => {
    it('demarre la verification periodique', () => {
      const twoHoursAgo = now - DEFAULT_REMINDER_DELAY_MS - 1000
      vi.setSystemTime(twoHoursAgo)

      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      vi.setSystemTime(now)
      service.start()

      vi.advanceTimersByTime(60000)
      expect(mockNotifyCallback).toHaveBeenCalled()
    })

    it('arrete la verification periodique', () => {
      service.start()
      service.stop()

      vi.setSystemTime(now - DEFAULT_REMINDER_DELAY_MS - 1000)
      service.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      vi.setSystemTime(now)
      vi.advanceTimersByTime(60000)

      expect(mockNotifyCallback).not.toHaveBeenCalled()
    })
  })

  describe('configuration', () => {
    it('permet de configurer le delai de rappel', () => {
      const oneHourMs = 60 * 60 * 1000
      const customService = createDraftReminderService({
        onReminder: mockNotifyCallback,
        reminderDelayMs: oneHourMs,
      })

      const oneHourAgo = now - oneHourMs - 1000
      vi.setSystemTime(oneHourAgo)

      customService.trackDraft({
        emailId: 'email-1',
        sender: 'client@example.com',
        draftId: 'draft-1',
      })

      vi.setSystemTime(now)
      customService.checkReminders()

      expect(mockNotifyCallback).toHaveBeenCalled()
      customService.stop()
    })
  })
})
