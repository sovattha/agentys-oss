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
