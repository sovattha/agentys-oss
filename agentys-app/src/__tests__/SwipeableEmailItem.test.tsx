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

import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SwipeableEmailItem } from '../components/SwipeableEmailItem'
import type { Email } from '../types/email'

// ── Mocks for the non-skipped PDF export tests ────────────────────────────────
vi.mock('../utils/exportEmailPdf', () => ({ exportEmailToPdf: vi.fn(() => Promise.resolve()) }))

// Pin to English so context-menu strings ("Export as PDF") match the
// assertions below. Without this the tests inherit the default French
// locale ("Exporter en PDF") and fail on text-content lookups.
import i18n from '../i18n';
beforeAll(async () => {
  await i18n.changeLanguage('en');
});
vi.mock('../config', () => ({ API_URL: 'http://localhost:5050' }))
vi.mock('../hooks/useShortcutsStore', () => ({ useShortcutsStore: () => ({ shortcuts: [] }) }))
vi.mock('../hooks/usePendingSends', () => ({
  usePendingSends: () => ({
    isPendingSend: () => false,
    getPendingSendRemaining: () => 0,
    cancelPendingSend: vi.fn(),
  }),
}))
vi.mock('../services/api', () => ({ blockSender: vi.fn(() => Promise.resolve()), apiClient: { request: vi.fn() } }))
vi.mock('../api/emails', () => ({ unsubscribeBySender: vi.fn() }))
vi.mock('../hooks/useSnooze', () => ({ writeSnoozeEntry: vi.fn() }))
vi.mock('../contexts/LabelsContext', () => ({
  useSharedLabelsData: () => ({ labels: [], favoriteLabels: [], projectLabels: [], loading: false, error: null, refreshLabels: vi.fn(), toggleFavorite: vi.fn(), reorderFavorites: vi.fn(), getLabelByName: vi.fn() }),
}))
vi.mock('../api/labels', () => ({
  learnFromCorrection: vi.fn(() => Promise.resolve({ final_labels: [], rules_count: 0 })),
}))

const mockEmail: Email = {
  id: 'test-123',
  sender: 'john@example.com',
  sender_name: 'John Doe',
  subject: 'Test Subject',
  received_at: '2026-01-05T10:00:00Z',
  has_attachments: false,
  conversation_id: null,
  is_read: false,
}

const mockReadEmail: Email = {
  ...mockEmail,
  id: 'test-read-123',
  is_read: true,
}

const defaultProps = {
  email: mockEmail,
  selected: false,
  onSelect: vi.fn(),
  onMarkReadToggle: vi.fn(),
  formatTime: (date: string) => date,
  getSenderDisplay: (email: Email) => email.sender_name || email.sender,
}

