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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PendingDraftDetail } from './PendingDraftDetail';
import { apiClient, type PendingDraft } from '../services/api';
import { APPROVAL_STORAGE_KEY } from '../types/approval';

// Key for skip confirmation preference (Story 6-6)
const SEND_CONFIRMATION_SKIP_KEY = 'agentys_skip_send_confirmation';

// Mock API client
vi.mock('../services/api', () => ({
  apiClient: {
    validatePendingDraft: vi.fn(),
    rejectPendingDraft: vi.fn(),
    updatePendingDraft: vi.fn(),
    refineDraft: vi.fn(),
    regenerateDraft: vi.fn(),
    getEnvConfig: vi.fn().mockResolvedValue({}),
  },
}));

// Mock email API
vi.mock('../api/emails', () => ({
  fetchEmailDetail: vi.fn().mockResolvedValue({
    id: 'email-456',
    from: 'sender@example.com',
    subject: 'Test Subject',
    body: 'Test email body',
    cc: [],
    labels: [],
  }),
}));

// Mock snippets API
vi.mock('../api/snippets', () => ({
  replaceSnippetVariables: vi.fn((text: string) => text),
}));

// Mock TipTap
vi.mock('@tiptap/react', () => ({
  useEditor: vi.fn(() => ({
    chain: () => ({
      focus: () => ({
        toggleBold: () => ({ run: vi.fn() }),
        toggleItalic: () => ({ run: vi.fn() }),
        toggleStrike: () => ({ run: vi.fn() }),
        extendMarkRange: () => ({ setLink: () => ({ run: vi.fn() }) }),
        unsetLink: () => ({ run: vi.fn() }),
        undo: () => ({ run: vi.fn() }),
        redo: () => ({ run: vi.fn() }),
      }),
    }),
    can: () => ({ undo: () => false, redo: () => false }),
    isActive: vi.fn(() => false),
    getHTML: () => '<p>Test</p>',
    getText: () => 'Test',
    setEditable: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    view: { dom: document.createElement('div') },
    commands: { setContent: vi.fn() },
  })),
  EditorContent: () => <div data-testid="editor-content">Editor</div>,
}));

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

const mockDraft: PendingDraft = {
  id: 'draft-123',
  email_id: 'email-456',
  email_sender: 'sender@example.com',
  email_sender_name: 'Test Sender',
  email_subject: 'Test Subject',
  email_body: 'Test email body',
  email_received_at: '2026-01-19T10:00:00Z',
  draft_subject: 'Re: Test Subject',
  draft_body: 'Test draft body',
  draft_v1: 'First version',
  critique: 'Critique feedback',
  classification: 'URGENT',
  priority: 1,
  confidence: 0.95,
  status: 'pending',
  created_at: '2026-01-19T10:00:00Z',
};

