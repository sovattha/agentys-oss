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
import { buildDictationInsert } from './DraftEditor';

/**
 * `buildDictationInsert` turns the Whisper hook's entity-escaped transcript
 * HTML into the literal text we insert at the caret, with smart leading-space
 * so back-to-back dictations flow ("que le texte se suivent"). The TipTap
 * caret/insertion plumbing around it is exercised in the browser; here we prove
 * the decode + spacing decision, which is where the bugs would hide.
 */
describe('buildDictationInsert', () => {
  it('strips the <p> wrapper the hook adds', () => {
    expect(buildDictationInsert('<p>Bonjour Marc</p>', '')).toBe('Bonjour Marc');
  });

  it('decodes the apostrophe entity (French speech is full of them)', () => {
    // escapeHtml turns ' into &#39; — without decoding the user would see
    // the literal "j&#39;ai" in their email.
    expect(buildDictationInsert('<p>j&#39;ai fini</p>', '')).toBe("j'ai fini");
    expect(buildDictationInsert('<p>l&#039;équipe</p>', '')).toBe("l'équipe");
  });

  it('decodes the other basic entities escapeHtml produces', () => {
    expect(buildDictationInsert('<p>Tom &amp; Jerry</p>', '')).toBe('Tom & Jerry');
    expect(buildDictationInsert('<p>say &quot;hi&quot;</p>', '')).toBe('say "hi"');
    expect(buildDictationInsert('<p>a &lt; b &gt; c</p>', '')).toBe('a < b > c');
  });

  it('returns empty string for blank / whitespace-only transcripts (caller no-ops)', () => {
    expect(buildDictationInsert('<p></p>', '')).toBe('');
    expect(buildDictationInsert('<p>   </p>', 'word')).toBe('');
    expect(buildDictationInsert('', '')).toBe('');
  });

  describe('leading-space (so chained dictations do not run together)', () => {
    it('adds no space at the start of the document', () => {
      expect(buildDictationInsert('<p>Hello</p>', '')).toBe('Hello');
    });

    it('adds a space when the caret is right after a word character', () => {
      // "Hello there." + "How are you" → "Hello there. How are you"
      expect(buildDictationInsert('<p>world</p>', 'o')).toBe(' world');
    });

    it('adds a space when the caret is right after sentence punctuation', () => {
      expect(buildDictationInsert('<p>How are you</p>', '.')).toBe(' How are you');
    });

    it('does NOT add a space when the caret already follows whitespace', () => {
      expect(buildDictationInsert('<p>world</p>', ' ')).toBe('world');
      expect(buildDictationInsert('<p>world</p>', '\n')).toBe('world');
    });

    it('does not double a space the transcript already carries', () => {
      // Transcript text is trimmed, so even a padded transcript joins cleanly.
      expect(buildDictationInsert('<p>  world  </p>', 'o')).toBe(' world');
    });
  });
});
