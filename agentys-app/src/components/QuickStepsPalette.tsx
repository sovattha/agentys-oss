/**
 * QuickStepsPalette — Cmd+K command palette for Quick Steps.
 *
 * Mounts in the email detail view; listens for Cmd+K / Ctrl+K while an
 * email is open and surfaces a fuzzy-searchable list of the user's enabled
 * Quick Steps. Enter runs the highlighted step on the current email; Esc
 * closes the palette without running.
 *
 * Power-user surface — keyboard-only navigation with arrow keys.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'

import { useQuickSteps } from '../hooks/useQuickSteps'
import { useQuickStepRunner } from '../hooks/useQuickStepRunner'
import type {
  QuickStep,
  QuickStepExecutionReport,
} from '../types/quickStep'
import './QuickStepsPalette.css'

type TFn = (k: string, opts?: Record<string, unknown>) => string

interface QuickStepsPaletteProps {
  emailId: string | null
  onExecuted?: (report: QuickStepExecutionReport) => void
}

export function QuickStepsPalette({ emailId, onExecuted }: QuickStepsPaletteProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const { t } = useTranslation('settings')

  const { steps } = useQuickSteps()
  const runner = useQuickStepRunner(report => {
    setOpen(false)
    onExecuted?.(report)
  })

  const enabled = useMemo(() => steps.filter(s => s.enabled), [steps])
  const filtered = useMemo(() => filterSteps(enabled, query), [enabled, query])

  // Keep the active index inside bounds when filtering.
  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(0)
  }, [filtered.length, activeIndex])

  // Global Cmd+K / Ctrl+K toggle — only while an email is open.
  useEffect(() => {
    if (!emailId) return
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K')) {
        event.preventDefault()
        setOpen(prev => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [emailId])

  // Focus the input as soon as the palette mounts so typing is immediate.
  useEffect(() => {
    if (open) {
      setQuery('')
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  const close = useCallback(() => setOpen(false), [])

  const runActive = useCallback(
    (event?: React.KeyboardEvent | KeyboardEvent) => {
      if (!emailId) return
      const target = filtered[activeIndex]
      if (!target) return
      const bypass = !!event && (event as KeyboardEvent).shiftKey
      void runner.run(target, emailId, { bypassConfirm: bypass })
    },
    [emailId, filtered, activeIndex, runner],
  )

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex(i => Math.min(i + 1, Math.max(0, filtered.length - 1)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex(i => Math.max(0, i - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      runActive(event)
    }
  }

  if (!open || !emailId) {
    // Still render the confirm modal even when the palette is closed —
    // a step started from the palette and now needs confirmation should
    // not be lost when the palette unmounts.
    return runner.pendingConfirm ? (
      <ConfirmFromPalette
        step={runner.pendingConfirm}
        onCancel={runner.cancelConfirm}
        onConfirm={runner.confirm}
      />
    ) : null
  }

  return (
    <div
      className="qs-palette"
      role="dialog"
      aria-modal="true"
      aria-label={t('quicksteps_palette_aria')}
      onClick={close}
      data-escape-owner=""
    >
      <div className="qs-palette__panel" onClick={e => e.stopPropagation()}>
        <input
          ref={inputRef}
          type="text"
          className="qs-palette__input"
          placeholder={t('quicksteps_palette_search_placeholder')}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        {filtered.length === 0 ? (
          <div className="qs-palette__empty">{t('quicksteps_palette_empty')}</div>
        ) : (
          <ul className="qs-palette__list" role="listbox">
            {filtered.map((step, index) => (
              <li
                key={step.id}
                role="option"
                aria-selected={index === activeIndex}
                className="qs-palette__item"
                data-active={index === activeIndex || undefined}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={event => {
                  event.stopPropagation()
                  void runner.run(step, emailId, { bypassConfirm: event.shiftKey })
                }}
              >
                <span className="qs-palette__name">{step.name}</span>
                <span className="qs-palette__summary">{summarize(step, t)}</span>
                {step.shortcut && (
                  <kbd className="qs-palette__kbd">{formatShortcut(step.shortcut)}</kbd>
                )}
              </li>
            ))}
          </ul>
        )}
        <footer className="qs-palette__footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('quicksteps_palette_footer_nav')}</span>
          <span><kbd>↵</kbd> {t('quicksteps_palette_footer_run')}</span>
          <span><kbd>{t('quicksteps_palette_kbd_shift')}</kbd>+<kbd>↵</kbd> {t('quicksteps_palette_footer_no_confirm')}</span>
          <span><kbd>Esc</kbd> {t('quicksteps_palette_footer_close')}</span>
        </footer>
      </div>

      {runner.pendingConfirm && (
        <ConfirmFromPalette
          step={runner.pendingConfirm}
          onCancel={runner.cancelConfirm}
          onConfirm={runner.confirm}
        />
      )}
    </div>
  )
}

interface ConfirmFromPaletteProps {
  step: QuickStep
  onCancel: () => void
  onConfirm: () => void
}

function ConfirmFromPalette({ step, onCancel, onConfirm }: ConfirmFromPaletteProps) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel, onConfirm])

  return (
    <div className="qs-palette__confirm" role="dialog" aria-modal="true">
      <div className="qs-palette__confirm-panel">
        <h4>{t('quicksteps_confirm_title', { name: step.name })}</h4>
        <ul>
          {step.actions.map((a, i) => (
            <li key={i}>{i + 1}. {actionLabel(a, t)}</li>
          ))}
        </ul>
        <div className="qs-palette__confirm-cta">
          <button type="button" onClick={onCancel}>{tCommon('cancel')}</button>
          <button type="button" className="primary" onClick={onConfirm} autoFocus>
            {tCommon('confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

function filterSteps(steps: QuickStep[], query: string): QuickStep[] {
  if (!query.trim()) return steps
  const needle = query.toLowerCase()
  return steps
    .map(step => ({ step, score: scoreMatch(step, needle) }))
    .filter(entry => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(entry => entry.step)
}

function scoreMatch(step: QuickStep, needle: string): number {
  const name = step.name.toLowerCase()
  if (name === needle) return 100
  if (name.startsWith(needle)) return 50
  if (name.includes(needle)) return 20
  // Subsequence match — every char in needle appears in order in name.
  let cursor = 0
  for (const char of needle) {
    const idx = name.indexOf(char, cursor)
    if (idx === -1) return 0
    cursor = idx + 1
  }
  return 5
}

function summarize(step: QuickStep, t: TFn): string {
  return step.actions.map(a => actionLabel(a, t)).join(' → ')
}

function actionLabel(action: QuickStep['actions'][number], t: TFn): string {
  switch (action.type) {
    case 'archive': return t('quicksteps_action_archive')
    case 'delete': return t('quicksteps_action_delete')
    case 'mark_read': return action.payload.value
      ? t('quicksteps_chain_mark_read')
      : t('quicksteps_chain_mark_unread')
    case 'move_to_spam': return t('quicksteps_action_move_to_spam')
    case 'reply_template': return t('quicksteps_chain_reply_template')
    case 'forward': return t('quicksteps_chain_forward_count', { count: action.payload.to.length })
    default: return (action as { type: string }).type
  }
}

function formatShortcut(value: string): string {
  return value
    .split('+')
    .map(p => (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)))
    .join('+')
}
