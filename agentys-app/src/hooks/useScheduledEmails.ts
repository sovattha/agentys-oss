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

import { useCallback, useEffect, useRef, useState } from 'react'
import i18n from '../i18n'
import { apiClient, type ScheduledEmailDTO } from '../services/api'
import { getWebSocketClient } from '../services/websocket'
import { getStoredToken } from '../services/authToken'

export interface UseScheduledEmailsResult {
  items: ScheduledEmailDTO[]
  count: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  cancel: (id: string) => Promise<boolean>
  patch: (id: string, patch: { send_at?: string; subject?: string; body?: string }) => Promise<boolean>
  sendNow: (id: string) => Promise<boolean>
}

const REFETCH_DEBOUNCE_MS = 250

export function useScheduledEmails(): UseScheduledEmailsResult {
  const [items, setItems] = useState<ScheduledEmailDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    // Skip when no JWT — login page would otherwise hit /api/emails/scheduled
    // with 401 (audit 2026-05-01 P1 finding #5).
    if (!getStoredToken()) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const resp = await apiClient.listScheduledEmails('pending')
      // Deep audit 2026-06-02 U (BS-01): the backend returns a degraded 200 when
      // its store read failed (a 5xx would trip the connection-lost interceptor).
      // Surface it as a retryable error and KEEP the last-known list instead of
      // flashing empty — "no scheduled sends" must not masquerade as success.
      if (resp?.degraded) {
        setError(i18n.t('common:toasts.scheduled_list_unavailable', {
          defaultValue: 'Could not load scheduled sends — try again',
        }))
        return
      }
      // Defensive: a misconfigured backend (or a stale endpoint stub during
      // tests) can return `{}` without `items`. Reading `.length` on the
      // resulting undefined later crashes the App into the ErrorBoundary.
      const next = Array.isArray(resp?.items) ? resp.items : []
      // Skip the state update when the list shape hasn't changed — prevents
      // a re-render storm when 50 scheduled emails fire in the same minute.
      setItems(prev => sameItemList(prev, next) ? prev : next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [])

  // Audit Toast Site 9 (2026-05-12): the previous handlers only stored the
  // error in local state — when the ScheduledEmailsList disposed of its
  // <div role="alert">, the user lost the only signal that their cancel /
  // reschedule had failed. Dispatch a global toast in addition.
  const cancel = useCallback(async (id: string): Promise<boolean> => {
    try {
      await apiClient.cancelScheduledEmail(id)
      setItems(prev => prev.filter(it => it.id !== id))
      return true
    } catch (err) {
      const msg = err instanceof Error ? err.message : i18n.t('errors:cancel_error')
      setError(msg)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.schedule_cancel_failed', { detail: msg }), type: 'error', duration: 6000 },
        }))
      }
      return false
    }
  }, [])

  const patch = useCallback(async (
    id: string,
    body: { send_at?: string; subject?: string; body?: string },
  ): Promise<boolean> => {
    try {
      const resp = await apiClient.patchScheduledEmail(id, body)
      setItems(prev => prev.map(it => (it.id === id ? resp.scheduled : it)))
      return true
    } catch (err) {
      const msg = err instanceof Error ? err.message : i18n.t('errors:update_error')
      setError(msg)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.schedule_reschedule_failed', { detail: msg }), type: 'error', duration: 6000 },
        }))
      }
      return false
    }
  }, [])

  const sendNow = useCallback(async (id: string): Promise<boolean> => {
    try {
      await apiClient.sendScheduledNow(id)
      // The row transitions pending → sent on the backend; remove it from the
      // local list immediately so the user sees feedback without waiting for
      // the WS event to round-trip.
      setItems(prev => prev.filter(it => it.id !== id))
      return true
    } catch (err) {
      const msg = err instanceof Error ? err.message : i18n.t('errors:send_now_error')
      setError(msg)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.schedule_send_now_failed', { detail: msg }), type: 'error', duration: 6000 },
        }))
      }
      return false
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Debounce the WS-driven refetch so a burst of N delivery events in one
  // tick (scheduler dispatching many emails) coalesces into a single GET.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event) => {
      if (
        event.type === 'email_scheduled' ||
        event.type === 'email_sent_scheduled' ||
        event.type === 'email_schedule_canceled' ||
        event.type === 'email_schedule_updated'
      ) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        debounceRef.current = setTimeout(() => {
          debounceRef.current = null
          refresh()
        }, REFETCH_DEBOUNCE_MS)
      }
    })
    return () => {
      unsubscribe()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [refresh])

  return {
    items,
    count: items.length,
    loading,
    error,
    refresh,
    cancel,
    patch,
    sendNow,
  }
}

function sameItemList(a: ScheduledEmailDTO[], b: ScheduledEmailDTO[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    const x = a[i]
    const y = b[i]
    if (x.id !== y.id || x.send_at !== y.send_at || x.status !== y.status || x.updated_at !== y.updated_at) {
      return false
    }
  }
  return true
}
