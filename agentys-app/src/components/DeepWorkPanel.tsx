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

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { CHECK_SLOT_PRESETS, WORK_BLOCK_PRESETS, type CheckSlot, type WorkBlock } from '../hooks/useDeepWorkSetting'
import type { UseDeepWorkTimerReturn } from '../hooks/useDeepWorkTimer'
import { API_URL } from '../config'
import { getAuthHeaders, handleAuthResponse } from '../services/authToken'
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount'
import { ChevronLeftIcon, CloseIcon } from './icons/ActionIcons'
import {
  slotGeometry,
  daylightGeometry,
  formatSlotTime,
  formatStartTime,
  durationLabel,
  nowMarkerPct,
} from './deepWorkTimeline'
import './DeepWorkPanel.css'

/**
 * Pure fetcher for `/api/labels/vip` — exported for unit testing without jsdom.
 *
 * F08 (MEDIUM): silent-failure regression fix. Pre-patch, a 401/500 was
 * masked as an empty success → user thought they had no VIP suggestions.
 * We now surface a typed error (kind: 'unauthorized' | 'http') so callers
 * can distinguish "no data" from "auth/server failure". 401 also
 * dispatches `auth:unauthorized` via handleAuthResponse so App.tsx
 * triggers the logout/redirect flow.
 */
export interface VipLabelResult {
  vipSenders: string[]
}

export type VipLabelError =
  | (Error & { kind: 'unauthorized' })
  | (Error & { kind: 'http'; status: number })

// eslint-disable-next-line react-refresh/only-export-components
export async function fetchVipLabelSenders(
  signal?: AbortSignal,
): Promise<VipLabelResult> {
  const r = await fetch(`${API_URL}/api/labels/vip`, {
    headers: { ...getAuthHeaders() },
    signal,
  })
  handleAuthResponse(r)
  if (r.status === 401) {
    throw Object.assign(new Error('unauthorized'), { kind: 'unauthorized' as const })
  }
  if (!r.ok) {
    throw Object.assign(new Error(`HTTP ${r.status}`), {
      kind: 'http' as const,
      status: r.status,
    })
  }
  const data = await r.json()
  return {
    vipSenders: Array.isArray(data?.vip_senders) ? data.vip_senders : [],
  }
}

interface DeepWorkPanelProps {
  timer: UseDeepWorkTimerReturn
  onClose: () => void
  onBack?: () => void
}

const WEEKDAY_DEFS = [
  { day: 1, key: 'mon' },
  { day: 2, key: 'tue' },
  { day: 3, key: 'wed' },
  { day: 4, key: 'thu' },
  { day: 5, key: 'fri' },
  { day: 6, key: 'sat' },
  { day: 7, key: 'sun' },
] as const

function getNextSlot<T extends { start: string; duration: number }>(
  slots: T[],
  nowMin: number,
): T | null {
  let next: T | null = null
  let bestStart = Infinity
  for (const s of slots) {
    const [h, m] = s.start.split(':').map(Number)
    const startMin = h * 60 + m
    if (startMin >= nowMin && startMin < bestStart) {
      next = s
      bestStart = startMin
    }
  }
  return next
}

type DwmTab = 'emails' | 'work'

