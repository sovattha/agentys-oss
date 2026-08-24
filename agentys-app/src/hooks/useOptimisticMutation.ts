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

import { useCallback } from 'react'
import i18n from '../i18n'

interface UseOptimisticMutationOptions {
  /** Logging prefix, e.g. 'training-delete-rule'. */
  scope: string
  /** i18n key (common namespace) for the toast message on failure. */
  i18nKey: string
  /** Toast variant. Defaults to 'warning'. */
  toastType?: 'warning' | 'error'
  /** Toast duration in ms. Defaults to 6000. */
  duration?: number
}

/**
 * Audit Cluster D (2026-05-17) meta-issue #330: a shared helper for
 * optimistic-UI mutations that surface failures to the user instead of
 * swallowing them in `console.warn` + broken-optimistic state.
 *
 * Usage:
 *   const run = useOptimisticMutation({
 *     scope: 'training-delete-rule',
 *     i18nKey: 'toasts.learning_delete_failed',
 *   })
 *
 *   const handleDelete = async (id: string) => {
 *     const prev = rules
 *     setRules(rules.filter(r => r.id !== id))    // optimistic
 *     await run(
 *       async () => okOrThrow(await fetch(`/api/rules/${id}`, { method: 'DELETE' })),
 *       () => setRules(prev),                      // rollback
 *     )
 *   }
 *
 * Returns the mutation result (`R`) on success, or `null` on failure.
 * Failure path runs rollback (if provided), dispatches an `agentys:toast`
 * event that `GlobalToastHost` already listens to, and logs to console.
 *
 * Note: `fetch()` does NOT throw on non-2xx — wrap with `okOrThrow(res)`
 * inside the mutation so HTTP failures actually reach the catch.
 */
export function useOptimisticMutation<R = unknown>(opts: UseOptimisticMutationOptions) {
  const { scope, i18nKey, toastType = 'warning', duration = 6000 } = opts
  return useCallback(
    async (
      mutation: () => Promise<R>,
      rollback?: () => void,
    ): Promise<R | null> => {
      try {
        return await mutation()
      } catch (err) {
        console.warn(`[${scope}]`, err)
        rollback?.()
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('agentys:toast', {
              detail: {
                message: i18n.t(i18nKey, { ns: 'common' }),
                type: toastType,
                duration,
              },
            }),
          )
        }
        return null
      }
    },
    [scope, i18nKey, toastType, duration],
  )
}

/**
 * Promotes a non-2xx `Response` into a thrown error. `fetch()` only
 * rejects on network failure — without this helper, HTTP 401/403/500
 * silently fall through every try/catch and the optimistic UI lies.
 */
export function okOrThrow(res: Response): Response {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText}`.trim())
  }
  return res
}
