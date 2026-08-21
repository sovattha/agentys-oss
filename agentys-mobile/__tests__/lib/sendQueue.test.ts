import * as SecureStore from 'expo-secure-store';

import {
  OUTBOX_QUEUE_MAX_AGE_DAYS,
  enqueue,
  getQueue,
  getQueueSize,
} from '../../src/lib/sendQueue';

const getItemAsync = SecureStore.getItemAsync as jest.Mock;
const setItemAsync = SecureStore.setItemAsync as jest.Mock;
const deleteItemAsync = SecureStore.deleteItemAsync as jest.Mock;

describe('sendQueue retention', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-05-17T00:00:00.000Z'));
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('enqueue persists a new message with a timestamp', async () => {
    getItemAsync.mockResolvedValueOnce(null);

    const queued = await enqueue({
      to: 'a@example.com',
      subject: 'Subject',
      body: 'Draft body',
    });

    expect(queued.createdAt).toBe('2026-05-17T00:00:00.000Z');
    expect(setItemAsync).toHaveBeenCalledWith(
      'outbox_v1',
      expect.stringContaining('Draft body'),
    );
  });

  it('getQueue prunes expired local email bodies', async () => {
    const fresh = {
      id: 'fresh',
      to: 'a@example.com',
      subject: 'Fresh',
      body: 'Fresh body',
      createdAt: '2026-05-16T00:00:00.000Z',
      attempts: 0,
    };
    const expired = {
      id: 'expired',
      to: 'b@example.com',
      subject: 'Expired',
      body: 'Expired private body',
      createdAt: new Date(
        Date.parse('2026-05-17T00:00:00.000Z')
          - (OUTBOX_QUEUE_MAX_AGE_DAYS + 1) * 24 * 60 * 60 * 1000,
      ).toISOString(),
      attempts: 2,
    };
    getItemAsync.mockResolvedValueOnce(JSON.stringify([expired, fresh]));

    const queue = await getQueue();

    expect(queue).toEqual([fresh]);
    expect(setItemAsync).toHaveBeenCalledWith('outbox_v1', JSON.stringify([fresh]));
    expect(JSON.stringify(setItemAsync.mock.calls[0][1])).not.toContain('Expired private body');
  });

  it('getQueueSize deletes the queue when every message expired', async () => {
    const expired = {
      id: 'expired',
      to: 'b@example.com',
      subject: 'Expired',
      body: 'Expired private body',
      createdAt: '2026-05-01T00:00:00.000Z',
      attempts: 2,
    };
    getItemAsync.mockResolvedValueOnce(JSON.stringify([expired]));

    await expect(getQueueSize()).resolves.toBe(0);

    expect(deleteItemAsync).toHaveBeenCalledWith('outbox_v1');
    expect(setItemAsync).not.toHaveBeenCalled();
  });
});
