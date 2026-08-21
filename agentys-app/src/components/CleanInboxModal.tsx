import { useState, useCallback, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { useBulkActionCount } from '../hooks/useBulkActionCount';
import { ChevronLeftIcon, CloseIcon } from './icons/ActionIcons';
import './CleanInboxModal.css';

interface CleanInboxModalProps {
  onClose: () => void;
  onClean: (options: CleanInboxOptions) => Promise<void>;
}

export interface CleanInboxOptions {
  olderThanDays: number;
  keepUnread: boolean;
  unsubscribeNewsletters: boolean;
}

type QuickOption = '1week' | '2weeks' | '1month' | 'custom';

const DAYS_MAP: Record<Exclude<QuickOption, 'custom'>, number> = {
  '1week': 7,
  '2weeks': 14,
  '1month': 30,
};

// Quick presets rendered as a segmented control (single source of truth for
// the labels + their order).
const QUICK_PERIODS: { value: Exclude<QuickOption, 'custom'>; labelKey: string }[] = [
  { value: '1week', labelKey: 'clean_1week' },
  { value: '2weeks', labelKey: 'clean_2weeks' },
  { value: '1month', labelKey: 'clean_1month' },
];

// Slider values: 1-12 months
const SLIDER_MIN = 1;
const SLIDER_MAX = 12;

// Tick guides under the slider, positioned at their true value on the track.
const SLIDER_TICKS = [1, 3, 6, 9, 12];

function monthsToDays(months: number): number {
  return months * 30;
}

export function CleanInboxModal({ onClose, onClean }: CleanInboxModalProps) {
  const { t } = useTranslation('settings');
  const { t: tInbox } = useTranslation('inbox');
  const [selectedOption, setSelectedOption] = useState<QuickOption>('1month');
  const [customMonths, setCustomMonths] = useState(3);

  const [isLoading, setIsLoading] = useState(false);

  // Live count preview — refetches whenever the period filter changes so
  // the summary line reflects what will actually happen.
  const olderThanDays = selectedOption === 'custom'
    ? monthsToDays(customMonths)
    : DAYS_MAP[selectedOption];
  const { count, willBeAsync } = useBulkActionCount({
    endpoint: '/emails/clean-inbox',
    enabled: true,
    body: { older_than_days: olderThanDays, keep_unread: true },
  });

  const handleQuickOptionChange = useCallback((option: QuickOption) => {
    setSelectedOption(option);
  }, []);

  const handleSliderChange = useCallback((value: number) => {
    setCustomMonths(value);
    setSelectedOption('custom');
  }, []);

  const handleClean = useCallback(async () => {
    setIsLoading(true);
    // Audit F-04 (2026-05-12): close the modal ONLY after onClean resolves —
    // not before. Previously onClose() was inside the try and ran after a
    // successful onClean, but on error nothing told the user the cleanup
    // failed. Now we surface a toast + keep the modal open so they can retry.
    try {
      const days = selectedOption === 'custom'
        ? monthsToDays(customMonths)
        : DAYS_MAP[selectedOption];

      await onClean({
        olderThanDays: days,
        keepUnread: true,
        unsubscribeNewsletters: false,
      });
    } catch (error) {
      console.error('Failed to clean inbox:', error);
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('toasts.clean_inbox_failed', { ns: 'common' }),
          type: 'error',
          duration: 8000,
        },
      }));
      setIsLoading(false);
      return;
    }
    setIsLoading(false);
    onClose();
  }, [selectedOption, customMonths, onClean, onClose, t]);

  const getMonthLabel = (months: number): string => t('clean_month', { count: months });

  const getSelectedDaysLabel = (): string => {
    if (selectedOption === 'custom') return getMonthLabel(customMonths);
    switch (selectedOption) {
      case '1week': return t('clean_1week');
      case '2weeks': return t('clean_2weeks');
      case '1month': return t('clean_1month');
      default: return '';
    }
  };

  // Fill the slider track up to the thumb so the control reads as "filled".
  const sliderPct = ((customMonths - SLIDER_MIN) / (SLIDER_MAX - SLIDER_MIN)) * 100;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      {/* Audit 2026-05-18: drop the manual aria-labelledby/role/aria-modal so
          Radix's auto-discovery sees our DialogTitle. The previous explicit
          labelledby pointed at our DialogTitle by id, but Radix v1's a11y
          check still warned because the internal labelledby it generated
          went elsewhere. Letting Radix wire DialogContent → DialogTitle on
          its own resolves the warning without changing the rendered DOM. */}
      <DialogContent className="clean-inbox-modal" showCloseButton={false} aria-describedby={undefined}>
        <div className="clean-inbox-top-bar">
          <button className="clean-inbox-back" onClick={onClose} aria-label={t('common:back', 'Back')} title={t('common:back', 'Back')}>
            <ChevronLeftIcon size={20} />
          </button>
          <DialogTitle className="clean-inbox-top-title">{t('clean_title')}</DialogTitle>
          <button className="clean-inbox-close" onClick={onClose} aria-label={t('clean_close')}>
            <CloseIcon />
          </button>
        </div>

        <div className="clean-inbox-description">
          <p>{t('clean_description')}</p>
          <p>{t('clean_description_2')}</p>
        </div>

        <div className="clean-inbox-options">
          <h3>{t('clean_archive_older_than')}</h3>

          <div
            className="clean-period-segments"
            role="radiogroup"
            aria-label={t('clean_archive_older_than')}
          >
            {QUICK_PERIODS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={selectedOption === opt.value}
                className={`clean-period-segment${selectedOption === opt.value ? ' active' : ''}`}
                onClick={() => handleQuickOptionChange(opt.value)}
              >
                {t(opt.labelKey)}
              </button>
            ))}
          </div>

          <div className={`custom-slider-section${selectedOption === 'custom' ? ' active' : ''}`}>
            <div className="slider-header">
              <span className="slider-label">{t('clean_custom_period')}</span>
              <span className="slider-value">{getMonthLabel(customMonths)}</span>
            </div>
            <div className="slider-container">
              <input
                type="range"
                min={SLIDER_MIN}
                max={SLIDER_MAX}
                value={customMonths}
                onChange={(e) => handleSliderChange(Number(e.target.value))}
                className="custom-slider"
                style={{ '--slider-fill': `${sliderPct}%` } as CSSProperties}
                aria-label={t('clean_slider_aria')}
              />
              <div className="slider-ticks">
                {SLIDER_TICKS.map((m) => (
                  <span
                    key={m}
                    style={{ left: `${((m - SLIDER_MIN) / (SLIDER_MAX - SLIDER_MIN)) * 100}%` }}
                  >
                    {`${m}m`}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="clean-inbox-summary">
          <p>
            {t('clean_summary', { period: getSelectedDaysLabel() })}
            {count !== null && count > 0 && (
              <> · {tInbox('bulk_count_summary', { count })}</>
            )}
          </p>
          {willBeAsync && (
            <p className="clean-inbox-summary-hint">{tInbox('bulk_queued_hint')}</p>
          )}
        </div>

        <button
          className="clean-inbox-submit"
          onClick={handleClean}
          disabled={isLoading}
          aria-busy={isLoading}
        >
          {isLoading ? (
            <>
              <span className="loading-spinner" />
              {t('clean_cleaning')}
            </>
          ) : (
            t('clean_now')
          )}
        </button>
      </DialogContent>
    </Dialog>
  );
}
