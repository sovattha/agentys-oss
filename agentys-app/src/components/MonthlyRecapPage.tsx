import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, type MonthlyRecap } from '../services/api'
import { referralService } from '../services/subscription'
import { copyToClipboard } from '../utils/clipboard'
import { CloseIcon, ChevronLeftIcon, ChevronRightIcon } from './icons/ActionIcons'
import './MonthlyRecapPage.css'

interface MonthlyRecapPageProps {
  onClose: () => void
  onBack?: () => void
}

function formatHoursParts(hours: number): { num: string; unit: string } {
  if (hours <= 0) return { num: '0', unit: 'h' }
  const total = Math.round(hours * 60)
  if (total < 60) return { num: `${total}`, unit: 'min' }
  const h = Math.floor(total / 60)
  const m = total % 60
  if (m === 0) return { num: `${h}`, unit: 'h' }
  return { num: `${h}h${m < 10 ? '0' : ''}${m}`, unit: '' }
}

function formatMinutes(minutes: number): string {
  if (minutes <= 0) return '0 min'
  if (minutes < 1) return '<1 min'
  if (minutes < 60) return `${Math.round(minutes)} min`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}min` : `${h}h`
}

function formatMonthLabel(yyyyMm: string, locale: string): string {
  const [year, month] = yyyyMm.split('-').map(Number)
  const date = new Date(year, month - 1, 1)
  const name = date.toLocaleString(locale, { month: 'long' })
  return `${name.toUpperCase()} ${year}`
}

function previousMonth(yyyyMm: string): string {
  const [year, month] = yyyyMm.split('-').map(Number)
  const prev = new Date(year, month - 2, 1)
  return `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`
}

function localizeDetail(f: { key: string; detail: string }, t: (k: string, opts?: Record<string, unknown>) => string): string {
  const num = parseInt(f.detail, 10)
  const count = isNaN(num) ? 0 : num
  const keyMap: Record<string, string> = {
    ai_drafting: 'recap_detail_drafts',
    autosort: 'recap_detail_sorted',
    autoarchive: 'recap_detail_archived',
    shortcuts: 'recap_detail_actions',
    followup: 'recap_detail_reminders',
    attachment_reminder: 'recap_detail_reminders',
  }
  const key = keyMap[f.key]
  if (!key) return f.detail
  return t(key, { count })
}

function AiRing({ percent }: { percent: number }) {
  const r = 22
  const c = 2 * Math.PI * r
  const ringRef = useRef<SVGCircleElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      if (ringRef.current) {
        const offset = c - (c * Math.min(percent, 100)) / 100
        ringRef.current.style.strokeDashoffset = `${offset}`
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [percent, c])

  return (
    <div className="recap-ai-ring">
      <svg aria-hidden="true" width="42" height="42" viewBox="0 0 52 52">
        <circle className="recap-ai-ring-bg" cx="26" cy="26" r={r} />
        <circle ref={ringRef} className="recap-ai-ring-fill" cx="26" cy="26" r={r} />
      </svg>
      <span className="recap-ai-ring-text">{percent}%</span>
    </div>
  )
}

const FEATURE_ICONS: Record<string, React.ReactElement> = {
  ai_drafting: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M11.5 2.5L13.5 4.5L5 13H3V11L11.5 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"/>
      <path d="M9.5 4.5L11.5 6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  ),
  autosort: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M2.5 4.5H13.5M4.5 8H11.5M6.5 11.5H9.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  ),
  autoarchive: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="12" height="2.5" rx="1" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M3 5.5V13H13V5.5" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
      <path d="M6 9H10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  ),
  shortcuts: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="1.5" y="4.5" width="13" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M4.5 8H5.5M7.5 8H8.5M10.5 8H11.5M6 10.5H10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  ),
  attachment_reminder: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13 8.5V11.5C13 12.6 12.1 13.5 11 13.5H5C3.9 13.5 3 12.6 3 11.5V4.5C3 3.4 3.9 2.5 5 2.5H8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <path d="M10.5 2.5L13.5 5.5L9 10H6V7L10.5 2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round"/>
    </svg>
  ),
  followup: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4"/>
      <path d="M8 5V8.5L10.5 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  default: (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.4"/>
    </svg>
  ),
}

export function MonthlyRecapPage({ onClose, onBack }: MonthlyRecapPageProps) {
  const { t, i18n } = useTranslation('settings')
  const [recap, setRecap] = useState<MonthlyRecap | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [linkCopied, setLinkCopied] = useState(false)
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiClient.getMonthlyRecap()
      .then(data => {
        if (!cancelled) {
          setRecap(data)
          setSelectedMonth(data.month)
        }
      })
      .catch(err => { if (!cancelled) setError(err.message || 'error') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const referralStats = useMemo(() => referralService.getReferralStats(), [])

  const handleCopyLink = useCallback(async () => {
    const link = referralStats?.link || 'https://agentys.app'
    // F-11 / Site 7 (audit 2026-06-11) : copyToClipboard ne throw jamais — il
    // retourne false quand les deux stratégies échouent. L'ancien try/catch ne
    // captait donc rien et « Copié ✓ » s'affichait même en échec.
    const ok = await copyToClipboard(link)
    if (ok) {
      setLinkCopied(true)
      setTimeout(() => setLinkCopied(false), 2000)
    } else {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('common:toasts.copy_failed'), type: 'warning' },
      }))
    }
  }, [referralStats, t])

  const handleEmailInvite = useCallback(() => {
    const link = referralStats?.link || 'https://agentys.app'
    const subject = encodeURIComponent('Try Agentys - AI Email Management')
    const body = encodeURIComponent(`I use Agentys to manage my emails and it's amazing!\nTry it for free: ${link}`)
    window.location.href = `mailto:?subject=${subject}&body=${body}`
  }, [referralStats])

  const goPrevMonth = useCallback(() => {
    if (!selectedMonth) return
    const [year, month] = selectedMonth.split('-').map(Number)
    const prev = new Date(year, month - 2, 1)
    setSelectedMonth(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`)
  }, [selectedMonth])

  const nextMonthDisabled = useMemo(() => {
    if (!selectedMonth) return true
    const [year, month] = selectedMonth.split('-').map(Number)
    const next = new Date(year, month, 1)
    const nextMonth = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
    const today = new Date()
    const current = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
    return nextMonth > current
  }, [selectedMonth])

  const goNextMonth = useCallback(() => {
    if (!selectedMonth || nextMonthDisabled) return
    const [year, month] = selectedMonth.split('-').map(Number)
    const next = new Date(year, month, 1)
    setSelectedMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`)
  }, [selectedMonth, nextMonthDisabled])

  if (loading) {
    return (
      <div className="recap-page">
        <div className="recap-top-bar">
          {onBack ? <span /> : <span />}
          <button className="recap-close" onClick={onClose} aria-label={t('recap_close')}>
            <CloseIcon size={16} />
          </button>
        </div>
        <div className="recap-loading">
          <div className="recap-skeleton recap-skeleton-title" />
          <div className="recap-skeleton recap-skeleton-tiles" />
          <div className="recap-skeleton-grid">
            <div className="recap-skeleton recap-skeleton-chip" />
            <div className="recap-skeleton recap-skeleton-chip" />
          </div>
          <div className="recap-skeleton recap-skeleton-row" />
          <div className="recap-skeleton recap-skeleton-row" />
          <div className="recap-skeleton recap-skeleton-row" />
        </div>
      </div>
    )
  }

  if (error || !recap) {
    return (
      <div className="recap-page">
        <div className="recap-top-bar">
          <span />
          <button className="recap-close" onClick={onClose} aria-label={t('recap_close')}>
            <CloseIcon size={16} />
          </button>
        </div>
        <div className="recap-error">
          <div className="recap-error-icon">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <circle cx="16" cy="16" r="13.5" stroke="currentColor" strokeWidth="1.5" opacity="0.3"/>
              <path d="M16 10V17" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
              <circle cx="16" cy="21" r="1.2" fill="currentColor"/>
            </svg>
          </div>
          <p>{error === 'Failed to fetch' ? t('recap_error_backend') : t('recap_error_no_data')}</p>
          <button className="recap-btn recap-btn-primary" onClick={onClose}>{t('recap_close')}</button>
        </div>
      </div>
    )
  }

  const best = recap.best || {}
  const breakdown = recap.feature_breakdown || []
  const hasActivity =
    recap.is_empty === false ||
    recap.time_saved_hours > 0 ||
    breakdown.length > 0 ||
    recap.inbox_zero_days > 0 ||
    recap.days_active > 0 ||
    recap.drafts_generated > 0
  const isEmpty = recap.is_empty ?? !hasActivity
  const isPartial = recap.data_quality === 'partial'
  const isFirstMonth = recap.comparison.type === 'first_month' && !isEmpty
  const canShowRecords = !isEmpty && !isPartial
  const isBest = (key: keyof typeof best, value: number, lowerBetter = false) => {
    if (isFirstMonth || !canShowRecords) return false
    const b = best[key]
    if (b === undefined || b === null) return false
    if (lowerBetter) return value > 0 && value <= b
    return value >= b && value > 0
  }

  const maxMinutes = Math.max(...breakdown.map(f => f.minutes), 1)

  const monthHero = formatHoursParts(recap.time_saved_hours)

  // Delta tile: skip entirely for first month, otherwise show a badge and short subtitle
  const delta = recap.comparison.delta_hours
  const deltaType = recap.comparison.type
  const deltaTone =
    isEmpty || deltaType === 'empty' ? 'flat' :
    deltaType === 'improving' ? 'up' :
    deltaType === 'declining' ? 'down' : 'flat'

  const deltaBadge = (() => {
    if (isEmpty || deltaType === 'empty') return '—'
    if (deltaType === 'improving') return `+${delta}h`
    if (deltaType === 'declining') return `−${Math.abs(delta)}h`
    return '='
  })()

  const comparisonMessage = (() => {
    const prevLabel = formatMonthLabel(previousMonth(selectedMonth || recap.month), i18n.language)
    if (isEmpty || deltaType === 'empty') {
      return t('recap_comparison_empty', 'Not enough data to compare this month yet.')
    }
    if (deltaType === 'first_month') {
      return t('recap_first_month_sub', 'Your first full month — this is the baseline.')
    }
    if (deltaType === 'improving') {
      return t('recap_comparison_improving', { delta, month: prevLabel })
    }
    if (deltaType === 'declining') {
      return t('recap_comparison_declining', { delta: Math.abs(delta), month: prevLabel })
    }
    if (deltaType === 'same') {
      return t('recap_comparison_same', { month: prevLabel })
    }
    return recap.comparison.message
  })()

  return (
    <div className="recap-page">
      <div className="recap-top-bar">
        {onBack ? (
          <button className="recap-back" onClick={onBack} aria-label={t('common:back')} title={t('common:back')}>
            <ChevronLeftIcon />
          </button>
        ) : <span />}
        <button className="recap-close" onClick={onClose} aria-label={t('recap_close')}>
          <CloseIcon size={16} />
        </button>
      </div>

      {/* 1. Month header */}
      <div className="recap-section recap-section-1">
        <div className="recap-month-header">
          <button
            className="recap-month-nav-btn"
            onClick={goPrevMonth}
            aria-label={t('common:previous', 'Previous month')}
            title={t('common:previous', 'Previous month')}
          >
            <ChevronLeftIcon />
          </button>
          <div className="recap-month-label">
            {t('recap_title', { month: formatMonthLabel(selectedMonth || recap.month, i18n.language) })}
          </div>
          <button
            className="recap-month-nav-btn"
            onClick={goNextMonth}
            disabled={nextMonthDisabled}
            aria-label={t('common:next', 'Next month')}
            title={t('common:next', 'Next month')}
          >
            <ChevronRightIcon />
          </button>
        </div>
      </div>

      {/* 2. Two tiles: THIS MONTH · vs PREV */}
      <div className="recap-section recap-section-2">
        <div className="recap-tiles">
          <div className={`recap-tile${hasActivity ? ' recap-tile-glow' : ''}`}>
            <span className="recap-tile-period">{t('recap_period_this_month', 'This month')}</span>
            <div className="recap-tile-hero">
              <span className="recap-tile-num">{monthHero.num}</span>
              {monthHero.unit && <span className="recap-tile-unit">{monthHero.unit}</span>}
            </div>
            <span className="recap-tile-sub">{t('recap_hero_text')}</span>
          </div>

          <div className="recap-tile">
            {isFirstMonth ? (
              <>
                <span className="recap-tile-period">{t('recap_period_baseline', 'Baseline')}</span>
                <div className="recap-tile-hero">
                  <span className="recap-tile-num" style={{ fontSize: 'var(--font-size-xl)' }}>
                    {t('recap_first_month_badge', 'New')}
                  </span>
                </div>
                <span className="recap-tile-sub">{t('recap_first_month_sub', 'Your first full month — this is the baseline.')}</span>
              </>
            ) : (
              <>
                <span className="recap-tile-period">
                  {isEmpty || deltaType === 'empty'
                    ? t('recap_period_no_comparison', 'No comparison')
                    : t('recap_period_vs_prev', 'vs previous month')}
                </span>
                <div className="recap-tile-hero">
                  <span className={`recap-tile-delta-badge recap-tile-delta-${deltaTone}`}>
                    {deltaBadge}
                  </span>
                </div>
                <span className="recap-tile-sub">{comparisonMessage}</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* 3. Inline chips: INBOX ZERO · AI-ASSISTED */}
      <div className="recap-section recap-section-3">
        <div className="recap-chips">
          <div className={`recap-chip${isBest('inbox_zero_days', recap.inbox_zero_days) ? ' is-best' : ''}`}>
            <div className="recap-chip-body">
              <span className="recap-chip-label">{t('recap_stat_inbox_zero')}</span>
              <div className="recap-chip-value-row">
                <span className="recap-chip-value">
                  {t('recap_inbox_zero_value', { count: recap.inbox_zero_days })}
                </span>
                {isFirstMonth && canShowRecords ? (
                  <span className="recap-chip-new">{t('recap_new_record')}</span>
                ) : canShowRecords && best.inbox_zero_days !== undefined && best.inbox_zero_days !== null && best.inbox_zero_days > 0 ? (
                  <span className="recap-chip-meta">
                    <span className="recap-chip-meta-star">{'✦'}</span>
                    {t('recap_inbox_zero_record', { count: best.inbox_zero_days })}
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className={`recap-chip${isBest('ai_assisted_percent', recap.ai_assisted_percent) ? ' is-best' : ''}`}>
            <AiRing percent={isEmpty ? 0 : recap.ai_assisted_percent} />
            <div className="recap-chip-body">
              <span className="recap-chip-label">{t('recap_stat_ai_assisted')}</span>
              <div className="recap-chip-value-row">
                {isFirstMonth && canShowRecords ? (
                  <span className="recap-chip-new">{t('recap_new_record')}</span>
                ) : canShowRecords && (best.ai_assisted_percent ?? 0) > 0 ? (
                  <span className="recap-chip-meta">
                    <span className="recap-chip-meta-star">{'✦'}</span>
                    {t('recap_ai_assisted_record', { percent: best.ai_assisted_percent ?? 0 })}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 4. Gain breakdown OR empty state */}
      <div className="recap-section recap-section-4">
        {breakdown.length > 0 ? (
          <div className="recap-breakdown">
            <div className="recap-breakdown-header">{t('recap_breakdown_header')}</div>
            {breakdown.map((f) => (
              <div key={f.key} className="recap-breakdown-row">
                <span className="recap-breakdown-icon">
                  {FEATURE_ICONS[f.key] ?? FEATURE_ICONS.default}
                </span>
                <div className="recap-breakdown-content">
                  <div className="recap-breakdown-top">
                    <span className="recap-breakdown-label">{t(`recap_feat_${f.key}`, f.label)}</span>
                    <span className="recap-breakdown-time">{formatMinutes(f.minutes)}</span>
                  </div>
                  <div className="recap-breakdown-bar-track">
                    <div
                      className="recap-breakdown-bar-fill"
                      style={{ width: `${Math.max(3, (f.minutes / maxMinutes) * 100)}%` }}
                    />
                  </div>
                  <span className="recap-breakdown-detail">{localizeDetail(f, t)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className={`recap-empty${isPartial ? ' recap-empty-partial' : ''}`}>
            <div className="recap-empty-icon">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6.5 2h11" />
                <path d="M6.5 22h11" />
                <path d="M7.5 2v2.5c0 2.2 1.2 4.2 3.1 5.3L12 10.7l-1.4.9A6.3 6.3 0 0 0 7.5 17v5" />
                <path d="M16.5 2v2.5c0 2.2-1.2 4.2-3.1 5.3L12 10.7l1.4.9a6.3 6.3 0 0 1 3.1 5.4v5" />
              </svg>
            </div>
            <p className="recap-empty-text">
              {t(isPartial ? 'recap_partial_text' : 'recap_empty_text')}
            </p>
            <p className="recap-empty-hint">
              {t(isPartial ? 'recap_partial_hint' : 'recap_empty_hint')}
            </p>
          </div>
        )}
      </div>

      {/* 5. Footer referral (demoted) */}
      <div className="recap-section recap-section-5">
        <div className="recap-foot">
          <span className="recap-foot-text">{t('recap_referral_title')}</span>
          <span className="recap-foot-actions">
            <button
              type="button"
              className="recap-foot-link"
              onClick={handleEmailInvite}
              aria-label={t('recap_invite_email')}
            >
              {t('recap_invite_email')}
            </button>
            <button
              type="button"
              className={`recap-foot-link${linkCopied ? ' copied' : ''}`}
              onClick={handleCopyLink}
            >
              {linkCopied ? t('recap_copied') : t('recap_copy_link')}
            </button>
            {referralStats && referralStats.referralsCount > 0 && (
              <span className="recap-foot-count">
                · {t('recap_referral_count', { count: referralStats.referralsCount })}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  )
}
