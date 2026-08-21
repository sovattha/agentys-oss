// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2024-2026 Agentys contributors
/**
 * silentFail — helper pour les `.catch(() => {})` qui doivent au minimum
 * logger et idéalement remonter à l'utilisateur via toast.
 *
 * Audit Cluster D (2026-05-11) : 5+ sites dans compose/reply utilisaient
 * `.catch(err => console.error(...))` log-only ou `.catch(() => {})` vide.
 * Le user voyait son contact réapparaître après "masquer", son brouillon
 * resurgir après "annuler", ses suggestions de sujet ne pas s'autoremplir,
 * sans aucune indication.
 *
 * Usage :
 *
 *   apiClient.hideContact(email).catch(silentFailWithToast('hide-contact'))
 *
 * Variants :
 *   - `silentFailLog(scope)` — log uniquement (pour cas vraiment best-effort
 *     comme telemetry / fire-and-forget)
 *   - `silentFailWithToast(scope, options?)` — log + toast warning
 *   - `silentFailWithErrorToast(scope, options?)` — log + toast error pour
 *     les flows critiques (envoi, sauvegarde)
 */

type FailScope = string

type ToastOptions = {
  /** Message custom au lieu du défaut `${scope}: ${err.message}` */
  message?: string
  /** Type de toast (default 'warning') */
  type?: 'success' | 'error' | 'info' | 'warning'
  /** Durée en ms (default 5000) */
  duration?: number
}

function _dispatchToast(message: string, type: ToastOptions['type'] = 'warning', duration = 5000) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('agentys:toast', {
    detail: { message, type, duration },
  }))
}

function _formatErr(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  try { return JSON.stringify(err) } catch { return String(err) }
}

/** Log only — pour vrais best-effort (telemetry, analytics). */
export function silentFailLog(scope: FailScope) {
  return (err: unknown) => {
    console.warn(`[${scope}]`, err)
  }
}

/** Log + toast warning (défaut). */
export function silentFailWithToast(scope: FailScope, options: ToastOptions = {}) {
  return (err: unknown) => {
    console.warn(`[${scope}]`, err)
    const msg = options.message ?? `${scope}: ${_formatErr(err)}`
    _dispatchToast(msg, options.type ?? 'warning', options.duration ?? 5000)
  }
}

/** Log + toast error — flows critiques (envoi, sauvegarde, suppression). */
export function silentFailWithErrorToast(scope: FailScope, options: ToastOptions = {}) {
  return (err: unknown) => {
    console.error(`[${scope}]`, err)
    const msg = options.message ?? `${scope}: ${_formatErr(err)}`
    _dispatchToast(msg, options.type ?? 'error', options.duration ?? 8000)
  }
}
