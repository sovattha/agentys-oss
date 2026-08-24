/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { useCallback, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { TimezonePicker, useSecondaryTimezone, useTz2Color } from './TimezoneUtils';
import { UpdateBell } from './UpdateBell';
import { ActivityIndicator } from './ActivityIndicator';
import { EditIcon, PlusIcon, SendIcon, TrashIcon, SettingsIcon } from './icons/ActionIcons';
import type { ActivityState } from '../types/activity';
import './Sidebar.css';

type SidebarTab = 'inbox' | 'drafts' | 'scheduled' | 'sent' | 'archived' | 'trash' | 'spam' | 'snoozed';
type AppMode = 'mail' | 'calendar';
type BillingMode = 'free' | 'paid' | 'unknown';

interface SidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  onCompose: () => void;
  onOpenSettings: () => void;
  billingMode?: BillingMode;
  onOpenBilling?: () => void;
  onOpenSupport: () => void;
  onOpenLearning?: () => void;
  unreadCount: number;
  draftCount: number;
  /** Count of AI-generated drafts the user hasn't opened — drives green dot indicator. */
  unviewedDraftCount?: number;
  spamCount?: number;
  snoozedCount?: number;
  scheduledCount?: number;
  appMode: AppMode;
  onAppModeChange: (mode: AppMode) => void;
  activeLabel?: string | null;
  onLabelChange?: (label: string | null) => void;
  activeFolderId?: string | null;
  onFolderSelect?: (folderId: string | null) => void;
  hasUpdate?: boolean;
  deepWorkActive?: boolean;
  onDeepWorkClick?: () => void;
  onCreateCalendarEvent?: () => void;
  activityState?: ActivityState;
  /** Mobile navigation props */
  isMobile?: boolean;
  isOpen?: boolean;
  onClose?: () => void;
  /** Minutes until next upcoming meeting — drives the calendar icon countdown badge. Null when none within ~60 min. */
  nextMeetingMinutes?: number | null;
}

export type { SidebarTab };

