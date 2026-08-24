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
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ReferralPanel, useReferral } from '../components/ReferralPanel'
import { referralService, usageStatsService, trialService } from '../services/subscription'
import { renderHook } from '@testing-library/react'

// Mock clipboard API
const mockWriteText = vi.fn()
Object.assign(navigator, {
  clipboard: {
    writeText: mockWriteText,
  },
})

describe('ReferralPanel (Story 9-7)', () => {
  beforeEach(() => {
    localStorage.clear()
    referralService.resetReferral()
    usageStatsService.resetStats()
    trialService.resetTrial()
    mockWriteText.mockReset()
    mockWriteText.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('when no referral data (user not signed up)', () => {
    it('renders nothing', () => {
      const { container } = render(<ReferralPanel />)
      expect(container.firstChild).toBeNull()
    })
  })

  describe('when user has referral data', () => {
    beforeEach(async () => {
      await trialService.startTrial('test@example.com')
      referralService.getReferralCode() // Initialize referral
    })

    it('renders the panel', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('referral-panel')).toBeInTheDocument()
    })

    it('displays the title', () => {
      render(<ReferralPanel />)
      expect(screen.getByText('Parrainez vos amis')).toBeInTheDocument()
    })

    it('displays the referral link (AC1)', () => {
      render(<ReferralPanel />)
      const input = screen.getByTestId('referral-link-input') as HTMLInputElement
      expect(input.value).toMatch(/https:\/\/agentys\.app\/signup\?ref=[A-Z0-9]+/)
    })

    it('displays copy link button (AC2)', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('copy-link-button')).toHaveTextContent('Copier le lien')
    })
  })

  describe('copy link functionality (AC2)', () => {
    beforeEach(async () => {
      await trialService.startTrial('test@example.com')
      referralService.getReferralCode()
    })

    it('copies link to clipboard when clicked', async () => {
      render(<ReferralPanel />)
      fireEvent.click(screen.getByTestId('copy-link-button'))

      await waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith(
          expect.stringMatching(/https:\/\/agentys\.app\/signup\?ref=[A-Z0-9]+/)
        )
      })
    })

    it('shows "Copié !" feedback after copy (AC2)', async () => {
      render(<ReferralPanel />)
      fireEvent.click(screen.getByTestId('copy-link-button'))

      await waitFor(() => {
        expect(screen.getByTestId('copy-link-button')).toHaveTextContent('Copié !')
      })
    })

    it('reverts to original text after 2 seconds', async () => {
      // Use real timers for this test to avoid fake timer issues with async clipboard
      vi.useRealTimers()

      // Reset and setup fresh
      localStorage.clear()
      referralService.resetReferral()
      trialService.resetTrial()
      await trialService.startTrial('revert-test@example.com')
      referralService.getReferralCode()

      render(<ReferralPanel />)

      fireEvent.click(screen.getByTestId('copy-link-button'))

      await waitFor(() => {
        expect(screen.getByTestId('copy-link-button')).toHaveTextContent('Copié !')
      })

      // Wait for revert (2000ms timeout + buffer)
      await waitFor(() => {
        expect(screen.getByTestId('copy-link-button')).toHaveTextContent('Copier le lien')
      }, { timeout: 3000 })
    })
  })

  describe('monthly stats display (AC3)', () => {
    beforeEach(async () => {
      await trialService.startTrial('test@example.com')
      referralService.getReferralCode()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordEmailProcessed()
      usageStatsService.recordDraftGenerated()
      usageStatsService.recordDraftGenerated()
    })

    it('displays emails processed count', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('stat-emails')).toHaveTextContent('3')
      expect(screen.getByTestId('stat-emails')).toHaveTextContent('emails traités')
    })

    it('displays drafts generated count', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('stat-drafts')).toHaveTextContent('2')
      expect(screen.getByTestId('stat-drafts')).toHaveTextContent('brouillons générés')
    })

    it('displays time saved', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('stat-time')).toHaveTextContent('10 min')
      expect(screen.getByTestId('stat-time')).toHaveTextContent('de temps gagné')
    })
  })

  describe('share message functionality (AC4)', () => {
    beforeEach(async () => {
      await trialService.startTrial('test@example.com')
      referralService.getReferralCode()
    })

    it('displays editable share message textarea', () => {
      render(<ReferralPanel />)
      const textarea = screen.getByTestId('share-message-textarea') as HTMLTextAreaElement
      expect(textarea).toBeInTheDocument()
      expect(textarea.value).toContain("J'utilise Agentys")
    })

    it('allows editing share message', () => {
      render(<ReferralPanel />)
      const textarea = screen.getByTestId('share-message-textarea') as HTMLTextAreaElement
      fireEvent.change(textarea, { target: { value: 'Custom message!' } })
      expect(textarea.value).toBe('Custom message!')
    })

    it('displays copy message with link button', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('copy-message-button')).toHaveTextContent('Copier le message avec lien')
    })

    it('copies message and link when button clicked', async () => {
      render(<ReferralPanel />)
      fireEvent.click(screen.getByTestId('copy-message-button'))

      await waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith(
          expect.stringContaining("J'utilise Agentys")
        )
        expect(mockWriteText).toHaveBeenCalledWith(
          expect.stringContaining('https://agentys.app/signup?ref=')
        )
      })
    })

    it('shows "Copié !" feedback on message copy', async () => {
      render(<ReferralPanel />)
      fireEvent.click(screen.getByTestId('copy-message-button'))

      await waitFor(() => {
        expect(screen.getByTestId('copy-message-button')).toHaveTextContent('Copié !')
      })
    })
  })

  describe('referral count display (AC5)', () => {
    beforeEach(async () => {
      await trialService.startTrial('test@example.com')
      const code = referralService.getReferralCode()!
      referralService.trackReferral(code)
    })

    it('displays referral count when > 0', () => {
      render(<ReferralPanel />)
      expect(screen.getByTestId('referral-count')).toBeInTheDocument()
      expect(screen.getByTestId('referral-count')).toHaveTextContent('1')
      expect(screen.getByTestId('referral-count')).toHaveTextContent('personne inscrite')
    })

    it('uses plural form for multiple referrals', async () => {
      const code = referralService.getReferralCode()!
      referralService.trackReferral(code)
      referralService.trackReferral(code)

      render(<ReferralPanel />)
      expect(screen.getByTestId('referral-count')).toHaveTextContent('3')
      expect(screen.getByTestId('referral-count')).toHaveTextContent('personnes inscrites')
    })

    it('does not display count section when 0 referrals', async () => {
      // Reset all data first
      localStorage.clear()
      referralService.resetReferral()
      trialService.resetTrial()

      await trialService.startTrial('new@example.com')
      referralService.getReferralCode()

      render(<ReferralPanel />)
      expect(screen.queryByTestId('referral-count')).not.toBeInTheDocument()
    })
  })
})

