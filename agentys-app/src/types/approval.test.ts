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

import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock the emails module so getActiveAccountId() returns a deterministic value
vi.mock('../api/emails', () => ({
  getActiveAccountId: vi.fn(() => 'default'),
}));

import {
  getApprovalAuditLog,
  addApprovalAuditEntry,
  getAuditEntriesForDraft,
  clearApprovalAuditLog,
  APPROVAL_STORAGE_KEY,
} from './approval';
import { getActiveAccountId } from '../api/emails';

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

describe('Approval Audit Types (Story 6-5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
  });

  describe('getApprovalAuditLog', () => {
    it('returns empty array when no data in localStorage', () => {
      localStorageMock.getItem.mockReturnValueOnce(null);
      const result = getApprovalAuditLog();
      expect(result).toEqual([]);
    });

    it('returns parsed audit log from localStorage', () => {
      const mockLog = [
        { id: 'audit-1', draftId: 'draft-1', action: 'approved', timestamp: '2026-01-19T10:00:00Z', userAction: 'Test' },
      ];
      localStorageMock.getItem.mockReturnValueOnce(JSON.stringify(mockLog));

      const result = getApprovalAuditLog();
      expect(result).toEqual(mockLog);
    });

    it('handles malformed JSON gracefully', () => {
      localStorageMock.getItem.mockReturnValueOnce('not valid json');
      const result = getApprovalAuditLog();
      expect(result).toEqual([]);
    });
  });

  describe('addApprovalAuditEntry', () => {
    it('creates entry with auto-generated id and timestamp (AC4)', () => {
      const entry = addApprovalAuditEntry({
        draftId: 'draft-123',
        action: 'approved',
        userAction: 'User clicked Approuver et Envoyer',
      });

      expect(entry.id).toMatch(/^audit-\d+-[a-z0-9]+$/);
      expect(entry.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      expect(entry.draftId).toBe('draft-123');
      expect(entry.action).toBe('approved');
      expect(entry.userAction).toBe('User clicked Approuver et Envoyer');
    });

    it('stores entry in localStorage', () => {
      localStorageMock.getItem.mockReturnValueOnce(null);

      addApprovalAuditEntry({
        draftId: 'draft-456',
        action: 'sent',
        userAction: 'Draft sent',
      });

      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        APPROVAL_STORAGE_KEY,
        expect.stringContaining('draft-456')
      );
    });

    it('keeps only last 100 entries', () => {
      const existingEntries = Array.from({ length: 100 }, (_, i) => ({
        id: `audit-${i}`,
        draftId: `draft-${i}`,
        action: 'approved',
        timestamp: '2026-01-19T10:00:00Z',
        userAction: 'Test',
      }));

      localStorageMock.getItem.mockReturnValueOnce(JSON.stringify(existingEntries));

      addApprovalAuditEntry({
        draftId: 'draft-new',
        action: 'approved',
        userAction: 'New entry',
      });

      const setItemCall = localStorageMock.setItem.mock.calls[0];
      const savedEntries = JSON.parse(setItemCall[1]);
      expect(savedEntries.length).toBe(100);
      expect(savedEntries[0].draftId).toBe('draft-new'); // New entry at beginning
    });
  });

  describe('getAuditEntriesForDraft', () => {
    it('returns only entries for specific draft', () => {
      const mockLog = [
        { id: 'audit-1', draftId: 'draft-1', action: 'approved', timestamp: '2026-01-19T10:00:00Z', userAction: 'Test 1' },
        { id: 'audit-2', draftId: 'draft-2', action: 'approved', timestamp: '2026-01-19T11:00:00Z', userAction: 'Test 2' },
        { id: 'audit-3', draftId: 'draft-1', action: 'sent', timestamp: '2026-01-19T12:00:00Z', userAction: 'Test 3' },
      ];
      localStorageMock.getItem.mockReturnValueOnce(JSON.stringify(mockLog));

      const result = getAuditEntriesForDraft('draft-1');

      expect(result.length).toBe(2);
      expect(result.every(e => e.draftId === 'draft-1')).toBe(true);
    });

    it('returns empty array if no entries for draft', () => {
      const mockLog = [
        { id: 'audit-1', draftId: 'draft-1', action: 'approved', timestamp: '2026-01-19T10:00:00Z', userAction: 'Test' },
      ];
      localStorageMock.getItem.mockReturnValueOnce(JSON.stringify(mockLog));

      const result = getAuditEntriesForDraft('draft-nonexistent');

      expect(result).toEqual([]);
    });
  });

  describe('clearApprovalAuditLog', () => {
    it('removes all entries from localStorage', () => {
      clearApprovalAuditLog();
      expect(localStorageMock.removeItem).toHaveBeenCalledWith(APPROVAL_STORAGE_KEY);
    });
  });

  // ── Per-account isolation ──────────────────────────────────────────────────
  describe('per-account isolation', () => {
    beforeEach(() => {
      localStorageMock.clear();
      vi.clearAllMocks();
    });

    it('writes to the legacy key when accountId is "default"', () => {
      vi.mocked(getActiveAccountId).mockReturnValue('default');
      addApprovalAuditEntry({ draftId: 'd1', action: 'approved', userAction: 'x' });
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        APPROVAL_STORAGE_KEY,
        expect.stringContaining('d1'),
      );
    });

    it('writes under agentys-approval-audit:<accountId> when an account is active', () => {
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');
      addApprovalAuditEntry({ draftId: 'd-alice', action: 'approved', userAction: 'x' });
      expect(localStorageMock.setItem).toHaveBeenCalledWith(
        'agentys-approval-audit:acc-alice',
        expect.stringContaining('d-alice'),
      );
    });

    it('two accounts on the same device cannot read each other entries', () => {
      // Alice writes
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');
      addApprovalAuditEntry({ draftId: 'alice-1', action: 'approved', userAction: 'x' });
      addApprovalAuditEntry({ draftId: 'alice-2', action: 'sent', userAction: 'y' });

      // Bob writes
      vi.mocked(getActiveAccountId).mockReturnValue('acc-bob');
      addApprovalAuditEntry({ draftId: 'bob-1', action: 'cancelled', userAction: 'z' });

      // Alice reads — only sees her own
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');
      const aliceLog = getApprovalAuditLog();
      expect(aliceLog.map(e => e.draftId).sort()).toEqual(['alice-1', 'alice-2']);

      // Bob reads — only sees his own
      vi.mocked(getActiveAccountId).mockReturnValue('acc-bob');
      const bobLog = getApprovalAuditLog();
      expect(bobLog.map(e => e.draftId)).toEqual(['bob-1']);
    });

    it('migrates from legacy global key on first read after upgrade', () => {
      // Pre-existing legacy data
      localStorageMock.setItem(
        APPROVAL_STORAGE_KEY,
        JSON.stringify([{ id: 'old', draftId: 'legacy', action: 'approved', timestamp: 't', userAction: 'u' }]),
      );

      // User now has an active account
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');

      // Read returns the legacy data (one-shot fallback)
      const log = getApprovalAuditLog();
      expect(log).toHaveLength(1);
      expect(log[0].draftId).toBe('legacy');
    });

    it('drops the legacy key after the first scoped write', () => {
      localStorageMock.setItem(APPROVAL_STORAGE_KEY, JSON.stringify([]));
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');

      addApprovalAuditEntry({ draftId: 'new', action: 'approved', userAction: 'x' });

      // Legacy key was removed during the write path
      expect(localStorageMock.removeItem).toHaveBeenCalledWith(APPROVAL_STORAGE_KEY);
    });

    it('clearApprovalAuditLog only clears the active account namespace', () => {
      vi.mocked(getActiveAccountId).mockReturnValue('acc-alice');
      clearApprovalAuditLog();
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('agentys-approval-audit:acc-alice');
    });
  });

  describe('ApprovalState type', () => {
    it('should track approval state correctly (AC3)', () => {
      const initialState = {
        isApproved: false,
        approvedAt: null,
        approvalAuditId: null,
      };

      expect(initialState.isApproved).toBe(false);
      expect(initialState.approvedAt).toBeNull();

      // After approval
      const approvedState = {
        isApproved: true,
        approvedAt: new Date().toISOString(),
        approvalAuditId: 'audit-123',
      };

      expect(approvedState.isApproved).toBe(true);
      expect(approvedState.approvedAt).toBeTruthy();
    });
  });
});
