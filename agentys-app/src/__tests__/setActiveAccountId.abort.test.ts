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
 * F11 (MEDIUM) — account-level AbortController regression guard.
 *
 * Pre-fix, switching accounts while a `fetchEmails(limit=200)` was still
 * resolving for account A could land its response after the switch and
 * clobber `setEmails` with account-A data on account B's UI.
 *
 * After fix: `setActiveAccountId` aborts the previous AbortController and
 * installs a fresh one. Callers that opt in via `getAccountFetchSignal()`
 * see AbortError and short-circuit cleanly.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  setActiveAccountId,
  getActiveAccountId,
  getAccountFetchSignal,
} from '../api/emails';

beforeEach(() => {
  // Reset the module-level state by going back to default.
  // Note: setActiveAccountId('default') is a no-op when already 'default',
  // so we force a transition through a real id then back.
  setActiveAccountId('reset-helper');
  setActiveAccountId('default');
});

describe('F11: setActiveAccountId aborts in-flight requests on switch', () => {
  it('exposes an AbortSignal for the active account', () => {
    const signal = getAccountFetchSignal();
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);
  });

  it('switching account aborts the previous signal', () => {
    setActiveAccountId('account-A');
    const signalA = getAccountFetchSignal();
    expect(signalA.aborted).toBe(false);

    // Switch to account B
    setActiveAccountId('account-B');

    // Previous signal must be aborted
    expect(signalA.aborted).toBe(true);
    // New signal is fresh and not aborted
    const signalB = getAccountFetchSignal();
    expect(signalB).not.toBe(signalA);
    expect(signalB.aborted).toBe(false);
    expect(getActiveAccountId()).toBe('account-B');
  });

  it('multiple switches abort each prior signal in order', () => {
    setActiveAccountId('account-1');
    const s1 = getAccountFetchSignal();
    setActiveAccountId('account-2');
    const s2 = getAccountFetchSignal();
    setActiveAccountId('account-3');
    const s3 = getAccountFetchSignal();

    expect(s1.aborted).toBe(true);
    expect(s2.aborted).toBe(true);
    expect(s3.aborted).toBe(false);
  });

  it('a fetch using getAccountFetchSignal is rejected with AbortError on switch', async () => {
    setActiveAccountId('account-A');
    const signal = getAccountFetchSignal();

    // Simulate a slow fetch
    const slowFetch = new Promise<string>((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        const err = new Error('aborted');
        (err as any).name = 'AbortError';
        reject(err);
      });
    });

    setActiveAccountId('account-B');

    await expect(slowFetch).rejects.toMatchObject({ name: 'AbortError' });
  });
});