export const Sidebar = memo(function Sidebar({
  activeTab,
  onTabChange,
  onCompose,
  onOpenSettings,
  billingMode = 'unknown',
  onOpenBilling,
  onOpenSupport,
  onOpenLearning,
  unreadCount,
  draftCount: _draftCount,
  unviewedDraftCount = 0,
  spamCount: _spamCount = 0,
  snoozedCount = 0,
  scheduledCount = 0,
  appMode,
  onAppModeChange,
  deepWorkActive: _deepWorkActive = false,
  onDeepWorkClick: _onDeepWorkClick,
  onCreateCalendarEvent,
  hasUpdate = false,
  activityState,
  isMobile = false,
  isOpen = false,
  onClose,
  nextMeetingMinutes,
}: SidebarProps) {

  const { t: tInbox } = useTranslation('inbox');
  const { t: tCommon } = useTranslation('common');
  const { t: tCalendar } = useTranslation('calendar');
  const { t: tSettings } = useTranslation('settings');
  const [secondaryTz, setSecondaryTz] = useSecondaryTimezone();
  const [tz2Color, setTz2Color] = useTz2Color();

  const handleTabChange = useCallback((tab: SidebarTab) => {
    onTabChange(tab);
  }, [onTabChange]);

  const handleMobileToggle = useCallback(() => {
    if (isMobile) onClose?.();
  }, [isMobile, onClose]);

  const sidebarClass = isMobile
    ? `sidebar ${isOpen ? 'expanded' : 'collapsed'}`
    : 'sidebar collapsed';

  const logoMark = (
    <span className="sidebar-logo-mark">
      <svg aria-hidden="true" width="38" height="38" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="agGlow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="1.2" result="blur"/>
            <feComposite in="SourceGraphic" in2="blur" operator="over"/>
          </filter>
        </defs>
        <g filter="url(#agGlow)">
          <path d="M16 2.5L1.5 29.5h29z" stroke="#2dd4bf" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" fill="none" opacity="0.7"/>
          <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
        </g>
        <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-primary, #1a1a1e)"/>
      </svg>
    </span>
  );

  return (
    <aside
      id="sidebar-nav"
      className={sidebarClass}
      role="navigation"
      aria-label={tCommon('main_nav')}
      data-testid="sidebar"
    >
      {/* Logo */}
      <div className="sidebar-header">
        {isMobile ? (
          <button
            type="button"
            className="sidebar-logo-toggle"
            onClick={handleMobileToggle}
            aria-label={isOpen ? tCommon('close') : tCommon('main_nav')}
            aria-expanded={isOpen}
            aria-controls="sidebar-nav"
          >
            {logoMark}
          </button>
        ) : logoMark}
      </div>

      {/* App mode switcher — mail / calendar */}
      <div className="sidebar-mode-switcher">
        <button
          className={`sidebar-item ${appMode === 'mail' ? 'active' : ''}`}
          onClick={() => {
            onAppModeChange('mail');
            // BUG-005: toujours naviguer vers inbox, que l'on vienne du calendrier
            // ou qu'on soit déjà en mode mail — le 1er clic suffisait mais
            // handleTabChange n'était appelé que si appMode === 'mail' déjà.
            handleTabChange('inbox');
          }}
          title={tInbox('mail')}
          aria-label={tInbox('mail')}
          aria-pressed={appMode === 'mail'}
        >
          <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <rect width="20" height="16" x="2" y="4" rx="2" />
            <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
          </svg>
          <span className="sidebar-label">{tInbox('mail')}</span>
        </button>
        <button
          className={`sidebar-item ${appMode === 'calendar' ? 'active' : ''}`}
          onClick={() => onAppModeChange('calendar')}
          title={tCalendar('title')}
          aria-label={tCalendar('title')}
          aria-pressed={appMode === 'calendar'}
          data-testid="nav-calendar"
        >
          <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <rect width="18" height="18" x="3" y="4" rx="2" />
            <path d="M16 2v4" /><path d="M8 2v4" /><path d="M3 10h18" />
          </svg>
          <span className="sidebar-label">{tCalendar('agenda')}</span>
          {typeof nextMeetingMinutes === 'number' && nextMeetingMinutes >= 0 && nextMeetingMinutes <= 60 && (
            <span
              className="sidebar-meeting-countdown"
              data-testid="sidebar-meeting-countdown"
              aria-label={tCalendar('next_meeting_in_minutes', { count: nextMeetingMinutes })}
              title={tCalendar('next_meeting_in_minutes', { count: nextMeetingMinutes })}
            >
              {nextMeetingMinutes <= 0 ? tCalendar('now_short') : `${nextMeetingMinutes}m`}
            </span>
          )}
        </button>
      </div>

      {/* Compose */}
      {appMode === 'mail' && (
        <button
          className="sidebar-compose"
          onClick={onCompose}
          title={tCommon('new_message')}
          aria-label={tCommon('new_message')}
          data-testid="compose-button"
        >
          <EditIcon className="compose-icon" />
          <span className="sidebar-label">{tCommon('new_message')}</span>
        </button>
      )}

      {/* New Calendar Event */}
      {appMode === 'calendar' && onCreateCalendarEvent && (
        <button
          className="sidebar-compose"
          onClick={onCreateCalendarEvent}
          title={tCalendar('new_event_shortcut')}
          aria-label={tCalendar('new_event')}
          data-testid="new-event-button"
        >
          <PlusIcon className="compose-icon" />
          <span className="sidebar-label">{tCalendar('new_event_btn')}</span>
        </button>
      )}

      {/* Mail nav */}
      {appMode === 'mail' && (
        <nav className="sidebar-nav">
          <button
            className={`sidebar-item ${activeTab === 'inbox' ? 'active' : ''}`}
            onClick={() => handleTabChange('inbox')}
            title={tInbox('title')}
            aria-label={tInbox('title')}
            aria-current={activeTab === 'inbox' ? 'page' : undefined}
            data-testid="nav-inbox"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
              <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
            </svg>
            <span className="sidebar-label">{tInbox('title')}</span>
            {unreadCount > 0 && <span className="sidebar-badge">{unreadCount}</span>}
          </button>

          <button
            className={`sidebar-item ${activeTab === 'drafts' ? 'active' : ''}`}
            onClick={() => handleTabChange('drafts')}
            title={unviewedDraftCount > 0
              ? tInbox('drafts_unviewed_tooltip', {
                  count: unviewedDraftCount,
                  defaultValue: '{{count}} brouillon(s) IA non consulté(s)',
                })
              : tInbox('drafts')}
            aria-label={unviewedDraftCount > 0
              ? tInbox('drafts_unviewed_aria', {
                  count: unviewedDraftCount,
                  defaultValue: 'Brouillons — {{count}} non consulté(s)',
                })
              : tInbox('drafts')}
            aria-current={activeTab === 'drafts' ? 'page' : undefined}
            data-testid="nav-drafts"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
              <path d="M14 2v4a1 1 0 0 0 1 1h4" />
              <path d="M10 13h4" /><path d="M10 17h4" />
            </svg>
            <span className="sidebar-label">{tInbox('drafts')}</span>
            {/* BUG-AB002 fix (Session AB, 2026-05-22): the badge counts only
                AI drafts the user hasn't opened yet (not total drafts) — same
                pattern as unread emails. Tooltip + aria-label above now make
                that explicit so QA / power users don't read it as "total". */}
            {unviewedDraftCount > 0 && (
              <span
                className="sidebar-badge"
                aria-label={tInbox('drafts_unviewed_aria', {
                  count: unviewedDraftCount,
                  defaultValue: '{{count}} non consulté(s)',
                })}
              >
                {unviewedDraftCount}
              </span>
            )}
          </button>

          <button
            className={`sidebar-item ${activeTab === 'snoozed' || activeTab === 'scheduled' ? 'active' : ''}`}
            onClick={() => handleTabChange('snoozed')}
            title={tInbox('later', 'Plus tard')}
            aria-label={tInbox('later', 'Plus tard')}
            aria-current={activeTab === 'snoozed' || activeTab === 'scheduled' ? 'page' : undefined}
            data-testid="nav-snoozed"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
            <span className="sidebar-label">{tInbox('later', 'Plus tard')}</span>
            {(snoozedCount + scheduledCount) > 0 && <span className="sidebar-badge">{snoozedCount + scheduledCount}</span>}
          </button>

          <button
            className={`sidebar-item ${activeTab === 'sent' ? 'active' : ''}`}
            onClick={() => handleTabChange('sent')}
            title={tInbox('sent')}
            aria-label={tInbox('sent')}
            aria-current={activeTab === 'sent' ? 'page' : undefined}
            data-testid="nav-sent"
          >
            <SendIcon className="sidebar-icon" />
            <span className="sidebar-label">{tInbox('sent')}</span>
          </button>

          <button
            className={`sidebar-item ${activeTab === 'archived' ? 'active' : ''}`}
            onClick={() => handleTabChange('archived')}
            title={tInbox('archive')}
            aria-label={tInbox('archive')}
            aria-current={activeTab === 'archived' ? 'page' : undefined}
            data-testid="nav-archived"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <rect width="20" height="5" x="2" y="3" rx="1" />
              <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />
              <path d="M10 12h4" />
            </svg>
            <span className="sidebar-label">{tInbox('archive')}</span>
          </button>

          <button
            className={`sidebar-item ${activeTab === 'spam' ? 'active' : ''}`}
            onClick={() => handleTabChange('spam')}
            title={tInbox('spam')}
            aria-label={tInbox('spam')}
            aria-current={activeTab === 'spam' ? 'page' : undefined}
            data-testid="nav-spam"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="m4.9 4.9 14.2 14.2" />
            </svg>
            <span className="sidebar-label">{tInbox('spam')}</span>
          </button>

          <button
            className={`sidebar-item ${activeTab === 'trash' ? 'active' : ''}`}
            onClick={() => handleTabChange('trash')}
            title={tInbox('trash')}
            aria-label={tInbox('trash')}
            aria-current={activeTab === 'trash' ? 'page' : undefined}
            data-testid="nav-trash"
          >
            <TrashIcon className="sidebar-icon" />
            <span className="sidebar-label">{tInbox('trash')}</span>
          </button>
        </nav>
      )}

      {/* Calendar nav */}
      {appMode === 'calendar' && (
        <nav className="sidebar-nav">
          <div className="sidebar-tz-wrap">
            <TimezonePicker
              value={secondaryTz}
              onChange={setSecondaryTz}
              tz2Color={tz2Color}
              onColorChange={setTz2Color}
            />
          </div>
        </nav>
      )}

      {/* Footer */}
      <div className="sidebar-footer">
        {billingMode === 'free' && (
          <button
            className="sidebar-item sidebar-plan-badge"
            onClick={onOpenBilling ?? onOpenSettings}
            title={`${tSettings('billing_status_free', { defaultValue: 'Gratuit' })} — ${tSettings('billing_subtitle', { defaultValue: 'Les fonctionnalités IA nécessitent un abonnement actif.' })}`}
            aria-label={`${tSettings('billing_status_free', { defaultValue: 'Gratuit' })} — ${tSettings('billing_subtitle', { defaultValue: 'Les fonctionnalités IA nécessitent un abonnement actif.' })}`}
            data-testid="nav-billing-free"
            type="button"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <rect x="5" y="10" width="14" height="10" rx="2" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            <span className="sidebar-label">{tSettings('billing_status_free', { defaultValue: 'Gratuit' })}</span>
          </button>
        )}
        {activityState && (
          <ActivityIndicator activityState={activityState} />
        )}
        {onOpenLearning && (
          <button
            className="sidebar-item"
            onClick={onOpenLearning}
            title={tCommon('learning_board')}
            aria-label={tCommon('learning_board')}
            data-testid="nav-learning"
          >
            <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
              <line x1="9" y1="21" x2="15" y2="21" />
              <line x1="10" y1="17" x2="14" y2="17" />
            </svg>
            <span className="sidebar-label">{tCommon('learning')}</span>
          </button>
        )}
        <button
          className="sidebar-item"
          onClick={onOpenSupport}
          title={tSettings('help_support')}
          aria-label={tSettings('help_support')}
          data-testid="nav-support"
        >
          <svg aria-hidden="true" className="sidebar-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            <circle cx="8" cy="10" r="1" fill="currentColor" stroke="none"/>
            <circle cx="12" cy="10" r="1" fill="currentColor" stroke="none"/>
            <circle cx="16" cy="10" r="1" fill="currentColor" stroke="none"/>
          </svg>
          <span className="sidebar-label">{tSettings('section_help')}</span>
        </button>
        <UpdateBell sidebar />
        <button
          className="sidebar-item"
          onClick={onOpenSettings}
          title={hasUpdate ? tSettings('update_available') : tSettings('title')}
          aria-label={hasUpdate ? tSettings('update_available') : tSettings('title')}
          data-testid="nav-settings"
        >
          <span className="sidebar-icon-wrapper">
            <SettingsIcon className="sidebar-icon" />
            {hasUpdate && <span className="sidebar-update-dot" />}
          </span>
          <span className="sidebar-label">{tSettings('title')}</span>
          {hasUpdate && <span className="sidebar-update-badge">1</span>}
        </button>
      </div>
    </aside>
  );
})