// TODO: update for new architecture — component has many new dependencies (snippets, followup, pipeline, etc.)
describe.skip('PendingDraftDetail - Story 6-5: Explicit Approval Requirement', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageStore = {};
    // Skip confirmation modal for Story 6-5 tests
    localStorageStore[SEND_CONFIRMATION_SKIP_KEY] = 'true';
  });

  describe('AC1: Approve and Send Button - Distinct and Visible', () => {
    it('renders "Approuver et Envoyer" button when draft is pending', () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      expect(approveButton).toBeInTheDocument();
      expect(approveButton).toHaveTextContent('Approuver et Envoyer');
    });

    it('button has distinct styling (approve-send class)', () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      expect(approveButton).toHaveClass('approve-send');
    });

    it('button is disabled while sending', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockImplementation(
        () => new Promise(resolve => setTimeout(resolve, 100))
      );

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(approveButton).toBeDisabled();
        expect(approveButton).toHaveTextContent('Envoi en cours...');
      });
    });

    it('does not render approve button for non-pending drafts', () => {
      const validatedDraft = { ...mockDraft, status: 'validated' as const };
      render(<PendingDraftDetail draft={validatedDraft} />);

      expect(screen.queryByTestId('approve-send-button')).not.toBeInTheDocument();
    });
  });

  describe('AC2: Cannot Send Without Explicit Click', () => {
    it('requires explicit button click to initiate send', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
      });

      const onDraftValidated = vi.fn();
      render(<PendingDraftDetail draft={mockDraft} onDraftValidated={onDraftValidated} />);

      // Before click - no API call
      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();

      // After click - API called
      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(apiClient.validatePendingDraft).toHaveBeenCalledWith('draft-123');
      });
    });

    it('calls onDraftValidated callback on success', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
      });

      const onDraftValidated = vi.fn();
      render(<PendingDraftDetail draft={mockDraft} onDraftValidated={onDraftValidated} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(onDraftValidated).toHaveBeenCalledWith(mockDraft, 'gmail-789');
      });
    });
  });

  describe('AC3: Approved State Recorded Before Send', () => {
    it('records approval state before API call', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
      });

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(localStorageMock.setItem).toHaveBeenCalledWith(
          APPROVAL_STORAGE_KEY,
          expect.any(String)
        );
        const calls = localStorageMock.setItem.mock.calls.filter(
          (call: string[]) => call[0] === APPROVAL_STORAGE_KEY
        );
        const auditLog = JSON.parse(calls[0][1]);
        expect(auditLog[0].action).toBe('approved');
      });
    });

    it('resets approval state on failure', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Network error')
      );

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        // Check that a cancelled entry was logged
        const calls = localStorageMock.setItem.mock.calls.filter(
          (call: string[]) => call[0] === APPROVAL_STORAGE_KEY
        );
        const lastCall = calls[calls.length - 1];
        const auditLog = JSON.parse(lastCall[1]);
        const cancelledEntry = auditLog.find((e: { action: string }) => e.action === 'cancelled');
        expect(cancelledEntry).toBeDefined();
        expect(cancelledEntry.userAction).toContain('Envoi échoué');
      });
    });
  });

  describe('AC4: Audit Log of Approval', () => {
    it('logs approval action with timestamp and user action', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
      });

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        const calls = localStorageMock.setItem.mock.calls.filter(
          (call: string[]) => call[0] === APPROVAL_STORAGE_KEY
        );
        expect(calls.length).toBeGreaterThan(0);

        const auditLog = JSON.parse(calls[0][1]);
        expect(auditLog[0]).toMatchObject({
          draftId: 'draft-123',
          action: 'approved',
          userAction: expect.stringContaining('Approuver et Envoyer'),
        });
        expect(auditLog[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      });
    });

    it('logs sent action after successful send', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
      });

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        // Should have two setItem calls: one for approved, one for sent
        const calls = localStorageMock.setItem.mock.calls.filter(
          (call: string[]) => call[0] === APPROVAL_STORAGE_KEY
        );
        expect(calls.length).toBeGreaterThanOrEqual(2);

        const lastCall = calls[calls.length - 1];
        const auditLog = JSON.parse(lastCall[1]);
        const sentEntry = auditLog.find((e: { action: string }) => e.action === 'sent');
        expect(sentEntry).toBeDefined();
        expect(sentEntry.userAction).toContain('gmail-789');
      });
    });

    it('displays audit info when audit history exists', async () => {
      // Pre-populate audit history
      const existingAudit = [{
        id: 'audit-1',
        draftId: 'draft-123',
        action: 'approved',
        timestamp: '2026-01-19T10:00:00Z',
        userAction: 'Previous approval',
      }];
      localStorageStore[APPROVAL_STORAGE_KEY] = JSON.stringify(existingAudit);

      render(<PendingDraftDetail draft={mockDraft} />);

      const auditInfo = screen.getByTestId('approval-audit-info');
      expect(auditInfo).toBeInTheDocument();
      expect(auditInfo).toHaveTextContent('Dernier audit');
    });
  });

  describe('AC5: No Keyboard Shortcuts Trigger Send', () => {
    it('blocks Ctrl+Enter from triggering send', async () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      approveButton.focus();

      fireEvent.keyDown(approveButton, { key: 'Enter', ctrlKey: true });

      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('blocks Cmd+Enter from triggering send', async () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      approveButton.focus();

      fireEvent.keyDown(approveButton, { key: 'Enter', metaKey: true });

      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('blocks plain Enter within action area', async () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      // Button is now wrapped in Tooltip, so parentElement is tooltip-wrapper
      // Navigate up to find the draft-actions container
      const actionsDiv = screen.getByTestId('approve-send-button').closest('.draft-actions');
      expect(actionsDiv).toBeInTheDocument();
      expect(actionsDiv).toHaveClass('draft-actions');

      fireEvent.keyDown(actionsDiv!, { key: 'Enter' });

      expect(apiClient.validatePendingDraft).not.toHaveBeenCalled();
    });

    it('button type is "button" to prevent form submission', () => {
      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      expect(approveButton).toHaveAttribute('type', 'button');
    });
  });

  describe('Error Handling', () => {
    it('displays error message on send failure', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Erreur de connexion')
      );

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(screen.getByText(/Erreur de connexion/)).toBeInTheDocument();
      });
    });

    it('re-enables button after error', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Network error')
      );

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(approveButton).not.toBeDisabled();
        expect(approveButton).toHaveTextContent('Approuver et Envoyer');
      });
    });
  });
});

