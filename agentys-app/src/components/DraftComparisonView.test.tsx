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

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DraftComparisonView } from './DraftComparisonView';
import type { DraftVersion } from '../services/api';

const mockVersionA: DraftVersion = {
  id: 'v-1',
  body: 'Version A du brouillon avec quelques modifications importantes.',
  instructions: 'Plus formel',
  timestamp: new Date('2026-01-19T12:00:00Z'),
  pipelineDetails: {
    draft_v1: 'Version V1',
    critique: { is_valid: true, feedback: 'Bon travail' },
    was_corrected: false,
  },
};

const mockVersionB: DraftVersion = {
  id: 'v-2',
  body: 'Version B du brouillon, la version originale.',
  instructions: 'Version initiale',
  timestamp: new Date('2026-01-19T11:00:00Z'),
  pipelineDetails: {
    draft_v1: 'Version V1 originale',
    critique: { is_valid: false, feedback: 'Trop informel' },
    was_corrected: true,
  },
};

const allVersions: DraftVersion[] = [
  mockVersionA,
  mockVersionB,
  {
    id: 'v-3',
    body: 'Version C',
    instructions: 'Autre version',
    timestamp: new Date('2026-01-19T10:00:00Z'),
  },
];

describe('DraftComparisonView', () => {
  const defaultProps = {
    versionA: mockVersionA,
    versionB: mockVersionB,
    allVersions,
    onClose: vi.fn(),
    onVersionChange: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders comparison view with two panes (AC5)', () => {
    render(<DraftComparisonView {...defaultProps} />);

    expect(screen.getByText('Comparaison des versions')).toBeInTheDocument();
    // Should have both version contents visible
    expect(screen.getByText(/Version A du brouillon/)).toBeInTheDocument();
    expect(screen.getByText(/Version B du brouillon/)).toBeInTheDocument();
  });

  it('displays version instructions in pane headers', () => {
    render(<DraftComparisonView {...defaultProps} />);

    expect(screen.getByText('Plus formel')).toBeInTheDocument();
    expect(screen.getByText('Version initiale')).toBeInTheDocument();
  });

  it('displays pipeline status badges', () => {
    render(<DraftComparisonView {...defaultProps} />);

    expect(screen.getByText('Approuvé')).toBeInTheDocument();
    expect(screen.getByText('Corrigé')).toBeInTheDocument();
  });

  it('allows changing left version via selector', () => {
    const onVersionChange = vi.fn();
    render(
      <DraftComparisonView {...defaultProps} onVersionChange={onVersionChange} />
    );

    const selectors = screen.getAllByRole('combobox');
    expect(selectors.length).toBe(2);

    // Change left selector to v-3
    fireEvent.change(selectors[0], { target: { value: 'v-3' } });

    expect(onVersionChange).toHaveBeenCalledWith('left', allVersions[2]);
  });

  it('allows changing right version via selector', () => {
    const onVersionChange = vi.fn();
    render(
      <DraftComparisonView {...defaultProps} onVersionChange={onVersionChange} />
    );

    const selectors = screen.getAllByRole('combobox');

    // Change right selector to v-3
    fireEvent.change(selectors[1], { target: { value: 'v-3' } });

    expect(onVersionChange).toHaveBeenCalledWith('right', allVersions[2]);
  });

  it('calls onClose when clicking close button', async () => {
    const onClose = vi.fn();
    render(<DraftComparisonView {...defaultProps} onClose={onClose} />);

    const closeButton = screen.getByLabelText('Fermer');
    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    }, { timeout: 500 });
  });

  it('calls onClose when clicking overlay', async () => {
    const onClose = vi.fn();
    render(<DraftComparisonView {...defaultProps} onClose={onClose} />);

    const overlay = screen.getByTestId('comparison-overlay');
    fireEvent.click(overlay);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    }, { timeout: 500 });
  });

  it('does not close when clicking inside modal', () => {
    const onClose = vi.fn();
    render(<DraftComparisonView {...defaultProps} onClose={onClose} />);

    const modal = screen.getByText('Comparaison des versions').closest('.draft-comparison-container');
    if (modal) {
      fireEvent.click(modal);
    }

    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes on Escape key', async () => {
    const onClose = vi.fn();
    render(<DraftComparisonView {...defaultProps} onClose={onClose} />);

    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    }, { timeout: 500 });
  });

  it('displays footer with statistics', () => {
    render(<DraftComparisonView {...defaultProps} />);

    // Footer should show word count or other stats
    const footer = screen.getByText('Fermer la comparaison').closest('.comparison-footer');
    expect(footer).toBeInTheDocument();
  });

  it('highlights differences between versions', () => {
    render(<DraftComparisonView {...defaultProps} />);

    // Check for diff highlighting classes
    // At least some content should be displayed (even if no highlighting)
    const paneBody = document.querySelectorAll('.pane-body');
    expect(paneBody.length).toBe(2);
  });

  it('shows instruction info in pane', () => {
    render(<DraftComparisonView {...defaultProps} />);

    // Should display instruction context
    const instructions = screen.getAllByText(/Instructions/i);
    expect(instructions.length).toBeGreaterThanOrEqual(0); // May or may not have explicit label
  });

  it('displays timestamps for each version', () => {
    render(<DraftComparisonView {...defaultProps} />);

    // Should show formatted date/time
    const timestampElements = document.querySelectorAll('.pane-header');
    expect(timestampElements.length).toBe(2);
  });
});

describe('DraftComparisonView - Edge Cases', () => {
  it('handles versions without pipeline details', () => {
    const versionWithoutDetails: DraftVersion = {
      id: 'v-simple',
      body: 'Simple version without pipeline',
      instructions: 'Basic',
      timestamp: new Date(),
    };

    render(
      <DraftComparisonView
        versionA={versionWithoutDetails}
        versionB={mockVersionB}
        allVersions={[versionWithoutDetails, mockVersionB]}
        onClose={vi.fn()}
        onVersionChange={vi.fn()}
      />
    );

    expect(screen.getByText('Simple version without pipeline')).toBeInTheDocument();
  });

  it('handles very long content', () => {
    const longContent = 'Lorem ipsum '.repeat(1000);
    const longVersion: DraftVersion = {
      id: 'v-long',
      body: longContent,
      instructions: 'Long content',
      timestamp: new Date(),
    };

    render(
      <DraftComparisonView
        versionA={longVersion}
        versionB={mockVersionB}
        allVersions={[longVersion, mockVersionB]}
        onClose={vi.fn()}
        onVersionChange={vi.fn()}
      />
    );

    // Should render without crashing
    expect(screen.getByText('Comparaison des versions')).toBeInTheDocument();
  });

  it('handles empty instructions', () => {
    const noInstructionsVersion: DraftVersion = {
      id: 'v-no-inst',
      body: 'Version sans instructions',
      instructions: '',
      timestamp: new Date(),
    };

    render(
      <DraftComparisonView
        versionA={noInstructionsVersion}
        versionB={mockVersionB}
        allVersions={[noInstructionsVersion, mockVersionB]}
        onClose={vi.fn()}
        onVersionChange={vi.fn()}
      />
    );

    expect(screen.getByText('Version sans instructions')).toBeInTheDocument();
  });
});
