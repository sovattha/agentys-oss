/**
 * Idempotency store for meeting reminders.
 *
 * Keyed by `${eventId}:${tier}` where tier is one of `lead` (T-leadMinutes),
 * `imminent` (T-1min). Entries auto-expire after 24h to avoid unbounded
 * growth and to allow re-firing if the same event id reappears next week
 * (e.g. weekly recurring meeting).
 */

const STORAGE_KEY = 'agentys_meeting_reminders_fired_v1'
const TTL_MS = 24 * 60 * 60 * 1000

export type ReminderTier = 'lead' | 'imminent' | 'buzzer'

interface FiredMap {
  [key: string]: number // firedAt epoch ms
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
    // localStorage full or disabled — accept duplicate notifications rather than crash
  }
}

function pruneExpired(map: FiredMap): FiredMap {
  const now = Date.now()
  const result: FiredMap = {}
  for (const [k, v] of Object.entries(map)) {
    if (now - v < TTL_MS) result[k] = v
  }
  return result
}

function makeKey(eventId: string, tier: ReminderTier): string {
  return `${eventId}:${tier}`
}

export function hasFired(eventId: string, tier: ReminderTier): boolean {
  const map = readMap()
  return makeKey(eventId, tier) in map
}

export function markFired(eventId: string, tier: ReminderTier): void {
  const map = pruneExpired(readMap())
  map[makeKey(eventId, tier)] = Date.now()
  writeMap(map)
}

/** Test helper — clears all fired markers. */
export function _resetFiredStore(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
