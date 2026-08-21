/* eslint-disable react-refresh/only-export-components */
/**
 * LimitReachedBanner - Stub component (Story 9-5)
 * Shows a banner when daily draft limit is reached
 */
import { useTranslation } from 'react-i18next';
import { usageLimitsService } from '../services/subscription';

interface LimitReachedBannerProps {
  onUpgrade?: () => void;
  className?: string;
}

/**
 * Hook to check if limit is reached
 */
export function useIsLimitReached(): boolean {
  const limits = usageLimitsService.getUsageLimits();
  return limits.isLimitReached;
}

/**
 * Banner component - only shows when limit is reached
 */
export function LimitReachedBanner({ onUpgrade, className }: LimitReachedBannerProps) {
  const { t } = useTranslation('common');
  const isLimitReached = useIsLimitReached();

  if (!isLimitReached) {
    return null;
  }

  return (
    <div className={`limit-reached-banner ${className || ''}`} style={{
      padding: '12px 16px',
      backgroundColor: '#fef3c7',
      border: '1px solid #f59e0b',
      borderRadius: '8px',
      marginBottom: '16px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '20px' }}>⚠️</span>
        <div style={{ flex: 1 }}>
          <strong>{t('limit_title')}</strong>
          <p style={{ margin: '4px 0 0', fontSize: '14px', color: '#92400e' }}>
            {t('limit_message')}
          </p>
        </div>
        {onUpgrade && (
          <button
            onClick={onUpgrade}
            style={{
              padding: '8px 16px',
              backgroundColor: '#f59e0b',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            {t('limit_upgrade')}
          </button>
        )}
      </div>
    </div>
  );
}
