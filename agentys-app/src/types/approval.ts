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
 * Approval Types for Story 6-5: Explicit Approval Requirement
 *
 * Defines types for tracking draft approval state and audit logging.
 *
 * Audit entries are stored per-account in localStorage so multi-account users
 * don't see each other's approval history on the same device.
 */

import { getActiveAccountId } from '../api/emails';

export interface ApprovalAuditEntry {
  id: string;
  draftId: string;
  action: 'approved' | 'sent' | 'cancelled';
  timestamp: string; // ISO format
  userAction: string; // Description of the action taken
}

export interface ApprovalState {
  isApproved: boolean;
  approvedAt: string | null; // ISO timestamp
  approvalAuditId: string | null;
}

/** Legacy global key (pre-account-scoping) — still read once for migration. */
export const APPROVAL_STORAGE_KEY = 'agentys-approval-audit';

function getStorageKey(): string {
  const accountId = getActiveAccountId();
  return accountId && accountId !== 'default'
    ? `agentys-approval-audit:${accountId}`
    : APPROVAL_STORAGE_KEY;
}

/**
 * Get all approval audit entries from localStorage (scoped to active account).
 *
 * One-shot fallback to the legacy global key so existing audit history isn't
 * lost on the first read after the upgrade.
 */
export function getApprovalAuditLog(): ApprovalAuditEntry[] {
  try {
    const scoped = localStorage.getItem(getStorageKey());
    if (scoped) return JSON.parse(scoped) as ApprovalAuditEntry[];
    const legacy = localStorage.getItem(APPROVAL_STORAGE_KEY);
    return legacy ? (JSON.parse(legacy) as ApprovalAuditEntry[]) : [];
  } catch {
    return [];
  }
}

/**
 * Add a new audit entry under the active account namespace.
 */
export function addApprovalAuditEntry(entry: Omit<ApprovalAuditEntry, 'id' | 'timestamp'>): ApprovalAuditEntry {
  const newEntry: ApprovalAuditEntry = {
    ...entry,
    id: `audit-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    timestamp: new Date().toISOString(),
  };

  const auditLog = getApprovalAuditLog();
  auditLog.unshift(newEntry); // Add to beginning

  // Keep only last 100 entries
  const trimmedLog = auditLog.slice(0, 100);

  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(trimmedLog));
    // Drop the legacy global key once we've migrated this account's data
    if (localStorage.getItem(APPROVAL_STORAGE_KEY) !== null) {
      localStorage.removeItem(APPROVAL_STORAGE_KEY);
    }
  } catch {
    // Ignore storage errors
  }

  return newEntry;
}

/**
 * Get audit entries for a specific draft
 */
export function getAuditEntriesForDraft(draftId: string): ApprovalAuditEntry[] {
  return getApprovalAuditLog().filter(entry => entry.draftId === draftId);
}

/**
 * Clear all audit entries for the active account (for testing)
 */
export function clearApprovalAuditLog(): void {
  try {
    localStorage.removeItem(getStorageKey());
  } catch {
    // Ignore errors
  }
}