// TODO: update for new architecture — component now uses role="option" instead of listitem, new DOM structure
describe.skip('SwipeableEmailItem', () => {
  it('renders email information correctly', () => {
    render(<SwipeableEmailItem {...defaultProps} />)

    expect(screen.getByText('John Doe')).toBeInTheDocument()
    expect(screen.getByText('Test Subject')).toBeInTheDocument()
  })

  it('calls onSelect when clicked', () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...defaultProps} onSelect={onSelect} />)

    const content = screen.getByRole('button', { name: /john doe/i })
    fireEvent.click(content)

    expect(onSelect).toHaveBeenCalledWith(mockEmail)
  })

  it('applies selected class when selected', () => {
    render(<SwipeableEmailItem {...defaultProps} selected={true} />)

    const item = screen.getByRole('listitem')
    expect(item).toHaveClass('selected')
  })

  it('shows attachment icon when email has attachments', () => {
    const emailWithAttachment = { ...mockEmail, has_attachments: true }
    render(<SwipeableEmailItem {...defaultProps} email={emailWithAttachment} />)

    expect(screen.getByTitle('Pièce jointe')).toBeInTheDocument()
  })

  it('does not show attachment icon when email has no attachments', () => {
    render(<SwipeableEmailItem {...defaultProps} />)

    expect(screen.queryByTitle('Pièce jointe')).not.toBeInTheDocument()
  })

  it('handles keyboard navigation with Enter', () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...defaultProps} onSelect={onSelect} />)

    const content = screen.getByRole('button', { name: /john doe/i })
    fireEvent.keyDown(content, { key: 'Enter' })

    expect(onSelect).toHaveBeenCalledWith(mockEmail)
  })

  it('handles keyboard navigation with Space', () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...defaultProps} onSelect={onSelect} />)

    const content = screen.getByRole('button', { name: /john doe/i })
    fireEvent.keyDown(content, { key: ' ' })

    expect(onSelect).toHaveBeenCalledWith(mockEmail)
  })

  it('uses formatTime prop for time display', () => {
    const formatTime = vi.fn().mockReturnValue('Il y a 5 min')
    render(<SwipeableEmailItem {...defaultProps} formatTime={formatTime} />)

    expect(formatTime).toHaveBeenCalledWith(mockEmail.received_at)
    expect(screen.getByText('Il y a 5 min')).toBeInTheDocument()
  })

  it('uses getSenderDisplay prop for sender display', () => {
    const getSenderDisplay = vi.fn().mockReturnValue('Custom Sender')
    render(<SwipeableEmailItem {...defaultProps} getSenderDisplay={getSenderDisplay} />)

    expect(getSenderDisplay).toHaveBeenCalledWith(mockEmail)
    expect(screen.getByText('Custom Sender')).toBeInTheDocument()
  })

  describe('Context Menu', () => {
    beforeEach(() => {
      vi.clearAllMocks()
    })

    it('should open context menu on right click', async () => {
      render(<SwipeableEmailItem {...defaultProps} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      await waitFor(() => {
        expect(screen.getByRole('menu')).toBeInTheDocument()
      })
    })

    it('should show "Marquer comme lu" for unread email', async () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      await waitFor(() => {
        expect(screen.getByRole('menuitem')).toHaveTextContent('Marquer comme lu')
      })
    })

    it('should show "Marquer comme non lu" for read email', async () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      await waitFor(() => {
        expect(screen.getByRole('menuitem')).toHaveTextContent('Marquer comme non lu')
      })
    })

    it('should call onMarkReadToggle with true when clicking "Marquer comme lu"', async () => {
      const user = userEvent.setup()
      const onMarkReadToggle = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} onMarkReadToggle={onMarkReadToggle} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      const menuItem = await screen.findByRole('menuitem')
      await user.click(menuItem)

      expect(onMarkReadToggle).toHaveBeenCalledWith(mockEmail, true)
    })

    it('should call onMarkReadToggle with false when clicking "Marquer comme non lu"', async () => {
      const user = userEvent.setup()
      const onMarkReadToggle = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} onMarkReadToggle={onMarkReadToggle} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      const menuItem = await screen.findByRole('menuitem')
      await user.click(menuItem)

      expect(onMarkReadToggle).toHaveBeenCalledWith(mockReadEmail, false)
    })

    it('should close context menu after clicking menu item', async () => {
      const user = userEvent.setup()
      render(<SwipeableEmailItem {...defaultProps} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      const menuItem = await screen.findByRole('menuitem')
      await user.click(menuItem)

      await waitFor(() => {
        expect(screen.queryByRole('menu')).not.toBeInTheDocument()
      })
    })

    it('should close context menu when pressing Escape', async () => {
      const user = userEvent.setup()
      render(<SwipeableEmailItem {...defaultProps} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

      await screen.findByRole('menu')

      await user.keyboard('{Escape}')

      await waitFor(() => {
        expect(screen.queryByRole('menu')).not.toBeInTheDocument()
      })
    })

    it('should position context menu at click coordinates', async () => {
      render(<SwipeableEmailItem {...defaultProps} />)

      const item = screen.getByRole('listitem')
      fireEvent.contextMenu(item, { clientX: 200, clientY: 150 })

      const menu = await screen.findByRole('menu')
      expect(menu).toHaveStyle({ left: '200px', top: '150px' })
    })
  })

  describe('Unread State', () => {
    it('should show unread indicator for unread email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      expect(screen.getByLabelText('Non lu')).toBeInTheDocument()
    })

    it('should not show unread indicator for read email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} />)

      expect(screen.queryByLabelText('Non lu')).not.toBeInTheDocument()
    })

    it('should have unread class for unread email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      const item = screen.getByRole('listitem')
      expect(item).toHaveClass('unread')
    })

    it('should not have unread class for read email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} />)

      const item = screen.getByRole('listitem')
      expect(item).not.toHaveClass('unread')
    })
  })

  describe('Quick Action Button', () => {
    beforeEach(() => {
      vi.clearAllMocks()
    })

    it('should render quick action button', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      const button = screen.getByRole('button', { name: /marquer comme lu/i })
      expect(button).toBeInTheDocument()
    })

    it('should show "Marquer comme lu" label for unread email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      const button = screen.getByLabelText('Marquer comme lu')
      expect(button).toBeInTheDocument()
    })

    it('should show "Marquer comme non lu" label for read email', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} />)

      const button = screen.getByLabelText('Marquer comme non lu')
      expect(button).toBeInTheDocument()
    })

    it('should call onMarkReadToggle with true when clicking button for unread email', async () => {
      const user = userEvent.setup()
      const onMarkReadToggle = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} onMarkReadToggle={onMarkReadToggle} />)

      const button = screen.getByLabelText('Marquer comme lu')
      await user.click(button)

      expect(onMarkReadToggle).toHaveBeenCalledWith(mockEmail, true)
    })

    it('should call onMarkReadToggle with false when clicking button for read email', async () => {
      const user = userEvent.setup()
      const onMarkReadToggle = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockReadEmail} onMarkReadToggle={onMarkReadToggle} />)

      const button = screen.getByLabelText('Marquer comme non lu')
      await user.click(button)

      expect(onMarkReadToggle).toHaveBeenCalledWith(mockReadEmail, false)
    })

    it('should not trigger email selection when clicking quick action button', async () => {
      const user = userEvent.setup()
      const onSelect = vi.fn()
      const onMarkReadToggle = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} onSelect={onSelect} onMarkReadToggle={onMarkReadToggle} />)

      const button = screen.getByLabelText('Marquer comme lu')
      await user.click(button)

      expect(onMarkReadToggle).toHaveBeenCalled()
      expect(onSelect).not.toHaveBeenCalled()
    })

    it('should have correct class for styling', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} />)

      const button = screen.getByLabelText('Marquer comme lu')
      expect(button).toHaveClass('quick-action-btn')
    })
  })

  describe('Multi-select Mode', () => {
    beforeEach(() => {
      vi.clearAllMocks()
    })

    it('should not show checkbox when multiSelectMode is false', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={false} />)

      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    })

    it('should show checkbox when multiSelectMode is true', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} />)

      expect(screen.getByRole('checkbox')).toBeInTheDocument()
    })

    it('should have checkbox unchecked when isChecked is false', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={false} />)

      const checkbox = screen.getByRole('checkbox')
      expect(checkbox).not.toBeChecked()
    })

    it('should have checkbox checked when isChecked is true', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={true} />)

      const checkbox = screen.getByRole('checkbox')
      expect(checkbox).toBeChecked()
    })

    it('should call onCheckChange when checkbox is clicked', async () => {
      const user = userEvent.setup()
      const onCheckChange = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={false} onCheckChange={onCheckChange} />)

      const checkbox = screen.getByRole('checkbox')
      await user.click(checkbox)

      expect(onCheckChange).toHaveBeenCalledWith(mockEmail, true)
    })

    it('should call onCheckChange with false when unchecking', async () => {
      const user = userEvent.setup()
      const onCheckChange = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={true} onCheckChange={onCheckChange} />)

      const checkbox = screen.getByRole('checkbox')
      await user.click(checkbox)

      expect(onCheckChange).toHaveBeenCalledWith(mockEmail, false)
    })

    it('should not trigger email selection when clicking checkbox', async () => {
      const user = userEvent.setup()
      const onSelect = vi.fn()
      const onCheckChange = vi.fn()
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} onSelect={onSelect} onCheckChange={onCheckChange} />)

      const checkbox = screen.getByRole('checkbox')
      await user.click(checkbox)

      expect(onCheckChange).toHaveBeenCalled()
      expect(onSelect).not.toHaveBeenCalled()
    })

    it('should have checked class when isChecked is true', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={true} />)

      const item = screen.getByRole('listitem')
      expect(item).toHaveClass('checked')
    })

    it('should not have checked class when isChecked is false', () => {
      render(<SwipeableEmailItem {...defaultProps} email={mockEmail} multiSelectMode={true} isChecked={false} />)

      const item = screen.getByRole('listitem')
      expect(item).not.toHaveClass('checked')
    })
  })
})

