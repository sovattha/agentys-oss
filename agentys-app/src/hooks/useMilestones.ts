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

import { useState, useCallback, useRef } from 'react'
import i18n from '../i18n'

const MILESTONES_KEY = 'agentys_milestones_seen'
const FIRST_DRAFT_KEY = 'agentys_first_draft_celebrated'

export interface Milestone {
  id: string
  threshold: number
  title: string
  description: string
  icon: string
}

// Resolved lazily (not at module load) so titles/descriptions follow the
// current i18n language, including a mid-session language switch.
const getMilestones = (): Milestone[] => [
  {
    id: 'refine_unlocked',
    threshold: 5,
    title: i18n.t('common:milestone_drafts_sent', { count: 5 }),
    description: i18n.t('common:milestone_refine_unlocked_desc'),
    icon: '\u26A1',
  },
  {
    id: 'learning_unlocked',
    threshold: 20,
    title: i18n.t('common:milestone_drafts_sent', { count: 20 }),
    description: i18n.t('common:milestone_learning_unlocked_desc'),
    icon: '\uD83D\uDCDA',
  },
]

export interface MilestonesState {
  pendingMilestone: Milestone | null
  dismissMilestone: () => void
  checkMilestones: (draftCount: number) => void
  firstDraftCelebrated: boolean
  celebrateFirstDraft: () => void
  dismissFirstDraft: () => void
  shouldCelebrateFirstDraft: (draftCount: number) => boolean
}

export function useMilestones(): MilestonesState {
  const [seenIds, setSeenIds] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(MILESTONES_KEY)
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch {
      return new Set()
    }
  })

  const [pendingMilestone, setPendingMilestone] = useState<Milestone | null>(null)

  const [firstDraftCelebrated, setFirstDraftCelebrated] = useState(() =>
    localStorage.getItem(FIRST_DRAFT_KEY) === 'true'
  )

  const queueRef = useRef<Milestone[]>([])

  const checkMilestones = useCallback((draftCount: number) => {
    const newMilestones = getMilestones().filter(
      m => draftCount >= m.threshold && !seenIds.has(m.id)
    )
    if (newMilestones.length > 0 && !pendingMilestone) {
      queueRef.current = newMilestones.slice(1)
      setPendingMilestone(newMilestones[0])
    }
  }, [seenIds, pendingMilestone])

  const dismissMilestone = useCallback(() => {
    if (pendingMilestone) {
      const newSeen = new Set(seenIds)
      newSeen.add(pendingMilestone.id)
      setSeenIds(newSeen)
      localStorage.setItem(MILESTONES_KEY, JSON.stringify([...newSeen]))

      // Show next in queue
      const next = queueRef.current.shift()
      setPendingMilestone(next || null)
    }
  }, [pendingMilestone, seenIds])

  const shouldCelebrateFirstDraft = useCallback((draftCount: number) => {
    return draftCount === 1 && !firstDraftCelebrated
  }, [firstDraftCelebrated])

  const celebrateFirstDraft = useCallback(() => {
    // Mark as shown — will be dismissed by user action
  }, [])

  const dismissFirstDraft = useCallback(() => {
    setFirstDraftCelebrated(true)
    localStorage.setItem(FIRST_DRAFT_KEY, 'true')
  }, [])

  return {
    pendingMilestone,
    dismissMilestone,
    checkMilestones,
    firstDraftCelebrated,
    celebrateFirstDraft,
    dismissFirstDraft,
    shouldCelebrateFirstDraft,
  }
}
