/**
 * Cross-platform URL opener
 * Uses a native Tauri command to ensure URLs open in the system's default browser,
 * not in an embedded webview (which Google blocks for OAuth)
 */

import { invoke } from '@tauri-apps/api/core'

export async function openUrl(url: string): Promise<void> {
  // Check if running in Tauri
  if ((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
    try {
      // Use our custom Rust command that uses the OS's native open command
      // This ensures the URL opens in the real system browser, not a webview
      await invoke('open_url_in_browser', { url })
      return
    } catch (err) {
      console.error('Tauri open_url_in_browser failed:', err)
      // Fallback to opener plugin
      try {
        const { openUrl: tauriOpenUrl } = await import('@tauri-apps/plugin-opener')
        await tauriOpenUrl(url)
        return
      } catch (openerErr) {
        console.error('Tauri opener plugin also failed:', openerErr)
      }
    }
  }

  // Browser fallback
  window.open(url, '_blank')
}
