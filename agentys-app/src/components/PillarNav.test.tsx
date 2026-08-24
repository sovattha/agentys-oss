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

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { PillarNav } from './PillarNav';

// i18n is initialized globally in src/__tests__/setup.ts (lng: 'fr'), so the
// sr-only status labels resolve to the real FR strings.

describe('PillarNav — completion status badge', () => {
  it('renders a "done" check + sr label for a configured pillar', () => {
    const { container } = render(
      <PillarNav activePillar="profil" onSelect={vi.fn()} detected={{ profil: true }} />
    );

    const done = container.querySelector('.pillar-nav-status.is-done');
    expect(done).toBeInTheDocument();
    expect(done?.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText('configuré')).toBeInTheDocument();
    // No to-do affordance when nothing is explicitly incomplete.
    expect(container.querySelector('.pillar-nav-status.is-todo')).not.toBeInTheDocument();
    expect(screen.queryByText('à configurer')).not.toBeInTheDocument();
  });

  it('renders a "to-do" dot + sr label for an un-configured pillar when markIncomplete is set', () => {
    const { container } = render(
      <PillarNav activePillar="profil" onSelect={vi.fn()} detected={{ autolabel: false }} markIncomplete />
    );

    const todo = container.querySelector('.pillar-nav-status.is-todo');
    expect(todo).toBeInTheDocument();
    expect(todo?.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText('à configurer')).toBeInTheDocument();
    expect(screen.queryByText('configuré')).not.toBeInTheDocument();
  });

  it('shows no status badge for an un-configured pillar without markIncomplete (onboarding default)', () => {
    const { container } = render(
      <PillarNav activePillar="profil" onSelect={vi.fn()} detected={{ autolabel: false }} />
    );

    expect(container.querySelector('.pillar-nav-status')).not.toBeInTheDocument();
    expect(screen.queryByText('configuré')).not.toBeInTheDocument();
    expect(screen.queryByText('à configurer')).not.toBeInTheDocument();
  });
});
