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

import * as Sentry from "@sentry/react";
import { makeBrowserOfflineTransport } from "@sentry/react";

const SENTRY_OPT_OUT_KEY = "sentry_opt_out";

// L-1 (audit security.md, issue #544) : DSN injecté via env Vite plutôt
// que hardcodé. Le DSN est public-by-design (Sentry frontend tourne dans
// le navigateur), mais l'extraire de l'env permet (a) de pivoter sans
// rebuild, (b) de désactiver l'envoi en preview / staging sans toucher
// au code, (c) d'éviter qu'un fork du repo embarque par accident notre
// DSN dans son bundle. Configurer dans Vercel : Settings → Environment
// Variables → `VITE_SENTRY_DSN` (Production scope).
const dsn = import.meta.env.VITE_SENTRY_DSN ?? "";

export function resolveSentryTunnel() {
  // The Vercel web build is currently static-only: there is no
  // /api/sentry-tunnel function deployed with agentys-app.
  return undefined;
}

// P0-3 (2026-05-17): gate Sentry initialization behind PROD so dev console
// noise (HMR re-renders, StrictMode double-invokes, dev-only assertions)
// never reaches the ingest endpoint and dev work doesn't depend on a
// reachable Sentry. The internal `enabled: !DEV` flag was insufficient
// because the SDK still bootstraps the global handler graph + transport.
const sentryEnabled = !!dsn && !!import.meta.env.PROD;
if (dsn) {
  if (!sentryEnabled) {
    // Dev / preview without PROD: do nothing. The else-branch below logs the
    // missing-DSN hint only when PROD is true.
  } else {
  Sentry.init({
    dsn,

    // Disable entirely in dev — no noise, no cost
    enabled: !import.meta.env.DEV,

    // P0-3: persist events to IndexedDB when ingest is unreachable (e.g. the
    // 503 incident at o4510937376751616.ingest.us.sentry.io on 2026-05-17).
    // Events are re-sent on the next successful round-trip. Without this,
    // anything thrown during an ingest outage is lost forever.
    transport: makeBrowserOfflineTransport(Sentry.makeFetchTransport),

    // Same-origin tunnel for the web app: direct ingest hosts are frequently
    // blocked by browser privacy tooling, showing as `(blocked:other)` on
    // Sentry envelope requests. Tauri/non-HTTPS builds keep direct ingest.
    tunnel: resolveSentryTunnel(),

    // Performance: sample 10% of transactions in production. Lowered from
    // 0.2 → 0.1 alongside the replay drop to keep envelope volume in check
    // during ingest backpressure (P0-3).
    tracesSampleRate: 0.1,

    // Session Replay: capture 5% of sessions (down from 10%), 100% of
    // sessions with errors. Same rationale as tracesSampleRate.
    replaysSessionSampleRate: 0.05,
    replaysOnErrorSampleRate: 1.0,

    // Heavy integrations (replay, tracing) are added lazily via
    // requestIdleCallback below to keep the critical bundle/main thread
    // free during first paint. In environments without requestIdleCallback
    // (JSDOM/tests, very old browsers), they're added synchronously so
    // behavior is unchanged.
    integrations: [],

    environment: "production",

    // Respect user opt-out preference + drop dev/library noise (P0-3).
    beforeSend(event) {
      if (localStorage.getItem(SENTRY_OPT_OUT_KEY) === "true") return null;
      // Drop the i18next Locize promo log and other library-side noise
      // that doesn't reflect an app problem worth a Sentry event.
      const msg = event?.message
        || (event?.exception?.values?.[0]?.value ?? "");
      if (typeof msg === "string" && /Locize|i18next: hasLoadedNamespace/i.test(msg)) {
        return null;
      }
      // Drop transient stale-chunk errors — they're handled by the reload
      // recovery in main.tsx (P0-2). Reporting them flooded Sentry on every
      // deploy day.
      if (typeof msg === "string" && /Failed to fetch dynamically imported module|Loading chunk \d+ failed|'text\/html' is not a valid JavaScript MIME type|Unable to preload CSS/i.test(msg)) {
        return null;
      }
      return event;
    },

    beforeSendTransaction(event) {
      if (localStorage.getItem(SENTRY_OPT_OUT_KEY) === "true") return null;
      return event;
    },
  });
  // TODO(P0-3, 2026-05-17): Sentry ingest returned HTTP 503 during this audit.
  // The frontend mitigation above (offline transport + lowered sample rates +
  // PROD gate) buffers events locally and prevents the loss-and-retry storm,
  // but the ingest endpoint itself still needs to be unwedged by the backend/
  // Sentry org owner before in-flight envelopes resume flowing.

  // Defer the heavy integrations to idle time. Replay+BrowserTracing weigh
  // ~110 KB gzipped of runtime work; pushing them off the critical path
  // measurably improves FCP on cold start (Tauri webview / slow networks).
  const addHeavyIntegrations = () => {
    Sentry.addIntegration(
      Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true })
    );
    Sentry.addIntegration(Sentry.browserTracingIntegration());
  };

  type IdleWindow = Window & {
    requestIdleCallback?: (
      cb: () => void,
      opts?: { timeout: number }
    ) => number;
  };
  const w = (typeof window !== "undefined" ? window : undefined) as
    | IdleWindow
    | undefined;
  if (w && typeof w.requestIdleCallback === "function") {
    w.requestIdleCallback(addHeavyIntegrations, { timeout: 3000 });
  } else {
    // No requestIdleCallback (JSDOM, older webviews) → eager registration
    // preserves prior behavior and keeps existing tests green.
    addHeavyIntegrations();
  }
  } // end PROD branch
} else if (!import.meta.env.DEV) {
  // Production sans DSN : Sentry désactivé silencieusement. Loggue un hint
  // côté console pour qu'un opérateur qui inspecte la prod comprenne
  // pourquoi il n'y a pas de telemetry. En dev on ne loggue rien — DSN
  // absent est le comportement attendu.
  console.warn(
    "[sentry] VITE_SENTRY_DSN not set — error reporting disabled. " +
    "Set it in Vercel: Settings → Environment Variables.",
  );
}