export function DeepWorkPanel({ timer, onClose, onBack }: DeepWorkPanelProps) {
  const { t, i18n } = useTranslation('deepfocus')
  const { t: tc } = useTranslation('common')
  const WEEKDAYS = WEEKDAY_DEFS.map(({ day, key }) => ({ day, label: tc(`days_short.${key}`) }))
  const ref = useRef<HTMLDivElement>(null)
  const { isClosing, handleClose } = useAnimatedUnmount(true, onClose, 180)
  const [activeTab, setActiveTab] = useState<DwmTab>('emails')

  // Initial state for cancel functionality
  const [initialState] = useState(() => ({
    slots: [...timer.settings.checkSlots],
    weekdays: [...timer.settings.weekdays],
    vipList: [...timer.settings.vipContacts],
    personalBlocks: timer.settings.personalBlocks.map(b => ({ ...b })),
  }))

  // Local draft state
  const [draftSlots, setDraftSlots] = useState<CheckSlot[]>(() => [...timer.settings.checkSlots])
  const [draftWeekdays, setDraftWeekdays] = useState<number[]>(() => [...timer.settings.weekdays])
  const [draftVipList, setDraftVipList] = useState<string[]>(() => [...timer.settings.vipContacts])
  const [draftPersonalBlocks, setDraftPersonalBlocks] = useState<WorkBlock[]>(
    () => timer.settings.personalBlocks.map(b => ({ ...b }))
  )
  const [saved, setSaved] = useState(false)

  const checkCount = draftSlots.length

  // Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [handleClose])

  function handleSave() {
    timer.setCheckSlots(draftSlots)
    timer.setWeekdays(draftWeekdays)
    timer.setVipContacts(draftVipList)
    timer.setPersonalBlocks(draftPersonalBlocks)
    setSaved(true)
    setTimeout(() => handleClose(), 600)
  }

  function handleCancel() {
    setDraftSlots([...initialState.slots])
    setDraftWeekdays([...initialState.weekdays])
    setDraftVipList([...initialState.vipList])
    setDraftPersonalBlocks(initialState.personalBlocks.map(b => ({ ...b })))
    handleClose()
  }

  // Total focus hours per day (8h work day = 480 min)
  const WORK_DAY_MIN = 8 * 60
  const totalCheckMin = draftSlots.reduce((sum, s) => sum + s.duration, 0)
  const focusMin = Math.max(0, WORK_DAY_MIN - totalCheckMin)
  const focusH = Math.floor(focusMin / 60)
  const focusM = focusMin % 60

  // Work blocks metrics
  const workBlockCount = draftPersonalBlocks.length
  const totalWorkMin = draftPersonalBlocks.reduce((sum, b) => sum + b.duration, 0)

  // Next upcoming slot today (used in toggle subtitles for actionable info).
  // Recomputed per render — fine here, panel re-renders on local state changes only.
  const _now = new Date()
  const _nowMin = _now.getHours() * 60 + _now.getMinutes()
  const nextEmailSlot = getNextSlot(draftSlots, _nowMin)
  const nextWorkBlock = getNextSlot(draftPersonalBlocks, _nowMin)
  // "Now" marker position on the 24h bar — computed once at render (the modal is
  // short-lived; no ticking interval needed).
  const nowPct = nowMarkerPct(_now)
  const daylight = daylightGeometry()

  const workH = Math.floor(totalWorkMin / 60)
  const workM = totalWorkMin % 60

  return (
    <div className={`dwm-overlay${isClosing ? ' dwm-closing' : ''}`} onMouseDown={(e) => {
      if (e.target === e.currentTarget) handleClose()
    }}>
      <div className={`dwm-modal${isClosing ? ' dwm-modal--closing' : ''}`} ref={ref}>
        {/* Header */}
        <div className="dwm-header">
          <div className="dwm-header-left">
            {onBack && (
              <button className="dwm-back" onClick={onBack} aria-label={tc('back')} title={tc('back')}>
                <ChevronLeftIcon size={20} />
              </button>
            )}
            <div>
              <h2 className="dwm-title">{t('title')}</h2>
            </div>
          </div>
          <button className="dwm-close" onClick={handleClose} aria-label={tc('close')}>
            <CloseIcon />
          </button>
        </div>

        {/* Tab bar */}
        <div className="dwm-tab-bar">
          <div
            className={`dwm-tab-slider${activeTab === 'work' ? ' dwm-tab-slider--work' : ''}`}
          />
          <button
            className={`dwm-tab-seg${activeTab === 'emails' ? ' dwm-tab-seg--active' : ''}`}
            onClick={() => setActiveTab('emails')}
            aria-label={t('tab_emails')}
          >
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <rect width="20" height="16" x="2" y="4" rx="2" />
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
            </svg>
            <span className="dwm-tab-label">{t('tab_emails')}</span>
          </button>
          <button
            className={`dwm-tab-seg${activeTab === 'work' ? ' dwm-tab-seg--active' : ''}`}
            onClick={() => setActiveTab('work')}
            aria-label={t('tab_work')}
          >
            <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" />
              <path d="M3 9h18" />
              <path d="M9 21V9" />
            </svg>
            <span className="dwm-tab-label">{t('tab_work')}</span>
          </button>
        </div>

        {/* Timeline — below tabs. Slots render in every state (ghost-outlined
            when the mode is paused) so the bar is never empty, and the active
            tab brings its own layer forward (dwm-timeline-track--{tab}). */}
        <div className="dwm-timeline-top">
          <span className="dwm-section-title dwm-timeline-label">{t('panel_day_preview')}</span>
          <div className="dwm-timeline">
            <div className={`dwm-timeline-track dwm-timeline-track--${activeTab}`}>
              {/* Working-hours daylight band — cosmetic "this is the day" backdrop */}
              <div
                className="dwm-timeline-daylight"
                style={{ left: `${daylight.leftPct}%`, width: `${daylight.widthPct}%` }}
              />
              {draftPersonalBlocks.map((block, idx) => {
                const { leftPct, widthPct } = slotGeometry(block.start, block.duration)
                return (
                  <div
                    key={`wb-${idx}`}
                    className={`dwm-timeline-work${timer.settings.workEnabled ? '' : ' dwm-timeline-work--ghost'}`}
                    style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                    title={`${block.label} · ${formatSlotTime(block.start, block.duration, i18n.language)}`}
                  />
                )
              })}
              {draftSlots.map((slot, idx) => {
                const { leftPct, widthPct } = slotGeometry(slot.start, slot.duration)
                return (
                  <div
                    key={idx}
                    className={`dwm-timeline-slot${timer.settings.emailsEnabled ? '' : ' dwm-timeline-slot--ghost'}`}
                    style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                    title={`${formatSlotTime(slot.start, slot.duration, i18n.language)} — ${durationLabel(slot.duration)}`}
                  />
                )
              })}
              {/* "Now" marker — where the user currently is in their day */}
              <div
                className="dwm-timeline-now"
                style={{ left: `${nowPct}%` }}
                title={t('panel_now')}
                aria-label={t('panel_now')}
              />
            </div>
            <div className="dwm-timeline-hours">
              <span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>24h</span>
            </div>
            <div className="dwm-timeline-legend">
              <span className="dwm-legend-item"><span className="dwm-legend-dot dwm-legend-dot--check" />Emails</span>
              <span className="dwm-legend-item"><span className="dwm-legend-dot dwm-legend-dot--work" />{t('panel_legend_work')}</span>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="dwm-body" key={activeTab}>
          {activeTab === 'emails' ? (
            <>
              {/* Mode toggle */}
              <button
                type="button"
                className={`dwm-mode-toggle${timer.settings.emailsEnabled ? ' dwm-mode-toggle--on' : ''}`}
                onClick={() => timer.setEmailsEnabled(!timer.settings.emailsEnabled)}
              >
                <div className={`dwm-mode-toggle-track${timer.settings.emailsEnabled ? ' on' : ''}`}>
                  <div className="dwm-mode-toggle-knob" />
                </div>
                <div className="dwm-mode-toggle-text">
                  <span className="dwm-mode-toggle-title">{t('emails_enabled')}</span>
                  <span className="dwm-mode-toggle-hint">
                    {!timer.settings.emailsEnabled
                      ? t('emails_hint_off')
                      : nextEmailSlot
                        ? t('next_at_email', { time: formatStartTime(nextEmailSlot.start, i18n.language), min: nextEmailSlot.duration })
                        : checkCount > 0
                          ? t('next_at_done')
                          : t('emails_hint', { count: checkCount, min: totalCheckMin })}
                  </span>
                </div>
              </button>

              {/* Summary strip */}
              <div className={`dwm-tab-content${!timer.settings.emailsEnabled ? ' dwm-tab-content--off' : ''}`}>
              <div className="dwm-summary-strip">
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value">{checkCount}</span>
                    <span className="dwm-summary-label">{t('summary_consultations', { count: checkCount })}</span>
                  </div>
                  <div className="dwm-summary-divider" />
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value">{totalCheckMin}</span>
                    <span className="dwm-summary-label">{t('summary_min_email')}</span>
                  </div>
                  <div className="dwm-summary-divider" />
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value dwm-summary-value--accent">{focusH}h{focusM > 0 ? String(focusM).padStart(2, '0') : ''}</span>
                    <span className="dwm-summary-label">{t('summary_focus')}</span>
                  </div>
                </div>

              {/* Frequency section */}
              <div className="dwm-section">
                <div className="dwm-section-header">
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                  <span className="dwm-section-title">{t('section_frequency')}</span>
                </div>
                <div className="dwm-freq-row">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`dwm-freq-btn${checkCount === n ? ' active' : ''}`}
                      onClick={() => setDraftSlots(CHECK_SLOT_PRESETS[n] || CHECK_SLOT_PRESETS[3])}
                    >
                      <span className="dwm-freq-num">{n}</span>
                      <span className="dwm-freq-unit">{t('frequency_unit')}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Slots section */}
              <div className="dwm-section">
                <div className="dwm-section-header">
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  <span className="dwm-section-title">{t('section_slots')}</span>
                </div>
                <div className="dwm-slots">
                  {draftSlots.map((slot, idx) => (
                    <div key={idx} className="dwm-slot">
                      <span className="dwm-slot-badge">{idx + 1}</span>
                      <div className="dwm-slot-fields">
                        {/* Native time input for picking; resting display is the
                            house "9:00" format (no leading zero) via overlay —
                            the native control always renders zero-padded. */}
                        <span className="dwm-slot-time-wrap">
                          <input
                            type="time"
                            lang="en-GB"
                            className="dwm-slot-time"
                            value={slot.start}
                            onChange={(e) => {
                              const updated = [...draftSlots]
                              updated[idx] = { ...updated[idx], start: e.target.value }
                              setDraftSlots(updated)
                            }}
                          />
                          <span className="dwm-slot-time-display" aria-hidden="true">
                            {formatStartTime(slot.start, i18n.language)}
                          </span>
                        </span>
                        <select
                          className="dwm-slot-dur"
                          value={slot.duration}
                          onChange={(e) => {
                            const updated = [...draftSlots]
                            updated[idx] = { ...updated[idx], duration: Number(e.target.value) }
                            setDraftSlots(updated)
                          }}
                        >
                          <option value={15}>15 min</option>
                          <option value={30}>30 min</option>
                          <option value={45}>45 min</option>
                          <option value={60}>{t('duration_1h')}</option>
                          <option value={90}>{t('duration_1h30')}</option>
                          <option value={120}>{t('duration_2h')}</option>
                        </select>
                      </div>
                      <span className="dwm-slot-range">{formatSlotTime(slot.start, slot.duration, i18n.language)}</span>
                    </div>
                  ))}
                </div>
              </div>
              </div>

            </>
          ) : (
            <>
              {/* Mode toggle */}
              <button
                type="button"
                className={`dwm-mode-toggle dwm-mode-toggle--work${timer.settings.workEnabled ? ' dwm-mode-toggle--on' : ''}`}
                onClick={() => timer.setWorkEnabled(!timer.settings.workEnabled)}
              >
                <div className={`dwm-mode-toggle-track dwm-mode-toggle-track--work${timer.settings.workEnabled ? ' on' : ''}`}>
                  <div className="dwm-mode-toggle-knob" />
                </div>
                <div className="dwm-mode-toggle-text">
                  <span className="dwm-mode-toggle-title">{t('work_enabled')}</span>
                  <span className="dwm-mode-toggle-hint">
                    {!timer.settings.workEnabled
                      ? t('work_hint_off')
                      : nextWorkBlock
                        ? t('next_at_work', { time: formatStartTime(nextWorkBlock.start, i18n.language), min: nextWorkBlock.duration })
                        : workBlockCount > 0
                          ? t('next_at_done')
                          : t('work_hint', { count: workBlockCount, min: totalWorkMin })}
                  </span>
                </div>
              </button>

              <div className={`dwm-tab-content${!timer.settings.workEnabled ? ' dwm-tab-content--off' : ''}`}>
              <div className="dwm-summary-strip dwm-summary-strip--work">
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value">{workBlockCount}</span>
                    <span className="dwm-summary-label">{t('summary_blocks', { count: workBlockCount })}</span>
                  </div>
                  <div className="dwm-summary-divider" />
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value">{totalWorkMin}</span>
                    <span className="dwm-summary-label">{t('summary_min_work')}</span>
                  </div>
                  <div className="dwm-summary-divider" />
                  <div className="dwm-summary-item">
                    <span className="dwm-summary-value dwm-summary-value--work">{workH}h{workM > 0 ? String(workM).padStart(2, '0') : ''}</span>
                    <span className="dwm-summary-label">{t('summary_productive')}</span>
                  </div>
                </div>

              {/* Frequency section — work */}
              <div className="dwm-section">
                <div className="dwm-section-header">
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                  <span className="dwm-section-title">{t('section_frequency')}</span>
                </div>
                <div className="dwm-freq-row">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={`dwm-freq-btn dwm-freq-btn--work${workBlockCount === n ? ' active' : ''}`}
                      onClick={() => setDraftPersonalBlocks(WORK_BLOCK_PRESETS[n] || WORK_BLOCK_PRESETS[2])}
                    >
                      <span className="dwm-freq-num">{n}</span>
                      <span className="dwm-freq-unit">{t('frequency_unit')}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Créneaux section — work blocks */}
              <div className="dwm-section">
                <div className="dwm-section-header">
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  <span className="dwm-section-title">{t('section_slots')}</span>
                </div>
                <div className="dwm-slots">
                  {draftPersonalBlocks.map((block, idx) => (
                    <div key={idx} className="dwm-slot dwm-slot--work">
                      <span className="dwm-slot-badge dwm-slot-badge--work">{idx + 1}</span>
                      <div className="dwm-slot-fields">
                        <span className="dwm-slot-time-wrap">
                          <input
                            type="time"
                            lang="en-GB"
                            className="dwm-slot-time"
                            value={block.start}
                            onChange={(e) => {
                              const updated = [...draftPersonalBlocks]
                              updated[idx] = { ...updated[idx], start: e.target.value }
                              setDraftPersonalBlocks(updated)
                            }}
                          />
                          <span className="dwm-slot-time-display" aria-hidden="true">
                            {formatStartTime(block.start, i18n.language)}
                          </span>
                        </span>
                        <select
                          className="dwm-slot-dur"
                          value={block.duration}
                          onChange={(e) => {
                            const updated = [...draftPersonalBlocks]
                            updated[idx] = { ...updated[idx], duration: Number(e.target.value) }
                            setDraftPersonalBlocks(updated)
                          }}
                        >
                          <option value={30}>30 min</option>
                          <option value={45}>45 min</option>
                          <option value={60}>{t('duration_1h')}</option>
                          <option value={90}>{t('duration_1h30')}</option>
                          <option value={120}>{t('duration_2h')}</option>
                          <option value={180}>{t('duration_3h')}</option>
                          <option value={240}>{t('duration_4h')}</option>
                        </select>
                      </div>
                      <span className="dwm-slot-range">{formatSlotTime(block.start, block.duration, i18n.language)}</span>
                    </div>
                  ))}
                </div>
              </div>
              </div>
            </>
          )}

          {/* Priority Contacts section removed — VIP-from-label suggestions
              + manual add-input both retired. `draftVipList` initial value is
              still saved as-is so anyone who configured contacts in a prior
              version keeps them; setDraftVipList is no longer called from
              the UI, so the saved list is now read-only here. */}

          {/* Jours actifs — shared */}
          <div className="dwm-section">
            <div className="dwm-section-header">
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
                <line x1="16" x2="16" y1="2" y2="6" />
                <line x1="8" x2="8" y1="2" y2="6" />
                <line x1="3" x2="21" y1="10" y2="10" />
              </svg>
              <span className="dwm-section-title">{t('active_days')}</span>
            </div>
            <div className="dwm-weekdays">
              {WEEKDAYS.map(({ day, label }) => (
                <button
                  key={day}
                  type="button"
                  className={`dwm-day${draftWeekdays.includes(day) ? ' active' : ''}`}
                  onClick={() => {
                    setDraftWeekdays((prev) =>
                      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]
                    )
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="dwm-footer">
          <div className="dwm-footer-accent" />
          <button
            type="button"
            className="dwm-btn dwm-btn--ghost"
            onClick={handleCancel}
          >
            {tc('cancel')}
          </button>
          <button
            type="button"
            className={`dwm-btn dwm-btn--primary${saved ? ' dwm-btn--saved' : ''}`}
            onClick={handleSave}
            disabled={saved}
          >
            {saved ? tc('saved') : tc('save')}
          </button>
        </div>
      </div>
    </div>
  )
}