// ── PDF export in context menu (non-skipped) ──────────────────────────────────
describe('SwipeableEmailItem — menu contextuel Export PDF', () => {
  const pdfProps = {
    email: mockEmail,
    selected: false,
    onSelect: vi.fn(),
    formatTime: (d: string) => d,
    getSenderDisplay: (e: Email) => e.sender_name || e.sender,
    onToast: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    (globalThis as unknown as { fetch: ReturnType<typeof vi.fn> }).fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ subject: 'Test Subject', body: 'Hello', sender: 'john@example.com', received_at: '2026-01-05T10:00:00Z' }) })
    );
  });

  it('affiche "Export as PDF" dans le menu contextuel', async () => {
    render(<SwipeableEmailItem {...pdfProps} />);
    const item = screen.getByRole('option');
    fireEvent.contextMenu(item, { clientX: 100, clientY: 100 });
    await waitFor(() => {
      expect(screen.getByRole('menu')).toBeInTheDocument();
    });
    expect(screen.getByText('Export as PDF')).toBeInTheDocument();
  });

  it('appelle exportEmailToPdf et ferme le menu au clic', async () => {
    const { exportEmailToPdf } = await import('../utils/exportEmailPdf');
    render(<SwipeableEmailItem {...pdfProps} />);
    const item = screen.getByRole('option');
    fireEvent.contextMenu(item, { clientX: 100, clientY: 100 });
    await waitFor(() => screen.getByRole('menu'));
    fireEvent.click(screen.getByText('Export as PDF'));
    await waitFor(() => {
      expect(exportEmailToPdf).toHaveBeenCalledOnce();
    });
    await waitFor(() => {
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });
});

