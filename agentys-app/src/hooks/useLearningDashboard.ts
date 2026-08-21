import { useState, useEffect, useCallback, useRef } from 'react'
import i18n from '../i18n'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'

// ── Types ──────────────────────────────────────────────────────────────

export interface HeroStats {
  acceptanceRate: number
  totalSent: number
  sentThisWeek: number
  timeSavedMin: number
  activeRules: number
  avgConfidence: number
}

export interface DailyTrend {
  date: string
  total: number
  unmodified: number
  rate: number
}

export interface TierBreakdown {
  simple: number
  standard: number
  complex: number
}

export interface LearningRule {
  id: string
  rule_text: string
  category: string
  scope: string
  contact?: string
  confidence: number
  active: boolean
  created_at?: string
}

export interface EditPatterns {
  greeting: number
  closing: number
  length: number
  tone: number
  content: number
  formule?: number
}

export interface ContactInsight {
  contact: string
  total_sends: number
  unmodified: number
  avg_edit_ratio: number
  avg_length: number | null
  cc_patterns: string[]
}

export interface Comparison {
  email_id: string
  contact: string
  original: string
  sent: string
  diff_summary: string
  timestamp: string
}

export interface LearningDashboardData {
  hero: HeroStats
  trend: DailyTrend[]
  tiers: TierBreakdown
  rules: LearningRule[]
  editPatterns: EditPatterns
  contacts: ContactInsight[]
  comparisons: Comparison[]
  isLoading: boolean
  error: string | null
  period: number
  setPeriod: (days: number) => void
  toggleRule: (ruleId: string, active: boolean) => Promise<void>
  deleteRule: (ruleId: string) => Promise<void>
  refresh: () => void
}

// ── Fetch helper ───────────────────────────────────────────────────────

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function patchJson(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status}`)
}

async function deleteJson(path: string): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, { method: 'DELETE', headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`${res.status}`)
}

// ── Hook ───────────────────────────────────────────────────────────────

export function useLearningDashboard(): LearningDashboardData {
  const [period, setPeriod] = useState(14)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [hero, setHero] = useState<HeroStats>({
    acceptanceRate: 0, totalSent: 0, sentThisWeek: 0,
    timeSavedMin: 0, activeRules: 0, avgConfidence: 0,
  })
  const [trend, setTrend] = useState<DailyTrend[]>([])
  const [tiers, setTiers] = useState<TierBreakdown>({ simple: 0, standard: 0, complex: 0 })
  const [rules, setRules] = useState<LearningRule[]>([])
  const [editPatterns] = useState<EditPatterns>({
    greeting: 0, closing: 0, length: 0, tone: 0, content: 0, formule: 0,
  })
  const [contacts, setContacts] = useState<ContactInsight[]>([])
  const [comparisons] = useState<Comparison[]>([])

  const mountedRef = useRef(true)

  const loadData = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      // Parallel fetch of all endpoints
      const [qualityRes, activityRes, rulesRes, contactsRes] = await Promise.allSettled([
        fetchJson<{
          total_sent: number; sent_unmodified: number; unmodified_rate: number;
          avg_edit_ratio: number; by_tier: Record<string, { total: number }>;
          daily: DailyTrend[];
        }>(`/draft-quality/stats?days=${period}`),
        fetchJson<{ week: { drafts: number; time_saved_min: number } }>('/stats/activity'),
        fetchJson<{ rules: LearningRule[] }>('/learning/rules'),
        fetchJson<{ contacts: ContactInsight[] }>('/contacts/insights?limit=10'),
      ])

      if (!mountedRef.current) return

      // Quality stats → hero + trend + tiers
      if (qualityRes.status === 'fulfilled') {
        const q = qualityRes.value
        setTrend(q.daily || [])
        setTiers({
          simple: q.by_tier?.simple?.total || 0,
          standard: q.by_tier?.standard?.total || 0,
          complex: q.by_tier?.complex?.total || 0,
        })
        setHero(prev => ({
          ...prev,
          acceptanceRate: q.unmodified_rate || 0,
          totalSent: q.total_sent || 0,
        }))
      }

      // Activity → time saved + weekly sends
      if (activityRes.status === 'fulfilled') {
        const a = activityRes.value
        setHero(prev => ({
          ...prev,
          sentThisWeek: a.week?.drafts || 0,
          timeSavedMin: a.week?.time_saved_min || 0,
        }))
      }

      // Rules
      if (rulesRes.status === 'fulfilled') {
        const r = rulesRes.value.rules || []
        setRules(r)
        const activeRules = r.filter(rule => rule.active)
        const avgConf = activeRules.length > 0
          ? activeRules.reduce((sum, rule) => sum + (rule.confidence || 0), 0) / activeRules.length
          : 0
        setHero(prev => ({
          ...prev,
          activeRules: activeRules.length,
          avgConfidence: Math.round(avgConf * 100) / 100,
        }))
      }

      // Contacts
      if (contactsRes.status === 'fulfilled') {
        setContacts(contactsRes.value.contacts || [])
      }

    } catch (e) {
      if (mountedRef.current) {
        setError(e instanceof Error ? e.message : 'Erreur de chargement')
      }
    } finally {
      if (mountedRef.current) setIsLoading(false)
    }
  }, [period])

  useEffect(() => {
    mountedRef.current = true
    loadData()
    return () => { mountedRef.current = false }
  }, [loadData])

  // Audit Toast Sites 7/8 (2026-05-12): the silent catches made rule toggles
  // and deletes look like flaky UI — the change reverted without explanation.
  // Surface the error so the user knows to retry.
  const toggleRule = useCallback(async (ruleId: string, active: boolean) => {
    try {
      await patchJson(`/learning/rules/${ruleId}`, { active })
      setRules(prev => prev.map(r => r.id === ruleId ? { ...r, active } : r))
    } catch (err) {
      console.warn('[useLearningDashboard] toggleRule failed:', err)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.rule_edit_failed'),
            type: 'warning',
            duration: 6000,
          },
        }))
      }
    }
  }, [])

  const deleteRule = useCallback(async (ruleId: string) => {
    try {
      await deleteJson(`/learning/rules/${ruleId}`)
      setRules(prev => prev.filter(r => r.id !== ruleId))
    } catch (err) {
      console.warn('[useLearningDashboard] deleteRule failed:', err)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.rule_delete_failed'),
            type: 'error',
            duration: 7000,
          },
        }))
      }
    }
  }, [])

  return {
    hero, trend, tiers, rules, editPatterns, contacts, comparisons,
    isLoading, error, period, setPeriod, toggleRule, deleteRule,
    refresh: loadData,
  }
}
