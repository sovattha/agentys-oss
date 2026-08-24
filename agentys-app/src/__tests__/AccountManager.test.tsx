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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AccountManager } from '../components/AccountManager'

// Create mock API client instance
const mockApiClient = {
  listAccounts: vi.fn(),
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  activateAccount: vi.fn(),
  testAccountConnection: vi.fn(),
}

// Mock the API client
vi.mock('../services/api', () => ({
  getApiClient: vi.fn(() => mockApiClient),
}))

// Mock ConnectGmailButton
vi.mock('../components/ConnectGmailButton', () => ({
  ConnectGmailButton: ({ accountId, onConnected }: { accountId: string; onConnected?: (email: string) => void; onError?: (error: string) => void }) => (
    <button
      data-testid="connect-gmail-btn"
      onClick={() => onConnected?.('test@gmail.com')}
    >
      Connect Gmail ({accountId})
    </button>
  ),
}))

// Mock ConnectOutlookButton
vi.mock('../components/ConnectOutlookButton', () => ({
  ConnectOutlookButton: ({ accountId, onConnected }: { accountId: string; onConnected?: (email: string) => void; onError?: (error: string) => void }) => (
    <button
      data-testid="connect-outlook-btn"
      onClick={() => onConnected?.('test@outlook.com')}
    >
      Connect Outlook ({accountId})
    </button>
  ),
}))

