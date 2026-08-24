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
import { monthlySummaryService, usageStatsService, referralService, trialService } from '../services/subscription'

describe('MonthlySummaryService (Story 9-8)', () => {
  beforeEach(() => {
    localStorage.clear()
    monthlySummaryService.resetHistory()
    usageStatsService.resetStats()
    referralService.resetReferral()
    trialService.resetTrial()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('getCurrentMonthStats (AC1)', () => {
    it('returns current month stats', () => {
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()

      const stats = monthlySummaryService.getCurrentMonthStats()

      expect(stats.emailsProcessed).toBe(2)
      expect(stats.draftsGenerated).toBe(1)
      expect(stats.timeSavedMinutes).toBe(5)
      expect(stats.month).toMatch(/^\d{4}-\d{2}$/)
    })

    it('returns zeros when no stats recorded', () => {
      const stats = monthlySummaryService.getCurrentMonthStats()

      expect(stats.emailsProcessed).toBe(0)
      expect(stats.draftsGenerated).toBe(0)
      expect(stats.timeSavedMinutes).toBe(0)
    })
  })

  describe('getMonthLabel', () => {
    it('returns month name with year', () => {
      expect(monthlySummaryService.getMonthLabel('2026-01')).toBe('January 2026')
      expect(monthlySummaryService.getMonthLabel('2026-06')).toBe('June 2026')
      expect(monthlySummaryService.getMonthLabel('2026-12')).toBe('December 2026')
    })
  })

  describe('saveMonthlySnapshot', () => {
    it('saves snapshot to history', () => {
      const snapshot = {
        month: '2025-12',
        emailsProcessed: 50,
        draftsGenerated: 30,
        timeSavedMinutes: 150,
      }

      monthlySummaryService.saveMonthlySnapshot(snapshot)
      const history = monthlySummaryService.getHistory()

      expect(history).toHaveLength(1)
      expect(history[0]).toEqual(snapshot)
    })

    it('updates existing month instead of duplicating', () => {
      const snapshot1 = {
        month: '2025-12',
        emailsProcessed: 50,
        draftsGenerated: 30,
        timeSavedMinutes: 150,
      }
      const snapshot2 = {
        month: '2025-12',
        emailsProcessed: 60,
        draftsGenerated: 40,
        timeSavedMinutes: 200,
      }

      monthlySummaryService.saveMonthlySnapshot(snapshot1)
      monthlySummaryService.saveMonthlySnapshot(snapshot2)
      const history = monthlySummaryService.getHistory()

      expect(history).toHaveLength(1)
      expect(history[0].emailsProcessed).toBe(60)
    })

    it('keeps only last 12 months', () => {
      for (let i = 1; i <= 15; i++) {
        const month = `2025-${String(i).padStart(2, '0')}`
        monthlySummaryService.saveMonthlySnapshot({
          month,
          emailsProcessed: i * 10,
          draftsGenerated: i * 5,
          timeSavedMinutes: i * 25,
        })
      }

      const history = monthlySummaryService.getHistory()
      expect(history).toHaveLength(12)
      expect(history[0].month).toBe('2025-04') // First 3 should be trimmed
    })
  })

  describe('getPreviousMonthStats (AC2)', () => {
    it('returns null when no history', () => {
      const stats = monthlySummaryService.getPreviousMonthStats()
      expect(stats).toBeNull()
    })

    it('returns previous month from history', () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-02-15T12:00:00Z'))

      const previousSnapshot = {
        month: '2026-01',
        emailsProcessed: 45,
        draftsGenerated: 32,
        timeSavedMinutes: 160,
      }
      monthlySummaryService.saveMonthlySnapshot(previousSnapshot)

      const stats = monthlySummaryService.getPreviousMonthStats()
      expect(stats).toEqual(previousSnapshot)
    })
  })

  describe('getComparison (AC2)', () => {
    it('returns comparison with no previous data', () => {
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()

      const comparison = monthlySummaryService.getComparison()

      expect(comparison.current.draftsGenerated).toBe(2)
      expect(comparison.previous).toBeNull()
      expect(comparison.emailsChange).toBeNull()
      expect(comparison.draftsChange).toBeNull()
    })

    it('calculates percentage changes correctly', () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-02-15T12:00:00Z'))

      // Save previous month data
      monthlySummaryService.saveMonthlySnapshot({
        month: '2026-01',
        emailsProcessed: 50,
        draftsGenerated: 20,
        timeSavedMinutes: 100,
      })

      // Record current month data
      for (let i = 0; i < 60; i++) usageStatsService.recordEmailProcessed()
      for (let i = 0; i < 25; i++) usageStatsService.recordDraftGenerated()

      const comparison = monthlySummaryService.getComparison()

      expect(comparison.emailsChange).toBe(20) // 60 vs 50 = +20%
      expect(comparison.draftsChange).toBe(25) // 25 vs 20 = +25%
      expect(comparison.timeChange).toBe(25) // 125 vs 100 = +25%
    })

    it('handles 100% increase when previous was 0', () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-02-15T12:00:00Z'))

      monthlySummaryService.saveMonthlySnapshot({
        month: '2026-01',
        emailsProcessed: 0,
        draftsGenerated: 0,
        timeSavedMinutes: 0,
      })

      usageStatsService.recordDraftGenerated()

      const comparison = monthlySummaryService.getComparison()
      expect(comparison.draftsChange).toBe(100)
    })
  })

  describe('getChartData (AC3)', () => {
    it('returns last 6 months by default', () => {
      // Add some history
      for (let i = 1; i <= 8; i++) {
        monthlySummaryService.saveMonthlySnapshot({
          month: `2025-${String(i).padStart(2, '0')}`,
          emailsProcessed: i * 10,
          draftsGenerated: i * 5,
          timeSavedMinutes: i * 25,
        })
      }

      const chartData = monthlySummaryService.getChartData(6)
      expect(chartData.length).toBeLessThanOrEqual(6)
    })

    it('includes current month in chart data', () => {
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()

      const chartData = monthlySummaryService.getChartData()
      expect(chartData.length).toBeGreaterThanOrEqual(1)

      const lastEntry = chartData[chartData.length - 1]
      expect(lastEntry.draftsGenerated).toBe(2)
    })
  })

  describe('getShareMessage (AC4)', () => {
    it('generates share message with stats', async () => {
      await trialService.startTrial('test@example.com')
      referralService.getReferralCode()

      usageStatsService.recordEmailProcessed()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()

      const message = monthlySummaryService.getShareMessage()

      expect(message).toContain('My month with Agentys')
      expect(message).toContain('2 emails processed')
      expect(message).toContain('1 drafts generated')
      expect(message).toContain('agentys.app')
    })

    it('includes referral link if available', async () => {
      await trialService.startTrial('test@example.com')
      const code = referralService.getReferralCode()

      const message = monthlySummaryService.getShareMessage()

      expect(message).toContain(`ref=${code}`)
    })

    it('uses default link if no referral', () => {
      const message = monthlySummaryService.getShareMessage()
      expect(message).toContain('https://agentys.app')
    })
  })

  describe('resetHistory', () => {
    it('clears all history', () => {
      monthlySummaryService.saveMonthlySnapshot({
        month: '2025-12',
        emailsProcessed: 50,
        draftsGenerated: 30,
        timeSavedMinutes: 150,
      })

      expect(monthlySummaryService.getHistory()).toHaveLength(1)

      monthlySummaryService.resetHistory()

      expect(monthlySummaryService.getHistory()).toHaveLength(0)
    })
  })
})

