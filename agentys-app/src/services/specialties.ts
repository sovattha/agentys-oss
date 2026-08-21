/**
 * Service pour les spécialités (Expert Mode).
 *
 * Mock de paiement via localStorage + API calls backend pour activation/désactivation.
 */

import { API_URL } from '../config'
import { getAuthHeaders } from './authToken'

// ── Types ────────────────────────────────────────────────────────────────

export interface SpecialtySummary {
  id: string
  name: string
  description: string
  jurisdiction: string
  language: string
  expert_count: number
  experts_summary: { id: string; name: string }[]
  is_active: boolean
  activated_at: string | null
  price_monthly: number
}

export interface SpecialtyDetail extends SpecialtySummary {
  version: string
  target_users: string[]
  experts: {
    id: string
    name: string
    topics: string[]
    priority: number
  }[]
  templates: string[]
  guidelines_preview: string
  risk_levels: Record<string, { description: string; trigger_count: number }>
  routing: Record<string, string[]>
}

export interface SpecialtyInfo {
  specialty_id: string
  specialty_name: string
  category: string
  expert_ids: string[]
  expert_names: string[]
  risk_level: 'high' | 'medium' | 'low'
  confidence: number
  keyword_hits: number
}

// ── LocalStorage keys ────────────────────────────────────────────────────

const LS_PURCHASED = 'agentys_specialty_purchases'

function getPurchased(): Record<string, { purchased_at: string }> {
  try {
    return JSON.parse(localStorage.getItem(LS_PURCHASED) || '{}')
  } catch {
    return {}
  }
}

function setPurchased(data: Record<string, { purchased_at: string }>) {
  localStorage.setItem(LS_PURCHASED, JSON.stringify(data))
}

// ── API calls ────────────────────────────────────────────────────────────

export async function getAvailableSpecialties(): Promise<SpecialtySummary[]> {
  const res = await fetch(`${API_URL}/api/specialties`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to fetch specialties')
  const data = await res.json()

  // Merge with local purchase state
  const purchased = getPurchased()
  return data.map((s: SpecialtySummary) => ({
    ...s,
    is_purchased: !!purchased[s.id],
  }))
}

export async function getSpecialtyDetail(id: string): Promise<SpecialtyDetail> {
  const res = await fetch(`${API_URL}/api/specialties/${id}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to fetch specialty detail')
  return res.json()
}

export async function purchaseSpecialty(id: string): Promise<void> {
  // Mock payment — store in localStorage
  const purchased = getPurchased()
  purchased[id] = { purchased_at: new Date().toISOString() }
  setPurchased(purchased)

  // Activate on backend
  const res = await fetch(`${API_URL}/api/specialties/${id}/activate`, { method: 'POST', headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to activate specialty')

  // Also update settings
  await fetch(`${API_URL}/api/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      active_specialties: Object.keys(purchased).filter(k => purchased[k]),
    }),
  })
}

export async function deactivateSpecialty(id: string): Promise<void> {
  const purchased = getPurchased()
  delete purchased[id]
  setPurchased(purchased)

  const res = await fetch(`${API_URL}/api/specialties/${id}/deactivate`, { method: 'POST', headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error('Failed to deactivate specialty')
}

export function isSpecialtyPurchased(id: string): boolean {
  const purchased = getPurchased()
  return !!purchased[id]
}
