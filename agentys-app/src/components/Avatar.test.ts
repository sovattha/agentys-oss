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

import { describe, it, expect } from 'vitest';
import { getInitials, generateColorFromString } from './Avatar';

// Règle unique app-wide (2026-06-09) : « je veux toujours voir 2 lettres comme AS ».
// getInitials est LE canon — toutes les surfaces d'avatar (détail email, drafts,
// chips destinataires, dropdown suggestions, inbox confortable, onboarding…)
// doivent en dériver leurs initiales.

describe('getInitials', () => {
  it.each([
    ['nom complet', 'Alexandre Simon', 'alexandre.simon@hotmail.com', 'AS'],
    ['nom complet — premier + DERNIER mot', 'Jean Marc Dupont', 'jm@d.com', 'JD'],
    ['email seul — local-part à points', null, 'alexandre.simon@hotmail.com', 'AS'],
    ['email seul — local-part à underscore', null, 'karine_morel@gmail.com', 'KM'],
    ['email seul — local-part simple', null, 'info@agentys.io', 'IN'],
    ['label de chip = local-part capitalisée', 'Alexandre.simon', 'alexandre.simon@hotmail.com', 'AS'],
    ['email complet passé comme nom (cas « You »)', 'cours.universite@gmail.com', '', 'CU'],
    ['nom à un seul mot', 'Madonna', 'madonna.ciccone@x.com', 'MA'],
    ['nom avec tiret', 'Anne-Sophie', 'as@x.com', 'AS'],
    ['nom 1 caractère + email exploitable', 'A', 'alexandre.simon@hotmail.com', 'AS'],
    ['accents préservés', 'Éric Dupont', 'eric@x.com', 'ÉD'],
  ])('%s → %s', (_label, name, email, expected) => {
    expect(getInitials(name, email)).toBe(expected);
  });

  it('ne renvoie jamais une chaîne vide pour des entrées dégénérées', () => {
    expect(getInitials(null, '')).toBe('?');
    expect(getInitials('', '')).toBe('?');
    expect(getInitials('   ', '@domaine.com')).toBe('?');
  });
});

describe('generateColorFromString', () => {
  it('est déterministe et borné à la palette', () => {
    const a = generateColorFromString('alexandre.simon@hotmail.com');
    const b = generateColorFromString('alexandre.simon@hotmail.com');
    expect(a).toBe(b);
    expect(a).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it('deux emails différents peuvent diverger (sanity)', () => {
    const a = generateColorFromString('a@x.com');
    const c = generateColorFromString('completely.other@y.org');
    expect(typeof a).toBe('string');
    expect(typeof c).toBe('string');
  });
});
