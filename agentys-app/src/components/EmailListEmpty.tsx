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

import React from 'react';
import { useTranslation } from 'react-i18next';
import type { EmailFolder } from '../api/emails';
import { EmptyState, InboxZeroIcon, NoResultsIcon, EmptyFolderIcon } from './EmptyState';
import { getLabelDisplayName } from '../types/labels';

export interface EmailListEmptyProps {
  folder: EmailFolder;
  activeLabel: string | null | undefined;
  hasActiveFilters: boolean;
  noiseLabelCount: number;
  hideNoise: boolean;
  onToggleHideNoise: () => void;
  isSearching?: boolean;
  searchQuery?: string;
}

export const EmailListEmpty = React.memo(function EmailListEmpty({
  folder,
  activeLabel,
  hasActiveFilters,
  noiseLabelCount,
  hideNoise,
  onToggleHideNoise,
  isSearching,
  searchQuery,
}: EmailListEmptyProps) {
  const { t } = useTranslation('inbox');
  const { t: tSearch } = useTranslation('search');

  // When inbox is empty but Noise emails exist and are hidden, show indicator
  const showNoiseHint = folder === 'inbox' && !activeLabel && !hasActiveFilters && hideNoise && noiseLabelCount > 0;

  return (
    <div className="email-list-empty" data-testid="email-list-empty">
      {isSearching && searchQuery ? (
        <EmptyState
          icon={<NoResultsIcon />}
          title={tSearch('no_results_title')}
        />
      ) : activeLabel ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('empty_no_label', { label: getLabelDisplayName(activeLabel) })}
        />
      ) : hasActiveFilters && folder === 'inbox' ? (
        <EmptyState
          icon={<NoResultsIcon />}
          title={t('empty_no_results')}
          subtitle={t('empty_no_results_sub')}
        />
      ) : folder === 'spam' ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('empty_no_spam')}
        />
      ) : folder === 'trash' ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('empty_trash')}
        />
      ) : folder === 'sent' ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('empty_no_sent')}
        />
      ) : folder === 'archived' ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('empty_no_archive')}
        />
      ) : (
        <EmptyState
          icon={<InboxZeroIcon />}
          title={t('empty_inbox_zero')}
          subtitle=""
        />
      )}
      {showNoiseHint && (
        <div className="noise-hidden-hint" data-testid="noise-hidden-hint">
          <p>{t('noise_hidden_hint', { count: noiseLabelCount })}</p>
          <button className="noise-hidden-toggle" onClick={onToggleHideNoise} type="button">
            {t('noise_hidden_show')}
          </button>
        </div>
      )}
    </div>
  );
});
