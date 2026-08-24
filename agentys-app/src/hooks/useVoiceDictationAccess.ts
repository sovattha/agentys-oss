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

import { useEffect, useMemo, useState } from 'react'

import { canUseVoiceDictation, stripeService } from '../services/subscription'
import type { BillingEntitlement } from '../services/subscription'
import { useAuth } from './useAuth'

/**
 * Accès à la dictée vocale, aligné sur le paywall IA.
 *
 * Source de vérité = l'entitlement billing live (`stripeService`), PAS le `user`
 * d'auth : ce dernier ne porte pas toujours le signal billing, ce qui faisait
 * tomber `canUseVoiceDictation` sur son défaut permissif et laissait la dictée
 * déverrouillée pour les comptes gratuits. On écoute `agentys:billing-updated`
 * pour rester synchrone avec le reste de l'UI.
 */
export function useVoiceDictationAccess(): boolean {
  const { user, isLoading } = useAuth()
  const [billing, setBilling] = useState<BillingEntitlement | null>(() =>
    stripeService.getCachedBilling(),
  )

  useEffect(() => {
    const cached = stripeService.getCachedBilling()
    if (cached) setBilling(cached)

    const handler = (event: Event) => {
      const detail = (event as CustomEvent<BillingEntitlement>).detail
      if (detail) setBilling(detail)
    }
    window.addEventListener('agentys:billing-updated', handler)
    return () => window.removeEventListener('agentys:billing-updated', handler)
  }, [])

  return useMemo(() => {
    if (isLoading && !user) return false
    // Le billing live prime ; fallback sur le user auth tant qu'il n'est pas chargé.
    return canUseVoiceDictation(billing ?? user)
  }, [isLoading, user, billing])
}
