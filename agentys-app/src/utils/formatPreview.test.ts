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

import { describe, expect, it } from 'vitest';
import { buildFormatPreviewEmail } from './formatPreview';
import enAgents from '../i18n/locales/en/agents.json';
import frAgents from '../i18n/locales/fr/agents.json';
import esAgents from '../i18n/locales/es/agents.json';

// A minimal i18next-`t` stand-in: resolves against a locale dict and returns
// the bare key on a miss (matching i18next's default returnKey behavior).
const makeT = (dict: Record<string, string>) => (key: string) => dict[key] ?? key;

const EN = enAgents as Record<string, string>;
const FR = frAgents as Record<string, string>;
const ES = esAgents as Record<string, string>;

describe('buildFormatPreviewEmail', () => {
  it('assembles greeting + localized body + default closing (EN)', () => {
    const out = buildFormatPreviewEmail(makeT(EN), 'moyen', 'standard');
    expect(out.startsWith('Hi Jean-Pierre,')).toBe(true);
    expect(out).toContain(EN.format_preview_body_moyen_standard);
    expect(out).toContain('Q3 report');
    expect(out.trim().endsWith('Best regards,')).toBe(true);
    // Regression: the EN preview must not leak the old hardcoded French body.
    expect(out).not.toContain('réunion');
  });

  it('renders the FR body + closing when t resolves the FR namespace', () => {
    const out = buildFormatPreviewEmail(makeT(FR), 'moyen', 'standard');
    expect(out.startsWith('Bonjour Jean-Pierre,')).toBe(true);
    expect(out).toContain('Décalons la réunion à jeudi');
    expect(out.trim().endsWith('Cordialement,')).toBe(true);
  });

  it('renders the ES body + closing', () => {
    const out = buildFormatPreviewEmail(makeT(ES), 'concis', 'accessible');
    expect(out.startsWith('Hola Jean-Pierre,')).toBe(true);
    expect(out).toContain(ES.format_preview_body_concis_accessible);
    expect(out.trim().endsWith('Saludos,')).toBe(true);
  });

  it('prefers an explicit closing over the localized default', () => {
    const out = buildFormatPreviewEmail(makeT(EN), 'concis', 'standard', 'Cheers,');
    expect(out.trim().endsWith('Cheers,')).toBe(true);
    expect(out).not.toContain('Best regards,');
  });

  it('appends the signature block after the closing', () => {
    const out = buildFormatPreviewEmail(makeT(EN), 'concis', 'standard', null, 'Alexandre Simon\nCo-founder');
    const lines = out.split('\n');
    expect(lines[lines.length - 1]).toBe('Co-founder');
    expect(out).toContain('Best regards,\n\nAlexandre Simon');
  });

  it('every length × complexity combo resolves to a real body in all 3 locales', () => {
    const lengths = ['concis', 'moyen', 'detaille'];
    const complexities = ['accessible', 'standard', 'elabore'];
    for (const dict of [EN, FR, ES]) {
      for (const l of lengths) {
        for (const c of complexities) {
          const key = `format_preview_body_${l}_${c}`;
          expect(dict[key], `${key} missing from a locale`).toBeTruthy();
          const out = buildFormatPreviewEmail(makeT(dict), l, c);
          expect(out).toContain(dict[key]);
          expect(out).not.toContain(key); // raw key must never leak as text
        }
      }
    }
  });

  it('falls back to moyen_standard for an unknown length/complexity combo', () => {
    const out = buildFormatPreviewEmail(makeT(EN), 'bogus', 'nope');
    expect(out).toContain(EN.format_preview_body_moyen_standard);
  });
});
