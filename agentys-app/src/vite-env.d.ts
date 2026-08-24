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

/// <reference types="vite/client" />

// Once this file is a module (because of `export {}` at the bottom), all
// interfaces must live inside `declare global` to augment the global scope.
declare global {
  // Injected at build time by vite.config.ts (see `define`).
  // Format: "<pkg.version>" on tag builds, "<pkg.version>-dev.<short_sha>" otherwise.
  const __APP_VERSION__: string

  interface ImportMetaEnv {
    readonly VITE_API_URL: string
    /** Sentry frontend DSN, injected at build time. Leave unset to disable Sentry. */
    readonly VITE_SENTRY_DSN?: string
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv
  }

  // Tauri internal globals
  interface Window {
    __TAURI_INTERNALS__?: unknown
    __TAURI__?: unknown
  }

  // View Transitions API (Chrome 111+)
  interface Document {
    startViewTransition?: (callback: () => void | Promise<void>) => {
      finished: Promise<void>
      ready: Promise<void>
      updateCallbackDone: Promise<void>
    }
  }
}

export {}