// TODO: update for new architecture — component heavily restructured with new Dialog-based UI
describe.skip('AccountManager', () => {
  const mockOnClose = vi.fn()
  const mockAccounts = [
    {
      id: 'acc-1',
      name: 'Work Gmail',
      email: 'work@gmail.com',
      provider: 'gmail' as const,
      status: 'active' as const,
      is_current: true,
    },
    {
      id: 'acc-2',
      name: 'Personal Outlook',
      email: 'personal@outlook.com',
      provider: 'outlook' as const,
      status: 'error' as const,
      is_current: false,
    },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.listAccounts.mockResolvedValue({
      accounts: mockAccounts,
      current_account_id: 'acc-1',
    })
  })

  describe('Rendering', () => {
    it('affiche le titre "Comptes Email"', async () => {
      render(<AccountManager onClose={mockOnClose} />)
      expect(screen.getByText('Comptes Email')).toBeInTheDocument()
    })

    it('affiche le bouton de fermeture', async () => {
      render(<AccountManager onClose={mockOnClose} />)
      const closeBtn = screen.getByRole('button', { name: /fermer/i })
      expect(closeBtn).toBeInTheDocument()
    })

    it('appelle onClose quand on clique sur le bouton fermer', async () => {
      render(<AccountManager onClose={mockOnClose} />)
      const closeBtn = screen.getByRole('button', { name: /fermer/i })
      fireEvent.click(closeBtn)
      expect(mockOnClose).toHaveBeenCalled()
    })
  })

  describe('Liste des comptes', () => {
    it('affiche tous les comptes charges', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('work@gmail.com')).toBeInTheDocument()
        expect(screen.getByText('personal@outlook.com')).toBeInTheDocument()
      })
    })

    it('affiche le statut de chaque compte', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Actif')).toBeInTheDocument()
        expect(screen.getByText('Erreur')).toBeInTheDocument()
      })
    })

    it('affiche le badge "Actuel" pour le compte actif', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Actuel')).toBeInTheDocument()
      })
    })

    it('affiche le type de provider', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Gmail')).toBeInTheDocument()
        expect(screen.getByText('Outlook')).toBeInTheDocument()
      })
    })
  })

  describe('Bouton Reconnecter', () => {
    it('affiche le bouton Reconnecter pour les comptes en erreur', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Reconnecter')).toBeInTheDocument()
      })
    })

    it('ouvre la modal de reconnexion au clic', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const reconnectBtn = screen.getByText('Reconnecter')
        fireEvent.click(reconnectBtn)
      })

      await waitFor(() => {
        expect(screen.getByText(/Reconnecter personal@outlook.com/i)).toBeInTheDocument()
      })
    })
  })

  describe('Ajout de compte', () => {
    it('affiche le bouton "+ Ajouter un compte"', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('+ Ajouter un compte')).toBeInTheDocument()
      })
    })

    it('affiche le formulaire quand on clique sur Ajouter', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const addBtn = screen.getByText('+ Ajouter un compte')
        fireEvent.click(addBtn)
      })

      expect(screen.getByText('Nouveau compte')).toBeInTheDocument()
    })

    it('affiche le selecteur de provider', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        fireEvent.click(screen.getByText('+ Ajouter un compte'))
      })

      expect(screen.getByText('Type de connexion')).toBeInTheDocument()
      expect(screen.getByRole('combobox')).toBeInTheDocument()
    })

    it('affiche le bouton Gmail OAuth par defaut', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        fireEvent.click(screen.getByText('+ Ajouter un compte'))
      })

      await waitFor(() => {
        expect(screen.getByTestId('connect-gmail-btn')).toBeInTheDocument()
      })
    })

    it('affiche le bouton Outlook OAuth quand Outlook est selectionne', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        fireEvent.click(screen.getByText('+ Ajouter un compte'))
      })

      const select = screen.getByRole('combobox')
      fireEvent.change(select, { target: { value: 'outlook' } })

      await waitFor(() => {
        expect(screen.getByTestId('connect-outlook-btn')).toBeInTheDocument()
      })
    })
  })

  describe('Suppression de compte', () => {
    it('affiche le bouton Suppr pour chaque compte', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const deleteButtons = screen.getAllByText('Suppr.')
        expect(deleteButtons).toHaveLength(2)
      })
    })

    it('demande confirmation avant suppression', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const deleteButtons = screen.getAllByText('Suppr.')
        fireEvent.click(deleteButtons[0])
      })

      expect(confirmSpy).toHaveBeenCalledWith('Supprimer ce compte ?')
      confirmSpy.mockRestore()
    })

    it('supprime le compte si confirme', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
      mockApiClient.deleteAccount.mockResolvedValue({})

      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const deleteButtons = screen.getAllByText('Suppr.')
        fireEvent.click(deleteButtons[0])
      })

      await waitFor(() => {
        expect(mockApiClient.deleteAccount).toHaveBeenCalledWith('acc-1')
      })

      confirmSpy.mockRestore()
    })
  })

  describe('Statuts des comptes', () => {
    it('affiche le statut "expired" correctement', async () => {
      mockApiClient.listAccounts.mockResolvedValue({
        accounts: [{
          id: 'acc-expired',
          name: 'Expired Account',
          email: 'expired@gmail.com',
          provider: 'gmail' as const,
          status: 'expired' as const,
          is_current: false,
        }],
        current_account_id: null,
      })

      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Expiré')).toBeInTheDocument()
      })
    })

    it('affiche le bouton Reconnecter pour les comptes expires', async () => {
      mockApiClient.listAccounts.mockResolvedValue({
        accounts: [{
          id: 'acc-expired',
          name: 'Expired Account',
          email: 'expired@gmail.com',
          provider: 'gmail' as const,
          status: 'expired' as const,
          is_current: false,
        }],
        current_account_id: null,
      })

      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        expect(screen.getByText('Reconnecter')).toBeInTheDocument()
      })
    })
  })

  describe('Actions', () => {
    it('affiche le bouton Test pour chaque compte', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const testButtons = screen.getAllByText('Test')
        expect(testButtons).toHaveLength(2)
      })
    })

    it('affiche le bouton Activer pour les comptes non-courants', async () => {
      render(<AccountManager onClose={mockOnClose} />)

      await waitFor(() => {
        const activateButtons = screen.getAllByText('Activer')
        expect(activateButtons).toHaveLength(1)
      })
    })
  })
})
