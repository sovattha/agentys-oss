import { useEffect, useRef, useState, useCallback } from 'react'
import { getWebSocketClient, type WebSocketEvent } from '../services/websocket'
import type { ActivityItem, ActivityState, ActivityType } from '../types/activity'

const ACTIVITY_TTL_MS = 60_000
const SWEEP_INTERVAL_MS = 5_000
const THROTTLE_MS = 500
const JUST_FINISHED_MS = 2_000

/** Priority order: higher = shown first in tier 1 */
const PRIORITY: Record<ActivityType, number> = {
  draft: 60,
  critique: 50,
  classify: 40,
  learning: 30,
  sync: 20,
  cleanup: 10,
  followup: 10,
}

export function useActivityMonitor(backendStatus: 'checking' | 'connected' | 'disconnected'): ActivityState {
  const [state, setState] = useState<ActivityState>({
    activities: [],
    isActive: false,
    primaryActivity: null,
    justFinished: false,
    error: null,
  })

  // Mutable ref for pending activities — updated synchronously on each WS event,
  // then flushed to React state at most every THROTTLE_MS.
  const pendingRef = useRef<Map<string, ActivityItem>>(new Map())
  const errorRef = useRef<{ message: string; timestamp: number } | null>(null)
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const justFinishedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Tracks every auxiliary setTimeout spawned inside WS event handlers
  // (flash activities, error auto-clear) so unmount can clear them all.
  // Without this, remounting during rapid events leaked timers.
  const pendingTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())
  const hadActivitiesRef = useRef(false)

  const scheduleTrackedTimeout = useCallback(
    (fn: () => void, delayMs: number) => {
      const handle: ReturnType<typeof setTimeout> = setTimeout(() => {
        pendingTimersRef.current.delete(handle)
        fn()
      }, delayMs)
      pendingTimersRef.current.add(handle)
      return handle
    },
    [],
  )

  const flush = useCallback(() => {
    flushTimerRef.current = null
    const activities = Array.from(pendingRef.current.values())
    const isActive = activities.length > 0

    // Detect transition from active to idle
    if (!isActive && hadActivitiesRef.current) {
      // Show "done" briefly
      setState({
        activities: [],
        isActive: false,
        primaryActivity: null,
        justFinished: true,
        error: errorRef.current,
      })
      // Clear justFinished after delay
      if (justFinishedTimerRef.current) clearTimeout(justFinishedTimerRef.current)
      justFinishedTimerRef.current = setTimeout(() => {
        setState(prev => ({ ...prev, justFinished: false }))
      }, JUST_FINISHED_MS)
    } else {
      // Sort by priority desc to pick primary
      activities.sort((a, b) => (PRIORITY[b.type] || 0) - (PRIORITY[a.type] || 0))
      setState({
        activities,
        isActive,
        primaryActivity: activities[0] || null,
        justFinished: false,
        error: errorRef.current,
      })
    }

    hadActivitiesRef.current = isActive
  }, [])

  const scheduleFlush = useCallback(() => {
    if (!flushTimerRef.current) {
      flushTimerRef.current = setTimeout(flush, THROTTLE_MS)
    }
  }, [flush])

  // Helpers to manipulate the mutable map
  const addActivity = useCallback((id: string, type: ActivityType, label: string, extra?: Partial<ActivityItem>) => {
    pendingRef.current.set(id, {
      id,
      type,
      label,
      startedAt: Date.now(),
      ...extra,
    })
    scheduleFlush()
  }, [scheduleFlush])

  const updateActivity = useCallback((id: string, updates: Partial<ActivityItem>) => {
    const existing = pendingRef.current.get(id)
    if (existing) {
      pendingRef.current.set(id, { ...existing, ...updates })
      scheduleFlush()
    }
  }, [scheduleFlush])

  const removeActivity = useCallback((id: string) => {
    pendingRef.current.delete(id)
    scheduleFlush()
  }, [scheduleFlush])

  const removeByPrefix = useCallback((prefix: string) => {
    for (const key of pendingRef.current.keys()) {
      if (key.startsWith(prefix)) pendingRef.current.delete(key)
    }
    scheduleFlush()
  }, [scheduleFlush])

  useEffect(() => {
    if (backendStatus !== 'connected') return

    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      switch (event.type) {
        // --- Sync ---
        case 'sync_complete':
          removeActivity('sync')
          break

        // --- Draft pipeline ---
        case 'processing_started': {
          const eid = event.data.email_id
          addActivity(`draft:${eid}`, 'draft', 'activity_drafting', { emailId: eid, progress: 0 })
          break
        }
        case 'draft_stage': {
          const eid = event.data.email_id
          const existing = pendingRef.current.get(`draft:${eid}`)
          if (!existing) {
            addActivity(`draft:${eid}`, 'draft', 'activity_drafting', { emailId: eid, progress: event.data.progress_percent })
          } else {
            updateActivity(`draft:${eid}`, { progress: event.data.progress_percent })
          }
          break
        }
        case 'draft_chunk': {
          const eid = event.data.email_id
          if (!pendingRef.current.has(`draft:${eid}`)) {
            addActivity(`draft:${eid}`, 'draft', 'activity_drafting', { emailId: eid, progress: event.data.progress_percent })
          }
          // Don't update on every chunk — too frequent. The stage events handle progress.
          break
        }
        case 'orchestration_start': {
          const eid = event.data.email_id
          addActivity(`draft:${eid}`, 'draft', 'activity_drafting', { emailId: eid, progress: 0 })
          break
        }
        case 'draft_complete':
        case 'draft_ready':
        case 'draft_error':
        case 'draft_skipped': {
          const eid = event.data.email_id
          removeActivity(`draft:${eid}`)
          break
        }
        case 'orchestration_complete':
        case 'orchestration_timeout':
        case 'orchestration_error': {
          const eid = event.data.email_id
          removeActivity(`draft:${eid}`)
          break
        }

        // --- Critique ---
        case 'critique_start': {
          const eid = event.data.email_id
          addActivity(`critique:${eid}`, 'critique', 'activity_reviewing', { emailId: eid })
          break
        }
        case 'critique_complete':
        case 'critique_error': {
          const eid = event.data.email_id
          removeActivity(`critique:${eid}`)
          break
        }

        // --- Classification ---
        case 'labels_classification_started':
          addActivity('classify', 'classify', 'activity_classifying')
          break
        case 'labels_classification_complete':
          removeActivity('classify')
          break
        case 'labels_updated':
        case 'relabel_complete':
          if (pendingRef.current.has('classify')) {
            removeActivity('classify')
          } else {
            // Fallback for older emitters that only send a completion/update event.
            addActivity('classify', 'classify', 'activity_classifying')
            scheduleTrackedTimeout(() => removeActivity('classify'), 1500)
          }
          break

        // --- Learning ---
        case 'learning:analysis_completed':
        case 'learning:refresh_completed':
          removeActivity('learning')
          break
        case 'learning:correction_recorded':
        case 'learning:label_corrected':
          if (!pendingRef.current.has('learning')) {
            addActivity('learning', 'learning', 'activity_learning')
          }
          // Auto-remove after 3s if no completion event
          scheduleTrackedTimeout(() => removeActivity('learning'), 3000)
          break

        // --- Cleanup ---
        case 'noise_cleanup_complete':
          addActivity('cleanup', 'cleanup', 'activity_cleanup')
          scheduleTrackedTimeout(() => removeActivity('cleanup'), 1500)
          break

        // --- Errors ---
        case 'processing_error':
          errorRef.current = { message: event.data.error, timestamp: Date.now() }
          scheduleFlush()
          // Auto-clear error after 10s
          scheduleTrackedTimeout(() => {
            errorRef.current = null
            scheduleFlush()
          }, 10_000)
          break

        default:
          break
      }
    })

    // Listen for sync_started (not yet in WebSocketEvent type — comes as daemon_event)
    // For now, the sync cycle is short (~1-3s), so we infer sync from sync_complete.
    // We'll add a lightweight periodic sync indicator instead.

    // Sweep stale activities every 5s
    const sweepInterval = setInterval(() => {
      const now = Date.now()
      let changed = false
      for (const [key, item] of pendingRef.current) {
        if (now - item.startedAt > ACTIVITY_TTL_MS) {
          pendingRef.current.delete(key)
          changed = true
        }
      }
      if (changed) scheduleFlush()
    }, SWEEP_INTERVAL_MS)

    // Capture the ref's Set instance once, so the cleanup clears the same
    // collection the tracked-timeout helper appends to (also silences the
    // react-hooks/exhaustive-deps warning about ref.current in cleanup).
    const trackedTimers = pendingTimersRef.current

    return () => {
      unsubscribe()
      clearInterval(sweepInterval)
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current)
      if (justFinishedTimerRef.current) clearTimeout(justFinishedTimerRef.current)
      for (const handle of trackedTimers) {
        clearTimeout(handle)
      }
      trackedTimers.clear()
    }
  }, [backendStatus, addActivity, updateActivity, removeActivity, removeByPrefix, scheduleFlush, scheduleTrackedTimeout])

  return state
}
