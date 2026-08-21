import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ScheduledEmailDTO } from '../services/api';
import { CloseIcon, SendIcon } from './icons/ActionIcons';
import { formatLongDateFromDate, formatHourMinute } from '../utils/dateFormat';
import './ScheduledDetail.css';

interface ScheduledDetailProps {
  item: ScheduledEmailDTO;
  onClose: () => void;
  onSendNow?: (id: string) => Promise<boolean>;
  onCancel?: (id: string) => Promise<boolean>;
}

function formatSendAt(iso: string, locale: string): string {
  try {
    const d = new Date(iso);
    // "Wednesday May 27th, 15:50" (EN ordinal) / "Mercredi 27 mai, 17h00" (FR day-first).
    const weekday = new Intl.DateTimeFormat(locale === 'fr' ? 'fr-FR' : locale, { weekday: 'long' }).format(d);
    const cap = weekday.charAt(0).toUpperCase() + weekday.slice(1);
    return `${cap} ${formatLongDateFromDate(d, locale)}, ${formatHourMinute(d, locale)}`;
  } catch {
    return iso;
  }
}

function stripHtml(html: string): string {
  return html
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function ScheduledDetail({ item, onClose, onSendNow, onCancel }: ScheduledDetailProps) {
  const { t, i18n } = useTranslation('inbox');
  const locale = i18n.language?.slice(0, 2) || 'fr';
  const [sendingNow, setSendingNow] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bodyText = item.is_html ? stripHtml(item.body) : item.body;
  const subject = item.subject || t('no_subject', '(sans objet)');

  const handleSendNow = async () => {
    if (!onSendNow || sendingNow) return;
    setError(null);
    setSendingNow(true);
    const ok = await onSendNow(item.id);
    if (!ok) {
      setError(t('send_now_failed', "L'envoi immédiat a échoué"));
      setSendingNow(false);
      return;
    }
    onClose();
  };

  const handleCancelSchedule = async () => {
    if (!onCancel) return;
    const ok = await onCancel(item.id);
    if (ok) onClose();
  };

  return (
    <div className="scheduled-detail" data-testid="scheduled-detail">
      <header className="scheduled-detail__header">
        <div className="scheduled-detail__when">
          <span className="scheduled-detail__when-icon" aria-hidden="true">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </span>
          <span className="scheduled-detail__when-label">
            {t('sending_at', 'Envoi prévu')} · {formatSendAt(item.send_at, locale)}
          </span>
        </div>
        <button
          type="button"
          className="scheduled-detail__close"
          onClick={onClose}
          aria-label={t('close', 'Fermer')}
          title={t('close', 'Fermer')}
        >
          <CloseIcon size={16} />
        </button>
      </header>

      <div className="scheduled-detail__body">
        <div className="scheduled-detail__rows">
          <div className="scheduled-detail__row">
            <span className="scheduled-detail__label">{t('to_label', 'À')}</span>
            <span className="scheduled-detail__value">{item.to.join(', ')}</span>
          </div>
          {item.cc.length > 0 && (
            <div className="scheduled-detail__row">
              <span className="scheduled-detail__label">{t('cc_label', 'Cc')}</span>
              <span className="scheduled-detail__value">{item.cc.join(', ')}</span>
            </div>
          )}
          {item.bcc.length > 0 && (
            <div className="scheduled-detail__row">
              <span className="scheduled-detail__label">{t('bcc_label', 'Cci')}</span>
              <span className="scheduled-detail__value">{item.bcc.join(', ')}</span>
            </div>
          )}
        </div>

        <h2 className="scheduled-detail__subject">{subject}</h2>

        {bodyText && (
          <pre className="scheduled-detail__content">{bodyText}</pre>
        )}

        {error && (
          <div className="scheduled-detail__error" role="alert">
            {error}
          </div>
        )}

        {(onSendNow || onCancel) && (
          <div className="scheduled-detail__actions">
            {onCancel && (
              <button
                type="button"
                className="scheduled-detail__btn scheduled-detail__btn--cancel"
                onClick={handleCancelSchedule}
                disabled={sendingNow}
                data-testid="scheduled-detail-cancel"
              >
                {t('cancel_schedule', "Annuler l'envoi")}
              </button>
            )}
            {onSendNow && (
              <button
                type="button"
                className="scheduled-detail__btn scheduled-detail__btn--send-now"
                onClick={handleSendNow}
                disabled={sendingNow}
                data-testid="scheduled-detail-send-now"
              >
                {sendingNow ? (
                  <span className="refine-spinner" aria-hidden="true" />
                ) : (
                  <SendIcon size={14} />
                )}
                <span>{sendingNow ? t('sending', 'Envoi…') : t('send_now', 'Envoyer maintenant')}</span>
              </button>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
