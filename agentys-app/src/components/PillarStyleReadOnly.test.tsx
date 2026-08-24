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

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { PillarStyleReadOnly } from './PillarStyleReadOnly';
import type { ProfileTone } from '../types/onboarding';

const TONE: ProfileTone = {
  default_tone: 'casual',
  average_response_length: 'medium',
  closing_style: 'warm',
  uses_emojis: false,
  humor_level: 'none',
} as ProfileTone;

const SAVED_CONTACTS_RESPONSE = {
  contacts: [
    {
      email: 'karine.morel@gmail.com',
      formality_override: 'casual',
      preferred_greeting: 'salut',
      preferred_closing: 'À bientôt',
      langue_variante: 'Québec',
      langue: 'Français',
      nickname: 'kiki',
    },
  ],
};

describe('PillarStyleReadOnly — contact nickname persistence', () => {
  beforeEach(() => {
    // Mock fetch to return the saved WritingStyleProfile contact profiles.
    // The component's useEffect calls GET /api/writing-style/contacts on mount,
    // and that response is what should populate the nickname badge.
    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/writing-style/contacts') && (!opts || opts.method === undefined || opts.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(SAVED_CONTACTS_RESPONSE),
        } as Response);
      }
      if (url.includes('/api/writing-style/contact-style') && opts?.method === 'PUT') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ success: true, contact_email: 'karine.morel@gmail.com' }),
        } as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ error: 'not found' }),
      } as Response);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('displays the saved nickname badge from the backend even when onboarding contacts are empty', async () => {
    // Render with empty onboarding contacts — the nickname should come from
    // the GET /api/writing-style/contacts response, not from onboarding.
    render(
      <PillarStyleReadOnly
        tone={TONE}
        contactRules={[]}
        contacts={[]}
      />
    );

    // Wait for the useEffect fetch to complete and the nickname badge to appear.
    await waitFor(() => {
      expect(screen.getByText('kiki')).toBeInTheDocument();
    });

    // The email header should also be present once the merge completed.
    expect(screen.getByText('karine.morel@gmail.com')).toBeInTheDocument();
  });

  it('merges onboarding contacts with server-side profile and keeps the nickname', async () => {
    render(
      <PillarStyleReadOnly
        tone={TONE}
        contactRules={[]}
        contacts={[
          {
            email: 'karine.morel@gmail.com',
            name: 'Karine Morel',
            type: 'personnel',
          },
        ]}
      />
    );

    // Backend nickname ("kiki") must win over any display-name fallback.
    await waitFor(() => {
      expect(screen.getByText('kiki')).toBeInTheDocument();
    });
  });
});
