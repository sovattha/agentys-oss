/**
 * Audit 2026-05-18: cover the new first-open seed for the AI command
 * palette. The previous Ctrl+J popover was an empty box for first-time
 * users; loadSaved now returns four default chips on the very first call
 * per account, but only the very first call (so deletion sticks).
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { loadSaved, persistSaved } from '../aiCommandStorage';

const ACCT = 'acct-1';
const KEY = 'ai-cmd-saved:acct-1';
const SEEDED_KEY = 'ai-cmd-seeded:acct-1';

describe('aiCommandStorage — first-open seeding', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('seeds 4 defaults on the first load for an empty account', () => {
    const out = loadSaved(ACCT);
    expect(out).toHaveLength(4);
    expect(out.map(c => c.label).sort()).toEqual([
      "Corriger l'orthographe",
      'Plus formel',
      'Raccourcir',
      'Traduire en anglais',
    ]);
  });

  it('persists the seeded chips to localStorage', () => {
    loadSaved(ACCT);
    const stored = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    expect(stored).toHaveLength(4);
    expect(localStorage.getItem(SEEDED_KEY)).toBe('1');
  });

  it('does NOT re-seed after the user has deleted all chips', () => {
    loadSaved(ACCT); // seed
    persistSaved(ACCT, []); // user wipes the list
    const out = loadSaved(ACCT);
    expect(out).toEqual([]);
  });

  it('keeps existing saved chips intact on subsequent loads', () => {
    persistSaved(ACCT, [{ id: 1, label: 'Mine', instruction: 'do my thing' }]);
    const out = loadSaved(ACCT);
    expect(out).toHaveLength(1);
    expect(out[0].label).toBe('Mine');
  });

  it('scopes seed per account (different account gets its own seed)', () => {
    loadSaved('acct-A');
    loadSaved('acct-B');
    expect(JSON.parse(localStorage.getItem('ai-cmd-saved:acct-A') ?? '[]')).toHaveLength(4);
    expect(JSON.parse(localStorage.getItem('ai-cmd-saved:acct-B') ?? '[]')).toHaveLength(4);
  });

  it('handles null account id (logged-out / loopback path)', () => {
    const out = loadSaved(null);
    expect(out).toHaveLength(4);
    expect(JSON.parse(localStorage.getItem('ai-cmd-saved') ?? '[]')).toHaveLength(4);
  });
});