describe('SwipeableEmailItem — changer de label n’ouvre jamais l’email', () => {
  const labeledEmail: Email = {
    ...mockEmail,
    id: 'labeled-1',
    labels: [{ name: 'Action', color: '#dc2626', confidence: 1 }],
  }
  const labelProps = {
    ...defaultProps,
    email: labeledEmail,
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('ouvre le sélecteur de label au clic gauche sur le badge, sans ouvrir l’email', async () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...labelProps} onSelect={onSelect} />)

    // Le badge est désormais un bouton accessible (clic = changer le label).
    const badge = screen.getByRole('button', { name: 'Action' })
    fireEvent.click(badge)

    // Le sélecteur (role=menu, portalé) s’ouvre…
    expect(await screen.findByRole('menu')).toBeInTheDocument()
    // …et SURTOUT l’email ne s’ouvre pas.
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('ouvre le sélecteur au clavier (Enter) sans ouvrir l’email', async () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...labelProps} onSelect={onSelect} />)

    const badge = screen.getByRole('button', { name: 'Action' })
    fireEvent.keyDown(badge, { key: 'Enter' })

    expect(await screen.findByRole('menu')).toBeInTheDocument()
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('ouvre encore le sélecteur au clic droit (comportement historique préservé)', async () => {
    const onSelect = vi.fn()
    render(<SwipeableEmailItem {...labelProps} onSelect={onSelect} />)

    const badge = screen.getByRole('button', { name: 'Action' })
    fireEvent.contextMenu(badge, { clientX: 50, clientY: 50 })

    expect(await screen.findByRole('menu')).toBeInTheDocument()
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('ouvre le sélecteur depuis le menu contextuel sans ouvrir l’email', async () => {
    const onSelect = vi.fn()
    const onLabelUpdate = vi.fn()
    render(
      <SwipeableEmailItem
        {...labelProps}
        onSelect={onSelect}
        onLabelUpdate={onLabelUpdate}
      />,
    )

    const item = screen.getByRole('option')
    fireEvent.contextMenu(item, { clientX: 100, clientY: 100 })

    const labelsItem = await screen.findByRole('menuitem', { name: /labels/i })
    fireEvent.click(labelsItem)

    expect(await screen.findByRole('menu', { name: /label/i })).toBeInTheDocument()
    expect(onSelect).not.toHaveBeenCalled()
    expect(onLabelUpdate).not.toHaveBeenCalled()
  })
})

describe('SwipeableEmailItem — sujet tronqué', () => {
  it('expose le sujet complet dans le title du sujet visible', () => {
    const longSubjectEmail: Email = {
      ...mockEmail,
      subject: 'Sujet très long qui doit rester inspectable même quand la colonne split-view le tronque visuellement',
    };

    render(<SwipeableEmailItem {...defaultProps} email={longSubjectEmail} />);

    expect(screen.getByTestId('email-subject')).toHaveAttribute('title', longSubjectEmail.subject);
  });
});

describe('SwipeableEmailItem — indicateur de triage', () => {
  it('garde la ligne visible et occupée pendant une action de triage', () => {
    const onSelect = vi.fn();

    render(
      <SwipeableEmailItem
        {...defaultProps}
        onSelect={onSelect}
        isTriagePending
      />
    );

    const item = screen.getByRole('option');
    expect(item).toHaveClass('triage-pending');
    expect(item).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByTestId('triage-pending-badge')).toHaveAccessibleName('Sorting in progress');

    fireEvent.click(screen.getByRole('button', { name: /John Doe/i }));

    expect(onSelect).not.toHaveBeenCalled();
  });
});
