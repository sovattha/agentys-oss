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
