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
 * usePendingSends — rehydration regression test (audit Send-HIGH-1, 2026-04-25).
 *
 * Bug: closing the window during the 15s undo-send timer used to lose the
 * payload silently because the timer lived in an in-memory Map. Fix:
 * persist to localStorage on register, walk it on module load, fire any
 * snapshot whose scheduled time has already passed.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const PERSIST_KEY = 'agentys:pending-sends-v1';

// Mock the apiClient so we can assert send-on-rehydrate without hitting network.
const sendNewEmail = vi.fn().mockResolvedValue({ success: true });
const updateCachedEmailDetail = vi.fn();
vi.mock('../services/api', () => ({
  apiClient: {
    sendNewEmail: (...args: unknown[]) => sendNewEmail(...args),
  },
}));
vi.mock('../api/emails', () => ({
  updateCachedEmailDetail: (...args: unknown[]) => updateCachedEmailDetail(...args),
}));
const saveComposeDraft = vi.fn();
vi.mock('../services/draftStorage', () => ({
  saveComposeDraft: (...args: unknown[]) => saveComposeDraft(...args),
}));

describe('usePendingSends — localStorage rehydration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sendNewEmail.mockClear();
    sendNewEmail.mockResolvedValue({ success: true });
    updateCachedEmailDetail.mockClear();
    saveComposeDraft.mockClear();
    window.localStorage.clear();
    vi.resetModules(); // clear module cache so hydrateFromStorage runs fresh
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('rehydrates an expired snapshot and fires send immediately', async () => {
    const now = Date.now();
    // A send scheduled 5 seconds in the past — should fire on hydrate.
    const expiredSnapshot = [{
      emailId: 'email-123',
      payload: {
        to: 'recipient@test.com',
        subject: 'Hello',
        body: 'Body',
      },
      scheduledAt: now - 5000,
      createdAt: now - 20000,
    }];
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(expiredSnapshot));

    // Importing the module triggers hydrateFromStorage via setTimeout(0).
    await import('./usePendingSends');
    await vi.advanceTimersByTimeAsync(10);

    expect(sendNewEmail).toHaveBeenCalledTimes(1);
    expect(sendNewEmail).toHaveBeenCalledWith(
      'recipient@test.com', 'Hello', 'Body',
      undefined, undefined, undefined, false, undefined, undefined,
      undefined, // accountId — not set in this snapshot
      'email-123',
    );
  });

  it('rehydrates a future snapshot and reschedules a fresh timer', async () => {
    const now = Date.now();
    const futureSnapshot = [{
      emailId: 'email-456',
      payload: { to: 'r@test.com', subject: 's', body: 'b' },
      scheduledAt: now + 5000,
      createdAt: now,
    }];
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(futureSnapshot));

    const mod = await import('./usePendingSends');
    await vi.advanceTimersByTimeAsync(10);

    expect(mod.isPendingSend('email-456')).toBe(true);
    expect(sendNewEmail).not.toHaveBeenCalled();

    // Advance time past the scheduled fire — send should now fire.
    await vi.advanceTimersByTimeAsync(6000);
    expect(sendNewEmail).toHaveBeenCalledTimes(1);
  });

  it('drops snapshots older than the 5min TTL', async () => {
    const now = Date.now();
    const ancientSnapshot = [{
      emailId: 'email-old',
      payload: { to: 'r@test.com', subject: 's', body: 'b' },
      scheduledAt: now - 60_000,
      createdAt: now - 6 * 60 * 1000, // 6 minutes ago, > 5min TTL
    }];
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(ancientSnapshot));

    const mod = await import('./usePendingSends');
    await vi.advanceTimersByTimeAsync(10);

    expect(sendNewEmail).not.toHaveBeenCalled();
    expect(mod.isPendingSend('email-old')).toBe(false);
  });

  it('skips invalid snapshots without crashing', async () => {
    // Garbage data — must not throw, must not fire.
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify([
      { emailId: 'no-payload' },
      'not-an-object',
      { emailId: 'malformed', payload: null, scheduledAt: 'not-a-number' },
    ]));

    await expect(import('./usePendingSends')).resolves.toBeDefined();
    await vi.advanceTimersByTimeAsync(10);
    expect(sendNewEmail).not.toHaveBeenCalled();
  });

  it('caches the sent body locally after the provider send succeeds', async () => {
    const mod = await import('./usePendingSends');

    mod.registerPendingSend('sent:compose-123', {
      to: 'agentys.demo@gmail.com',
      subject: 'Test Agentys',
      body: '<p>Bonjour depuis Agentys</p>',
    }, 0);

    await vi.advanceTimersByTimeAsync(10);

    expect(sendNewEmail).toHaveBeenCalledWith(
      'agentys.demo@gmail.com',
      'Test Agentys',
      '<p>Bonjour depuis Agentys</p>',
      undefined,
      undefined,
      undefined,
      false,
      undefined,
      undefined,
      undefined,
      'compose-123',
    );
    expect(updateCachedEmailDetail).toHaveBeenCalledWith(
      'sent:compose-123',
      expect.objectContaining({
        id: 'sent:compose-123',
        subject: 'Test Agentys',
        body: '<p>Bonjour depuis Agentys</p>',
        body_html: '<p>Bonjour depuis Agentys</p>',
        body_text: 'Bonjour depuis Agentys',
        to: ['agentys.demo@gmail.com'],
      }),
    );
  });

  // ── Audit 2026-06-02 K: in-flight guard must not permanently drop a send ──

  it('re-fires a guard-kept snapshot after the in-flight window when it never completed', async () => {
    const now = Date.now();
    // A due snapshot a previous boot already "fired" 10s ago (within the 90s
    // in-flight guard) whose POST never completed — still persisted.
    const stuck = [{
      emailId: 'email-stuck',
      payload: { to: 'r@test.com', subject: 's', body: 'b' },
      scheduledAt: now - 20_000,
      createdAt: now - 30_000,
      firedAt: now - 10_000,
    }];
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(stuck));

    await import('./usePendingSends');
    await vi.advanceTimersByTimeAsync(10);
    // Still inside the guard window → NOT re-fired immediately (avoids the
    // double-send the guard protects against).
    expect(sendNewEmail).not.toHaveBeenCalled();

    // Advance past the guard window. The snapshot is still persisted (the first
    // attempt never completed), so the in-session re-check fires it for delivery.
    await vi.advanceTimersByTimeAsync(82_000);
    expect(sendNewEmail).toHaveBeenCalledTimes(1);
  });

  it('does NOT re-fire a guard-kept snapshot whose first attempt completed', async () => {
    const now = Date.now();
    const stuck = [{
      emailId: 'email-done',
      payload: { to: 'r@test.com', subject: 's', body: 'b' },
      scheduledAt: now - 20_000,
      createdAt: now - 30_000,
      firedAt: now - 10_000,
    }];
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify(stuck));

    await import('./usePendingSends');
    await vi.advanceTimersByTimeAsync(10);
    expect(sendNewEmail).not.toHaveBeenCalled();

    // Simulate the in-flight first attempt completing: its finally ran
    // persistRemove, emptying the store before the guard window closes.
    window.localStorage.setItem(PERSIST_KEY, JSON.stringify([]));

    await vi.advanceTimersByTimeAsync(82_000);
    // Re-check found nothing persisted → no duplicate send.
    expect(sendNewEmail).not.toHaveBeenCalled();
  });

  // ── Audit e2e 2026-06-10 U-02: terminal failure must not destroy content ──

  it('restores the payload as a compose draft when the send fails terminally', async () => {
    sendNewEmail.mockRejectedValueOnce(Object.assign(new Error('Internal Server Error'), { status: 500 }));
    const sendFailedEvents: CustomEvent[] = [];
    const onFailed = (evt: Event) => sendFailedEvents.push(evt as CustomEvent);
    window.addEventListener('agentys:send-failed', onFailed);

    const mod = await import('./usePendingSends');
    mod.registerPendingSend('sent:compose-fail1', {
      to: 'client@test.com',
      subject: 'Réponse importante',
      body: '<p>longue réponse au client</p>',
      cc: 'cc@test.com',
    }, 0);
    await vi.advanceTimersByTimeAsync(10);

    expect(saveComposeDraft).toHaveBeenCalledTimes(1);
    expect(saveComposeDraft).toHaveBeenCalledWith({
      id: 'restored-sent:compose-fail1',
      to: 'client@test.com',
      cc: 'cc@test.com',
      bcc: '',
      subject: 'Réponse importante',
      body: '<p>longue réponse au client</p>',
    });
    expect(sendFailedEvents).toHaveLength(1);
    expect(sendFailedEvents[0].detail.draftRestored).toBe(true);
    window.removeEventListener('agentys:send-failed', onFailed);
  });

  it('does NOT restore a draft on 429 (the live snapshot auto-refires)', async () => {
    sendNewEmail.mockRejectedValueOnce(Object.assign(new Error('Too Many Requests'), { status: 429, retryAfter: 5 }));
    const mod = await import('./usePendingSends');
    mod.registerPendingSend('sent:compose-rl', { to: 'r@test.com', subject: 's', body: 'b' }, 0);
    await vi.advanceTimersByTimeAsync(10);

    expect(saveComposeDraft).not.toHaveBeenCalled();
    // The 429 snapshot must stay persisted for the retry window.
    const persisted = JSON.parse(window.localStorage.getItem(PERSIST_KEY) || '[]');
    expect(persisted.some((s: { emailId: string }) => s.emailId === 'sent:compose-rl')).toBe(true);
  });

  it('does NOT restore a draft on a successful send', async () => {
    const mod = await import('./usePendingSends');
    mod.registerPendingSend('sent:compose-ok', { to: 'r@test.com', subject: 's', body: 'b' }, 0);
    await vi.advanceTimersByTimeAsync(10);

    expect(sendNewEmail).toHaveBeenCalledTimes(1);
    expect(saveComposeDraft).not.toHaveBeenCalled();
  });

  // The persist-on-register / remove-on-cancel paths are exercised end-to-end
  // by the existing usePendingSends e2e Playwright spec (see e2e/pending-send.spec.ts).
  // Here we focus on the regression that motivated the audit: a window-close
  // mid-undo-window must rehydrate from localStorage on next module load.
});
