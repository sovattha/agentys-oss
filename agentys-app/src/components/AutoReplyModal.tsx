import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useAutoReplySetting } from '../hooks/useAutoReplySetting';
import { FrenchDatePicker } from './ui/FrenchDatePicker';
import { ContactAutocomplete } from './compose/ContactAutocomplete';
import { RichTextEditor, type RichTextEditorHandle, type PlaceholderSuggestion } from './ui/RichTextEditor';
import { formatAbsencePeriodParts } from '../utils/absenceDates';
import { SignatureFooter } from './ui/SignatureFooter';
import { ChevronLeftIcon, CloseIcon } from './icons/ActionIcons';
import {
  AR_TOKEN_ATTR,
  isBlankAutoReplyMessage,
  buildAutoReplySuggestionHtml,
  suggestionFingerprint,
  matchesAnySuggestionFingerprint,
} from '../utils/autoReplySuggestion';
import './AutoReplyModal.css';

interface AutoReplyModalProps {
  onClose: () => void;
  accountId?: number;
}

// Month names / labels are the only dynamic content, but escape defensively so
// the chip HTML can never be broken by an unexpected character.
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Dynamic-field chips carry `data-ar-token` so they can be recognised later:
//  - "absence_period": resolved client-side (re-sync effect below), sent as-is.
//  - "name" / "first_name": resolved per-recipient on the backend at send time
//    (the sender isn't known while editing), see app/services/auto_reply.py.
const TOKEN_ATTR = AR_TOKEN_ATTR;
const ABSENCE_TOKEN_VALUE = 'absence_period';

// Builds a dynamic-field chip. `contenteditable=false` makes it one atomic unit
// (a single backspace deletes it). The class only styles it in-app.
function buildChipHtml(token: string, text: string): string {
  return `<span class="ar-token" ${TOKEN_ATTR}="${token}" contenteditable="false">${escapeHtml(text)}</span>`;
}

// Languages whose pristine suggestion a saved message may be frozen in.
// `de` resolves through the i18n fallback today — harmless duplicate candidate
// that becomes meaningful the day de/settings.json ships its own template.
const SUGGESTION_LANGS = ['fr', 'en', 'es', 'de'] as const;

