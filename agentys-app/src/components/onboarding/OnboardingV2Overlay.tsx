import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { V2Phase } from '../../hooks/useOnboardingV2'
import { TriangleLogo } from '../brand/TriangleLogo'
import { LabelBadge } from '../labels/LabelBadge'
import { DEFAULT_LABELS } from '../../types/labels'
import './OnboardingV2Overlay.css'

interface Props {
  phase: V2Phase
  onNext: () => void
  onSkip: () => void
  isMobile?: boolean
  onOpenNewMessage?: () => void
}

// Drill into the `.shortcut-key` span so the arrow points at the literal "N"
// pill rather than the whole shortcut item (key + label). The CSS spotlight
// at OnboardingV2Overlay.css:785 still illuminates the parent item, so the
// user sees "the highlighted area is the [N] key with the 'New message'
// label" while the arrow tightly targets the keycap.
const SHORTCUT_TARGET = '[data-onboarding-target="new-message"] .shortcut-key'
// Spotlight on the actual LABEL pill inside the first email row (2026-05-05).
// Was `.swipeable-email-item` (whole row) but the user feedback was clear:
// "point the label!" — the tip tells users to right-click the label to
// retrain auto-sort, so the spotlight should target the label itself.
//
// 2026-05-22 — we deliberately DON'T fall back to the bare row anymore. On a
// first run the background labeller (daemon, ~1 Haiku call/email) hasn't
// produced any label yet, so pointing the tooltip at an unlabeled row taught
// a feature the user couldn't see. When no label pill exists we render the
// self-contained "sorting in progress" card with sample badges instead.
const EMAIL_LABEL_TARGET = '.swipeable-email-item .label-badge'

