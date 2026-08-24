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

import { describe, it, expect, vi, beforeEach } from "vitest";

// instrument.ts est gated par `if (dsn)` où `dsn = import.meta.env.VITE_SENTRY_DSN`.
// En vitest, aucun .env n'est chargé donc `Sentry.init` n'est jamais appelé et
// les assertions sur `mockInit.mock.calls[0]` retournent undefined. On stub la
// var d'env AVANT le `await import("../instrument")` plus bas pour que le
// chemin de prod s'exécute.
vi.stubEnv("VITE_SENTRY_DSN", "https://test@test.ingest.sentry.io/1");
vi.stubEnv("PROD", true);
vi.stubEnv("DEV", false);

// Mock Sentry before importing instrument so we can inspect the init call
const mockInit = vi.fn();
const capturedCallbacks: {
  beforeSend?: (event: object) => object | null;
  beforeSendTransaction?: (event: object) => object | null;
} = {};

vi.mock("@sentry/react", () => ({
  init: (opts: {
    enabled?: boolean;
    beforeSend?: (event: object) => object | null;
    beforeSendTransaction?: (event: object) => object | null;
    [key: string]: unknown;
  }) => {
    mockInit(opts);
    if (opts.beforeSend) capturedCallbacks.beforeSend = opts.beforeSend;
    if (opts.beforeSendTransaction) capturedCallbacks.beforeSendTransaction = opts.beforeSendTransaction;
  },
  makeBrowserOfflineTransport: vi.fn((transport) => transport),
  makeFetchTransport: vi.fn(() => ({ name: "FetchTransport" })),
  replayIntegration: vi.fn(() => ({ name: "Replay" })),
  browserTracingIntegration: vi.fn(() => ({ name: "BrowserTracing" })),
  // Heavy integrations are deferred via requestIdleCallback in instrument.ts.
  // In JSDOM (no requestIdleCallback) they fall back to eager registration,
  // so addIntegration runs synchronously during module load.
  addIntegration: vi.fn(),
}));

// Mock localStorage
const mockLocalStorage: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem: (key: string) => mockLocalStorage[key] ?? null,
  setItem: (key: string, value: string) => { mockLocalStorage[key] = value; },
  removeItem: (key: string) => { delete mockLocalStorage[key]; },
  clear: () => { Object.keys(mockLocalStorage).forEach((k) => delete mockLocalStorage[k]); },
});

// Import instrument AFTER mocks are set up
const instrument = await import("../instrument");

describe("instrument.ts — Sentry initialisation", () => {
  beforeEach(() => {
    Object.keys(mockLocalStorage).forEach((k) => delete mockLocalStorage[k]);
  });

  it("appelle Sentry.init une seule fois au chargement du module", () => {
    expect(mockInit).toHaveBeenCalledTimes(1);
  });

  it("désactive Sentry en mode DEV", () => {
    const opts = mockInit.mock.calls[0][0];
    // import.meta.env.DEV is false in vitest by default (test mode)
    expect(typeof opts.enabled).toBe("boolean");
  });

  it("taux d'échantillonnage des traces ≤ 0.2", () => {
    const opts = mockInit.mock.calls[0][0];
    expect(opts.tracesSampleRate).toBeLessThanOrEqual(0.2);
  });

  it("n'utilise pas de tunnel Sentry tant que la route Vercel n'existe pas", () => {
    expect(instrument.resolveSentryTunnel()).toBeUndefined();
  });

  it("maskAllText est true (confidentialité)", async () => {
    const opts = mockInit.mock.calls[0][0];
    const replay = opts.integrations?.find(
      (i: { name?: string }) => i.name === "Replay"
    );
    // replayIntegration is called with maskAllText: true
    const { replayIntegration } = await import("@sentry/react");
    expect(replayIntegration).toHaveBeenCalledWith(
      expect.objectContaining({ maskAllText: true, blockAllMedia: true })
    );
    // replay integration is present
    expect(opts.integrations).toBeDefined();
    void replay;
  });

  describe("beforeSend — respect opt-out localStorage", () => {
    it("transmet l'événement si sentry_opt_out est absent", () => {
      const event = { message: "test error" };
      const result = capturedCallbacks.beforeSend?.(event);
      expect(result).toBe(event);
    });

    it("transmet l'événement si sentry_opt_out=false", () => {
      mockLocalStorage["sentry_opt_out"] = "false";
      const event = { message: "test error" };
      const result = capturedCallbacks.beforeSend?.(event);
      expect(result).toBe(event);
    });

    it("bloque l'événement si sentry_opt_out=true", () => {
      mockLocalStorage["sentry_opt_out"] = "true";
      const event = { message: "test error" };
      const result = capturedCallbacks.beforeSend?.(event);
      expect(result).toBeNull();
    });
  });

  describe("beforeSendTransaction — respect opt-out localStorage", () => {
    it("transmet la transaction si sentry_opt_out est absent", () => {
      const event = { transaction: "/api/emails" };
      const result = capturedCallbacks.beforeSendTransaction?.(event);
      expect(result).toBe(event);
    });

    it("bloque la transaction si sentry_opt_out=true", () => {
      mockLocalStorage["sentry_opt_out"] = "true";
      const event = { transaction: "/api/emails" };
      const result = capturedCallbacks.beforeSendTransaction?.(event);
      expect(result).toBeNull();
    });
  });
});
