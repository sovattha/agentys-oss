/**
 * useQuickSteps — single shared cache of the user's Quick Steps.
 *
 * Multiple components (chip bar in detail view, hover strip on email list
 * rows, Cmd+K palette) read the same list. A naïve hook would refetch per
 * mount, so we hoist state to module scope and broadcast updates through
 * a small subscriber list.
 *
 * Refresh triggers:
 *  - First subscriber: lazy fetch.
 *  - `window.dispatchEvent(new Event('agentys:quicksteps-changed'))`
 *    fired by the settings panel after save/delete.
 *  - Manual `refresh()` exposed by the hook.
 */
import { useEffect, useState } from 'react'

import { listQuickSteps } from '../services/api'
import type { QuickStep } from '../types/quickStep'
import { normalizeQuickStep } from '../types/quickStep'

const QUICKSTEPS_CHANGED_EVENT = 'agentys:quicksteps-changed'

let cache: QuickStep[] | null = null
let inFlight: Promise<void> | null = null
const subscribers = new Set<(steps: QuickStep[]) => void>()

async function fetchOnce(): Promise<void> {
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const data = await listQuickSteps()
      // Backend may omit optional fields (triggers, triggerOperator, autoEnabled)
      // for steps that don't use them. Normalize so consumers always get a full
      // QuickStep shape — otherwise the editor crashes on legacy records.
      cache = (data.quick_steps || []).map(normalizeQuickStep)
    } catch {
      cache = []
    }
    subscribers.forEach(fn => fn(cache!))
    inFlight = null
  })()
  return inFlight
}

async function refresh(): Promise<void> {
  cache = null
  await fetchOnce()
}

/**
 * Optimistically patch a single step in the cache and notify subscribers
 * without a network round-trip. Use BEFORE firing a PATCH so toggles feel
 * instant; on failure call again with the original value to roll back.
 *
 * No-op when the cache hasn't been loaded yet — the next ``refresh`` will
 * pick up the persisted value.
 */
export function patchCachedStep(id: string, patch: Partial<QuickStep>): void {
  if (!cache) return
  cache = cache.map(s => (s.id === id ? { ...s, ...patch } : s))
  subscribers.forEach(fn => fn(cache!))
}

if (typeof window !== 'undefined') {
  window.addEventListener(QUICKSTEPS_CHANGED_EVENT, () => {
    void refresh()
  })
}

export interface UseQuickStepsResult {
  steps: QuickStep[]
  loaded: boolean
  refresh: () => Promise<void>
}

export function useQuickSteps(): UseQuickStepsResult {
  const [steps, setSteps] = useState<QuickStep[]>(cache ?? [])
  const [loaded, setLoaded] = useState<boolean>(cache !== null)

  useEffect(() => {
    const handler = (next: QuickStep[]) => {
      setSteps(next)
      setLoaded(true)
    }
    subscribers.add(handler)
    if (cache === null) {
      void fetchOnce()
    } else {
      setSteps(cache)
      setLoaded(true)
    }
    return () => {
      subscribers.delete(handler)
    }
  }, [])

  return { steps, loaded, refresh }
}

/** Test-only escape hatch — clears the module-level cache. */
export function _resetQuickStepsCacheForTests(): void {
  cache = null
  inFlight = null
  subscribers.clear()
}
