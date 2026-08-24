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

export type Language = {
  value: string;
  flag: string;
  native: string;
  latin: string;
};

export const LANGUAGES: Language[] = [
  { value: 'Français', flag: '🇫🇷', native: 'Français', latin: 'French' },
  { value: 'English', flag: '🇬🇧', native: 'English', latin: 'English' },
  { value: 'Español', flag: '🇪🇸', native: 'Español', latin: 'Spanish' },
  { value: 'Italiano', flag: '🇮🇹', native: 'Italiano', latin: 'Italian' },
  { value: 'Português', flag: '🇵🇹', native: 'Português', latin: 'Portuguese' },
  { value: '日本語', flag: '🇯🇵', native: '日本語', latin: 'Japanese' },
  { value: '中文', flag: '🇨🇳', native: '中文', latin: 'Chinese' },
  { value: 'العربية', flag: '🇸🇦', native: 'العربية', latin: 'Arabic' },
];

export type Variant = { code: string; flag: string; country: string };
export type VariantGroup = { label: string; flag: string; variants: Variant[] };

export const VARIANT_GROUPS: VariantGroup[] = [
  {
    label: 'Français',
    flag: '🇫🇷',
    variants: [
      { code: 'fr-FR', flag: '🇫🇷', country: 'France' },
      { code: 'fr-CA', flag: '🇨🇦', country: 'Québec' },
      { code: 'fr-BE', flag: '🇧🇪', country: 'Belgique' },
      { code: 'fr-CH', flag: '🇨🇭', country: 'Suisse' },
    ],
  },
  {
    label: 'English',
    flag: '🇬🇧',
    variants: [
      { code: 'en-US', flag: '🇺🇸', country: 'États-Unis' },
      { code: 'en-GB', flag: '🇬🇧', country: 'Royaume-Uni' },
      { code: 'en-AU', flag: '🇦🇺', country: 'Australie' },
    ],
  },
  {
    label: 'Español',
    flag: '🇪🇸',
    variants: [
      { code: 'es-ES', flag: '🇪🇸', country: 'Espagne' },
      { code: 'es-MX', flag: '🇲🇽', country: 'Mexique' },
    ],
  },
  {
    label: 'Português',
    flag: '🇵🇹',
    variants: [{ code: 'pt-BR', flag: '🇧🇷', country: 'Brésil' }],
  },
];

export const LEGACY_NAME_TO_CODE: Record<string, string> = {
  'Québec': 'fr-CA',
  'France': 'fr-FR',
  'Belgique': 'fr-BE',
  'Suisse': 'fr-CH',
  'Australie': 'en-AU',
  'Espagne': 'es-ES',
  'Mexique': 'es-MX',
  'Brésil': 'pt-BR',
  'États-Unis': 'en-US',
  'Royaume-Uni': 'en-GB',
};

export function getLanguage(value: string): Language | null {
  return LANGUAGES.find(l => l.value === value) || null;
}

export function getVariant(code: string): { v: Variant; group: string } | null {
  const normalized = LEGACY_NAME_TO_CODE[code] || code;
  for (const g of VARIANT_GROUPS) {
    const v = g.variants.find(x => x.code === normalized);
    if (v) return { v, group: g.label };
  }
  return null;
}

export function formatLanguageLabel(value: string): string {
  if (!value) return value;
  const exact = getLanguage(value);
  if (exact) return exact.native;
  const lower = value.trim().toLowerCase();
  const ci = LANGUAGES.find(
    l => l.native.toLowerCase() === lower || l.latin.toLowerCase() === lower
  );
  if (ci) return ci.native;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function formatVariantLabel(value: string): string {
  if (!value) return value;
  const found = getVariant(value);
  if (found) return `${found.v.country} (${found.v.code})`;
  return value;
}
