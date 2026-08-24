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
import { SignatureModal } from './SignatureModal';

// Mock the network layer so the modal loads instantly with a known account.
vi.mock('../api/accounts', () => ({
  fetchAccounts: vi.fn().mockResolvedValue({
    accounts: [{ id: 'acc1', email: 'me@example.com', provider: 'gmail', signature: 'Hi', signature_html: null }],
    current_account_id: 'acc1',
  }),
  updateAccountSignature: vi.fn().mockResolvedValue({}),
  syncSignature: vi.fn(),
  uploadSignatureImage: vi.fn(),
  listSignatures: vi.fn().mockResolvedValue({
    signatures: [{ id: 'sig_a', name: 'Signature 1', html: '<div>Hi</div>', text: 'Hi', is_default: true }],
    default_id: 'sig_a',
  }),
  createSignature: vi.fn(),
  updateSignatureEntry: vi.fn(),
  deleteSignatureEntry: vi.fn(),
  setDefaultSignature: vi.fn(),
}));
vi.mock('../hooks/useAccountSignature', () => ({
  setAccountSignatureCache: vi.fn(),
}));

const popoverOpen = () => document.querySelector('.sig-popover') !== null;

async function openTemplatesPopover() {
  render(<SignatureModal isOpen onClose={vi.fn()} />);
  // The modal now opens on the signature LIST — enter the editor first.
  const row = await screen.findByText('Signature 1');
  fireEvent.click(row);
  // Wait for the editor toolbar, then open the popover.
  const trigger = await screen.findByRole('button', { name: 'Modèles' });
  fireEvent.click(trigger);
  await waitFor(() => expect(popoverOpen()).toBe(true));
  return trigger;
}

describe('SignatureModal — templates dropdown is dismissable', () => {
  beforeEach(() => vi.clearAllMocks());

  it('Escape closes the popover (and keeps the modal open)', async () => {
    await openTemplatesPopover();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(popoverOpen()).toBe(false));
    // Modal itself stays open.
    expect(screen.getByRole('button', { name: 'Modèles' })).toBeInTheDocument();
  });

  it('click outside the toolbar (on the modal body) closes the popover', async () => {
    await openTemplatesPopover();
    const desc = document.querySelector('.sig-description') as HTMLElement;
    expect(desc).toBeTruthy();
    fireEvent.mouseDown(desc);
    await waitFor(() => expect(popoverOpen()).toBe(false));
  });

  it('re-clicking the trigger toggles the popover closed', async () => {
    const trigger = await openTemplatesPopover();
    fireEvent.click(trigger);
    await waitFor(() => expect(popoverOpen()).toBe(false));
  });
});
