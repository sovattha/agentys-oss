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
 * WebSocket → QueryClient invalidation bus.
 *
 * Phase 0 — scaffold only. The class exists, registers no events, exposes
 * `attach(client)` / `detach()` so the wiring side can be in place before
 * any phase actually subscribes to WS messages.
 *
 * Phase 5 will populate `WS_INVALIDATIONS` with the actual event→queryKey
 * mappings (e.g. `email-upsert` → `qk.emails(accountId, …)`).
 */
import type { QueryClient } from "@tanstack/react-query";

export class WebSocketInvalidator {
  private client: QueryClient | null = null;

  attach(client: QueryClient): void {
    this.client = client;
  }

  detach(): void {
    this.client = null;
  }

  /** Phase 5 will fill this. For now it's a typed no-op stub. */
  handle(_event: string, _payload: unknown): void {
    // intentionally empty — Phase 5 populates the routing table
  }

  /** Test introspection. */
  isAttached(): boolean {
    return this.client !== null;
  }
}

let _instance: WebSocketInvalidator | null = null;

export function getWebSocketInvalidator(): WebSocketInvalidator {
  if (_instance === null) _instance = new WebSocketInvalidator();
  return _instance;
}

export function __resetWebSocketInvalidatorForTests(): void {
  _instance = null;
}
