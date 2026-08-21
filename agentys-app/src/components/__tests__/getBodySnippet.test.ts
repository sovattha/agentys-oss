/**
 * Regression tests for collapsed-thread snippet generation.
 *
 * Audit 2026-05-18: a thread row with a short body ("ok") plus an Agentys
 * signature ("Alexandre Simon / Co-fondateur d'Agentys") leaked the full
 * signature into the snippet preview. The fix strips signature-class blocks
 * BEFORE the generic tag-strip pass.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { getBodySnippet } from '../EmailDetailModal';

beforeAll(() => {
  // jsdom is the default vitest environment, but assert it for clarity —
  // getBodySnippet uses document.createElement() for entity decoding.
  expect(typeof document).toBe('object');
});

describe('getBodySnippet — signature stripping', () => {
  it('drops the agentys-signature block on a short body', () => {
    const body =
      '<p>ok</p>' +
      '<div class="agentys-signature">' +
      '<p>Alexandre Simon</p><p>Co-fondateur d&#39;Agentys</p>' +
      '</div>';
    const snippet = getBodySnippet(body, 120);
    expect(snippet).toBe('ok');
    expect(snippet).not.toMatch(/Alexandre Simon/);
    expect(snippet).not.toMatch(/Co-fondateur/);
  });

  it('drops gmail_signature blocks', () => {
    const body =
      '<p>Sounds good!</p>' +
      '<div class="gmail_signature"><p>Jane</p><p>VP Sales</p></div>';
    const snippet = getBodySnippet(body, 120);
    expect(snippet).toBe('Sounds good!');
  });

  it('drops generic class="signature" blocks', () => {
    const body =
      '<p>Confirmed.</p>' +
      '<div class="email-signature"><p>Bob, CEO Acme</p></div>';
    const snippet = getBodySnippet(body, 120);
    expect(snippet).toBe('Confirmed.');
  });

  it('cuts at the standard "-- " plain-text signature delimiter', () => {
    const body = 'See you Monday.\n\n-- \nBob Smith\nCTO, Acme';
    const snippet = getBodySnippet(body, 120);
    expect(snippet).toBe('See you Monday.');
  });

  it('preserves normal-length prose unchanged', () => {
    const body =
      'Hello Alex,\n\nThanks for the update. ' +
      'I will review the contract this afternoon and circle back.';
    const snippet = getBodySnippet(body, 200);
    expect(snippet).toContain('Hello Alex');
    expect(snippet).toContain('review the contract');
  });

  it('still truncates at maxLength', () => {
    const body = 'x'.repeat(500);
    const snippet = getBodySnippet(body, 50);
    expect(snippet.length).toBeLessThanOrEqual(51); // 50 + ellipsis
    expect(snippet.endsWith('…')).toBe(true);
  });

  it('returns empty for empty body', () => {
    expect(getBodySnippet('', 120)).toBe('');
    expect(getBodySnippet(null as unknown as string, 120)).toBe('');
  });
});
