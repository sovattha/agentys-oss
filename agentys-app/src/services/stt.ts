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
 * Service for STT keyterms (auto-seeded from project labels +
 * user overrides). Consumed by the Settings UI.
 *
 * The keyterms list is also read server-side at /api/transcribe time —
 * this client just manages the override list, the backend resolves the
 * full list from the auth context.
 */

import { API_URL } from '../config'
import { getAuthHeaders } from './authToken'

export interface SttKeyterms {
  /** Project label names — read-only (auto-seeded). */
  auto: string[]
  /** User overrides — added/removed via this service. */
  custom: string[]
  /**
   * Dictation-effective limit on custom words. Past this the backend rejects
   * the add (the merge truncates at this cap, so extra words never reach the
   * decoder). Optional for backward-compat with older API responses; the UI
   * falls back to a sane default when absent.
   */
  cap?: number
}

export async function getKeyterms(): Promise<SttKeyterms> {
  const res = await fetch(`${API_URL}/api/stt/keyterms`, {
    headers: { ...getAuthHeaders() },
  })
  if (!res.ok) throw new Error(`Failed to fetch keyterms (${res.status})`)
  return res.json()
}

export async function addKeyterm(term: string): Promise<{ inserted: boolean; custom: string[] }> {
  const res = await fetch(`${API_URL}/api/stt/keyterms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ term }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Failed to add keyterm (${res.status})`)
  }
  return res.json()
}

export async function removeAutoKeyterm(term: string): Promise<{ excluded: boolean; auto: string[] }> {
  const res = await fetch(
    `${API_URL}/api/stt/keyterms/auto/${encodeURIComponent(term)}`,
    { method: 'DELETE', headers: { ...getAuthHeaders() } },
  )
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Failed to exclude auto keyterm (${res.status})`)
  }
  return res.json()
}

export async function removeKeyterm(term: string): Promise<{ removed: boolean; custom: string[] }> {
  const res = await fetch(
    `${API_URL}/api/stt/keyterms/${encodeURIComponent(term)}`,
    { method: 'DELETE', headers: { ...getAuthHeaders() } },
  )
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Failed to remove keyterm (${res.status})`)
  }
  return res.json()
}
