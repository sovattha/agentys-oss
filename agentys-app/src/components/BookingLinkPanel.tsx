import { useEffect, useCallback, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import { useBookingUrlSetting, classifyBookingUrl } from '../hooks/useBookingUrlSetting';
import { apiClient } from '../services/api';
import { ChevronLeftIcon, CloseIcon, CheckIcon } from './icons/ActionIcons';
import './BookingLinkPanel.css';

interface BookingLinkPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onBack?: () => void;
  accountId?: number;
}

type Provider = 'gmail' | 'outlook' | 'imap_smtp' | 'unknown';

// Personal-Outlook domains where Microsoft Bookings with me isn't available.
const PERSONAL_OUTLOOK_DOMAINS = new Set([
  'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'hotmail.co.uk', 'hotmail.fr',
]);

// Deep-link straight to the create-appointment-schedule view in Google Calendar.
const GOOGLE_DEEP_LINK = 'https://calendar.google.com/calendar/u/0/r/eventedit/appointment';
const OUTLOOK_DEEP_LINK = 'https://outlook.office.com/bookwithme/me';
const CALENDLY_LINK = 'https://calendly.com/signup';
const CALCOM_LINK = 'https://cal.com/signup';

export function BookingLinkPanel({ isOpen, onClose, onBack, accountId }: BookingLinkPanelProps) {
  const { t } = useTranslation('settings');
  const { t: tc } = useTranslation('common');
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose);
  const { bookingUrl, setBookingUrl, loaded } = useBookingUrlSetting(accountId);

  const [draft, setDraft] = useState('');
  const [provider, setProvider] = useState<Provider>('unknown');
  const [accountEmail, setAccountEmail] = useState('');
  const [savedFlash, setSavedFlash] = useState(false);
  const [copiedFlash, setCopiedFlash] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState(false);

  // Sync the draft with the persisted value once it loads, but don't fight
  // the user mid-edit if they've already typed something.
  useEffect(() => {
    if (loaded) setDraft(bookingUrl);
  }, [loaded, bookingUrl]);

  // Detect provider for the active account → tailor the help section.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    apiClient.listAccounts().then((res) => {
      if (cancelled) return;
      const accounts = res.accounts || [];
      // Match by id when provided, otherwise fall back to whatever the
      // backend marks as current.
      const acct = (accountId !== undefined
        ? accounts.find(a => Number(a.id) === accountId)
        : accounts.find(a => a.is_current))
        || accounts[0];
      if (acct) {
        setProvider(acct.provider as Provider);
        setAccountEmail(acct.email || '');
      }
    }).catch(() => { /* non-blocking */ });
    return () => { cancelled = true; };
  }, [isOpen, accountId]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleClose();
      }
    },
    [handleClose]
  );

  useEffect(() => {
    if (!isOpen) return;
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleKeyDown]);

  // Soft validation: classify against known booking platforms. Backend
  // already enforces http(s)://; this only powers the inline hint.
  const classification = useMemo(() => classifyBookingUrl(draft), [draft]);
  const isUnknownTool = !!draft && classification?.kind === 'unknown';
  const isDirty = draft.trim() !== bookingUrl.trim();

  // Explicit save (button or Enter) when the value differs from the
  // already-saved one. Blur-autosave was too invisible to trust.
  const commitSave = useCallback(async () => {
    if (!isDirty) return;
    setError(null);
    setPendingSave(true);
    const result = await setBookingUrl(draft);
    setPendingSave(false);
    if (!result.ok) {
      setError(result.error || tc('error_generic', 'Something went wrong'));
      return;
    }
    setSavedFlash(true);
    setTimeout(() => setSavedFlash(false), 1800);
  }, [draft, isDirty, setBookingUrl, tc]);

  const handleCopy = useCallback(async () => {
    if (!bookingUrl) return;
    try {
      await navigator.clipboard.writeText(bookingUrl);
      setCopiedFlash(true);
      setTimeout(() => setCopiedFlash(false), 1500);
    } catch (err) {
      // Audit Cluster D (2026-05-17) F-05: clipboard can be blocked by
      // iframe sandbox / Tauri webview restricted mode / browser policy.
      // Without feedback the user clicks Copy 3-4 times thinking it broke.
      console.warn('[BookingLinkPanel] clipboard.writeText blocked:', err);
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: tc('toasts.clipboard_blocked'),
          type: 'warning',
          duration: 5000,
        },
      }));
    }
  }, [bookingUrl, tc]);

  const handleOpen = useCallback(() => {
    if (!bookingUrl) return;
    window.open(bookingUrl, '_blank', 'noopener,noreferrer');
  }, [bookingUrl]);

  const handleClear = useCallback(async () => {
    setDraft('');
    await setBookingUrl('');
  }, [setBookingUrl]);

  // Resolve which helper card to show. Outlook splits into "M365"
  // (likely-business) vs "personal" based on the email domain.
  const isOutlookPersonal = useMemo(() => {
    if (provider !== 'outlook') return false;
    const domain = accountEmail.split('@')[1]?.toLowerCase();
    return !!domain && PERSONAL_OUTLOOK_DOMAINS.has(domain);
  }, [provider, accountEmail]);

  if (!shouldRender) return null;

  return (
    <div className="booking-link-overlay" onClick={handleClose}>
      <div
        className={`booking-link-panel${isClosing ? ' closing' : ''}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="booking-link-title"
      >
        <div className="booking-link-header">
          <div className="booking-link-header-left">
            {onBack && (
              <button
                type="button"
                className="booking-link-back"
                onClick={onBack}
                aria-label={tc('back')}
                title={tc('back')}
              >
                <ChevronLeftIcon size={20} />
              </button>
            )}
            <h2 id="booking-link-title">{t('booking_url')}</h2>
          </div>
          <button
            type="button"
            className="booking-link-close"
            onClick={handleClose}
            aria-label={tc('close')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="booking-link-content">
          <p className="booking-link-intro">{t('booking_link_panel_intro')}</p>

          <div className="booking-url-card">
            <div className="booking-url-header">
              <div className="booking-url-icon-wrap" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                </svg>
              </div>
              <span className="booking-url-title">{t('booking_url')}</span>
              {bookingUrl && !isDirty && (
                <span className={`booking-link-saved-pill${savedFlash ? ' just-saved' : ''}`}>
                  <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
                  {savedFlash ? t('saved') : t('link_configured')}
                </span>
              )}
              {pendingSave && (
                <span className="booking-link-saved-pill is-pending">
                  <svg className="booking-link-spinner" aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12a9 9 0 1 1-6.22-8.56" />
                  </svg>
                  {tc('saving', 'Saving…')}
                </span>
              )}
            </div>

            <div className="booking-url-input-row">
              <input
                type="url"
                className="booking-url-input"
                placeholder={t('booking_url_placeholder')}
                value={draft}
                onChange={(e) => { setDraft(e.target.value); setError(null); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && isDirty) {
                    e.preventDefault();
                    void commitSave();
                  }
                }}
                spellCheck={false}
              />
              <div className="booking-url-actions" role="group">
                <button
                  type="button"
                  className={`booking-url-btn${copiedFlash ? ' booking-url-btn--success' : ''}`}
                  onClick={handleCopy}
                  disabled={!bookingUrl}
                  title={t('copy_link')}
                  aria-label={t('copy_link')}
                >
                  {copiedFlash ? (
                    <CheckIcon size={14} />
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
                  )}
                </button>
                <button
                  type="button"
                  className="booking-url-btn"
                  onClick={handleOpen}
                  disabled={!bookingUrl}
                  title={t('open_in_browser')}
                  aria-label={t('open_in_browser')}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 17 17 7" /><path d="M7 7h10v10" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="booking-url-save-btn"
                  onClick={() => { void commitSave(); }}
                  disabled={!isDirty || pendingSave}
                >
                  {pendingSave ? tc('saving', 'Saving…') : tc('save')}
                </button>
              </div>
            </div>

            <div className="booking-link-row">
              <div className="booking-link-row-status">
                {error && <span className="booking-link-error">{error}</span>}
                {!error && isUnknownTool && (
                  <span className="booking-link-hint booking-link-hint--warn">
                    <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                    {t('booking_link_unrecognized_warning')}
                  </span>
                )}
                {!error && !isUnknownTool && draft && classification && classification.kind !== 'unknown' && (
                  <span className="booking-link-hint booking-link-hint--ok">
                    <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
                    {t('booking_link_recognized', { tool: providerLabel(classification.kind, t) })}
                  </span>
                )}
              </div>
              {(draft || bookingUrl) && (
                <button
                  type="button"
                  className="booking-link-clear-link"
                  onClick={handleClear}
                >
                  {t('booking_link_clear')}
                </button>
              )}
            </div>

            <p className="booking-url-hint">{t('booking_url_desc')}</p>
          </div>

          <SetupHelper
            provider={provider}
            isOutlookPersonal={isOutlookPersonal}
            t={t as unknown as (key: string, ...args: unknown[]) => string}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider-tailored help card. Shows the path of least resistance for the
// user's actual provider, with a deep-link button.
// ---------------------------------------------------------------------------

type ProviderLogoKind = 'google' | 'microsoft' | 'generic';

function SetupHelper({
  provider,
  isOutlookPersonal,
  t,
}: {
  provider: Provider;
  isOutlookPersonal: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (key: string, ...args: any[]) => string;
}) {
  if (provider === 'gmail') {
    return (
      <HelpCard
        logo="google"
        title={t('booking_link_help_title')}
        intro={t('booking_link_help_gmail_intro')}
        steps={[
          t('booking_link_steps_gmail_1'),
          t('booking_link_steps_gmail_2'),
          t('booking_link_steps_gmail_3'),
          t('booking_link_steps_gmail_4'),
        ]}
        primaryHref={GOOGLE_DEEP_LINK}
        primaryLabel={t('booking_link_open_google')}
      />
    );
  }
  if (provider === 'outlook' && !isOutlookPersonal) {
    return (
      <HelpCard
        logo="microsoft"
        title={t('booking_link_help_title')}
        intro={t('booking_link_help_outlook_intro')}
        steps={[
          t('booking_link_steps_outlook_1'),
          t('booking_link_steps_outlook_2'),
          t('booking_link_steps_outlook_3'),
        ]}
        primaryHref={OUTLOOK_DEEP_LINK}
        primaryLabel={t('booking_link_open_outlook')}
        secondaryHref={CALENDLY_LINK}
        secondaryLabel={t('booking_link_open_calendly')}
        footnote={t('booking_link_help_outlook_personal')}
      />
    );
  }
  // Personal Outlook + IMAP/SMTP → no native option, recommend third-party.
  return (
    <HelpCard
      logo="generic"
      title={t('booking_link_help_title')}
      intro={t('booking_link_help_imap_intro')}
      steps={[]}
      primaryHref={CALENDLY_LINK}
      primaryLabel={t('booking_link_open_calendly')}
      secondaryHref={CALCOM_LINK}
      secondaryLabel={t('booking_link_open_calcom')}
    />
  );
}

function ProviderLogo({ kind }: { kind: ProviderLogoKind }) {
  if (kind === 'google') {
    // Google "G" — multi-color official mark, scaled to 18px.
    return (
      <svg className="booking-link-help-logo" aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
        <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
        <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.1 8 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
        <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2c-2 1.5-4.5 2.4-7.2 2.4-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
        <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.6l6.2 5.2C40 35.6 44 30.3 44 24c0-1.3-.1-2.4-.4-3.5z"/>
      </svg>
    );
  }
  if (kind === 'microsoft') {
    return (
      <svg className="booking-link-help-logo" aria-hidden="true" width="18" height="18" viewBox="0 0 24 24">
        <rect x="1" y="1"  width="10" height="10" fill="#F25022" />
        <rect x="13" y="1"  width="10" height="10" fill="#7FBA00" />
        <rect x="1" y="13" width="10" height="10" fill="#00A4EF" />
        <rect x="13" y="13" width="10" height="10" fill="#FFB900" />
      </svg>
    );
  }
  return (
    <svg className="booking-link-help-logo booking-link-help-logo--generic" aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  );
}

function HelpCard({
  logo,
  title,
  intro,
  steps,
  primaryHref,
  primaryLabel,
  secondaryHref,
  secondaryLabel,
  footnote,
}: {
  logo: ProviderLogoKind;
  title: string;
  intro: string;
  steps: string[];
  primaryHref: string;
  primaryLabel: string;
  secondaryHref?: string;
  secondaryLabel?: string;
  footnote?: string;
}) {
  return (
    <div className="booking-link-help-card">
      <div className="booking-link-help-head">
        <ProviderLogo kind={logo} />
        <div className="booking-link-help-head-text">
          <h3 className="booking-link-help-title">{title}</h3>
          <p className="booking-link-help-intro">{intro}</p>
        </div>
      </div>
      {steps.length > 0 && (
        <ol className="booking-link-help-steps" role="list">
          {steps.map((s, i) => (
            <li key={i} className="booking-link-help-step">
              <span className="booking-link-help-step-num" aria-hidden="true">{i + 1}</span>
              <span className="booking-link-help-step-text">{s}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="booking-link-help-actions">
        <a
          href={primaryHref}
          target="_blank"
          rel="noopener noreferrer"
          className="booking-link-help-btn booking-link-help-btn--primary"
        >
          {primaryLabel}
          <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 17 17 7" /><path d="M7 7h10v10" />
          </svg>
        </a>
        {secondaryHref && secondaryLabel && (
          <a
            href={secondaryHref}
            target="_blank"
            rel="noopener noreferrer"
            className="booking-link-help-btn booking-link-help-btn--secondary"
          >
            {secondaryLabel}
            <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 17 17 7" /><path d="M7 7h10v10" />
            </svg>
          </a>
        )}
      </div>
      {footnote && <p className="booking-link-help-footnote">{footnote}</p>}
    </div>
  );
}

function providerLabel(kind: string, _t: (key: string) => string): string {
  switch (kind) {
    case 'google': return 'Google Calendar';
    case 'microsoft': return 'Microsoft Bookings';
    case 'calendly': return 'Calendly';
    case 'cal_com': return 'Cal.com';
    case 'savvycal': return 'SavvyCal';
    case 'tidycal': return 'TidyCal';
    case 'youcanbookme': return 'YouCanBook.me';
    case 'hubspot': return 'HubSpot Meetings';
    case 'chilipiper': return 'Chili Piper';
    default: return kind;
  }
}
