/**
 * WebSocket contract regressions for generateProcessDraftFast:
 * - reject on `draft_skipped` instead of polling 90s for nothing;
 * - keep the persisted PendingDraft ID from canonical `draft_ready` events.
 *
 * Bug: user dictates a reply on an auto-sender email; backend prefilter skips
 * (4ms); mobile polls /pending-drafts/by-email for 90s; eventually times out
 * with "Génération trop longue" (misleading toast).
 *
 * Fixes: propagate a matching `draft_skipped` as `DraftSkippedError`, and
 * resolve sendable drafts only from a backend-persisted ID.
 */

import * as SecureStore from 'expo-secure-store';
import {
  generateProcessDraftFast,
  DraftSkippedError,
} from '../../src/services/api';

// Mock the websocket module before importing api so the lazy `await import` resolves to our stub.
jest.mock('../../src/services/websocket', () => {
  const listeners: Record<string, Array<(data: any) => void>> = {};
  const fakeSocket = {
    on: jest.fn((event: string, fn: (data: any) => void) => {
      listeners[event] = listeners[event] || [];
      listeners[event].push(fn);
    }),
    off: jest.fn((event: string, fn: (data: any) => void) => {
      if (!listeners[event]) return;
      listeners[event] = listeners[event].filter((f) => f !== fn);
    }),
    __emit: (event: string, data: any) => {
      (listeners[event] || []).slice().forEach((fn) => fn(data));
    },
    __reset: () => {
      Object.keys(listeners).forEach((k) => delete listeners[k]);
    },
  };
  return {
    __esModule: true,
    getSocket: () => fakeSocket,
    __socket: fakeSocket,
  };
});

const mockFetch = global.fetch as jest.Mock;

function mockOnce(data: unknown, status = 200) {
  mockFetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(data),
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValue('test-token');
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ws = require('../../src/services/websocket');
  ws.__socket.__reset();
});

describe('generateProcessDraftFast — WebSocket paths', () => {
  it('uses the persisted draft ID from the canonical draft_ready event', async () => {
    mockOnce({ success: true, status: 'processing', task_id: 'task-1' }, 202);
    // Regression: the legacy draft_complete listener used this temporary
    // lookup result to manufacture a `ws-*` ID that /validate cannot resolve.
    mockOnce({ draft: null }, 200);

    const promise = generateProcessDraftFast('email-1', 'Reply yes', 'reply');
    await new Promise((r) => setTimeout(r, 0));

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const ws = require('../../src/services/websocket');
    ws.__socket.__emit('draft_complete', {
      email_id: 'email-1',
      draft: 'Persisted reply',
    });
    // Let the legacy lookup return `draft:null` before the canonical event.
    await new Promise((r) => setTimeout(r, 0));
    ws.__socket.__emit('daemon_event', {
      type: 'draft_ready',
      email_id: 'email-1',
      payload: {
        draft_id: 'pending-draft-uuid',
        pending_draft_id: 'pending-draft-uuid',
        draft_content: 'Persisted reply',
      },
    });

    await expect(promise).resolves.toEqual({
      draft_id: 'pending-draft-uuid',
      content: 'Persisted reply',
    });
  });

  it('rejects with DraftSkippedError when backend emits draft_skipped for the email', async () => {
    // POST /process returns 202 (queued)
    mockOnce({ success: true, status: 'processing', task_id: 'task-1' }, 202);
    // Polling response (might be hit briefly before WS skip arrives)
    mockOnce({ draft: null }, 200);

    const promise = generateProcessDraftFast('email-auto-1', 'Reply yes', 'reply');

    // Let the WS subscription register before emitting.
    await new Promise((r) => setTimeout(r, 0));

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const ws = require('../../src/services/websocket');
    ws.__socket.__emit('daemon_event', {
      type: 'draft_skipped',
      data: { email_id: 'email-auto-1', reason: 'no_reply_needed' },
    });

    await expect(promise).rejects.toBeInstanceOf(DraftSkippedError);
  });

  it('ignores draft_skipped events for OTHER email IDs', async () => {
    mockOnce({ success: true, status: 'processing', task_id: 'task-1' }, 202);
    mockOnce({ draft: { id: 'pending-draft-1', draft_body: 'hello there' } }, 200);

    const promise = generateProcessDraftFast('email-1', '', 'reply');

    await new Promise((r) => setTimeout(r, 0));

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const ws = require('../../src/services/websocket');
    // Skip event for a different email — must not reject our promise.
    ws.__socket.__emit('daemon_event', {
      type: 'draft_skipped',
      data: { email_id: 'email-OTHER', reason: 'noise' },
    });
    // Then deliver the real draft for our email via WS.
    ws.__socket.__emit('draft_complete', {
      email_id: 'email-1',
      draft: 'hello there',
    });

    const result = await promise;
    expect(result.content).toBe('hello there');
  });

  it('ignores daemon_event of other types (e.g. new_email, email_archived)', async () => {
    mockOnce({ success: true, status: 'processing', task_id: 'task-1' }, 202);
    mockOnce({ draft: { id: 'pending-draft-1', draft_body: 'real draft' } }, 200);

    const promise = generateProcessDraftFast('email-1', '', 'reply');

    await new Promise((r) => setTimeout(r, 0));

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const ws = require('../../src/services/websocket');
    ws.__socket.__emit('daemon_event', {
      type: 'new_email',
      data: { email_id: 'email-1' },
    });
    ws.__socket.__emit('draft_complete', { email_id: 'email-1', draft: 'real draft' });

    const result = await promise;
    expect(result.content).toBe('real draft');
  });

  it('exposes the skip reason on the thrown error', async () => {
    mockOnce({ success: true, status: 'processing', task_id: 'task-1' }, 202);
    mockOnce({ draft: null }, 200);

    const promise = generateProcessDraftFast('email-1', '', 'reply');
    await new Promise((r) => setTimeout(r, 0));

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const ws = require('../../src/services/websocket');
    ws.__socket.__emit('daemon_event', {
      type: 'draft_skipped',
      data: { email_id: 'email-1', reason: 'noise' },
    });

    try {
      await promise;
      throw new Error('should have rejected');
    } catch (err: any) {
      expect(err).toBeInstanceOf(DraftSkippedError);
      expect(err.reason).toBe('noise');
    }
  });
});
