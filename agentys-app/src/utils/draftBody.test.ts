import { describe, expect, it } from 'vitest';
import { cleanDraftBody } from './draftBody';

describe('cleanDraftBody', () => {
  it('strips a leading AI subject-echo preamble', () => {
    expect(cleanDraftBody('Objet: Re: votre facture\n\nBonjour,\nMerci.'))
      .toBe('Bonjour,\nMerci.');
  });

  it('strips several leading header + blank lines until real content', () => {
    expect(cleanDraftBody('Subject: X\nRe: Y\n\nHello there'))
      .toBe('Hello there');
  });

  it('PRESERVES a mid-body line starting with "Re:" (regression — was deleted)', () => {
    const body = `Bonjour,\n\nRe: ton point d'hier — je suis d'accord.\n\nCordialement`;
    expect(cleanDraftBody(body)).toBe(body);
    expect(cleanDraftBody(body)).toContain('Re: ton point');
  });

  it('PRESERVES a mid-body line starting with "Subject:" (regression — was deleted)', () => {
    const body = 'Voici ma proposition.\nSubject: Q3 budget review reste à valider.';
    expect(cleanDraftBody(body)).toContain('Subject: Q3 budget review');
  });

  it('returns the whole body untouched when the first line is real content', () => {
    const body = 'Merci pour votre message.\nÀ bientôt.';
    expect(cleanDraftBody(body)).toBe(body);
  });

  it('converts simple draft HTML to text while preserving paragraph breaks', () => {
    expect(cleanDraftBody('<p>Bonjour,</p><p>Merci.</p>')).toBe('Bonjour,\nMerci.');
  });

  it('handles empty / nullish input', () => {
    expect(cleanDraftBody('')).toBe('');
    expect(cleanDraftBody(null)).toBe('');
    expect(cleanDraftBody(undefined)).toBe('');
  });
});
