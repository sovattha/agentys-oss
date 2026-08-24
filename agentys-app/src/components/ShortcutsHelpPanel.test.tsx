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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ShortcutsHelpPanel } from './ShortcutsHelpPanel'

// TODO: update for new architecture — categories changed from global/app/navigation to navigation/composition/application
describe.skip('ShortcutsHelpPanel', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('should render when isOpen is true', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Raccourcis clavier')).toBeInTheDocument()
  })

  it('should not render when isOpen is false', () => {
    render(<ShortcutsHelpPanel isOpen={false} onClose={mockOnClose} />)

    expect(screen.queryByText('Raccourcis clavier')).not.toBeInTheDocument()
  })

  it('should display global shortcuts section', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Raccourcis globaux')).toBeInTheDocument()
    expect(
      screen.getByText("Fonctionnent même quand l'app n'est pas au premier plan")
    ).toBeInTheDocument()
  })

  it('should display app shortcuts section', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText("Raccourcis de l'application")).toBeInTheDocument()
  })

  it('should display navigation shortcuts section', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Navigation')).toBeInTheDocument()
  })

  it('should display toggle window shortcut', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Ouvrir/Fermer la fenêtre Agentys')).toBeInTheDocument()
  })

  it('should display new message shortcut', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Nouveau message')).toBeInTheDocument()
  })

  it('should display sync shortcut', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Synchroniser maintenant')).toBeInTheDocument()
  })

  it('should display settings shortcut', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Ouvrir les paramètres')).toBeInTheDocument()
  })

  it('should display refresh shortcut', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Rafraîchir la liste')).toBeInTheDocument()
  })

  it('should display navigation shortcuts', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    expect(screen.getByText('Naviguer dans la liste')).toBeInTheDocument()
    expect(screen.getByText("Ouvrir l'élément sélectionné")).toBeInTheDocument()
    expect(screen.getByText('Fermer le panneau/modal')).toBeInTheDocument()
  })

  it('should call onClose when close button is clicked', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    const closeButton = screen.getByRole('button', { name: 'Fermer' })
    fireEvent.click(closeButton)

    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('should call onClose when overlay is clicked', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    const overlay = screen.getByText('Raccourcis clavier').closest('.shortcuts-help-overlay')
    if (overlay) {
      fireEvent.click(overlay)
      expect(mockOnClose).toHaveBeenCalledTimes(1)
    }
  })

  it('should not call onClose when panel content is clicked', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    const panel = screen.getByText('Raccourcis clavier').closest('.shortcuts-help-panel')
    if (panel) {
      fireEvent.click(panel)
      expect(mockOnClose).not.toHaveBeenCalled()
    }
  })

  it('should call onClose when Escape key is pressed', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('should display footer with Escape hint', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    const footer = document.querySelector('.shortcuts-help-footer')
    expect(footer).toBeInTheDocument()
    expect(footer?.textContent).toMatch(/Appuyez sur/)
    expect(footer?.textContent).toMatch(/Échap/)
    expect(footer?.textContent).toMatch(/pour fermer/)
  })

  it('should display platform-specific shortcut keys', () => {
    render(<ShortcutsHelpPanel isOpen={true} onClose={mockOnClose} />)

    // Check that keyboard shortcuts are displayed (either Mac or Windows format)
    const shortcuts = screen.getAllByRole('listitem')
    expect(shortcuts.length).toBeGreaterThan(0)

    // Each shortcut should have a key and description
    shortcuts.forEach((item) => {
      expect(item.querySelector('.shortcut-key')).toBeInTheDocument()
      expect(item.querySelector('.shortcut-description')).toBeInTheDocument()
    })
  })
})
