/**
 * Idempotency store for the follow-up draft wake-time toast.
 *
 * Keyed by ``PendingDraft.id``. Two storage forms coexist:
 *
 *  - **Permanent**: `markFired(draftId)` writes a sentinel with no expiry.
 *    Used when the user clicks the toast `[×]` ("I saw it, stop nagging me")
 *    or after a successful `[Send]`.
 *  - **Until-timestamp**: `markFiredUntil(draftId, expiresAt)` writes an
 *    explicit wake-time. Used by `[Snooze 1d]` so the next poll past the
 *    expiry re-surfaces the toast.
 *
 * Storage layout (JSON in localStorage):
 *   {
 *     "<draftId>": { "at": <firedAt-ms>, "until": <expiry-ms | null> }
 *   }
 *
 * Why this is a separate store from `meetingReminderStore.ts`:
 *   - Draft IDs are UUIDs, meeting IDs are calendar event ids — different
 *     key namespaces.
 *   - Drafts need per-entry TTL (Snooze 1d vs permanent dismiss); the
 *     meeting store's hardcoded 24h TTL doesn't fit.
 *   - Decoupling lets the meeting flow keep its weekly-recurring re-fire
 *     behaviour without us inheriting it for one-shot draft toasts.
 */

const STORAGE_KEY = 'agentys_draft_wake_fired_v1'

interface FiredEntry {
  /** Epoch ms when the entry was written. Diagnostic only. */
  at: number
  /** Epoch ms when this entry should be ignored. `null` = forever. */
  until: number | null
}

interface FiredMap {
  [draftId: string]: FiredEntry
}

function readMap(): FiredMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as FiredMap
    return typeof parsed === 'object' && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

function writeMap(map: FiredMap): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    // localStorage full or disabled — accept duplicate toasts rather than crash.
  }
}

/** Drop entries whose `until` is in the past so the store doesn't grow unboundedly. */
function pruneExpired(map: FiredMap): FiredMap {
  const now = Date.now()
  const result: FiredMap = {}
  for (const [k, v] of Object.entries(map)) {
    if (v.until === null || v.until > now) {
      result[k] = v
    }
  }
  return result
}

/** True when the toast for this draft should be suppressed right now. */
export function hasFired(draftId: string): boolean {
  if (!draftId) return false
  const map = readMap()
  const entry = map[draftId]
  if (!entry) return false
  if (entry.until === null) return true
  return entry.until > Date.now()
}

/** Permanent suppression (until user resets localStorage or `_resetFiredStore`). */
export function markFired(draftId: string): void {
  if (!draftId) return
  const map = pruneExpired(readMap())
  map[draftId] = { at: Date.now(), until: null }
  writeMap(map)
}

/**
 * Time-limited suppression. After `expiresAtMs` the entry is treated as
 * absent — the next poll will re-surface the draft.
 *
 * Defensive: callers passing a past timestamp clear any existing entry
 * instead of installing an already-expired one.
 */
export function markFiredUntil(draftId: string, expiresAtMs: number): void {
  if (!draftId) return
  const map = pruneExpired(readMap())
  if (expiresAtMs <= Date.now()) {
    delete map[draftId]
  } else {
    map[draftId] = { at: Date.now(), until: expiresAtMs }
  }
  writeMap(map)
}

/** Test helper — wipes every fired entry. */
export function _resetFiredStore(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
