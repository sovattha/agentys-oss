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

import { lazy, type ComponentType } from 'react'

/**
 * Wrapper autour de React.lazy qui détecte les erreurs de chunk manquant
 * après un redeploy et force un reload (une seule fois pour éviter les boucles).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyWithRetry<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>,
): React.LazyExoticComponent<T> {
  return lazy(async () => {
    const storageKey = 'chunk_reload_ts'
    try {
      return await importFn()
    } catch (error) {
      const lastReload = Number(sessionStorage.getItem(storageKey) || '0')
      const now = Date.now()
      // Reload une seule fois par session (fenêtre de 60s anti-boucle)
      if (now - lastReload > 60_000) {
        sessionStorage.setItem(storageKey, String(now))
        window.location.reload()
      }
      throw error
    }
  })
}
