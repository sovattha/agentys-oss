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
import { parseMarkdownToTraining, serializeTrainingToMarkdown } from './training';

// Audit 2026-05-14 F-02 — the contact_nicknames removal (commit ce02f2c8)
// deleted the "Surnoms" parser + serializer, so a Training-page Save silently
// stripped the "- **Surnoms**:" line out of an older memoire.md on every
// round-trip. The line is now round-tripped verbatim as an opaque passthrough
// (ProfilData.surnoms_passthrough) — not parsed, not used by drafts, just
// preserved so a no-op-looking Save never mutates memoire.md.
describe('training markdown — Surnoms passthrough (audit F-02)', () => {
  const mdWithSurnoms = [
    '## Profil',
    '',
    '- **Nom complet**: Alex Simon',
    '- **Entreprise**: Agentys',
    '- **Poste**: Dev',
    '- **Langue**: French',
    '- **Surnoms**: a@x.com:Kiki, b@y.com:Bob',
    '',
    '## Savoir',
    '',
    '_No knowledge entries recorded._',
    '## Regles',
    '',
    '- Professional but warm tone',
    '',
  ].join('\n');

  it('captures the Surnoms line into surnoms_passthrough', () => {
    const parsed = parseMarkdownToTraining(mdWithSurnoms);
    expect(parsed.profil.surnoms_passthrough).toBe('a@x.com:Kiki, b@y.com:Bob');
  });

  it('re-emits the Surnoms line on serialize (no silent strip)', () => {
    const out = serializeTrainingToMarkdown(parseMarkdownToTraining(mdWithSurnoms));
    expect(out).toContain('- **Surnoms**: a@x.com:Kiki, b@y.com:Bob');
  });

  it('survives a parse -> serialize -> parse round-trip', () => {
    const once = serializeTrainingToMarkdown(parseMarkdownToTraining(mdWithSurnoms));
    const twice = parseMarkdownToTraining(once);
    expect(twice.profil.surnoms_passthrough).toBe('a@x.com:Kiki, b@y.com:Bob');
  });

  it('emits nothing when the source memoire.md has no Surnoms line', () => {
    const mdNoSurnoms = mdWithSurnoms.replace(
      '- **Surnoms**: a@x.com:Kiki, b@y.com:Bob\n',
      '',
    );
    const parsed = parseMarkdownToTraining(mdNoSurnoms);
    expect(parsed.profil.surnoms_passthrough).toBeUndefined();
    expect(serializeTrainingToMarkdown(parsed)).not.toContain('**Surnoms**');
  });
});