describe('UsageStatsService monthly archiving (Story 9-8)', () => {
  beforeEach(() => {
    localStorage.clear()
    usageStatsService.resetStats()
    monthlySummaryService.resetHistory()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('archives stats when month changes', () => {
    vi.useFakeTimers()

    // Set to January 15
    vi.setSystemTime(new Date('2026-01-15T12:00:00Z'))
    usageStatsService.recordEmailProcessed()
    usageStatsService.recordEmailProcessed()
    usageStatsService.recordDraftGenerated()

    // Move to February 1
    vi.setSystemTime(new Date('2026-02-01T12:00:00Z'))

    // This should trigger archiving
    usageStatsService.recordEmailProcessed()

    // Check that January was archived
    const history = monthlySummaryService.getHistory()
    expect(history).toHaveLength(1)
    expect(history[0].month).toBe('2026-01')
    expect(history[0].emailsProcessed).toBe(2)
    expect(history[0].draftsGenerated).toBe(1)
  })

  it('does not archive if no data in previous month', () => {
    vi.useFakeTimers()

    // Set to January 15 (no data recorded)
    vi.setSystemTime(new Date('2026-01-15T12:00:00Z'))
    usageStatsService.getEmailsProcessed() // Initialize without recording

    // Move to February 1
    vi.setSystemTime(new Date('2026-02-01T12:00:00Z'))
    usageStatsService.recordEmailProcessed()

    // Check that nothing was archived (no data to archive)
    const history = monthlySummaryService.getHistory()
    expect(history).toHaveLength(0)
  })
})
