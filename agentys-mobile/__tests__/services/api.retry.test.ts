/**
 * F01 regression — non-idempotent verbs MUST NOT be retried automatically.
 *
 * Background: a previous version of api.ts marked any 5xx/timeout/network
 * error as retryable regardless of HTTP method. On Railway cold starts
 * (>30s), `sendNewEmail` would timeout client-side, retry, and the warm
 * server would accept BOTH requests → duplicate emails sent.
 *
 * This test pins the contract: GET retries on 5xx, POST/PATCH/PUT/DELETE
 * never retry by default. Idempotent retries can be opted in via `retries`
 * but the wrapper still gates 5xx detection on method.
 */

import * as SecureStore from 'expo-secure-store';
import {
  shouldRetryByDefault,
  getEmails,
  sendNewEmail,
  approveDraft,
  archiveEmail,
  createVoiceDraft,
  rejectDraft,
  updateUserPreferences,
} from '../../src/services/api';

const mockFetch = global.fetch as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValue('test-token');
});

describe('shouldRetryByDefault — pure helper', () => {
  it('GET + 500 → retry', () => {
    expect(shouldRetryByDefault('GET', 500)).toBe(true);
    expect(shouldRetryByDefault('GET', 502)).toBe(true);
    expect(shouldRetryByDefault('GET', 599)).toBe(true);
  });

  it('GET + 4xx → no retry', () => {
    expect(shouldRetryByDefault('GET', 400)).toBe(false);
    expect(shouldRetryByDefault('GET', 404)).toBe(false);
  });

  it('HEAD + 500 → retry', () => {
    expect(shouldRetryByDefault('HEAD', 500)).toBe(true);
  });

  it('POST + 500 → NEVER retry (F01 regression guard)', () => {
    expect(shouldRetryByDefault('POST', 500)).toBe(false);
    expect(shouldRetryByDefault('POST', 502)).toBe(false);
    expect(shouldRetryByDefault('POST', 503)).toBe(false);
    expect(shouldRetryByDefault('POST', 504)).toBe(false);
  });

  it('PATCH + 500 → NEVER retry', () => {
    expect(shouldRetryByDefault('PATCH', 500)).toBe(false);
  });

  it('PUT + 500 → NEVER retry', () => {
    expect(shouldRetryByDefault('PUT', 500)).toBe(false);
  });

  it('DELETE + 500 → NEVER retry', () => {
    expect(shouldRetryByDefault('DELETE', 500)).toBe(false);
  });

  it('undefined method (defaults to GET) + 500 → retry', () => {
    expect(shouldRetryByDefault(undefined, 500)).toBe(true);
  });

  it('lowercase method → still detected', () => {
    expect(shouldRetryByDefault('get', 500)).toBe(true);
    expect(shouldRetryByDefault('post', 500)).toBe(false);
  });
});

describe('apiFetch retry behavior — integration via exported endpoints', () => {
  function mockOnce(data: unknown, status = 200) {
    mockFetch.mockResolvedValueOnce({
      ok: status >= 200 && status < 300,
      status,
      json: jest.fn().mockResolvedValue(data),
    });
  }

  it('getEmails (GET) retries on 502 then succeeds on 2nd attempt', async () => {
    mockOnce({ error: 'Bad Gateway' }, 502);
    mockOnce({ emails: [] }, 200);
    const result = await getEmails();
    expect(result).toEqual({ emails: [] });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('sendNewEmail (POST) does NOT retry on 502 — fails immediately (F01)', async () => {
    mockOnce({ error: 'Bad Gateway' }, 502);
    await expect(
      sendNewEmail({ to: 'a@b.com', subject: 's', body: 'b' })
    ).rejects.toThrow('Bad Gateway');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('sendNewEmail (POST) does NOT retry on 503', async () => {
    mockOnce({ error: 'Service Unavailable' }, 503);
    await expect(
      sendNewEmail({ to: 'a@b.com', subject: 's', body: 'b' })
    ).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('approveDraft (POST) does NOT retry on 504 (cold start)', async () => {
    mockOnce({ error: 'Gateway Timeout' }, 504);
    await expect(approveDraft('d1')).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('archiveEmail (POST) does NOT retry on 502', async () => {
    mockOnce({ error: 'Bad Gateway' }, 502);
    await expect(archiveEmail('e1')).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('createVoiceDraft (POST) does NOT retry on 500', async () => {
    mockOnce({ error: 'Internal' }, 500);
    await expect(createVoiceDraft('e1', 'transcript')).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('rejectDraft (PATCH) does NOT retry on 502', async () => {
    mockOnce({ error: 'Bad Gateway' }, 502);
    await expect(rejectDraft('d1', 'reason')).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('updateUserPreferences (PATCH) does NOT retry on 503', async () => {
    mockOnce({ error: 'Down' }, 503);
    await expect(
      updateUserPreferences({ preferred_language: 'fr' })
    ).rejects.toThrow();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('sendNewEmail does NOT retry on AbortError/timeout (network drop)', async () => {
    // Simulate timeout: AbortController triggers AbortError
    const abortErr = Object.assign(new Error('aborted'), { name: 'AbortError' });
    mockFetch.mockRejectedValueOnce(abortErr);
    await expect(
      sendNewEmail({ to: 'a@b.com', subject: 's', body: 'b' })
    ).rejects.toThrow(/Timeout/);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('getEmails DOES retry on timeout (idempotent)', async () => {
    const abortErr = Object.assign(new Error('aborted'), { name: 'AbortError' });
    mockFetch.mockRejectedValueOnce(abortErr);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: jest.fn().mockResolvedValue({ emails: [] }),
    });
    const result = await getEmails();
    expect(result).toEqual({ emails: [] });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('GET on 4xx does NOT retry', async () => {
    mockOnce({ error: 'Bad Request' }, 400);
    await expect(getEmails()).rejects.toThrow('Bad Request');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('GET on 401 does NOT retry (confirme via probe puis clears token)', async () => {
    mockOnce({}, 401); // appel API — ne doit PAS être retenté
    mockOnce({}, 401); // probe /api/auth/me (#1121) — confirme l'invalidité
    await expect(getEmails()).rejects.toThrow('Unauthorized');
    // 2 fetch = 1 appel API + 1 probe. Aucun retry du GET lui-même.
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(SecureStore.deleteItemAsync).toHaveBeenCalled();
  });
});
