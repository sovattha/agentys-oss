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

// Hoisted so the vi.mock factories below (which are themselves hoisted) can
// reference this shared data/spy without a TDZ error.
const mocks = vi.hoisted(() => {
  const snippet = {
    id: 's1', name: 'Greeting', content: 'Hi there', subject: 'Hello',
    to: ['a@b.com'], is_private: false, created_at: '', updated_at: '', use_count: 0,
  };
  return {
    searchContacts: vi.fn(),
    labels: [{ name: 'Action', color: '#dc2626', description: '', is_default: true, is_favorite: true, created_at: '', rules: [] }],
    snippets: [snippet],
    snippet,
  };
});

vi.mock('../services/api', () => ({ apiClient: { searchContacts: mocks.searchContacts } }));
vi.mock('../contexts/LabelsContext', () => ({ useSharedLabelsData: () => ({ labels: mocks.labels }) }));
vi.mock('../hooks/useSnippets', () => ({ useSnippets: () => ({ snippets: mocks.snippets }) }));

import { CommandPaletteContainer } from '../components/CommandPaletteContainer';

const noop = () => {};

function renderContainer(over: Partial<Parameters<typeof CommandPaletteContainer>[0]> = {}) {
  const props = {
    isOpen: true,
    onClose: noop,
    baseActions: [],
    onFilterLabel: vi.fn(),
    onComposeTo: vi.fn(),
    onUseSnippet: vi.fn(),
    ...over,
  };
  render(<CommandPaletteContainer {...props} />);
  return props;
}

beforeEach(() => {
  mocks.searchContacts.mockReset();
  mocks.searchContacts.mockResolvedValue([{ name: 'John Doe', email: 'john@acme.com' }]);
});

describe('CommandPaletteContainer', () => {
  it('lists labels and snippets (with subject as sublabel) when opened', () => {
    renderContainer();
    expect(screen.getByText('Action')).toBeInTheDocument();
    expect(screen.getByText('Greeting')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('selecting a label filters the inbox to it', async () => {
    const onFilterLabel = vi.fn();
    renderContainer({ onFilterLabel });
    fireEvent.click(screen.getByText('Action'));
    await waitFor(() => expect(onFilterLabel).toHaveBeenCalledWith('Action'));
  });

  it('selecting a snippet hands the full snippet to onUseSnippet', async () => {
    const onUseSnippet = vi.fn();
    renderContainer({ onUseSnippet });
    fireEvent.click(screen.getByText('Greeting'));
    await waitFor(() => expect(onUseSnippet).toHaveBeenCalledWith(expect.objectContaining({ id: 's1', content: 'Hi there' })));
  });

  it('live-searches contacts as you type and composes to the chosen one', async () => {
    const onComposeTo = vi.fn();
    renderContainer({ onComposeTo });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'john' } });
    await waitFor(() => expect(mocks.searchContacts).toHaveBeenCalledWith('john', undefined, { limit: 6 }));

    const hit = await screen.findByText('John Doe');
    fireEvent.click(hit);
    await waitFor(() => expect(onComposeTo).toHaveBeenCalledWith('john@acme.com', 'John Doe'));
  });

  it('does not hit the contacts endpoint for queries below the minimum length', async () => {
    renderContainer();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'j' } });
    await new Promise(r => setTimeout(r, 300));
    expect(mocks.searchContacts).not.toHaveBeenCalled();
  });
});
