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

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraftVersion } from '../services/api';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import { CloseIcon } from './icons/ActionIcons';
import './DraftComparisonView.css';

interface DraftComparisonViewProps {
  versionA: DraftVersion;
  versionB: DraftVersion;
  allVersions: DraftVersion[];
  onClose: () => void;
  onVersionChange: (side: 'left' | 'right', version: DraftVersion) => void;
}

export function DraftComparisonView({
  versionA,
  versionB,
  allVersions,
  onClose,
  onVersionChange,
}: DraftComparisonViewProps) {
  const { t } = useTranslation('drafts');
  const { t: tCommon } = useTranslation('common');
  const { isClosing, handleClose } = useAnimatedUnmount(true, onClose, 180);
  const [highlightDiffs] = useState(false);

  // Handle escape key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleClose]);

  const formatTimestamp = (date: Date) => {
    return new Date(date).toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getVersionLabel = (version: DraftVersion) => {
    const index = allVersions.findIndex(v => v.id === version.id);
    return `Version ${allVersions.length - index}`;
  };

  // Simple line-by-line comparison
  const getLineClass = (line: string, otherContent: string) => {
    if (!highlightDiffs) return '';
    const otherLines = otherContent.split('\n');
    if (!otherLines.includes(line)) {
      return 'line-added';
    }
    return '';
  };

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      handleClose();
    }
  };

  return (
    <div
      className={`draft-comparison-overlay${isClosing ? ' closing' : ''}`}
      data-testid="comparison-overlay"
      onClick={handleOverlayClick}
    >
      <div className={`draft-comparison-container${isClosing ? ' closing' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="comparison-header">
          <h2>{tCommon('version_comparison')}</h2>
          <button
            className="comparison-close"
            onClick={handleClose}
            aria-label={tCommon('close')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="comparison-content">
          {/* Left pane (newer version typically) */}
          <div className="comparison-pane">
            <div className="pane-header">
              <select
                className="version-selector"
                value={versionA.id}
                onChange={(e) => {
                  const selected = allVersions.find(v => v.id === e.target.value);
                  if (selected) onVersionChange('left', selected);
                }}
                data-testid="version-selector-left"
              >
                {allVersions.map((v, idx) => (
                  <option key={v.id} value={v.id} disabled={v.id === versionB.id}>
                    Version {allVersions.length - idx} - {formatTimestamp(v.timestamp)}
                  </option>
                ))}
              </select>
              <span className="version-label">{getVersionLabel(versionA)}</span>
            </div>

            {versionA.instructions && (
              <div className="pane-instructions">
                <strong>{tCommon('instructions_label')}</strong> {versionA.instructions}
              </div>
            )}

            <div className="pane-body">
              {versionA.body.split('\n').map((line, idx) => (
                <div
                  key={idx}
                  className={`comparison-line ${getLineClass(line, versionB.body)}`}
                >
                  {line || '\u00A0'}
                </div>
              ))}
            </div>

            {versionA.pipelineDetails && (
              <div className="pane-pipeline">
                <span className={`pipeline-badge ${versionA.pipelineDetails.critique.is_valid ? 'valid' : 'corrected'}`}>
                  {versionA.pipelineDetails.critique.is_valid ? t('approved') : t('corrected')}
                </span>
              </div>
            )}
          </div>

          {/* Divider */}
          <div className="comparison-divider" />

          {/* Right pane (older version typically) */}
          <div className="comparison-pane">
            <div className="pane-header">
              <select
                className="version-selector"
                value={versionB.id}
                onChange={(e) => {
                  const selected = allVersions.find(v => v.id === e.target.value);
                  if (selected) onVersionChange('right', selected);
                }}
                data-testid="version-selector-right"
              >
                {allVersions.map((v, idx) => (
                  <option key={v.id} value={v.id} disabled={v.id === versionA.id}>
                    Version {allVersions.length - idx} - {formatTimestamp(v.timestamp)}
                  </option>
                ))}
              </select>
              <span className="version-label">{getVersionLabel(versionB)}</span>
            </div>

            {versionB.instructions && (
              <div className="pane-instructions">
                <strong>{tCommon('instructions_label')}</strong> {versionB.instructions}
              </div>
            )}

            <div className="pane-body">
              {versionB.body.split('\n').map((line, idx) => (
                <div
                  key={idx}
                  className={`comparison-line ${getLineClass(line, versionA.body)}`}
                >
                  {line || '\u00A0'}
                </div>
              ))}
            </div>

            {versionB.pipelineDetails && (
              <div className="pane-pipeline">
                <span className={`pipeline-badge ${versionB.pipelineDetails.critique.is_valid ? 'valid' : 'corrected'}`}>
                  {versionB.pipelineDetails.critique.is_valid ? t('approved') : t('corrected')}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="comparison-footer">
          <div className="comparison-stats">
            <span>{tCommon('left_chars', { length: versionA.body.length })}</span>
            <span>|</span>
            <span>{tCommon('right_chars', { length: versionB.body.length })}</span>
            <span>|</span>
            <span>{tCommon('diff_chars', { length: Math.abs(versionA.body.length - versionB.body.length) })}</span>
          </div>
          <button className="comparison-close-button" onClick={handleClose}>
            {tCommon('close_comparison')}
          </button>
        </div>
      </div>
    </div>
  );
}
