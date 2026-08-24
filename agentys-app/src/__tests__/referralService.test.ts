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

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { referralService, usageStatsService, trialService } from '../services/subscription'

describe('ReferralService (Story 9-7 AC1, AC5)', () => {
  beforeEach(() => {
    localStorage.clear()
    referralService.resetReferral()
    trialService.resetTrial()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('generateReferralCode (AC1)', () => {
    it('generates a code from email', () => {
      const code = referralService.generateReferralCode('test@example.com')
      expect(code).toBeDefined()
      expect(code.length).toBe(8)
      expect(code).toMatch(/^[A-Z0-9]+$/)
    })

    it('returns same code for same email', () => {
      const code1 = referralService.generateReferralCode('test@example.com')
      const code2 = referralService.generateReferralCode('test@example.com')
      expect(code1).toBe(code2)
    })

    it('generates different codes for different emails', () => {
      const code1 = referralService.generateReferralCode('user1@example.com')
      referralService.resetReferral()
      const code2 = referralService.generateReferralCode('user2@example.com')
      expect(code1).not.toBe(code2)
    })

    it('throws error if email is empty', () => {
      expect(() => referralService.generateReferralCode('')).toThrow('Email is required')
    })

    it('stores code in localStorage', () => {
      referralService.generateReferralCode('test@example.com')
      expect(localStorage.getItem('agentys_referral_code')).toBeDefined()
    })

    it('initializes referrals count to 0', () => {
      referralService.generateReferralCode('test@example.com')
      expect(localStorage.getItem('agentys_referrals_count')).toBe('0')
    })
  })

  describe('getReferralCode', () => {
    it('returns null if no code exists and no trial email', () => {
      const code = referralService.getReferralCode()
      expect(code).toBeNull()
    })

    it('returns existing code if available', () => {
      referralService.generateReferralCode('test@example.com')
      const code = referralService.getReferralCode()
      expect(code).toBeDefined()
      expect(code?.length).toBe(8)
    })

    it('generates code from trial email if no code exists', async () => {
      await trialService.startTrial('trial@example.com')
      const code = referralService.getReferralCode()
      expect(code).toBeDefined()
      expect(code?.length).toBe(8)
    })
  })

  describe('getReferralLink (AC1)', () => {
    it('returns null if no referral code', () => {
      const link = referralService.getReferralLink()
      expect(link).toBeNull()
    })

    it('returns correct link format', () => {
      referralService.generateReferralCode('test@example.com')
      const link = referralService.getReferralLink()
      expect(link).toMatch(/^https:\/\/agentys\.app\/signup\?ref=[A-Z0-9]{8}$/)
    })

    it('includes the referral code in URL', () => {
      const code = referralService.generateReferralCode('test@example.com')
      const link = referralService.getReferralLink()
      expect(link).toContain(`ref=${code}`)
    })
  })

  describe('trackReferral (AC5)', () => {
    it('increments count for matching code', () => {
      const code = referralService.generateReferralCode('test@example.com')
      expect(referralService.getReferralsCount()).toBe(0)

      referralService.trackReferral(code)
      expect(referralService.getReferralsCount()).toBe(1)

      referralService.trackReferral(code)
      expect(referralService.getReferralsCount()).toBe(2)
    })

    it('does not increment for non-matching code', () => {
      referralService.generateReferralCode('test@example.com')
      referralService.trackReferral('WRONGCODE')
      expect(referralService.getReferralsCount()).toBe(0)
    })
  })

  describe('getReferralsCount (AC5)', () => {
    it('returns 0 when no referrals tracked', () => {
      referralService.generateReferralCode('test@example.com')
      expect(referralService.getReferralsCount()).toBe(0)
    })

    it('returns correct count after tracking', () => {
      const code = referralService.generateReferralCode('test@example.com')
      referralService.trackReferral(code)
      referralService.trackReferral(code)
      referralService.trackReferral(code)
      expect(referralService.getReferralsCount()).toBe(3)
    })
  })

  describe('getReferralStats (AC1, AC5)', () => {
    it('returns null if no referral code', () => {
      const stats = referralService.getReferralStats()
      expect(stats).toBeNull()
    })

    it('returns complete stats object', () => {
      const code = referralService.generateReferralCode('test@example.com')
      referralService.trackReferral(code)

      const stats = referralService.getReferralStats()
      expect(stats).toEqual({
        code,
        link: `https://agentys.app/signup?ref=${code}`,
        referralsCount: 1,
      })
    })
  })

  describe('resetReferral', () => {
    it('clears all referral data', () => {
      referralService.generateReferralCode('test@example.com')
      referralService.resetReferral()

      expect(localStorage.getItem('agentys_referral_code')).toBeNull()
      expect(localStorage.getItem('agentys_referrals_count')).toBeNull()
      expect(referralService.getReferralCode()).toBeNull()
    })
  })
})

describe('UsageStatsService (Story 9-7 AC3)', () => {
  beforeEach(() => {
    localStorage.clear()
    usageStatsService.resetStats()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('recordEmailProcessed', () => {
    it('increments email count', () => {
      expect(usageStatsService.getEmailsProcessed()).toBe(0)
      usageStatsService.recordEmailProcessed()
      expect(usageStatsService.getEmailsProcessed()).toBe(1)
      usageStatsService.recordEmailProcessed()
      expect(usageStatsService.getEmailsProcessed()).toBe(2)
    })
  })

  describe('recordDraftGenerated', () => {
    it('increments draft count', () => {
      expect(usageStatsService.getDraftsGenerated()).toBe(0)
      usageStatsService.recordDraftGenerated()
      expect(usageStatsService.getDraftsGenerated()).toBe(1)
      usageStatsService.recordDraftGenerated()
      expect(usageStatsService.getDraftsGenerated()).toBe(2)
    })
  })

  describe('getMonthlyStats (AC3)', () => {
    it('returns stats object with all fields', () => {
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()

      const stats = usageStatsService.getMonthlyStats()

      expect(stats.emailsProcessed).toBe(2)
      expect(stats.draftsGenerated).toBe(1)
      expect(stats.timeSavedMinutes).toBe(5) // 1 draft * 5 minutes
      expect(stats.periodStart).toMatch(/^\d{4}-\d{2}-01$/)
    })

    it('calculates time saved correctly (5 min per draft)', () => {
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()

      const stats = usageStatsService.getMonthlyStats()
      expect(stats.timeSavedMinutes).toBe(20) // 4 drafts * 5 minutes
    })
  })

  describe('getTimeSavedFormatted', () => {
    it('returns minutes only when < 60 min', () => {
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()
      expect(usageStatsService.getTimeSavedFormatted()).toBe('10 min')
    })

    it('returns hours and minutes when >= 60 min', () => {
      // Generate 15 drafts = 75 minutes = 1h15
      for (let i = 0; i < 15; i++) {
        usageStatsService.recordDraftGenerated()
      }
      expect(usageStatsService.getTimeSavedFormatted()).toBe('1h15')
    })

    it('returns hours only when minutes are 0', () => {
      // Generate 12 drafts = 60 minutes = 1h
      for (let i = 0; i < 12; i++) {
        usageStatsService.recordDraftGenerated()
      }
      expect(usageStatsService.getTimeSavedFormatted()).toBe('1h')
    })

    it('returns 0 min when no drafts', () => {
      expect(usageStatsService.getTimeSavedFormatted()).toBe('0 min')
    })
  })

  describe('monthly reset', () => {
    it('resets stats when month changes', () => {
      vi.useFakeTimers()

      // Set to January 15
      vi.setSystemTime(new Date('2026-01-15T12:00:00Z'))
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()

      expect(usageStatsService.getEmailsProcessed()).toBe(1)
      expect(usageStatsService.getDraftsGenerated()).toBe(1)

      // Move to February 1
      vi.setSystemTime(new Date('2026-02-01T12:00:00Z'))

      // Next call should trigger reset
      expect(usageStatsService.getEmailsProcessed()).toBe(0)
      expect(usageStatsService.getDraftsGenerated()).toBe(0)
    })

    it('does not reset within same month', () => {
      vi.useFakeTimers()

      // Set to January 15
      vi.setSystemTime(new Date('2026-01-15T12:00:00Z'))
      usageStatsService.recordDraftGenerated()

      // Move to January 25 (same month)
      vi.setSystemTime(new Date('2026-01-25T12:00:00Z'))
      usageStatsService.recordDraftGenerated()

      expect(usageStatsService.getDraftsGenerated()).toBe(2)
    })
  })

  describe('resetStats', () => {
    it('clears all stats data', () => {
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()
      usageStatsService.resetStats()

      expect(localStorage.getItem('agentys_stats_emails_processed')).toBeNull()
      expect(localStorage.getItem('agentys_stats_drafts_generated')).toBeNull()
      expect(localStorage.getItem('agentys_stats_monthly_reset')).toBeNull()
    })
  })
})