export function OnboardingV2Overlay({ phase, onNext, onSkip, isMobile = false, onOpenNewMessage }: Props) {
  const { t } = useTranslation('onboarding')
  const [pillRect, setPillRect] = useState<DOMRect | null>(null)
  const [emailRect, setEmailRect] = useState<DOMRect | null>(null)

  useEffect(() => {
    if (phase !== 'shortcutBar') {
      setPillRect(null)
      return
    }
    const findRect = () => {
      const el = document.querySelector<HTMLElement>(SHORTCUT_TARGET)
      setPillRect(el ? el.getBoundingClientRect() : null)
    }
    findRect()
    const retry = setTimeout(findRect, 150)
    window.addEventListener('resize', findRect)
    window.addEventListener('scroll', findRect, true)
    return () => {
      clearTimeout(retry)
      window.removeEventListener('resize', findRect)
      window.removeEventListener('scroll', findRect, true)
    }
  }, [phase])

  useEffect(() => {
    if (phase !== 'labelTip') {
      setEmailRect(null)
      return
    }
    // Only anchor the spotlight to a real label pill. When none exists yet
    // (first run, labelling still in flight) emailRect stays null and the
    // centered "sorting in progress" card is shown. We poll briefly (~2s) so a
    // label that lands a beat later upgrades the card into the anchored
    // spotlight — but once anchored we stop, to avoid a jarring late jump
    // while the user is reading the centered card.
    let settled = false
    const findRect = () => {
      const labelEl = document.querySelector<HTMLElement>(EMAIL_LABEL_TARGET)
      if (labelEl) {
        settled = true
        setEmailRect(labelEl.getBoundingClientRect())
      }
    }
    findRect()
    const poll = setInterval(() => {
      if (settled) return
      findRect()
    }, 300)
    const stop = setTimeout(() => clearInterval(poll), 2100)
    window.addEventListener('resize', findRect)
    window.addEventListener('scroll', findRect, true)
    return () => {
      clearInterval(poll)
      clearTimeout(stop)
      window.removeEventListener('resize', findRect)
      window.removeEventListener('scroll', findRect, true)
    }
  }, [phase])

  if (phase === 'idle') return null

  if (phase === 'welcome') {
    return (
      <div className="ob-v2-backdrop ob-v2-backdrop--hero" role="dialog" aria-modal="true">
        <div className="ob-v2-ambient" aria-hidden="true">
          <span className="ob-v2-orb ob-v2-orb--a" />
          <span className="ob-v2-orb ob-v2-orb--b" />
          <span className="ob-v2-orb ob-v2-orb--c" />
        </div>
        <div className="ob-v2-card ob-v2-card--premium ob-v2-welcome">
          <div className="ob-v2-card-shimmer" aria-hidden="true" />
          <div className="ob-v2-logo-wrap">
            <span className="ob-v2-logo-glow" aria-hidden="true" />
            <TriangleLogo size={56} />
          </div>
          <div className="ob-v2-eyebrow">{t('v2_eyebrow_last')}</div>
          <h2 className="ob-v2-display">{t('v2_welcome_title')}</h2>
          <p className="ob-v2-welcome-desc">{t('v2_welcome_desc')}</p>
          <div className="ob-v2-actions ob-v2-actions--stacked">
            <button type="button" className="ob-v2-btn-primary" onClick={onNext}>
              <span>{t('v2_welcome_cta')}</span>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M2 7h10m0 0L7.5 2.5M12 7l-4.5 4.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button type="button" className="ob-v2-btn-skip" onClick={onSkip}>
              {t('v2_skip')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (phase === 'labelTip') {
    if (!emailRect) {
      return (
        <div className="ob-v2-backdrop ob-v2-backdrop--light" role="dialog" aria-modal="true" onClick={onSkip}>
          <div className="ob-v2-card ob-v2-card--premium" onClick={(e) => e.stopPropagation()}>
            <div className="ob-v2-card-shimmer" aria-hidden="true" />
            <div className="ob-v2-label-icon-badge" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M7 7h-.01M3 11.5L11.5 3H21v9.5L12.5 21a2 2 0 01-2.83 0l-6.17-6.17A2 2 0 013 13.5v-2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h2 className="ob-v2-display">{t('v2_label_title')}</h2>
            <p className="ob-v2-label-sorting">{t('v2_label_sorting')}</p>
            <div className="ob-v2-label-samples">
              {DEFAULT_LABELS.map((l) => (
                <LabelBadge key={l.name} name={l.name} color={l.color} size="medium" />
              ))}
            </div>
            <p>{t('v2_label_desc')}</p>
            <p>{t('v2_label_desc_2')}</p>
            <div className="ob-v2-actions ob-v2-actions--stacked">
              <button type="button" className="ob-v2-btn-primary" onClick={onNext}>
                <span>{t('v2_label_cta')}</span>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M2 7h10m0 0L7.5 2.5M12 7l-4.5 4.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <button type="button" className="ob-v2-btn-skip" onClick={onSkip}>
                {t('v2_skip')}
              </button>
            </div>
          </div>
        </div>
      )
    }

    // emailRect now refers to the LABEL pill (not the whole row) when one
    // is found — see EMAIL_LABEL_TARGET. Tooltip arrow points at the label
    // center horizontally; falls back to row-center when no label visible.
    const targetCenterX = emailRect.left + emailRect.width / 2
    const tooltipWidth = 320
    const halfTip = tooltipWidth / 2
    const viewportMargin = 16
    let tipLeft = targetCenterX - halfTip
    tipLeft = Math.max(viewportMargin, Math.min(tipLeft, window.innerWidth - tooltipWidth - viewportMargin))
    const tipTop = emailRect.bottom + 20
    const arrowLeft = Math.max(20, Math.min(targetCenterX - tipLeft, tooltipWidth - 20))

    // 2026-05-05 — backdrop removed per user directive ("no black screen
    // or blur screen"). The spotlight + tooltip alone are enough to draw
    // attention without dimming the inbox. Click-outside-to-dismiss is
    // gone too — user has the explicit Skip button + Got it CTA in the
    // tip card. The spotlight gets a tighter padding (2px) since it now
    // wraps a small label pill rather than a full row.
    return (
      <>
        <div
          className="ob-v2-tip ob-v2-tip--premium ob-v2-tip--anchored"
          role="dialog"
          aria-modal="false"
          style={{ left: tipLeft, top: tipTop, width: tooltipWidth }}
        >
          <h4 className="ob-v2-tip-title-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M7 7h-.01M3 11.5L11.5 3H21v9.5L12.5 21a2 2 0 01-2.83 0l-6.17-6.17A2 2 0 013 13.5v-2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('v2_label_title')}
          </h4>
          <p>{t('v2_label_desc')}</p>
          <p>{t('v2_label_desc_2')}</p>
          <div className="ob-v2-actions ob-v2-actions--stacked">
            <button type="button" className="ob-v2-btn-primary" onClick={onNext}>
              <span>{t('v2_label_cta')}</span>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M2 7h10m0 0L7.5 2.5M12 7l-4.5 4.5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <button type="button" className="ob-v2-btn-skip" onClick={onSkip}>
              {t('v2_skip')}
            </button>
          </div>
          <div
            className="ob-v2-tip-arrow ob-v2-tip-arrow--up"
            style={{ left: arrowLeft }}
            aria-hidden="true"
          />
        </div>
      </>
    )
  }

  if (phase === 'shortcutBar') {
    if (isMobile || !pillRect) {
      const handleOpenComposer = () => {
        if (isMobile && onOpenNewMessage) {
          onOpenNewMessage()
          return
        }
        onNext()
      }

      return (
        <div className="ob-v2-backdrop ob-v2-backdrop--light" onClick={onSkip}>
          <div className="ob-v2-card ob-v2-card--premium" onClick={(e) => e.stopPropagation()}>
            <h2 className="ob-v2-display">
              {isMobile ? t('v2_mobile_bar_title') : t('v2_bar_title')}
            </h2>
            <p>{isMobile ? t('v2_mobile_bar_desc') : t('v2_bar_desc')}</p>
            <p>{isMobile ? t('v2_mobile_bar_desc_2') : t('v2_bar_desc_2')}</p>
            {!isMobile && (
              <div className="ob-v2-kbd-row ob-v2-kbd-row--center">
                <kbd className="ob-v2-kbd ob-v2-kbd--lg ob-v2-kbd--tap">N</kbd>
              </div>
            )}
            <div className={`ob-v2-actions ${isMobile ? 'ob-v2-actions--stacked' : ''}`}>
              {isMobile && (
                <button type="button" className="ob-v2-btn-primary" onClick={handleOpenComposer}>
                  <span>{t('v2_bar_cta')}</span>
                </button>
              )}
              <button type="button" className="ob-v2-btn-skip" onClick={onSkip}>
                {t('v2_skip')}
              </button>
            </div>
          </div>
        </div>
      )
    }

    const pillCenterX = pillRect.left + pillRect.width / 2
    const tooltipWidth = 320
    const halfTip = tooltipWidth / 2
    const viewportMargin = 16
    let tipLeft = pillCenterX - halfTip
    tipLeft = Math.max(viewportMargin, Math.min(tipLeft, window.innerWidth - tooltipWidth - viewportMargin))
    const tipBottom = window.innerHeight - pillRect.top + 22

    return (
      <>
        <div
          className="ob-v2-tip ob-v2-tip--premium ob-v2-tip--anchored"
          role="dialog"
          aria-modal="false"
          style={{ left: tipLeft, bottom: tipBottom, width: tooltipWidth }}
        >
          <h4>{t('v2_bar_title')}</h4>
          <p>{t('v2_bar_desc')}</p>
          <p>{t('v2_bar_desc_2')}</p>
          <div className="ob-v2-kbd-row ob-v2-kbd-row--center">
            <span className="ob-v2-kbd-label">{t('v2_press')}</span>
            <kbd className="ob-v2-kbd ob-v2-kbd--lg ob-v2-kbd--tap">N</kbd>
          </div>
          <div className="ob-v2-actions ob-v2-actions--skip-only">
            <button type="button" className="ob-v2-btn-skip" onClick={onSkip}>
              {t('v2_skip')}
            </button>
          </div>
          <div
            className="ob-v2-tip-arrow ob-v2-tip-arrow--down"
            style={{ left: Math.max(20, Math.min(pillCenterX - tipLeft, tooltipWidth - 20)) }}
            aria-hidden="true"
          />
        </div>
      </>
    )
  }

  if (phase === 'compose') {
    return (
      <div className={`ob-v2-tip ob-v2-tip--premium ob-v2-tip--top-left ${isMobile ? 'ob-v2-tip--mobile' : ''}`} role="dialog" aria-modal="false">
        <h4 className="ob-v2-tip-title-row">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M12 3 L13.5 9 L20 11 L13.5 13 L12 19 L10.5 13 L4 11 L10.5 9 Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('v2_compose_title')}
        </h4>
        <p>{t('v2_compose_desc')}</p>
        {isMobile ? (
          <p className="ob-v2-hint ob-v2-hint--alt">{t('v2_mobile_compose_hint')}</p>
        ) : (
          <>
            <div className="ob-v2-kbd-row ob-v2-kbd-row--center">
              <kbd className="ob-v2-kbd ob-v2-kbd--tap">Ctrl</kbd>
              <span className="ob-v2-kbd-plus">+</span>
              <kbd className="ob-v2-kbd ob-v2-kbd--tap ob-v2-kbd--tap-delayed">G</kbd>
            </div>
            <p className="ob-v2-hint ob-v2-hint--alt">{t('v2_compose_alt')}</p>
            <div className="ob-v2-mic-tip">
              <svg className="ob-v2-mic-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect x="9" y="3" width="6" height="12" rx="3" stroke="currentColor" strokeWidth="2" />
                <path d="M5 11c0 4 3 7 7 7s7-3 7-7M12 18v4M8 22h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span className="ob-v2-mic-text">
                {t('v2_mic_prefix')}
                {' '}
                <kbd className="ob-v2-kbd ob-v2-kbd--space ob-v2-kbd--hold">{t('v2_mic_space_label')}</kbd>
                {' '}
                {t('v2_mic_suffix')}
              </span>
            </div>
          </>
        )}
        <div className={`ob-v2-actions ${isMobile ? 'ob-v2-actions--stacked' : 'ob-v2-actions--skip-only'}`}>
          <button type="button" className={isMobile ? 'ob-v2-btn-primary' : 'ob-v2-btn-skip'} onClick={onSkip}>
            {isMobile ? t('v2_mobile_done_cta') : t('v2_skip')}
          </button>
        </div>
      </div>
    )
  }

  return null
}
