import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DraftVersionHistory } from './DraftVersionHistory';
import type { DraftVersion } from '../services/api';

const mockVersions: DraftVersion[] = [
  {
    id: 'current',
    body: 'Version actuelle du brouillon',
    instructions: 'Sois plus formel',
    timestamp: new Date('2026-01-19T12:00:00Z'),
    pipelineDetails: {
      draft_v1: 'Version V1',
      critique: { is_valid: true, feedback: 'Bon' },
      was_corrected: false,
    },
  },
  {
    id: 'v-1',
    body: 'Version précédente',
    instructions: 'Raccourcir',
    timestamp: new Date('2026-01-19T11:00:00Z'),
    pipelineDetails: {
      draft_v1: 'Version V1 précédente',
      critique: { is_valid: false, feedback: 'Trop long' },
      was_corrected: true,
    },
  },
  {
    id: 'v-2',
    body: 'Première version',
    instructions: 'Version initiale',
    timestamp: new Date('2026-01-19T10:00:00Z'),
  },
];

describe('DraftVersionHistory', () => {
  const defaultProps = {
    versions: mockVersions,
    currentVersionId: 'current',
    isOpen: true,
    onClose: vi.fn(),
    onVersionSelect: vi.fn(),
    onCompare: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <DraftVersionHistory {...defaultProps} isOpen={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders panel when open (AC4)', () => {
    render(<DraftVersionHistory {...defaultProps} />);
    expect(screen.getByText('Historique des versions')).toBeInTheDocument();
  });

  it('displays all versions with their instructions (AC4)', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    expect(screen.getByText(/Sois plus formel/)).toBeInTheDocument();
    expect(screen.getByText(/Raccourcir/)).toBeInTheDocument();
    expect(screen.getByText(/Version initiale/)).toBeInTheDocument();
  });

  it('highlights current version with badge', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    expect(screen.getByText('Actuelle')).toBeInTheDocument();
  });

  it('displays pipeline status badge', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    // First version is valid (not corrected)
    expect(screen.getByText('Approuvé')).toBeInTheDocument();
    // Second version was corrected
    expect(screen.getByText('Corrigé')).toBeInTheDocument();
  });

  it('calls onVersionSelect when clicking Voir button', () => {
    const onVersionSelect = vi.fn();
    render(
      <DraftVersionHistory {...defaultProps} onVersionSelect={onVersionSelect} />
    );

    // Find and click a "Voir" button for a non-current version
    const viewButtons = screen.getAllByText('Voir');
    fireEvent.click(viewButtons[0]);

    expect(onVersionSelect).toHaveBeenCalledWith(mockVersions[1]);
  });

  it('disables Voir button for current version', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    // The current version should show "Affichée" and be disabled
    const displayedButton = screen.getByText('Affichée');
    expect(displayedButton).toBeDisabled();
  });

  it('calls onClose when clicking close button', async () => {
    const onClose = vi.fn();
    render(<DraftVersionHistory {...defaultProps} onClose={onClose} />);

    const closeButton = screen.getByLabelText('Fermer');
    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    }, { timeout: 500 });
  });

  it('shows Comparer button for versions with a next version (AC5)', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    // Should have compare buttons for first and second versions (not the last one)
    const compareButtons = screen.getAllByText('Comparer');
    expect(compareButtons.length).toBe(2);
  });

  it('calls onCompare when clicking Comparer button (AC5)', () => {
    const onCompare = vi.fn();
    render(<DraftVersionHistory {...defaultProps} onCompare={onCompare} />);

    const compareButtons = screen.getAllByText('Comparer');
    fireEvent.click(compareButtons[0]);

    // Should compare with the next version in the list
    expect(onCompare).toHaveBeenCalledWith(mockVersions[0], mockVersions[1]);
  });

  it('displays "Comparer la première et la dernière version" button when 2+ versions', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    expect(screen.getByText('Comparer la première et la dernière version')).toBeInTheDocument();
  });

  it('calls onCompare with first and last versions when clicking compare all button', () => {
    const onCompare = vi.fn();
    render(<DraftVersionHistory {...defaultProps} onCompare={onCompare} />);

    const compareAllButton = screen.getByText('Comparer la première et la dernière version');
    fireEvent.click(compareAllButton);

    expect(onCompare).toHaveBeenCalledWith(mockVersions[0], mockVersions[2]);
  });

  it('renders empty state when no versions', () => {
    render(
      <DraftVersionHistory
        {...defaultProps}
        versions={[]}
      />
    );

    expect(screen.getByText('Aucune version précédente')).toBeInTheDocument();
  });

  it('displays version numbers correctly', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    expect(screen.getByText('Version 3')).toBeInTheDocument(); // Most recent
    expect(screen.getByText('Version 2')).toBeInTheDocument();
    expect(screen.getByText('Version 1')).toBeInTheDocument(); // Oldest
  });

  it('displays formatted timestamps', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    // Should display date in fr-FR format
    const timestampElements = document.querySelectorAll('.version-timestamp');
    expect(timestampElements.length).toBe(3);
  });

  it('displays version preview text', () => {
    render(<DraftVersionHistory {...defaultProps} />);

    expect(screen.getByText(/Version actuelle du brouillon/)).toBeInTheDocument();
    expect(screen.getByText(/Version précédente/)).toBeInTheDocument();
    expect(screen.getByText(/Première version/)).toBeInTheDocument();
  });
});
