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
 * API client for label management
 */

import type {
  Label,
  LabelingRule,
  LabelAssignment,
  LabelsResponse,
  RulesResponse,
  CreateLabelPayload,
  UpdateLabelPayload,
  CreateRulePayload,
} from '../types/labels'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'

const API_BASE = `${API_URL}/api/labels`

/**
 * Fetch all labels
 */
export async function fetchLabels(): Promise<LabelsResponse> {
  const response = await fetch(API_BASE, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    throw new Error(`Failed to fetch labels: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch a specific label by name
 */
export async function fetchLabel(name: string): Promise<{ label: Label }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(name)}`, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    throw new Error(`Failed to fetch label: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Create a new label
 */
export async function createLabel(payload: CreateLabelPayload): Promise<{
  label: Label
  message: string
}> {
  const response = await fetch(API_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to create label: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Update an existing label
 */
export async function updateLabel(
  name: string,
  payload: UpdateLabelPayload
): Promise<{ label: Label; message: string }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to update label: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Delete a label
 */
export async function deleteLabel(name: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to delete label: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Fetch all labeling rules
 */
export async function fetchRules(): Promise<RulesResponse> {
  const response = await fetch(`${API_BASE}/rules`, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    throw new Error(`Failed to fetch rules: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Create a new labeling rule
 */
export async function createRule(payload: CreateRulePayload): Promise<{
  rule: LabelingRule
  message: string
}> {
  const response = await fetch(`${API_BASE}/rules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to create rule: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Update a labeling rule
 */
export async function updateRule(
  ruleId: string,
  updates: { label_name?: string; condition_type?: string; condition_value?: string; is_active?: boolean }
): Promise<{ rule: LabelingRule; message: string }> {
  const response = await fetch(`${API_BASE}/rules/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(updates),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to update rule: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Delete a labeling rule
 */
export async function deleteRule(ruleId: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/rules/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to delete rule: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Auto-assign labels to an email
 */
export async function assignLabels(email: {
  email_id: string
  sender: string
  subject: string
  body: string
  to?: string[]
  cc?: string[]
  user_email?: string
}): Promise<{
  assignment: LabelAssignment
  labels: string[]
}> {
  const response = await fetch(`${API_BASE}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(email),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to assign labels: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Learn from user correction
 */
export async function learnFromCorrection(data: {
  email_id: string
  sender: string
  subject: string
  body: string
  old_labels: string[]
  new_labels: string[]
  reason?: string
  /** i18n key of the predefined suggestion chip clicked (e.g. 'suggestion_invoice').
   *  When set, the backend short-circuits LLM rule extraction with a
   *  deterministic mapping. Omit for free-text "Autre..." reasons. */
  reason_key?: string
}): Promise<{
  learned_rules: LabelingRule[]
  rules_count: number
  message: string
  final_labels?: Array<{ name: string; confidence: number; color?: string }>
}> {
  const response = await fetch(`${API_BASE}/learn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to learn: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Get label assignment for an email
 */
export async function getAssignment(emailId: string): Promise<{
  assignment: LabelAssignment
}> {
  const response = await fetch(`${API_BASE}/assignments/${encodeURIComponent(emailId)}`, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Assignment not found')
    }
    throw new Error(`Failed to get assignment: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Toggle label favorite status
 */
export async function toggleLabelFavorite(
  name: string,
  isFavorite: boolean
): Promise<{ label: Label; message: string }> {
  return updateLabel(name, { is_favorite: isFavorite })
}

/**
 * Reorder favorite labels (save order to localStorage)
 */
export function saveFavoriteLabelOrder(labelNames: string[]): void {
  localStorage.setItem('agentys_favorite_labels_order', JSON.stringify(labelNames))
}

/**
 * Get saved favorite label order
 */
export function getFavoriteLabelOrder(): string[] {
  const saved = localStorage.getItem('agentys_favorite_labels_order')
  if (!saved) return []
  try {
    return JSON.parse(saved)
  } catch {
    return []
  }
}

/**
 * Fetch label counts (number of emails per label).
 * Account-scoped, folder-agnostic — cf. issue #234.
 *
 * When `unreadOnly` is true, the backend restricts the count to unread
 * emails so the inbox header tabs can show Gmail-style unread badges.
 * Callers that need total volume (onboarding distribution, training
 * stats) leave it false.
 */
export async function fetchLabelCounts(unreadOnly: boolean = false): Promise<{
  counts: Record<string, number>
  total: number
}> {
  const url = unreadOnly ? `${API_BASE}/counts?unread_only=true` : `${API_BASE}/counts`
  const response = await fetch(url, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    throw new Error(`Failed to fetch label counts: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch email IDs by label
 */
export async function fetchEmailsByLabel(labelName: string): Promise<{
  label: string
  email_ids: string[]
  count: number
}> {
  const response = await fetch(`${API_BASE}/emails/${encodeURIComponent(labelName)}`, { headers: { ...getAuthHeaders() } })
  if (!response.ok) {
    throw new Error(`Failed to fetch emails by label: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Relabel all emails (force re-classification, preserving user corrections)
 */
export async function relabelAllEmails(): Promise<{
  message: string
  count: number
  skipped_user: number
}> {
  const response = await fetch(`${API_BASE}/classify-all`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ force: true }),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to relabel emails: ${response.statusText}`)
  }

  return response.json()
}

export interface LabelExampleEmail {
  id: string
  sender: string
  sender_name?: string
  subject: string
  received_at: string
  body?: string
  labels?: Array<{ name: string; color: string; confidence?: number }>
}

/**
 * Fetch example emails for a label (cross-match label email IDs with full email list)
 */
export async function fetchLabelExampleEmails(
  labelName: string,
  limit: number = 10
): Promise<LabelExampleEmail[]> {
  const [labelData, emailsResponse] = await Promise.all([
    fetchEmailsByLabel(labelName),
    fetch(`${API_URL}/api/emails?limit=100`, { headers: { ...getAuthHeaders() } }).then(r => {
      if (!r.ok) throw new Error('Failed to fetch emails')
      return r.json()
    }),
  ])

  const labelEmailIds = new Set(labelData.email_ids)
  const matchedEmails: LabelExampleEmail[] = emailsResponse.emails
    .filter((e: LabelExampleEmail) => labelEmailIds.has(e.id))
    .slice(0, limit)

  return matchedEmails
}
