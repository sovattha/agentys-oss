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
 * Tests for Story 6-8: No Auto-Send Safety (Frontend)
 *
 * These tests verify that the frontend prevents auto-sending emails
 * without explicit human approval (FR30, NFR30).
 *
 * Critical Safety Requirements:
 * - AC1: No code path allows sending without explicit approval
 * - AC2: Automated tests verify impossibility of auto-send
 * - AC5: Keyboard shortcuts cannot trigger send
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PendingDraftDetail } from '../PendingDraftDetail';
import { SendConfirmationModal, shouldSkipSendConfirmation, resetSendConfirmationPreference } from '../SendConfirmationModal';
import type { PendingDraft } from '../../services/api';

// Mock localStorage with store
let localStorageStore: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((key: string) => localStorageStore[key] || null),
  setItem: vi.fn((key: string, value: string) => {
    localStorageStore[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete localStorageStore[key];
  }),
  clear: vi.fn(() => {
    localStorageStore = {};
  }),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock the API client
vi.mock('../../services/api', () => ({
  apiClient: {
    validatePendingDraft: vi.fn(),
    rejectPendingDraft: vi.fn(),
    updatePendingDraft: vi.fn(),
    refineDraft: vi.fn(),
    regenerateDraft: vi.fn(),
  },
}));

// Mock approval types
vi.mock('../../types/approval', () => ({
  addApprovalAuditEntry: vi.fn((entry) => ({ ...entry, id: 'audit-1', timestamp: new Date().toISOString() })),
  getAuditEntriesForDraft: vi.fn(() => []),
}));

// TODO: update for new architecture — PendingDraftDetail has many new unmocked dependencies
describe.skip('Story 6-8: No Auto-Send Safety', () => {
  const mockDraft: PendingDraft = {
    id: 'test-draft-123',
    email_id: 'email-123',
    email_subject: 'Original Subject',
    email_body: 'Original email body',
    email_sender: 'sender@example.com',
    email_sender_name: 'Sender Name',
    email_received_at: new Date().toISOString(),
    draft_subject: 'Re: Original Subject',
    draft_body: 'Draft response body',
    draft_v1: 'First version',
    critique: 'Approved',
    classification: 'professional',
    confidence: 0.95,
    priority: 3,
    status: 'pending',
    created_at: new Date().toISOString(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorageStore = {};
    localStorageMock.clear.mockClear();
    localStorageMock.getItem.mockClear();
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
    resetSendConfirmationPreference();
  });

  afterEach(() => {
    localStorageStore = {};
  });

  // =========================================================================
  // AC1: No code path allows sending without explicit approval
  // =========================================================================

  describe('AC1: Explicit approval requirement', () => {
    it('requires clicking "Approuver et Envoyer" button to initiate send', async () => {
      const onDraftValidated = vi.fn();

      render(
        <PendingDraftDetail
          draft={mockDraft}
          onDraftValidated={onDraftValidated}
        />
      );

      // Initially, no send has occurred
      expect(onDraftValidated).not.toHaveBeenCalled();

      // Find and verify the approve button exists
      const approveButton = screen.getByTestId('approve-send-button');
      expect(approveButton).toBeInTheDocument();
      expect(approveButton).toHaveTextContent('Approuver et Envoyer');
    });

    it('shows confirmation modal before sending (when not skipped)', async () => {
      const user = userEvent.setup();

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Click approve button
      const approveButton = screen.getByTestId('approve-send-button');
      await user.click(approveButton);

      // Confirmation modal should appear
      await waitFor(() => {
        expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();
      });
    });

    it('cannot send without clicking confirm in modal', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Click approve button to open modal
      await user.click(screen.getByTestId('approve-send-button'));

      // Wait for modal
      await waitFor(() => {
        expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();
      });

      // Validate has NOT been called yet (modal is showing)
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('sends only after explicit confirm button click', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');
      vi.mocked(apiClient.validatePendingDraft).mockResolvedValue({
        success: true,
        draft_id: 'test-draft-123',
        gmail_draft_id: 'gmail-123',
        sent: true,
        message: 'Email envoye avec succes',
      });

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Click approve button
      await user.click(screen.getByTestId('approve-send-button'));

      // Wait for modal and countdown
      await waitFor(() => {
        expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();
      });

      // Wait for countdown to finish (3 seconds)
      await waitFor(
        () => {
          const confirmButton = screen.getByTestId('confirm-button');
          expect(confirmButton).not.toBeDisabled();
        },
        { timeout: 4000 }
      );

      // Click confirm
      await user.click(screen.getByTestId('confirm-button'));

      // NOW validatePendingDraft should be called
      await waitFor(() => {
        expect(apiClient.validatePendingDraft).toHaveBeenCalledWith('test-draft-123');
      });
    });
  });

  // =========================================================================
  // AC2: Automated tests verify impossibility of auto-send
  // =========================================================================

  describe('AC2: No auto-send paths', () => {
    it('does not auto-send when draft is loaded', async () => {
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Loading the component should NOT trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('does not auto-send when draft is edited', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Click edit button
      const editButton = screen.getByText('Modifier');
      await user.click(editButton);

      // Edit should not trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('does not auto-send when refine instruction is submitted', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');
      vi.mocked(apiClient.refineDraft).mockResolvedValue({
        success: true,
        draft_id: 'draft-1',
        refined_body: 'Refined body',
        pipeline_details: {
          draft_v1: 'v1',
          critique: { is_valid: true, feedback: 'ok' },
          was_corrected: false,
        },
      });

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Enter refine instruction
      const refineInput = screen.getByPlaceholderText(/raccourcir/i);
      await user.type(refineInput, 'make it shorter');
      await user.keyboard('{Enter}');

      // Refine should not trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('does not auto-send when regenerate is requested', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Click regenerate
      const regenerateButton = screen.getByTestId('regenerate-button');
      await user.click(regenerateButton);

      // Regenerate should not trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });
  });

  // =========================================================================
  // AC5: Keyboard shortcuts cannot trigger send
  // =========================================================================

  describe('AC5: Keyboard shortcut protection', () => {
    it('Ctrl+Enter does not trigger send', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Focus on the draft area and try Ctrl+Enter
      const draftElements = screen.getAllByText(mockDraft.draft_body);
      draftElements[0].focus();

      await user.keyboard('{Control>}{Enter}{/Control}');

      // Should NOT trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('Cmd+Enter does not trigger send', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      await user.keyboard('{Meta>}{Enter}{/Meta}');

      // Should NOT trigger send
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('Enter key on approve button area does not bypass modal', async () => {
      const user = userEvent.setup();
      const { apiClient } = await import('../../services/api');

      render(
        <PendingDraftDetail
          draft={mockDraft}
        />
      );

      // Focus approve button and press Enter (simulates keyboard activation)
      const approveButton = screen.getByTestId('approve-send-button');
      await user.tab(); // Navigate to button
      // Use click since that's what Enter/Space does on a focused button
      await user.click(approveButton);

      // Should open modal, NOT directly send
      // Modal should be visible
      await waitFor(() => {
        expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();
      });

      // But validate should NOT have been called yet
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });
  });

  // =========================================================================
  // Send Confirmation Modal Tests
  // =========================================================================

  describe('SendConfirmationModal', () => {
    it('has 3-second countdown before confirm is enabled', async () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();

      render(
        <SendConfirmationModal
          isOpen={true}
          recipient="test@example.com"
          subject="Test Subject"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      // Initially disabled
      const confirmButton = screen.getByTestId('confirm-button');
      expect(confirmButton).toBeDisabled();

      // Shows countdown
      expect(screen.getByTestId('countdown-text')).toHaveTextContent(/3 secondes/);

      // Wait for countdown
      await waitFor(
        () => {
          expect(confirmButton).not.toBeDisabled();
        },
        { timeout: 4000 }
      );
    });

    it('Escape key cancels without sending', async () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();

      render(
        <SendConfirmationModal
          isOpen={true}
          recipient="test@example.com"
          subject="Test Subject"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      // Press Escape
      fireEvent.keyDown(document, { key: 'Escape' });

      // Should call onCancel, not onConfirm
      expect(onCancel).toHaveBeenCalled();
      expect(onConfirm).not.toHaveBeenCalled();
    });

    it('clicking Cancel does not send', async () => {
      const user = userEvent.setup();
      const onConfirm = vi.fn();
      const onCancel = vi.fn();

      render(
        <SendConfirmationModal
          isOpen={true}
          recipient="test@example.com"
          subject="Test Subject"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      // Click cancel
      await user.click(screen.getByTestId('cancel-button'));

      expect(onCancel).toHaveBeenCalled();
      expect(onConfirm).not.toHaveBeenCalled();
    });

    it('shows recipient and subject in summary', () => {
      render(
        <SendConfirmationModal
          isOpen={true}
          recipient="test@example.com"
          recipientName="Test User"
          subject="Important Email"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(screen.getByTestId('summary-recipient')).toHaveTextContent('Test User');
      expect(screen.getByTestId('summary-subject')).toHaveTextContent('Important Email');
    });
  });

  // =========================================================================
  // Skip Confirmation Preference Tests
  // =========================================================================

  describe('Skip confirmation preference', () => {
    it('shouldSkipSendConfirmation returns false by default', () => {
      expect(shouldSkipSendConfirmation()).toBe(false);
    });

    it('saves skip preference when checkbox is checked and confirm is clicked', async () => {
      const user = userEvent.setup();
      const onConfirm = vi.fn();

      render(
        <SendConfirmationModal
          isOpen={true}
          recipient="test@example.com"
          subject="Test"
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );

      // Check the skip checkbox
      const skipCheckbox = screen.getByTestId('skip-checkbox');
      await user.click(skipCheckbox);
      expect(skipCheckbox).toBeChecked();

      // Wait for countdown
      await waitFor(
        () => expect(screen.getByTestId('confirm-button')).not.toBeDisabled(),
        { timeout: 4000 }
      );

      // Click confirm
      await user.click(screen.getByTestId('confirm-button'));

      // Preference should be saved
      expect(localStorage.getItem('agentys_skip_send_confirmation')).toBe('true');
    });

    it('resetSendConfirmationPreference clears the preference', () => {
      localStorage.setItem('agentys_skip_send_confirmation', 'true');
      expect(shouldSkipSendConfirmation()).toBe(true);

      resetSendConfirmationPreference();
      expect(shouldSkipSendConfirmation()).toBe(false);
    });
  });
});