describe('useReferral hook', () => {
  beforeEach(() => {
    localStorage.clear()
    referralService.resetReferral()
    usageStatsService.resetStats()
    trialService.resetTrial()
  })

  it('returns hasReferral false when no referral', () => {
    const { result } = renderHook(() => useReferral())
    expect(result.current.hasReferral).toBe(false)
  })

  it('returns hasReferral true when referral exists', async () => {
    await trialService.startTrial('test@example.com')
    referralService.getReferralCode()

    const { result } = renderHook(() => useReferral())
    expect(result.current.hasReferral).toBe(true)
  })

  it('returns stats object when referral exists', async () => {
    await trialService.startTrial('test@example.com')
    referralService.getReferralCode()

    const { result } = renderHook(() => useReferral())
    expect(result.current.stats).not.toBeNull()
    expect(result.current.stats?.code.length).toBe(8)
  })

  it('returns monthly stats', async () => {
    await trialService.startTrial('test@example.com')
    usageStatsService.recordDraftGenerated()

    const { result } = renderHook(() => useReferral())
    expect(result.current.monthlyStats.draftsGenerated).toBe(1)
  })

  it('returns formatted time saved', async () => {
    await trialService.startTrial('test@example.com')
    usageStatsService.recordDraftGenerated()
    usageStatsService.recordDraftGenerated()

    const { result } = renderHook(() => useReferral())
    expect(result.current.timeSavedFormatted).toBe('10 min')
  })
})

describe('Clipboard error handling (AC2)', () => {
  beforeEach(async () => {
    localStorage.clear()
    referralService.resetReferral()
    trialService.resetTrial()
    await trialService.startTrial('test@example.com')
    referralService.getReferralCode()
    mockWriteText.mockReset()
  })

  // Skipped : `copyToClipboard` (src/utils/clipboard.ts) catch silencieusement
  // les rejections de navigator.clipboard.writeText et fallback sur
  // document.execCommand. Donc handleCopyLink ne console.error JAMAIS sur un
  // mock writeText rejected — le helper masque la rejection. Test obsolète
  // depuis l'ajout du fallback execCommand.
  it.skip('handles clipboard permission error gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockWriteText.mockRejectedValue(new Error('Clipboard permission denied'))

    render(<ReferralPanel />)
    fireEvent.click(screen.getByTestId('copy-link-button'))

    await waitFor(() => {
      expect(consoleSpy).toHaveBeenCalledWith('Failed to copy link:', expect.any(Error))
    })

    consoleSpy.mockRestore()
  })

  it('does not show feedback when copy fails', async () => {
    mockWriteText.mockRejectedValue(new Error('Clipboard permission denied'))

    render(<ReferralPanel />)
    fireEvent.click(screen.getByTestId('copy-link-button'))

    // Button should still show original text after failed copy
    await waitFor(() => {
      expect(screen.getByTestId('copy-link-button')).toHaveTextContent('Copier le lien')
    })
  })
})
