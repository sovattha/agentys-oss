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
import {
  AR_TOKEN_ATTR,
  isBlankAutoReplyMessage,
  buildAutoReplySuggestionHtml,
  suggestionFingerprint,
  matchesAnySuggestionFingerprint,
} from './autoReplySuggestion';

describe('isBlankAutoReplyMessage', () => {
  it.each([
    ['empty string', ''],
    ['whitespace only', '   '],
    ['bare <br>', '<br>'],
    ['empty div with break', '<div><br></div>'],
    ['empty paragraph', '<p></p>'],
    ['nbsp only', '&nbsp;'],
    ['div wrapping nbsp', '<div>&nbsp;</div>'],
    ['nested empty blocks', '<div></div><div><br></div>'],
  ])('treats %s as blank', (_label, html) => {
    expect(isBlankAutoReplyMessage(html)).toBe(true);
  });

  it.each([
    ['plain text', '<div>Bonjour</div>'],
    ['text after a break', '<br>Hello'],
    ['text plus nbsp', '<div>&nbsp;Hi</div>'],
  ])('treats %s as non-blank', (_label, html) => {
    expect(isBlankAutoReplyMessage(html)).toBe(false);
  });

  it('treats a message that is ONLY a dynamic-field chip as non-blank', () => {
    // A chip carries no readable text on its own but is real, user-meaningful
    // content — pre-filling over it would silently wipe an inserted field.
    const chipOnly = `<span ${AR_TOKEN_ATTR}="absence_period" contenteditable="false"></span>`;
    expect(isBlankAutoReplyMessage(chipOnly)).toBe(false);
  });
});

describe('buildAutoReplySuggestionHtml', () => {
  it('requests the suggestion key with the chip spliced in and escaping off', () => {
    const t = vi.fn((_key: string, opts: Record<string, unknown>) =>
      String(opts.defaultValue).replace('{{period}}', String(opts.period)),
    );
    const chip = `<span ${AR_TOKEN_ATTR}="absence_period" contenteditable="false">vos dates d'absence</span>&nbsp;`;

    const html = buildAutoReplySuggestionHtml(t, chip);

    // Correct key + interpolation contract.
    expect(t).toHaveBeenCalledWith(
      'auto_reply_message_suggestion',
      expect.objectContaining({
        period: chip,
        interpolation: { escapeValue: false },
      }),
    );
    // The marker is gone and the chip survives verbatim (not HTML-escaped).
    expect(html).not.toContain('{{period}}');
    expect(html).toContain(chip);
    expect(html).not.toContain('&lt;span');
  });
});

// ---------------------------------------------------------------------------
// Pristine-suggestion fingerprinting (bug Karine 2026-06-09): the starter is
// auto-persisted on first open, so it froze in that day's language — and, for
// messages saved before 4be7990e, with a legacy `&nbsp;` after the chip. The
// fingerprint decides whether a SAVED message may be relocalized.
// ---------------------------------------------------------------------------

const FR_TEMPLATE = (chip: string) =>
  `Bonjour,<br><br>Merci pour votre message. Je suis actuellement absent(e) ${chip} et vous répondrai dès mon retour.<br><br>Cordialement,`;
const EN_TEMPLATE = (chip: string) =>
  `Hello,<br><br>Thank you for your message. I am currently away ${chip} and will reply when I return.<br><br>Best regards,`;

const chipHtml = (text: string) =>
  `<span class="ar-token" ${AR_TOKEN_ATTR}="absence_period" contenteditable="false">${text}</span>`;

describe('suggestionFingerprint', () => {
  it('neutralizes the chip text — placeholder label vs live dates fingerprint equal', () => {
    const withLabel = FR_TEMPLATE(chipHtml('vos dates d’absence'));
    const withDates = FR_TEMPLATE(chipHtml('du 25 mars au 29 mars'));
    expect(suggestionFingerprint(withLabel)).toBe(suggestionFingerprint(withDates));
  });

  it('collapses the legacy trailing &nbsp; after the chip (pre-4be7990e saves)', () => {
    const legacy = FR_TEMPLATE(`${chipHtml('vos dates d’absence')}&nbsp;`);
    const clean = FR_TEMPLATE(chipHtml('vos dates d’absence'));
    expect(suggestionFingerprint(legacy)).toBe(suggestionFingerprint(clean));
  });

  it('ignores markup churn — contenteditable div-shape equals the br-shape', () => {
    const divShape =
      '<div>Bonjour,</div><div><br></div><div>Merci pour votre message. Je suis actuellement absent(e) ' +
      chipHtml('vos dates d’absence') +
      ' et vous répondrai dès mon retour.</div><div><br></div><div>Cordialement,</div>';
    expect(suggestionFingerprint(divShape)).toBe(
      suggestionFingerprint(FR_TEMPLATE(chipHtml('vos dates d’absence'))),
    );
  });

  it('changes when the body text was edited by the user', () => {
    const pristine = FR_TEMPLATE(chipHtml('vos dates d’absence'));
    const edited = pristine.replace('dès mon retour', 'dès que possible');
    expect(suggestionFingerprint(edited)).not.toBe(suggestionFingerprint(pristine));
  });

  it('changes when the chip was deleted — chip removal is a user edit', () => {
    const pristine = FR_TEMPLATE(chipHtml('vos dates d’absence'));
    const chipDeleted = FR_TEMPLATE('').replace('  ', ' ');
    expect(suggestionFingerprint(chipDeleted)).not.toBe(suggestionFingerprint(pristine));
  });
});

describe('matchesAnySuggestionFingerprint', () => {
  const candidates = [
    FR_TEMPLATE(chipHtml('vos dates d’absence')),
    EN_TEMPLATE(chipHtml('your absence dates')),
  ];

  it('matches a stale FR save (legacy nbsp + dates in chip) against the FR candidate', () => {
    const karineSave = FR_TEMPLATE(`${chipHtml('vos dates d’absence')}&nbsp;`);
    expect(matchesAnySuggestionFingerprint(karineSave, candidates)).toBe(true);
  });

  it('rejects an edited message', () => {
    const edited = FR_TEMPLATE(chipHtml('vos dates d’absence')).replace('Bonjour', 'Allo');
    expect(matchesAnySuggestionFingerprint(edited, candidates)).toBe(false);
  });

  it('rejects blank input', () => {
    expect(matchesAnySuggestionFingerprint('', candidates)).toBe(false);
    expect(matchesAnySuggestionFingerprint('<div><br></div>', candidates)).toBe(false);
  });
});
