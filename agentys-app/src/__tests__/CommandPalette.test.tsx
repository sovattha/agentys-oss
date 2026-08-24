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
import { describe, it, expect, vi } from 'vitest';
import { CommandPalette, type CommandAction } from '../components/CommandPalette';

function makeAction(over: Partial<CommandAction> & { id: string; label: string }): CommandAction {
  return { section: 'Tools', action: vi.fn(), ...over };
}

describe('CommandPalette', () => {
  it('renders actions grouped by section without any icon element', () => {
    const actions = [
      makeAction({ id: 'reply', label: 'Reply', section: 'Quick actions', shortcut: 'R' }),
      makeAction({ id: 'new', label: 'New message', section: 'Tools', shortcut: 'N' }),
    ];
    const { container } = render(<CommandPalette isOpen onClose={vi.fn()} actions={actions} />);

    expect(screen.getByText('Reply')).toBeInTheDocument();
    expect(screen.getByText('New message')).toBeInTheDocument();
    expect(screen.getByText('Quick actions')).toBeInTheDocument();
    // "no icons" — the icon span must be gone entirely.
    expect(container.querySelector('.command-palette-item-icon')).toBeNull();
  });

  it('renders a dimmed sublabel when provided (e.g. a contact email)', () => {
    const actions = [makeAction({ id: 'c1', label: 'John Doe', sublabel: 'john@acme.com', section: 'Contacts' })];
    const { container } = render(<CommandPalette isOpen onClose={vi.fn()} actions={actions} />);

    const sub = container.querySelector('.command-palette-item-sublabel');
    expect(sub).not.toBeNull();
    expect(sub).toHaveTextContent('john@acme.com');
  });

  it('matches on hidden keywords as well as the visible label', () => {
    const actions = [
      makeAction({ id: 'a', label: 'Reply', section: 'Quick actions' }),
      makeAction({ id: 'b', label: 'John Doe', section: 'Contacts', keywords: 'john@acme.com' }),
    ];
    render(<CommandPalette isOpen onClose={vi.fn()} actions={actions} />);

    // "acme" only appears in the keyword field of the contact.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'acme' } });
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.queryByText('Reply')).not.toBeInTheDocument();
  });

  it('notifies onQueryChange as the user types', () => {
    const onQueryChange = vi.fn();
    render(<CommandPalette isOpen onClose={vi.fn()} actions={[]} onQueryChange={onQueryChange} />);

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'jo' } });
    expect(onQueryChange).toHaveBeenLastCalledWith('jo');
  });

  it('suppresses the empty state while searching is true', () => {
    const actions = [makeAction({ id: 'a', label: 'Reply', section: 'Quick actions' })];
    const { container, rerender } = render(
      <CommandPalette isOpen onClose={vi.fn()} actions={actions} searching />,
    );

    // A query that matches nothing in the static actions.
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'zzzzz' } });
    expect(container.querySelector('.command-palette-empty')).toBeNull();

    // Once the async search settles, the empty state is allowed back.
    rerender(<CommandPalette isOpen onClose={vi.fn()} actions={actions} searching={false} />);
    expect(container.querySelector('.command-palette-empty')).not.toBeNull();
  });

  it('runs the selected action on Enter', async () => {
    const reply = vi.fn();
    const actions = [makeAction({ id: 'a', label: 'Reply', section: 'Quick actions', action: reply })];
    render(<CommandPalette isOpen onClose={vi.fn()} actions={actions} />);

    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' });
    await waitFor(() => expect(reply).toHaveBeenCalledTimes(1));
  });

  it('runs an action on click', async () => {
    const run = vi.fn();
    const actions = [makeAction({ id: 'a', label: 'Settings', section: 'Tools', action: run })];
    render(<CommandPalette isOpen onClose={vi.fn()} actions={actions} />);

    fireEvent.click(screen.getByText('Settings'));
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
  });
});
