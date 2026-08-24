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

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Sidebar } from '../components/Sidebar';
import type { ActivityState } from '../types/activity';

vi.mock('../components/TimezoneUtils', () => ({
  TimezonePicker: () => null,
  useSecondaryTimezone: () => [null, vi.fn()],
  useTz2Color: () => ['', vi.fn()],
}));

vi.mock('../components/UpdateBell', () => ({
  UpdateBell: () => null,
}));

const defaultProps = {
  activeTab: 'inbox' as const,
  onTabChange: vi.fn(),
  onCompose: vi.fn(),
  onOpenSettings: vi.fn(),
  onOpenSupport: vi.fn(),
  unreadCount: 0,
  draftCount: 0,
  appMode: 'mail' as const,
  onAppModeChange: vi.fn(),
};

const classifyingState: ActivityState = {
  activities: [
    {
      id: 'classify',
      type: 'classify',
      label: 'activity_classifying',
      startedAt: Date.now(),
    },
  ],
  isActive: true,
  primaryActivity: {
    id: 'classify',
    type: 'classify',
    label: 'activity_classifying',
    startedAt: Date.now(),
  },
  justFinished: false,
  error: null,
};

describe('Sidebar — activity indicator', () => {
  it("affiche un statut discret quand le triage IA est en cours", () => {
    render(<Sidebar {...defaultProps} activityState={classifyingState} />);

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Triage IA...');
    expect(screen.queryByRole('button', { name: /triage ia/i })).not.toBeInTheDocument();
  });
});

// Bouton hamburger retiré du composant Sidebar (feature mobile-toggle
// supprimée upstream). Le CSS .sidebar-hamburger existe encore dans
// Sidebar.css mais le composant ne le rend plus. Tests skipped en
// attendant une éventuelle réimplémentation du toggle mobile.
describe.skip('Sidebar — navigation mobile (feature retirée)', () => {
  it('affiche un bouton hamburger quand isMobile=true', () => {
    render(<Sidebar {...defaultProps} isMobile isOpen={false} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /ouvrir le menu/i })).toBeInTheDocument();
  });

  it("le bouton hamburger change d'aria-label quand le menu est ouvert", () => {
    render(<Sidebar {...defaultProps} isMobile isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /fermer le menu/i })).toBeInTheDocument();
  });

  it('appelle onClose quand le bouton hamburger est cliqué (menu ouvert)', () => {
    const onClose = vi.fn();
    render(<Sidebar {...defaultProps} isMobile isOpen={true} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /fermer le menu/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("n'affiche pas le bouton hamburger en mode desktop (isMobile=false)", () => {
    render(<Sidebar {...defaultProps} isMobile={false} />);
    expect(screen.queryByRole('button', { name: /ouvrir le menu|fermer le menu/i })).toBeNull();
  });
});