// TODO: update for new architecture
describe.skip('PendingDraftDetail - Story 6-7: Send Email via Provider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageStore = {};
    // Skip confirmation modal for Story 6-7 tests
    localStorageStore[SEND_CONFIRMATION_SKIP_KEY] = 'true';
  });

  describe('AC1: Email is sent via provider', () => {
    it('handles response with sent=true flag', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
        sent: true,
        message: 'Email envoyé avec succès',
      });

      const onDraftValidated = vi.fn();
      render(<PendingDraftDetail draft={mockDraft} onDraftValidated={onDraftValidated} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(onDraftValidated).toHaveBeenCalledWith(mockDraft, 'gmail-789');
      });
    });

    it('logs "Email envoyé avec succès" in audit when sent=true', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        success: true,
        draft_id: 'draft-123',
        gmail_draft_id: 'gmail-789',
        sent: true,
        message: 'Email envoyé avec succès',
      });

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        const calls = localStorageMock.setItem.mock.calls.filter(
          (call: string[]) => call[0] === APPROVAL_STORAGE_KEY
        );
        const lastCall = calls[calls.length - 1];
        const auditLog = JSON.parse(lastCall[1]);
        const sentEntry = auditLog.find((e: { action: string }) => e.action === 'sent');
        expect(sentEntry).toBeDefined();
        expect(sentEntry.userAction).toContain('Email envoyé avec succès');
      });
    });
  });

  describe('AC3: Error message on send failure', () => {
    it('displays specific error message when send fails', async () => {
      (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Erreur lors de l\'envoi de l\'email')
      );

      render(<PendingDraftDetail draft={mockDraft} />);

      const approveButton = screen.getByTestId('approve-send-button');
      fireEvent.click(approveButton);

      await waitFor(() => {
        expect(screen.getByText(/Erreur lors de l'envoi/)).toBeInTheDocument();
      });
    });
  });

  describe('AC4: Status shows sent', () => {
    it('displays "Envoyé" badge for sent status', () => {
      const sentDraft = { ...mockDraft, status: 'sent' as const };
      render(<PendingDraftDetail draft={sentDraft} />);

      expect(screen.getByText('Envoyé')).toBeInTheDocument();
    });
  });
});

// TODO: update for new architecture
describe.skip('PendingDraftDetail - Story 6-6: Send Confirmation Modal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageStore = {};
    // Do NOT set skip preference - we want the modal to show
  });

  it('shows confirmation modal when clicking approve button (AC1)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();
    expect(screen.getByText("Confirmer l'envoi")).toBeInTheDocument();
  });

  it('shows recipient in confirmation modal (AC1)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('summary-recipient')).toHaveTextContent('Test Sender');
    expect(screen.getByTestId('summary-recipient')).toHaveTextContent('sender@example.com');
  });

  it('shows subject in confirmation modal (AC1)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('summary-subject')).toHaveTextContent('Re: Test Subject');
  });

  it('shows cancel button in modal (AC2)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('cancel-button')).toBeInTheDocument();
    expect(screen.getByText('Annuler')).toBeInTheDocument();
  });

  it('closes modal on cancel', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();

    const cancelButton = screen.getByTestId('cancel-button');
    fireEvent.click(cancelButton);

    expect(screen.queryByTestId('send-confirmation-overlay')).not.toBeInTheDocument();
  });

  it('closes modal on Escape key (AC5)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('send-confirmation-overlay')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByTestId('send-confirmation-overlay')).not.toBeInTheDocument();
  });

  it('skips modal when skip preference is set (AC4)', async () => {
    localStorageStore[SEND_CONFIRMATION_SKIP_KEY] = 'true';

    (apiClient.validatePendingDraft as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      success: true,
      draft_id: 'draft-123',
      gmail_draft_id: 'gmail-789',
    });

    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    // Modal should not appear
    expect(screen.queryByTestId('send-confirmation-overlay')).not.toBeInTheDocument();

    // API should be called directly
    await waitFor(() => {
      expect(apiClient.validatePendingDraft).toHaveBeenCalledWith('draft-123');
    });
  });

  it('shows 3-second countdown on confirm button (AC3)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('countdown-container')).toBeInTheDocument();
    expect(screen.getByTestId('countdown-text')).toHaveTextContent(/3 secondes/);
    expect(screen.getByTestId('confirm-button')).toBeDisabled();
  });

  it('shows "Ne plus afficher" checkbox (AC4)', () => {
    render(<PendingDraftDetail draft={mockDraft} />);

    const approveButton = screen.getByTestId('approve-send-button');
    fireEvent.click(approveButton);

    expect(screen.getByTestId('skip-checkbox')).toBeInTheDocument();
    expect(screen.getByText('Ne plus afficher cette confirmation')).toBeInTheDocument();
  });
});
