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

import { useTranslation } from 'react-i18next';
import type { DraftVersion } from '../services/api';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import { formatCompactDateTime } from '../utils/dateFormat';
import { CloseIcon } from './icons/ActionIcons';
import './DraftVersionHistory.css';

interface DraftVersionHistoryProps {
  versions: DraftVersion[];
  currentVersionId?: string;
  onVersionSelect: (version: DraftVersion) => void;
  onCompare: (versionA: DraftVersion, versionB: DraftVersion) => void;
  isOpen: boolean;
  onClose: () => void;
}

export function DraftVersionHistory({
  versions,
  currentVersionId,
  onVersionSelect,
  onCompare,
  isOpen,
  onClose,
}: DraftVersionHistoryProps) {
  const { t: tDrafts } = useTranslation('drafts');
  const { t: tCommon } = useTranslation('common');
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose, 180);

  const formatTimestamp = (date: Date) => {
    return formatCompactDateTime(new Date(date));
  };

  const truncateText = (text: string, maxLength: number = 100) => {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  if (!shouldRender) return null;

  return (
    <div className={`draft-version-history${isClosing ? ' closing' : ''}`} data-testid="draft-version-history">
      <div className="version-history-header">
        <h3>{tCommon('version_history')}</h3>
        <button
          className="version-history-close"
          onClick={handleClose}
          aria-label={tCommon('close')}
        >
          <CloseIcon />
        </button>
      </div>

      {versions.length === 0 ? (
        <div className="version-history-empty">
          <p>{tCommon('no_previous_version')}</p>
          <p className="version-history-hint">
            {tCommon('versions_saved_hint')}
          </p>
        </div>
      ) : (
        <>
          <div className="version-history-list">
            {versions.map((version, index) => (
              <div
                key={version.id}
                className={`version-history-item ${currentVersionId === version.id ? 'current' : ''}`}
                data-testid={`version-item-${index}`}
              >
                <div className="version-item-header">
                  <span className="version-number">
                    {tCommon('version_number', { n: versions.length - index })}
                    {currentVersionId === version.id && (
                      <span className="current-badge">{tCommon('current_version')}</span>
                    )}
                  </span>
                  <span className="version-timestamp">
                    {formatTimestamp(version.timestamp)}
                  </span>
                </div>

                {version.instructions && (
                  <div className="version-instructions">
                    <span className="instructions-label">{tCommon('instructions_label')}</span>
                    <span className="instructions-text">
                      {truncateText(version.instructions, 80)}
                    </span>
                  </div>
                )}

                <div className="version-preview">
                  {truncateText(version.body, 150)}
                </div>

                {version.pipelineDetails && (
                  <div className="version-pipeline-badge">
                    {version.pipelineDetails.critique.is_valid ? (
                      <span className="badge valid">{tDrafts('approved')}</span>
                    ) : (
                      <span className="badge corrected">{tDrafts('corrected')}</span>
                    )}
                  </div>
                )}

                <div className="version-item-actions">
                  <button
                    className="version-action-button view"
                    onClick={() => onVersionSelect(version)}
                    disabled={currentVersionId === version.id}
                    title={currentVersionId === version.id ? tCommon('current_version') : tCommon('view')}
                  >
                    {currentVersionId === version.id ? tCommon('shown') : tCommon('view')}
                  </button>
                  {index < versions.length - 1 && (
                    <button
                      className="version-action-button compare"
                      onClick={() => onCompare(version, versions[index + 1])}
                      title={tDrafts('compare_prev_version')}
                    >
                      {tCommon('compare')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {versions.length >= 2 && (
            <div className="version-history-footer">
              <button
                className="compare-all-button"
                onClick={() => onCompare(versions[0], versions[versions.length - 1])}
              >
                {tCommon('compare_first_last')}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
