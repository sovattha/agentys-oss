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
 * Dérive l'état de la bannière de plan (conversion free/essai → forfait payant).
 *
 * Source de vérité : l'entitlement billing renvoyé par `/api/billing/me`.
 * - abonné payant actif → bannière masquée (rien à convertir)
 * - essai (`trialing`) → variante "trial" + jours restants
 * - gratuit / statut inactif → variante "free"
 */

const DAY_MS = 1000 * 60 * 60 * 24
const ACTIVE_PAID_STATUSES = new Set(['active'])

export type PlanBannerVariant = 'free' | 'trial'

export interface PlanBannerState {
  show: boolean
  variant: PlanBannerVariant | null
  daysRemaining: number | null
}

interface BillingLike {
  plan?: string
  subscription_status?: string
  ai_enabled?: boolean
  current_period_end?: string | null
}

const HIDDEN: PlanBannerState = { show: false, variant: null, daysRemaining: null }

function daysUntil(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null
  const end = new Date(iso).getTime()
  if (Number.isNaN(end)) return null
  return Math.max(0, Math.ceil((end - now) / DAY_MS))
}

export function derivePlanBanner(
  billing: BillingLike | null | undefined,
  now: number = Date.now(),
): PlanBannerState {
  if (!billing) return HIDDEN

  const status = (billing.subscription_status ?? '').toLowerCase()
  const plan = (billing.plan ?? '').toLowerCase()

  // Abonné payant actif : aucune bannière de conversion.
  if (ACTIVE_PAID_STATUSES.has(status) && plan !== 'free') {
    return HIDDEN
  }

  if (status === 'trialing') {
    return { show: true, variant: 'trial', daysRemaining: daysUntil(billing.current_period_end, now) ?? 0 }
  }

  // Tout le reste (none / free / past_due / canceled / unpaid…) = gratuit à convertir.
  return { show: true, variant: 'free', daysRemaining: null }
}
