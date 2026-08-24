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

import { describe, it, expect, afterEach } from 'vitest';
import { hasEscapeOwner, ESCAPE_OWNER_ATTR } from './escapeOwner';

/**
 * escapeOwner is the structural signal that fixes the LocalePickers bug class
 * app-wide (audit 2026-05-30): an inner popover tags its open root with
 * `data-escape-owner`; every host's Escape close-path bails while such a node
 * exists. This pins the helper's contract and the host-guard behaviour.
 */
describe('escapeOwner', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('reports no owner when nothing is tagged', () => {
    expect(hasEscapeOwner()).toBe(false);
  });

  it('detects a tagged popover anywhere in the document', () => {
    const node = document.createElement('div');
    node.setAttribute(ESCAPE_OWNER_ATTR, '');
    document.body.appendChild(node);
    expect(hasEscapeOwner()).toBe(true);
  });

  it('goes back to false once the popover node is removed (no leak)', () => {
    const node = document.createElement('div');
    node.setAttribute(ESCAPE_OWNER_ATTR, '');
    document.body.appendChild(node);
    expect(hasEscapeOwner()).toBe(true);
    // Mirrors React unmounting the conditionally-rendered popover on close.
    node.remove();
    expect(hasEscapeOwner()).toBe(false);
  });

  it('models the host-guard contract: a host defers while a popover owns Escape', () => {
    // A host close-path that only closes when no popover owns Escape.
    let hostClosed = 0;
    const hostEscape = () => { if (!hasEscapeOwner()) hostClosed++; };

    // Popover open → first Escape: host defers, popover would close itself.
    const popover = document.createElement('div');
    popover.setAttribute(ESCAPE_OWNER_ATTR, '');
    document.body.appendChild(popover);
    hostEscape();
    expect(hostClosed).toBe(0);

    // Popover dismissed itself → second Escape: host now closes.
    popover.remove();
    hostEscape();
    expect(hostClosed).toBe(1);
  });
});
