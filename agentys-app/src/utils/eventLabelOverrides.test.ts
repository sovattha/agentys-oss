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

import { describe, expect, it } from 'vitest';
import { remapEventLabelOverride, type EventLabelOverrides } from './eventLabelOverrides';

const RED = { name: 'Important', color: '#dc2626' };
const BLUE = { name: 'Client', color: '#3b82f6' };

describe('remapEventLabelOverride', () => {
  it('re-keys an override from a temp id to the real id (the core fix)', () => {
    const before: EventLabelOverrides = { 'temp-123': RED };
    const after = remapEventLabelOverride(before, 'temp-123', 'real-abc');
    expect(after).toEqual({ 'real-abc': RED });
    expect(after['temp-123']).toBeUndefined();
  });

  it('leaves other events untouched while re-keying one', () => {
    const before: EventLabelOverrides = { 'temp-123': RED, 'real-xyz': BLUE };
    const after = remapEventLabelOverride(before, 'temp-123', 'real-abc');
    expect(after).toEqual({ 'real-abc': RED, 'real-xyz': BLUE });
  });

  it('drops the override when toId is null (create rolled back)', () => {
    const before: EventLabelOverrides = { 'temp-123': RED, 'real-xyz': BLUE };
    const after = remapEventLabelOverride(before, 'temp-123', null);
    expect(after).toEqual({ 'real-xyz': BLUE });
  });

  it('returns the same reference when there is no entry for fromId (no-op)', () => {
    const before: EventLabelOverrides = { 'real-xyz': BLUE };
    expect(remapEventLabelOverride(before, 'temp-123', 'real-abc')).toBe(before);
    expect(remapEventLabelOverride(before, 'temp-123', null)).toBe(before);
  });

  it('returns the same reference when toId === fromId (no-op)', () => {
    const before: EventLabelOverrides = { 'real-xyz': BLUE };
    expect(remapEventLabelOverride(before, 'real-xyz', 'real-xyz')).toBe(before);
  });

  it('does not mutate the input object', () => {
    const before: EventLabelOverrides = { 'temp-123': RED };
    remapEventLabelOverride(before, 'temp-123', 'real-abc');
    expect(before).toEqual({ 'temp-123': RED });
  });
});
