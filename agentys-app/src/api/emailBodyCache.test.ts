import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmailDetail } from '../types/email';
import {
  _decryptEmailDetailForTests,
  _encryptEmailDetailForTests,
  _resetEmailBodyCacheForTests,
  buildCachedDraftEmailContext,
  clearEmailBodyCache,
  readEmailBodyCache,
  writeEmailBodyCache,
} from './emailBodyCache';

function detail(overrides: Partial<EmailDetail> = {}): EmailDetail {
  return {
    id: 'email-1',
    sender: 'alex@example.com',
    sender_name: 'Alex',
    subject: 'Question',
    received_at: '2026-05-18T08:00:00Z',
    body: 'Bonjour, peux-tu confirmer ?',
    body_html: '<p>Bonjour, peux-tu confirmer ?</p>',
    body_text: 'Bonjour, peux-tu confirmer ?',
    is_read: false,
    has_attachments: false,
    to: ['nat@example.com'],
    cc: [],
    ...overrides,
  };
}

describe('emailBodyCache', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-18T08:00:00Z'));
    vi.stubGlobal('indexedDB', undefined);
    await _resetEmailBodyCacheForTests();
    localStorage.clear();
  });

  afterEach(async () => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    await _resetEmailBodyCacheForTests();
  });

  it('stores email bodies in memory fallback without localStorage', async () => {
    const setItem = vi.spyOn(localStorage, 'setItem');

    await writeEmailBodyCache('account-1', 'email-1', detail());

    expect(await readEmailBodyCache('account-1', 'email-1')).toMatchObject({
      id: 'email-1',
      body: 'Bonjour, peux-tu confirmer ?',
    });
    expect(setItem).not.toHaveBeenCalled();
  });

  it('encrypts persisted body payloads without leaking plaintext', async () => {
    if (!globalThis.crypto?.subtle) return;
    const key = await globalThis.crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt'],
    );

    const encrypted = await _encryptEmailDetailForTests(detail(), key);

    expect(encrypted.encryptedDetail).not.toContain('Bonjour');
    expect(encrypted.encryptedDetail).not.toContain('<p>');
    expect(encrypted.iv.length).toBeGreaterThan(0);
    await expect(_decryptEmailDetailForTests(encrypted, key)).resolves.toMatchObject({
      id: 'email-1',
      body: 'Bonjour, peux-tu confirmer ?',
    });
  });

  it('isolates cached bodies by account', async () => {
    await writeEmailBodyCache('account-1', 'email-1', detail({ body: 'A' }));
    await writeEmailBodyCache('account-2', 'email-1', detail({ body: 'B' }));

    expect((await readEmailBodyCache('account-1', 'email-1'))?.body).toBe('A');
    expect((await readEmailBodyCache('account-2', 'email-1'))?.body).toBe('B');
  });

  it('expires cached bodies after the short TTL', async () => {
    await writeEmailBodyCache('account-1', 'email-1', detail());

    vi.setSystemTime(new Date('2026-05-18T08:10:01Z'));

    expect(await readEmailBodyCache('account-1', 'email-1')).toBeNull();
  });

  it('keeps the newest bodies when the per-account limit is exceeded', async () => {
    const base = new Date('2026-05-18T08:00:00Z').getTime();

    for (let index = 0; index < 101; index += 1) {
      vi.setSystemTime(new Date(base + index));
      await writeEmailBodyCache(
        'account-1',
        `email-${index}`,
        detail({ id: `email-${index}`, body: `Body ${index}` }),
      );
    }

    expect(await readEmailBodyCache('account-1', 'email-0')).toBeNull();
    expect((await readEmailBodyCache('account-1', 'email-100'))?.body).toBe('Body 100');
  });

  it('clears only the requested account when scoped', async () => {
    await writeEmailBodyCache('account-1', 'email-1', detail({ body: 'A' }));
    await writeEmailBodyCache('account-2', 'email-1', detail({ body: 'B' }));

    await clearEmailBodyCache('account-1');

    expect(await readEmailBodyCache('account-1', 'email-1')).toBeNull();
    expect((await readEmailBodyCache('account-2', 'email-1'))?.body).toBe('B');
  });

  it('builds the draft context only when sender, subject, and body are present', () => {
    expect(buildCachedDraftEmailContext('email-1', detail())).toMatchObject({
      id: 'email-1',
      sender: 'alex@example.com',
      subject: 'Question',
      body: 'Bonjour, peux-tu confirmer ?',
      source: 'local_email_body_cache',
    });
    expect(buildCachedDraftEmailContext('email-1', detail({ body: '', body_html: null, body_text: '' }))).toBeNull();
    expect(buildCachedDraftEmailContext('email-1', detail({ sender: '' }))).toBeNull();
  });
});
