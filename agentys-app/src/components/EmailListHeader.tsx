import React, { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { getLabelDisplayName, type Label, DEFAULT_LABELS } from '../types/labels';
import type { EmailFolder } from '../api/emails';
import { SearchIcon } from './icons/ActionIcons';

// Hardcoded fallback: always show Action/FYI/Noise tabs even if labels API hasn't loaded
const CORE_TABS_FALLBACK: Label[] = DEFAULT_LABELS
  .filter(l => ['Action', 'FYI', 'Noise'].includes(l.name))
  .map(l => ({ ...l, created_at: '', rules: [] }));

export interface EmailListHeaderProps {
  folder: EmailFolder;
  folderTitle: string;
  /** The currently active label filter (null = no filter) */
  activeLabel: string | null | undefined;
  /** Unread count to display in the folder tab */
  unreadCount: number;
  /** Favorite labels to render as tabs (inbox only) */
  favoriteLabels: Label[];
  /** Counts per label name */
  labelCounts: Record<string, number>;
  /** Callback when label tab is clicked */
  onLabelClick: (labelName: string) => void;
  /** Callback to clear the active label */
  onClearLabel: () => void;
  /** Whether the search bar is currently shown */
  showSearchBar: boolean;
  /** Toggle search bar visibility */
  onToggleSearchBar: () => void;
  /** Whether this is a loading/skeleton state header (limited actions) */
  skeleton?: boolean;
  /** Whether multi-select mode is active */
  multiSelectMode?: boolean;
  /** Number of currently selected emails */
  selectedCount?: number;
  /** Total number of visible emails */
  totalCount?: number;
  /** Select all visible emails */
  onSelectAll?: () => void;
  /** Deselect all and exit multi-select */
  onDeselectAll?: () => void;
  /** Select all from currently selected email downwards */
  onSelectAllFromHere?: () => void;
}

export const EmailListHeader = React.memo(function EmailListHeader({
  folder,
  folderTitle,
  activeLabel,
  unreadCount: _unreadCount,
  favoriteLabels,
  labelCounts,
  onLabelClick,
  onClearLabel,
  showSearchBar,
  onToggleSearchBar,
  skeleton = false,
  multiSelectMode = false,
  selectedCount = 0,
  totalCount = 0,
  onSelectAll,
  onDeselectAll,
  onSelectAllFromHere,
}: EmailListHeaderProps) {
  const { t } = useTranslation('inbox');
  const allSelected = totalCount > 0 && selectedCount === totalCount;
  const someSelected = selectedCount > 0 && !allSelected;
  const [showSelectMenu, setShowSelectMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCheckboxClick = () => {
    if (allSelected) {
      onDeselectAll?.();
    } else {
      onSelectAll?.();
    }
  };

  const handleMouseEnter = () => {
    if (hideTimerRef.current) { clearTimeout(hideTimerRef.current); hideTimerRef.current = null; }
    setShowSelectMenu(true);
  };

  const handleMouseLeave = () => {
    hideTimerRef.current = setTimeout(() => setShowSelectMenu(false), 200);
  };

  const handleMenuSelectAll = useCallback(() => {
    onSelectAll?.();
    setShowSelectMenu(false);
  }, [onSelectAll]);

  const handleMenuSelectFromHere = useCallback(() => {
    onSelectAllFromHere?.();
    setShowSelectMenu(false);
  }, [onSelectAllFromHere]);
  if (skeleton) {
    return (
      <div className="email-list-header">
        <div className="header-tabs">
        </div>
        <div className="header-actions">
          <button className="header-icon-btn" onClick={onToggleSearchBar} title={t('search')} aria-label={t('search')}>
            <SearchIcon />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="email-list-header">
      {onSelectAll && multiSelectMode && (
        <div className="header-select-wrapper" ref={menuRef} onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
          <button
            className={`header-select-btn${someSelected ? ' partial' : ''}${allSelected ? ' all' : ''}`}
            onClick={handleCheckboxClick}
            aria-label={allSelected ? t('deselect_all') : t('select_all')}
          >
            {allSelected ? (
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="1" y="1" width="14" height="14" rx="3" fill="var(--accent-primary)" stroke="var(--accent-primary)" strokeWidth="1.5" />
                <path d="M4.5 8L7 10.5L11.5 5.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : someSelected ? (
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="1" y="1" width="14" height="14" rx="3" fill="var(--accent-primary)" stroke="var(--accent-primary)" strokeWidth="1.5" />
                <line x1="4.5" y1="8" x2="11.5" y2="8" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            ) : (
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="1" y="1" width="14" height="14" rx="3" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
              </svg>
            )}
            {selectedCount > 0 && (
              <span className="header-select-count">{selectedCount}</span>
            )}
          </button>
          {showSelectMenu && (
            <div className="header-select-menu">
              <button className="header-select-menu-item" onClick={handleMenuSelectAll}>
                <span>{t('select_all')}</span>
                <span className="shortcut-keys">
                  <kbd>ctrl</kbd><kbd>shift</kbd><kbd>A</kbd>
                </span>
              </button>
              <button className="header-select-menu-item" onClick={handleMenuSelectFromHere}>
                <span>{t('select_from_here')}</span>
                <span className="shortcut-keys">
                  <kbd>ctrl</kbd><kbd>A</kbd>
                </span>
              </button>
            </div>
          )}
        </div>
      )}
      <div className="header-tabs">
        {folder === 'inbox' ? (
          <>
            {/* Audit Cluster D (2026-05-17) U-08: a11y — tabs lacked
                aria-pressed so screen readers couldn't tell which was
                active. The visual `active` class was the only signal. */}
            <button
              type="button"
              className={`header-tab ${!activeLabel ? 'active' : ''}`}
              onClick={onClearLabel}
              aria-pressed={!activeLabel}
            >
              {t('mail', 'Boîte de réception')}
              {(labelCounts['__total__'] || 0) > 0 && (
                <span className="header-tab-count">{(labelCounts['__total__'] as number).toLocaleString()}</span>
              )}
            </button>
            {(favoriteLabels.length > 0 ? favoriteLabels : CORE_TABS_FALLBACK).map(label => {
              const count = labelCounts[label.name] || 0;
              const isActive = activeLabel === label.name;
              return (
                <button
                  type="button"
                  key={label.name}
                  className={`header-tab header-tab-label ${isActive ? 'active' : ''}`}
                  onClick={() => onLabelClick(label.name)}
                  style={{ '--label-color': label.color } as React.CSSProperties}
                  aria-pressed={isActive}
                >
                  {getLabelDisplayName(label.name)}
                  {count > 0 && <span className="header-tab-count">{count.toLocaleString()}</span>}
                </button>
              );
            })}
          </>
        ) : (
          <span className="header-location">{folderTitle}</span>
        )}
      </div>
      <div className="header-actions">
        <button
          className={`header-icon-btn ${showSearchBar ? 'active' : ''}`}
          onClick={onToggleSearchBar}
          title={t('search')}
          aria-label={t('search')}
          aria-expanded={showSearchBar}
        >
          <SearchIcon />
        </button>
      </div>
    </div>
  );
});
