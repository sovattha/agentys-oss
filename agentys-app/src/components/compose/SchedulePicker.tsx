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

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CloseIcon } from '../icons/ActionIcons'
import { formatShortDateFromDate, formatHourMinute } from '../../utils/dateFormat'
import './SchedulePicker.css'

interface Position {
  x: number
  y: number
  buttonTop?: number
}

interface SchedulePickerProps {
  position: Position
  onSelect: (dateUtc: Date) => void
  onClose: () => void
  /** Si true, affiche le bouton "Programmer maintenant" pour confirmer une date deja choisie */
  initialDate?: Date | null
}

interface Preset {
  key: string
  label: string
  iso: string  // affichage local "26 avr 08 h 00"
  date: Date   // local Date
}

function _nextMonday(now: Date): Date {
  const d = new Date(now)
  const dow = d.getDay() // 0=Sun, 1=Mon...
  const daysUntilMonday = ((1 - dow) + 7) % 7 || 7  // si on est lundi, on prend le suivant
  d.setDate(d.getDate() + daysUntilMonday)
  d.setHours(8, 0, 0, 0)
  return d
}

function _formatPresetTime(d: Date, locale: string): string {
  // House style: ordinal date + 24h clock — "Apr 26th, 8:00" (EN) / "26 avr, 8h00" (FR).
  // Date via the shared ordinal helper, time via the app-wide clock-time contract.
  return `${formatShortDateFromDate(d, locale)}, ${formatHourMinute(d, locale)}`
}

function _buildPresets(now: Date, locale: string, t: (k: string, fallback?: string) => string): Preset[] {
  const tomorrowMorning = new Date(now)
  tomorrowMorning.setDate(now.getDate() + 1)
  tomorrowMorning.setHours(8, 0, 0, 0)

  const tomorrowAfternoon = new Date(tomorrowMorning)
  tomorrowAfternoon.setHours(13, 0, 0, 0)

  const monday = _nextMonday(now)

  return [
    {
      key: 'tomorrow_morning',
      label: t('schedule_tomorrow_morning', 'Demain matin'),
      iso: _formatPresetTime(tomorrowMorning, locale),
      date: tomorrowMorning,
    },
    {
      key: 'tomorrow_afternoon',
      label: t('schedule_tomorrow_afternoon', 'Demain après-midi'),
      iso: _formatPresetTime(tomorrowAfternoon, locale),
      date: tomorrowAfternoon,
    },
    {
      key: 'monday_morning',
      label: t('schedule_monday_morning', 'Lundi matin'),
      iso: _formatPresetTime(monday, locale),
      date: monday,
    },
  ]
}

function _toLocalInputValue(d: Date): string {
  // datetime-local accepte "YYYY-MM-DDTHH:mm" (sans timezone, heure locale)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function SchedulePicker({ position, onSelect, onClose, initialDate }: SchedulePickerProps) {
  const { t, i18n } = useTranslation('inbox')
  const locale = i18n.language?.slice(0, 2) || 'fr'
  const [showCustom, setShowCustom] = useState(false)
  const [customValue, setCustomValue] = useState(() => {
    const base = initialDate || (() => {
      const d = new Date()
      d.setHours(d.getHours() + 1, 0, 0, 0)
      return d
    })()
    return _toLocalInputValue(base)
  })
  const ref = useRef<HTMLDivElement | null>(null)

  // Recompute on each render so presets stay anchored to "now" if the popover
  // stays open across midnight; the cost is one Date alloc + 3 toLocaleString.
  const presets = _buildPresets(new Date(), locale, (k: string, fb?: string) => t(k, fb || k) as string)

  // Click hors popover -> close
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // ESC -> close
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleCustomConfirm = () => {
    const local = new Date(customValue)
    if (isNaN(local.getTime())) return
    if (local.getTime() <= Date.now()) return
    onSelect(local)
  }

  // P3-18 (2026-05-17): pin the popover inside the viewport. The previous
  // logic always placed the popover 240px above the chevron, which could
  // produce a negative `top` when the compose modal was scrolled near the
  // top of the page — the popover rendered off-screen and looked "broken"
  // (the QA "click does nothing" repro on small viewports).
  const PICKER_HEIGHT = 260
  const topAbove = (position.buttonTop ?? position.y) - PICKER_HEIGHT
  const topBelow = position.y + 8
  const fitsAbove = topAbove >= 8
  const fitsBelow = topBelow + PICKER_HEIGHT <= (typeof window !== 'undefined' ? window.innerHeight : Infinity) - 8
  const finalTop = fitsAbove ? topAbove : (fitsBelow ? topBelow : Math.max(8, (typeof window !== 'undefined' ? window.innerHeight - PICKER_HEIGHT - 8 : topAbove)))

  return (
    <div
      ref={ref}
      className="schedule-picker"
      role="dialog"
      aria-label={t('schedule_picker_title', 'Planifier un envoi')}
      style={{
        position: 'fixed',
        left: position.x,
        top: finalTop,
        zIndex: 5000,
      }}
      data-testid="schedule-picker"
      data-escape-owner=""
    >
      <header className="schedule-picker__header">
        <span>{t('schedule_picker_title', 'Planifier un envoi')}</span>
        <button
          type="button"
          className="schedule-picker__close"
          onClick={onClose}
          aria-label={t('close', 'Fermer')}
        >
          <CloseIcon size={16} />
        </button>
      </header>

      {!showCustom && (
        <ul className="schedule-picker__presets">
          {presets.map((p) => (
            <li key={p.key}>
              <button
                type="button"
                className="schedule-picker__preset"
                onClick={() => onSelect(p.date)}
                data-testid={`schedule-preset-${p.key}`}
              >
                <span className="schedule-picker__preset-label">{p.label}</span>
                <span className="schedule-picker__preset-time">{p.iso}</span>
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="schedule-picker__custom-btn"
              onClick={() => setShowCustom(true)}
              data-testid="schedule-custom-btn"
            >
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                <rect width="18" height="18" x="3" y="4" rx="2" />
                <path d="M16 2v4" /><path d="M8 2v4" /><path d="M3 10h18" />
              </svg>
              <span>{t('schedule_pick_datetime', 'Selectionner une date et une heure')}</span>
            </button>
          </li>
        </ul>
      )}

      {showCustom && (
        <div className="schedule-picker__custom">
          <label className="schedule-picker__custom-label">
            {t('schedule_custom_label', 'Date et heure')}
            <input
              type="datetime-local"
              value={customValue}
              onChange={(e) => setCustomValue(e.target.value)}
              min={_toLocalInputValue(new Date(Date.now() + 60_000))}
              data-testid="schedule-custom-input"
            />
          </label>
          <div className="schedule-picker__custom-actions">
            <button
              type="button"
              className="schedule-picker__custom-back"
              onClick={() => setShowCustom(false)}
            >
              {t('back', 'Retour')}
            </button>
            <button
              type="button"
              className="schedule-picker__custom-confirm"
              onClick={handleCustomConfirm}
              data-testid="schedule-custom-confirm"
            >
              {t('schedule_confirm', 'Programmer')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