export function AutoReplyModal({ onClose, accountId }: AutoReplyModalProps) {
  const { t, i18n } = useTranslation('settings');
  const {
    autoReplyEnabled, autoReplyMessage, autoReplyStart, autoReplyEnd,
    autoTransferEnabled, autoTransferEmail,
    calendarSynced, calendarSyncError, loaded,
    toggleAutoReply, toggleTransfer, setAutoReply, flushPending,
  } = useAutoReplySetting(accountId);

  const editorRef = useRef<RichTextEditorHandle>(null);
  // One-shot guard so the empty-editor pre-fill runs at most once per mount.
  const prefilledRef = useRef(false);

  // Locale-aware "du 25 mars au 29 mars" built from the Période dates. Falls
  // back to a generic label until both dates are set (the chip self-fills via
  // the re-sync effect once they are).
  const formatAbsenceRange = useCallback((): string => {
    const parts = formatAbsencePeriodParts(autoReplyStart, autoReplyEnd, i18n.language);
    if (!parts) return t('auto_reply_period_token_empty', { defaultValue: 'vos dates d’absence' });
    return t('auto_reply_period_range', {
      defaultValue: 'du {{start}} au {{end}}',
      start: parts.start,
      end: parts.end,
    });
  }, [autoReplyStart, autoReplyEnd, i18n.language, t]);

  // The `{ }` toolbar menu. Three placeholders:
  //  - Période d'absence: the live date chip, resolved client-side and kept in
  //    sync by the effect below.
  //  - Nom / Prénom: the sender's name, resolved per-recipient on the backend
  //    at send time (unknown while editing — the chip shows the field label).
  const placeholders = useMemo<PlaceholderSuggestion[]>(() => [
    {
      id: ABSENCE_TOKEN_VALUE,
      label: t('auto_reply_period_token_label', { defaultValue: 'Période d’absence' }),
      preview: formatAbsenceRange(),
      buildHtml: () => buildChipHtml(ABSENCE_TOKEN_VALUE, formatAbsenceRange()),
    },
    {
      id: 'first_name',
      label: t('auto_reply_field_first_name', { defaultValue: 'Prénom' }),
      buildHtml: () => buildChipHtml('first_name', t('auto_reply_field_first_name', { defaultValue: 'Prénom' })),
    },
    {
      id: 'name',
      label: t('auto_reply_field_name', { defaultValue: 'Nom' }),
      buildHtml: () => buildChipHtml('name', t('auto_reply_field_name', { defaultValue: 'Nom' })),
    },
  ], [t, formatAbsenceRange]);

  // The localized starter dropped into an empty editor: a short out-of-office
  // body in the user's language with the live absence-period chip embedded, so
  // it self-fills with the dates and stays in sync via the effect below.
  const buildSuggestedMessageHtml = useCallback(
    () => buildAutoReplySuggestionHtml(t, buildChipHtml(ABSENCE_TOKEN_VALUE, formatAbsenceRange())),
    [t, formatAbsenceRange]
  );

  // Pre-fill the message when the modal opens with a blank editor. Gated on
  // `loaded` so we never overwrite a saved message that's still in flight, and
  // on `prefilledRef` so it fires once — a user who deliberately clears the
  // body while editing isn't re-filled. `setAutoReply` persists it (the chosen
  // "appears automatically, already saved" behaviour); auto-reply stays off
  // until the user enables it, so nothing is sent just by opening the modal.
  useEffect(() => {
    if (!loaded || prefilledRef.current) return;
    prefilledRef.current = true;
    if (isBlankAutoReplyMessage(autoReplyMessage)) {
      setAutoReply({ message: buildSuggestedMessageHtml() });
      return;
    }
    // Bug Karine 2026-06-09 : the starter is auto-persisted on first open, so
    // it froze in that day's language (and, pre-4be7990e, with the legacy
    // trailing `&nbsp;` after the chip). When the saved message is still a
    // PRISTINE suggestion — fingerprint-equal to the template of any supported
    // language — rebuild it in the current language. Any user edit breaks the
    // fingerprint match, so real content is never touched.
    const fresh = buildSuggestedMessageHtml();
    if (suggestionFingerprint(autoReplyMessage) === suggestionFingerprint(fresh)) return;
    const chip = buildChipHtml(ABSENCE_TOKEN_VALUE, formatAbsenceRange());
    const pristineCandidates = SUGGESTION_LANGS.map((lng) =>
      buildAutoReplySuggestionHtml(i18n.getFixedT(lng, 'settings'), chip),
    );
    if (matchesAnySuggestionFingerprint(autoReplyMessage, pristineCandidates)) {
      setAutoReply({ message: fresh });
    }
  }, [loaded, autoReplyMessage, setAutoReply, buildSuggestedMessageHtml, formatAbsenceRange, i18n]);

  // Keep every inserted chip in step with the Période dates. This is the only
  // surface that edits those dates, so rewriting the chip text here means the
  // stored message — and therefore the sent auto-reply — always reflects the
  // current window without touching the send path.
  useEffect(() => {
    const handle = editorRef.current;
    if (!handle || !autoReplyStart || !autoReplyEnd) return;
    const html = handle.getHtml();
    if (!html.includes(`${TOKEN_ATTR}="${ABSENCE_TOKEN_VALUE}"`)) return;
    const range = formatAbsenceRange();
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    let changed = false;
    tmp.querySelectorAll(`[${TOKEN_ATTR}="${ABSENCE_TOKEN_VALUE}"]`).forEach((chip) => {
      if (chip.textContent !== range) { chip.textContent = range; changed = true; }
    });
    if (changed) setAutoReply({ message: tmp.innerHTML });
  }, [autoReplyStart, autoReplyEnd, formatAbsenceRange, setAutoReply]);

  const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  const transferEmailInvalid = useMemo(
    () => autoTransferEmail.length > 0 && !emailRegex.test(autoTransferEmail),
    [autoTransferEmail]
  );

  const dateRangeInvalid = useMemo(
    () => autoReplyStart && autoReplyEnd && autoReplyStart > autoReplyEnd,
    [autoReplyStart, autoReplyEnd]
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Inner popups (calendar, contact autocomplete) handle Escape themselves
      // — skip the modal close when an editable target is focused, so the inner
      // dropdown gets dismissed first without taking the whole modal with it.
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return;
      }
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="autoreply-overlay" role="dialog" aria-modal="true" aria-label={t('auto_reply_title')} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="autoreply-modal" onClick={(e) => e.stopPropagation()}>
        <div className="autoreply-top-bar">
          <button className="autoreply-back" onClick={onClose} aria-label={t('common:back', 'Back')} title={t('common:back', 'Back')}>
            <ChevronLeftIcon size={20} />
          </button>
          <h2 className="autoreply-title">{t('auto_reply_title')}</h2>
          <button className="autoreply-close" onClick={onClose} title={t('auto_reply_close')} aria-label={t('auto_reply_close')}>
            <CloseIcon />
          </button>
        </div>

        <label
          className="autoreply-toggle"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleAutoReply(); }}
        >
          <span className="autoreply-toggle-label">{t('auto_reply_enable')}</span>
          <input
            type="checkbox"
            checked={autoReplyEnabled}
            onChange={() => {/* handled by label onClick */}}
            tabIndex={-1}
            aria-label={t('auto_reply_enable')}
            aria-checked={autoReplyEnabled}
          />
          <span className="settings-switch" />
        </label>

        <div className="autoreply-body" data-disabled={!autoReplyEnabled}>
          <div>
            <div className="autoreply-field-label">{t('auto_reply_period')}</div>
            <div className="autoreply-date-row">
              <div className="autoreply-date-group">
                <span>{t('auto_reply_start')}</span>
                <FrenchDatePicker
                  value={autoReplyStart}
                  onChange={(v) => setAutoReply({ start: v })}
                  ariaLabel={t('auto_reply_start')}
                />
              </div>
              <span className="autoreply-separator">-</span>
              <div className="autoreply-date-group">
                <span>{t('auto_reply_end')}</span>
                <FrenchDatePicker
                  value={autoReplyEnd}
                  onChange={(v) => setAutoReply({ end: v })}
                  min={autoReplyStart}
                  ariaLabel={t('auto_reply_end')}
                />
              </div>
            </div>
            {dateRangeInvalid && (
              <p className="autoreply-date-error">{t('auto_reply_date_range_error', 'La date de début doit être antérieure à la date de fin')}</p>
            )}

            {autoReplyEnabled && autoReplyStart && autoReplyEnd && (
              calendarSyncError ? (
                <div className="ar-calendar-sync ar-calendar-sync--error">
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  <span>{t('auto_reply_calendar_error')}</span>
                </div>
              ) : (
                <div className={`ar-calendar-sync${calendarSynced ? '' : ' ar-calendar-sync--pending'}`}>
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                    <line x1="16" y1="2" x2="16" y2="6"/>
                    <line x1="8" y1="2" x2="8" y2="6"/>
                    <line x1="3" y1="10" x2="21" y2="10"/>
                  </svg>
                  <span>
                    {calendarSynced ? t('auto_reply_calendar_synced') : t('auto_reply_calendar_syncing')}
                  </span>
                </div>
              )
            )}
          </div>

          <div>
            <div className="autoreply-field-label">{t('auto_reply_message_label')}</div>
            <RichTextEditor
              ref={editorRef}
              value={autoReplyMessage}
              onChange={(html) => setAutoReply({ message: html })}
              placeholder={t('auto_reply_message_placeholder')}
              ariaLabel={t('auto_reply_message_label')}
              minHeight={120}
              enableSnippets={false}
              placeholders={placeholders}
            />
            <SignatureFooter className="autoreply-signature-footer" />
          </div>

          <div className="autoreply-divider" />

          <label
            className="autoreply-toggle"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); toggleTransfer(); }}
          >
            <span className="autoreply-toggle-label">{t('auto_reply_transfer_label')}</span>
            <input
              type="checkbox"
              checked={autoTransferEnabled}
              onChange={() => {/* handled by label onClick */}}
              tabIndex={-1}
              aria-label={t('auto_reply_transfer_label')}
              aria-checked={autoTransferEnabled}
            />
            <span className="settings-switch" />
          </label>

          <div className="autoreply-transfer-body" data-disabled={!autoTransferEnabled}>
            <div className="autoreply-field-label">{t('auto_reply_transfer_address')}</div>
            <div className={`autoreply-email-input${transferEmailInvalid ? ' autoreply-email-invalid' : ''}`}>
              <ContactAutocomplete
                value={autoTransferEmail}
                onChange={(v) => setAutoReply({ transferEmail: v })}
                onContactSelect={({ email }) => setAutoReply({ transferEmail: email })}
                placeholder={t('auto_reply_transfer_placeholder')}
                multi={false}
                accountId={accountId !== undefined ? String(accountId) : undefined}
                includeAllContacts
                includeSelf
              />
            </div>
            {transferEmailInvalid && (
              <p className="autoreply-email-error">{t('auto_reply_transfer_email_invalid')}</p>
            )}
            <p className="autoreply-hint">
              {t('auto_reply_transfer_hint')}
            </p>
          </div>
        </div>

        <button className="autoreply-save" onClick={() => { flushPending(); onClose(); }} type="button" disabled={dateRangeInvalid || false}>
          {t('auto_reply_save')}
        </button>
      </div>
    </div>
  );
}
