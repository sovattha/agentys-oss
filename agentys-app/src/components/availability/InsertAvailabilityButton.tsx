import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useBookingUrlSetting } from '../../hooks/useBookingUrlSetting';
import { formatBookingLineOnly } from '../../utils/availabilityFormatter';
import { AvailabilityPicker } from './AvailabilityPicker';
import './InsertAvailabilityButton.css';

interface InsertAvailabilityButtonProps {
  /** Called when text should be inserted into the compose body at the cursor. */
  onInsert: (text: string) => void;
  accountId?: number;
  className?: string;
  /** Disable the button (e.g. while AI is generating, or transcribing). */
  disabled?: boolean;
  /**
   * Locale for the inserted text. Forwarded to the picker / booking-line
   * formatter. Use the composer's REPLY language (e.g. voiceLanguage)
   * rather than the UI language — the dates land in the reply body, which
   * is written in the reply language. Falls back to `i18n.language` when
   * omitted or when 'auto' (no detected reply language).
   */
  language?: string;
}

type Mode = 'link-only' | 'free-times' | 'free-times-and-link';

export function InsertAvailabilityButton({
  onInsert,
  accountId,
  className,
  disabled,
  language,
}: InsertAvailabilityButtonProps) {
  const { t, i18n } = useTranslation('availability');
  const { bookingUrl } = useBookingUrlSetting(accountId);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<'free-times' | 'free-times-and-link'>('free-times');
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Compute menu placement: prefer below the trigger, but flip above when
  // the trigger is near the bottom of the viewport (the compose toolbar
  // typically sits at the screen bottom, where "below" gets clipped).
  const computeMenuPos = () => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const GAP = 6;
    // Use the rendered menu's actual height when available, otherwise an
    // estimate large enough for 3 menu items + padding.
    const measured = menuRef.current?.getBoundingClientRect().height;
    const menuHeight = measured && measured > 0 ? measured : 180;

    const spaceBelow = window.innerHeight - rect.bottom;
    const fitsBelow = spaceBelow >= menuHeight + GAP + 8; // 8px viewport margin

    const top = fitsBelow
      ? rect.bottom + GAP
      : Math.max(8, rect.top - menuHeight - GAP);

    setMenuPos({
      top,
      right: window.innerWidth - rect.right,
    });
  };

  // After the menu first paints, re-measure with its actual height so the
  // upward placement sits flush against the trigger (no gap from a too-
  // generous estimate).
  useLayoutEffect(() => {
    if (!menuOpen || !menuRef.current) return;
    computeMenuPos();

  }, [menuOpen, menuRef.current]);

  useEffect(() => {
    if (!menuOpen) return;
    computeMenuPos();
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    const onResize = () => computeMenuPos();
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  }, [menuOpen]);

  // Reply language wins over UI language — see `language` prop doc.
  const effectiveLocale =
    (language && language !== 'auto' ? language : i18n.language) || 'en';

  const handlePick = (mode: Mode) => {
    setMenuOpen(false);
    if (mode === 'link-only') {
      // HTML output → TipTap renders the URL as a real <a> link.
      const line = formatBookingLineOnly(bookingUrl, effectiveLocale, 'html');
      if (line) onInsert(line);
      return;
    }
    setPickerMode(mode);
    setPickerOpen(true);
  };

  const hasBookingLink = !!bookingUrl;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`rc-icon-btn iab-trigger${menuOpen ? ' is-open' : ''}${className ? ' ' + className : ''}`}
        onClick={() => setMenuOpen(o => !o)}
        disabled={disabled}
        title={t('button_title')}
        aria-label={t('button_title')}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </button>

      {menuOpen && menuPos && createPortal(
        <div
          ref={menuRef}
          className="iab-menu"
          role="menu"
          data-escape-owner=""
          style={{ top: menuPos.top, right: menuPos.right }}
        >
          {!hasBookingLink && (
            // Audit 2026-05-18: when no booking link is configured, the
            // link-only and combo items are disabled — but the user had no
            // path to fix that without leaving the compose modal. Surface
            // an inline shortcut to the Productivité settings panel so the
            // intent ("I want to share a booking link") completes in one
            // hop instead of a hunt through menus.
            <button
              type="button"
              role="menuitem"
              className="iab-menu-item iab-menu-item--link"
              onClick={() => {
                setMenuOpen(false);
                window.dispatchEvent(
                  new CustomEvent('agentys:open-settings', {
                    detail: { section: 'productivite', subsection: 'booking-link' },
                  }),
                );
              }}
            >
              <span className="iab-menu-icon" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 8v8M8 12h8" />
                </svg>
              </span>
              <span className="iab-menu-label">
                {t('configure_booking_link', { defaultValue: 'Configurer un lien de réservation…' })}
              </span>
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="iab-menu-item"
            onClick={() => handlePick('link-only')}
            disabled={!hasBookingLink}
            title={!hasBookingLink ? t('no_booking_link_warning') : undefined}
          >
            <span className="iab-menu-icon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
              </svg>
            </span>
            <span className="iab-menu-label">{t('mode_link_only')}</span>
            {!hasBookingLink && (
              <span className="iab-menu-badge">{t('mode_link_missing_badge')}</span>
            )}
          </button>
          <button
            type="button"
            role="menuitem"
            className="iab-menu-item"
            onClick={() => handlePick('free-times')}
          >
            <span className="iab-menu-icon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
                <path d="M8 14h2v2H8z M14 14h2v2h-2z" />
              </svg>
            </span>
            <span className="iab-menu-label">{t('mode_free_times')}</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="iab-menu-item iab-menu-item--combo"
            onClick={() => handlePick('free-times-and-link')}
            disabled={!hasBookingLink}
            title={!hasBookingLink ? t('no_booking_link_warning') : undefined}
          >
            <span className="iab-menu-icon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="13" rx="2" />
                <line x1="3" y1="10" x2="21" y2="10" />
                <path d="M8 19a3 3 0 0 0 4 0M14 19a3 3 0 0 1 4 0" />
              </svg>
            </span>
            <span className="iab-menu-label">{t('mode_free_times_and_link')}</span>
            {!hasBookingLink && (
              <span className="iab-menu-badge">{t('mode_link_missing_badge')}</span>
            )}
          </button>
        </div>,
        document.body,
      )}

      <AvailabilityPicker
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onInsert={(formatted) => {
          // Formatted output is HTML — TipTap parses <p>/<ul>/<a> nodes
          // directly. No trailing newline needed; <p> creates a paragraph
          // break naturally so the user's cursor lands below.
          onInsert(formatted);
        }}
        appendBookingLink={pickerMode === 'free-times-and-link'}
        bookingUrl={bookingUrl}
        accountId={accountId}
        language={language}
      />
    </>
  );
}
