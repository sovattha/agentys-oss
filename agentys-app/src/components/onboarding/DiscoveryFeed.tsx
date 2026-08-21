import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Discovery } from '../../types/onboarding'
import './DiscoveryFeed.css'

interface DiscoveryFeedProps {
  /** Rolling buffer of findings. The feed picks the last N to render. */
  discoveries: Discovery[]
  /** How many discoveries to keep visible at once. Older ones fade out. */
  max?: number
  /** Stagger between revealing queued discoveries arriving in the same
   *  WebSocket burst. 0 = show all at once (not recommended). */
  staggerMs?: number
}

interface DisplayedDiscovery {
  discovery: Discovery
  /** ms since epoch when this item should become visible. */
  revealAt: number
}

const ICON_BY_KIND: Record<Discovery['kind'], string> = {
  starting: '›',
  finding: '✓',
  insight: '✦',
}

function normalizeOnboardingKey(key: string): string {
  return key.startsWith('onboarding.')
    ? key.slice('onboarding.'.length)
    : key
}

/**
 * Rolling narrative log of findings surfaced by the onboarding pipeline.
 *
 * Each discovery is emitted by the backend as ``onboarding:discovery``
 * and stored in the ``LearningProgress.discoveries`` buffer. This component
 * animates the last ``max`` items in, staggering reveals so a burst of 5
 * findings arriving in the same tick scrolls naturally instead of popping
 * all at once.
 */
export function DiscoveryFeed({
  discoveries,
  max = 5,
  staggerMs = 650,
}: DiscoveryFeedProps) {
  const { t, i18n } = useTranslation('onboarding')
  const [now, setNow] = useState(() => Date.now())
  // Tracks the scheduled reveal time per discovery id. Prevents a
  // late-arriving discovery from stealing the slot of one already
  // scheduled but not yet visible.
  const scheduleRef = useRef(new Map<string, number>())
  // Highest reveal timestamp scheduled so far — the next discovery
  // will land at max(now, this + staggerMs) to preserve ordering.
  const lastScheduledRef = useRef(0)

  // Schedule reveal times for any newly-arrived discoveries.
  useEffect(() => {
    const schedule = scheduleRef.current
    const current = Date.now()
    for (const d of discoveries) {
      if (schedule.has(d.id)) continue
      const revealAt = Math.max(
        current,
        (lastScheduledRef.current || current) + staggerMs,
      )
      schedule.set(d.id, revealAt)
      lastScheduledRef.current = revealAt
    }
  }, [discoveries, staggerMs])

  // Tick the "now" state so items become visible at their scheduled
  // time. We only need ~100ms granularity — rAF would be wasted here.
  useEffect(() => {
    const iv = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(iv)
  }, [])

  const displayed: DisplayedDiscovery[] = discoveries
    .map(d => ({
      discovery: d,
      revealAt: scheduleRef.current.get(d.id) ?? d.timestampMs,
    }))
    .filter(entry => entry.revealAt <= now)
    .slice(-max)

  if (displayed.length === 0) return null

  return (
    <div className="disc-feed" role="log" aria-live="polite" aria-atomic="false">
      {displayed.map(({ discovery: d }) => {
        const messageKey = normalizeOnboardingKey(d.messageKey)
        const translated = i18n.exists(messageKey, { ns: 'onboarding' })
          ? t(messageKey, d.messageParams as Record<string, unknown>)
          : (d.fallbackMessage || d.messageKey)
        return (
          <div
            key={d.id}
            className={`disc-item disc-item--${d.kind}`}
            data-agent={d.agent}
          >
            <span className="disc-icon" aria-hidden="true">
              {ICON_BY_KIND[d.kind]}
            </span>
            <span className="disc-text">{translated}</span>
          </div>
        )
      })}
    </div>
  )
}
