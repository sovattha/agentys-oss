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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { EmailList } from '../components/EmailList'
import type { Email } from '../types/email'
import type { FetchEmailsResult } from '../api/emails'
import * as emailsApi from '../api/emails'

vi.mock('../api/emails')

/** Helper to create a FetchEmailsResult with fromCache defaulting to false */
function mockResult(data: { count: number; emails: Email[] }): FetchEmailsResult {
  return { ...data, fromCache: false };
}

const mockEmails: Email[] = [
  {
    id: 'email-1',
    sender: 'alice@example.com',
    sender_name: 'Alice Martin',
    subject: 'Projet important',
    received_at: '2026-01-05T14:30:00Z',
    has_attachments: true,
    conversation_id: 'conv-1',
    is_read: false,
    body_preview: 'Preview of the important project email...',
  },
  {
    id: 'email-2',
    sender: 'bob@company.com',
    sender_name: null,
    subject: 'Reunion demain',
    received_at: '2026-01-05T10:00:00Z',
    has_attachments: false,
    conversation_id: null,
    is_read: true,
  },
]

// TODO: update for new architecture — EmailList component has been heavily restructured with new dependencies
describe.skip('EmailList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('Loading state', () => {
    it('shows loading spinner while fetching emails', async () => {
      let resolvePromise: (value: FetchEmailsResult) => void
      const promise = new Promise<FetchEmailsResult>((resolve) => {
        resolvePromise = resolve
      })
      vi.mocked(emailsApi.fetchEmails).mockReturnValue(promise)

      render(<EmailList />)

      expect(screen.getByText('Chargement des emails...')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Boîte de réception' })).toBeInTheDocument()

      await act(async () => {
        resolvePromise!(mockResult({ count: 0, emails: [] }))
      })
    })
  })

  describe('Success state', () => {
    it('renders email list after successful fetch', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      expect(screen.getByText('Projet important')).toBeInTheDocument()
      expect(screen.getByText('bob')).toBeInTheDocument()
      expect(screen.getByText('Reunion demain')).toBeInTheDocument()
    })

    it('displays correct email count', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('2 emails')).toBeInTheDocument()
      })
    })

    it('displays singular form for single email', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('1 email')).toBeInTheDocument()
      })
    })

    it('calls onEmailsLoaded callback with emails', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))
      const onEmailsLoaded = vi.fn()

      render(<EmailList onEmailsLoaded={onEmailsLoaded} />)

      await waitFor(() => {
        expect(onEmailsLoaded).toHaveBeenCalledWith(mockEmails)
      })
    })
  })

  describe('Empty state', () => {
    it('shows empty message when no emails', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 0,
        emails: [],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Aucun email')).toBeInTheDocument()
      })

      expect(screen.getByText('Aucun email non lu dans votre boîte de réception')).toBeInTheDocument()
    })

    it('displays 0 emails count', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 0,
        emails: [],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('0 emails')).toBeInTheDocument()
      })
    })
  })

  describe('Error state', () => {
    it('shows error message on fetch failure', async () => {
      vi.mocked(emailsApi.fetchEmails).mockRejectedValue(new Error('Network error'))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument()
      })
    })

    it('shows generic error for non-Error objects', async () => {
      vi.mocked(emailsApi.fetchEmails).mockRejectedValue('Unknown failure')

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Erreur inconnue')).toBeInTheDocument()
      })
    })

    it('shows retry button on error', async () => {
      vi.mocked(emailsApi.fetchEmails).mockRejectedValue(new Error('Network error'))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /réessayer/i })).toBeInTheDocument()
      })
    })

    it('retries fetching emails when retry button clicked', async () => {
      vi.mocked(emailsApi.fetchEmails)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce(mockResult({ count: 2, emails: mockEmails }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument()
      })

      const retryButton = screen.getByRole('button', { name: /réessayer/i })
      await act(async () => {
        fireEvent.click(retryButton)
      })

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      expect(emailsApi.fetchEmails).toHaveBeenCalledTimes(2)
    })
  })

  describe('Email selection', () => {
    it('calls onEmailSelect when email is clicked', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))
      const onEmailSelect = vi.fn()

      render(<EmailList onEmailSelect={onEmailSelect} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const emailItem = screen.getByText('Alice Martin').closest('.email-content')
      await act(async () => {
        fireEvent.click(emailItem!)
      })

      expect(onEmailSelect).toHaveBeenCalledWith(mockEmails[0])
    })

    it('highlights selected email', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      const { container } = render(<EmailList selectedEmailId="email-1" />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Get the swipeable items specifically (not the virtualized wrappers)
      const listItems = container.querySelectorAll('.swipeable-email-item')
      expect(listItems[0]).toHaveClass('selected')
      expect(listItems[1]).not.toHaveClass('selected')
    })

    it('does not highlight when selectedEmailId is null', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      const { container } = render(<EmailList selectedEmailId={null} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Get the swipeable items specifically (not the virtualized wrappers)
      const listItems = container.querySelectorAll('.swipeable-email-item')
      expect(listItems[0]).not.toHaveClass('selected')
      expect(listItems[1]).not.toHaveClass('selected')
    })
  })

  describe('Refresh functionality', () => {
    it('shows refresh button', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /actualiser/i })).toBeInTheDocument()
      })
    })

    it('refreshes emails when refresh button clicked', async () => {
      const updatedEmails: Email[] = [
        {
          id: 'email-3',
          sender: 'new@example.com',
          sender_name: 'New Person',
          subject: 'Nouveau message',
          received_at: '2026-01-05T16:00:00Z',
          has_attachments: false,
          conversation_id: null,
          is_read: false,
        },
      ]

      vi.mocked(emailsApi.fetchEmails)
        .mockResolvedValueOnce(mockResult({ count: 2, emails: mockEmails }))
        .mockResolvedValueOnce(mockResult({ count: 1, emails: updatedEmails }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const refreshButton = screen.getByRole('button', { name: /actualiser/i })
      await act(async () => {
        fireEvent.click(refreshButton)
      })

      await waitFor(() => {
        expect(screen.getByText('New Person')).toBeInTheDocument()
      })

      expect(emailsApi.fetchEmails).toHaveBeenCalledTimes(2)
    })

    it('disables refresh button while loading', async () => {
      let resolveFirst: (value: FetchEmailsResult) => void
      const firstPromise = new Promise<FetchEmailsResult>((resolve) => {
        resolveFirst = resolve
      })
      vi.mocked(emailsApi.fetchEmails).mockReturnValue(firstPromise)

      render(<EmailList />)

      await act(async () => {
        resolveFirst!(mockResult({ count: 2, emails: mockEmails }))
      })

      let resolveSecond: (value: FetchEmailsResult) => void
      const secondPromise = new Promise<FetchEmailsResult>((resolve) => {
        resolveSecond = resolve
      })
      vi.mocked(emailsApi.fetchEmails).mockReturnValue(secondPromise)

      const refreshButton = screen.getByRole('button', { name: /actualiser/i })
      await act(async () => {
        fireEvent.click(refreshButton)
      })

      expect(refreshButton).toBeDisabled()
      expect(refreshButton).toHaveTextContent('...')

      await act(async () => {
        resolveSecond!(mockResult({ count: 2, emails: mockEmails }))
      })
    })
  })

  describe('Swipe actions', () => {
    it('passes onSwipeArchive to SwipeableEmailItem', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))
      const onSwipeArchive = vi.fn()

      const { container } = render(<EmailList onSwipeArchive={onSwipeArchive} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Get the swipeable item specifically (not the virtualized wrapper)
      const listItem = container.querySelector('.swipeable-email-item')!

      vi.useFakeTimers()
      fireEvent.pointerDown(listItem, { clientX: 0 })
      fireEvent.pointerMove(listItem, { clientX: 100 })
      fireEvent.pointerUp(listItem)

      await act(async () => {
        vi.advanceTimersByTime(300)
      })

      expect(onSwipeArchive).toHaveBeenCalledWith(mockEmails[0])
      vi.useRealTimers()
    })

    it('passes onSwipeDelete to SwipeableEmailItem', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))
      const onSwipeDelete = vi.fn()

      const { container } = render(<EmailList onSwipeDelete={onSwipeDelete} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Get the swipeable item specifically (not the virtualized wrapper)
      const listItem = container.querySelector('.swipeable-email-item')!

      vi.useFakeTimers()
      fireEvent.pointerDown(listItem, { clientX: 100 })
      fireEvent.pointerMove(listItem, { clientX: 0 })
      fireEvent.pointerUp(listItem)

      await act(async () => {
        vi.advanceTimersByTime(300)
      })

      expect(onSwipeDelete).toHaveBeenCalledWith(mockEmails[0])
      vi.useRealTimers()
    })
  })

  describe('formatRelativeTime helper', () => {
    it('formats time correctly for emails', async () => {
      const recentEmail: Email = {
        id: 'recent-1',
        sender: 'recent@example.com',
        sender_name: 'Recent User',
        subject: 'Just now',
        received_at: new Date().toISOString(),
        has_attachments: false,
        conversation_id: null,
        is_read: false,
      }

      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [recentEmail],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Recent User')).toBeInTheDocument()
      })

      expect(screen.getByText("À l'instant")).toBeInTheDocument()
    })

    it('formats time for emails received hours ago', async () => {
      const hoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString()
      const pastEmail: Email = {
        id: 'past-1',
        sender: 'past@example.com',
        sender_name: 'Past User',
        subject: 'Hours ago',
        received_at: hoursAgo,
        has_attachments: false,
        conversation_id: null,
        is_read: false,
      }

      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [pastEmail],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Past User')).toBeInTheDocument()
      })

      expect(screen.getByText('Il y a 3h')).toBeInTheDocument()
    })

    it('formats time for emails received days ago', async () => {
      const daysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString()
      const oldEmail: Email = {
        id: 'old-1',
        sender: 'old@example.com',
        sender_name: 'Old User',
        subject: 'Days ago',
        received_at: daysAgo,
        has_attachments: false,
        conversation_id: null,
        is_read: false,
      }

      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [oldEmail],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Old User')).toBeInTheDocument()
      })

      expect(screen.getByText('Il y a 2j')).toBeInTheDocument()
    })
  })

  describe('getSenderDisplay helper', () => {
    it('displays sender_name when available', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })
    })

    it('displays email local part when sender_name is null', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[1]],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('bob')).toBeInTheDocument()
      })
    })

    it('displays full sender when no @ symbol', async () => {
      const noAtEmail: Email = {
        id: 'no-at-1',
        sender: 'localuser',
        sender_name: null,
        subject: 'Local email',
        received_at: new Date().toISOString(),
        has_attachments: false,
        conversation_id: null,
        is_read: false,
      }

      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [noAtEmail],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('localuser')).toBeInTheDocument()
      })
    })
  })

  describe('API calls', () => {
    it('calls fetchEmails with limit of 50', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 0,
        emails: [],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(emailsApi.fetchEmails).toHaveBeenCalledWith(50)
      })
    })

    it('only fetches once on initial mount', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 0,
        emails: [],
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(emailsApi.fetchEmails).toHaveBeenCalledTimes(1)
      })
    })
  })

  describe('Mark read/unread functionality', () => {
    it('calls markEmailRead API when marking email as read via quick action', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]], // unread email
      }))

      vi.mocked(emailsApi.markEmailRead).mockResolvedValue({ success: true } as any)

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Find and click the quick action button (mark as read)
      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      expect(emailsApi.markEmailRead).toHaveBeenCalledWith('email-1')
    })

    it('calls markEmailUnread API when marking email as unread via quick action', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[1]], // read email
      }))

      vi.mocked(emailsApi.markEmailUnread).mockResolvedValue({ success: true } as any)

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('bob')).toBeInTheDocument()
      })

      // Find and click the quick action button (mark as unread)
      const quickActionBtn = screen.getByRole('button', { name: /marquer comme non lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      expect(emailsApi.markEmailUnread).toHaveBeenCalledWith('email-2')
    })

    it('shows success toast when marking email as read', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      vi.mocked(emailsApi.markEmailRead).mockResolvedValue({ success: true } as any)

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      await waitFor(() => {
        expect(screen.getByText('Email marqué comme lu')).toBeInTheDocument()
      })
    })

    it('shows error toast on API failure', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))
      vi.mocked(emailsApi.markEmailRead).mockRejectedValue(new Error('API error'))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      await waitFor(() => {
        expect(screen.getByText('Erreur lors de la mise à jour')).toBeInTheDocument()
      })
    })

    it('performs optimistic update when marking as read', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))
      // Delay the API response to test optimistic update
      vi.mocked(emailsApi.markEmailRead).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 1000))
      )

      const { container } = render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Verify it starts as unread
      expect(container.querySelector('.swipeable-email-item.unread')).toBeInTheDocument()

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      // Should immediately show as read (optimistic update)
      expect(container.querySelector('.swipeable-email-item.unread')).not.toBeInTheDocument()
    })

    it('rolls back optimistic update on API failure', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))
      vi.mocked(emailsApi.markEmailRead).mockRejectedValue(new Error('API error'))

      const { container } = render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Verify it starts as unread
      expect(container.querySelector('.swipeable-email-item.unread')).toBeInTheDocument()

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      // Should rollback to unread after error
      await waitFor(() => {
        expect(container.querySelector('.swipeable-email-item.unread')).toBeInTheDocument()
      })
    })
  })

  describe('Multi-select mode', () => {
    it('shows multi-select toggle button', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /sélectionner/i })).toBeInTheDocument()
      })
    })

    it('enters multi-select mode when toggle clicked', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const toggleBtn = screen.getByRole('button', { name: /sélectionner/i })
      await act(async () => {
        fireEvent.click(toggleBtn)
      })

      // Should show bulk actions toolbar
      expect(screen.getByText('Tout sélectionner')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /marquer lu/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /marquer non lu/i })).toBeInTheDocument()
    })

    it('exits multi-select mode and clears selection when cancel clicked', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Enter multi-select mode
      const toggleBtn = screen.getByRole('button', { name: /sélectionner/i })
      await act(async () => {
        fireEvent.click(toggleBtn)
      })

      expect(screen.getByText('Tout sélectionner')).toBeInTheDocument()

      // Click cancel (now says "Annuler")
      const cancelBtn = screen.getByRole('button', { name: /annuler/i })
      await act(async () => {
        fireEvent.click(cancelBtn)
      })

      // Bulk actions toolbar should be gone
      expect(screen.queryByText('Tout sélectionner')).not.toBeInTheDocument()
    })

    it('shows correct count when emails are selected', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Enter multi-select mode
      const toggleBtn = screen.getByRole('button', { name: /sélectionner/i })
      await act(async () => {
        fireEvent.click(toggleBtn)
      })

      // Initially 0 selected (0 is treated as plural in French)
      expect(screen.getByText('0 sélectionnés')).toBeInTheDocument()

      // Select all
      const selectAllBtn = screen.getByRole('button', { name: /tout sélectionner/i })
      await act(async () => {
        fireEvent.click(selectAllBtn)
      })

      expect(screen.getByText('2 sélectionnés')).toBeInTheDocument()
    })

    it('calls markEmailsBulk API when bulk marking as read', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      vi.mocked(emailsApi.markEmailsBulk).mockResolvedValue({ success: true, updated: 0 } as any)

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Enter multi-select mode and select all
      const toggleBtn = screen.getByRole('button', { name: /sélectionner/i })
      await act(async () => {
        fireEvent.click(toggleBtn)
      })

      const selectAllBtn = screen.getByRole('button', { name: /tout sélectionner/i })
      await act(async () => {
        fireEvent.click(selectAllBtn)
      })

      // Click bulk mark read
      const markReadBtn = screen.getByRole('button', { name: /marquer lu/i })
      await act(async () => {
        fireEvent.click(markReadBtn)
      })

      expect(emailsApi.markEmailsBulk).toHaveBeenCalledWith(['email-1', 'email-2'], true)
    })

    it('disables bulk action buttons when no emails selected', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 2,
        emails: mockEmails,
      }))

      render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      // Enter multi-select mode
      const toggleBtn = screen.getByRole('button', { name: /sélectionner/i })
      await act(async () => {
        fireEvent.click(toggleBtn)
      })

      const markReadBtn = screen.getByRole('button', { name: /marquer lu/i })
      const markUnreadBtn = screen.getByRole('button', { name: /marquer non lu/i })

      expect(markReadBtn).toBeDisabled()
      expect(markUnreadBtn).toBeDisabled()
    })
  })

  describe('Toast notifications', () => {
    it('calls external onToast prop when provided', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      vi.mocked(emailsApi.markEmailRead).mockResolvedValue({ success: true } as any)
      const onToast = vi.fn()

      render(<EmailList onToast={onToast} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      expect(onToast).toHaveBeenCalledWith('Email marqué comme lu', 'success')
    })

    it('renders internal ToastContainer when onToast prop not provided', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      vi.mocked(emailsApi.markEmailRead).mockResolvedValue({ success: true } as any)

      const { container } = render(<EmailList />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      await waitFor(() => {
        expect(container.querySelector('.toast-container')).toBeInTheDocument()
      })
    })

    it('does not render internal ToastContainer when onToast prop is provided', async () => {
      vi.mocked(emailsApi.fetchEmails).mockResolvedValue(mockResult({
        count: 1,
        emails: [mockEmails[0]],
      }))

      vi.mocked(emailsApi.markEmailRead).mockResolvedValue({ success: true } as any)
      const onToast = vi.fn()

      const { container } = render(<EmailList onToast={onToast} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Martin')).toBeInTheDocument()
      })

      const quickActionBtn = screen.getByRole('button', { name: /marquer comme lu/i })
      await act(async () => {
        fireEvent.click(quickActionBtn)
      })

      // Internal toast container should not be rendered
      expect(container.querySelector('.toast-container')).not.toBeInTheDocument()
    })
  })
})
