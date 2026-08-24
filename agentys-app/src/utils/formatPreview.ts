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

/**
 * Builds the localized "Preview based on your choices" email shown in the
 * Writing Format settings (FormatSection) and the onboarding read-only style
 * pillar (PillarStyleReadOnly).
 *
 * Previously each component hardcoded a French `BODY_EXAMPLES` map plus an
 * English `Hi Jean-Pierre,` / `Best regards,` shell, so the preview body stayed
 * French regardless of the active UI language (visible bug: English UI, French
 * answer). Every visible string now resolves through the `agents` namespace so
 * the preview follows the selected language.
 *
 * `t` is the i18next `t` bound to the `agents` namespace (e.g. from
 * `useTranslation('agents')`). Typed structurally so dynamically-built keys
 * (format_preview_body_<length>_<complexity>) don't trip the TFunction key
 * union.
 */
type Translate = (key: string) => string;

const FALLBACK_BODY_KEY = 'format_preview_body_moyen_standard';

/**
 * @param longueur     'concis' | 'moyen' | 'detaille'
 * @param complexite   'accessible' | 'standard' | 'elabore'
 * @param closingText  user's preferred closing; falls back to the localized default
 * @param signatureText optional signature block appended after the closing
 */
export function buildFormatPreviewEmail(
  t: Translate,
  longueur: string,
  complexite: string,
  closingText?: string | null,
  signatureText?: string | null,
): string {
  const bodyKey = `format_preview_body_${longueur}_${complexite}`;
  let body = t(bodyKey);
  // Defensive: an unknown length/complexity combo (or a missing key) returns
  // the bare key / empty string from i18next — fall back to the neutral example.
  if (!body || body === bodyKey) {
    body = t(FALLBACK_BODY_KEY);
  }

  const greeting = t('format_preview_greeting');
  const closing = (closingText && closingText.trim())
    ? closingText.trim()
    : t('format_preview_closing_default');

  const lines = [greeting, '', body, '', closing];
  if (signatureText && signatureText.trim()) {
    lines.push('', signatureText.trim());
  }
  return lines.join('\n');
}
