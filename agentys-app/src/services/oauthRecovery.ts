/**
 * OAuth stale-bundle auto-recovery (#557 follow-up, audit 2026-05-15).
 *
 * Context: the backend `_validate_outlook_identity()` defense (deployed
 * 2026-05-05) rejects Outlook logins when Microsoft didn't issue an
 * id_token. The original cause was a frontend that built the auth URL
 * without `openid email profile` scopes (fixed 2026-05-12). Users whose
 * browser is still serving the pre-fix bundle from cache hit
 * `identity_invalid/id_token_absent` on every retry.
 *
 * The fix below short-circuits the manual "open devtools, hard-reload"
 * dance: when we detect the stale-bundle signature, we clear caches and
 * reload the page once per session. The next attempt runs against the
 * fresh bundle and succeeds.
 *
 * Used by:
 *   - useOAuth.ts (popup postMessage handler + Tauri/COOP polling fallback)
 *   - OAuthCallback.tsx (redirect-flow same-tab error handler)
 */

const STALE_BUNDLE_RELOAD_KEY = 'agentys_oauth_stale_bundle_reloaded'

/**
 * Attempt a one-shot cache-clearing reload when the backend's identity
 * defense rejected us for `id_token_absent` (the stale-bundle signature).
 *
 * Returns `true` if the page is being reloaded — caller must NOT proceed
 * to update UI state (the page is navigating away). Returns `false` when:
 *   - the reason is not `id_token_absent`, OR
 *   - we've already attempted recovery this session (prevents reload loops), OR
 *   - sessionStorage is unavailable (private mode — fail safe by skipping).
 */
export function attemptStaleBundleRecovery(reason: string | undefined | null): boolean {
  if (reason !== 'id_token_absent') return false
  try {
    if (sessionStorage.getItem(STALE_BUNDLE_RELOAD_KEY)) return false
    sessionStorage.setItem(STALE_BUNDLE_RELOAD_KEY, String(Date.now()))
  } catch {
    return false
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c: any = (globalThis as any).caches
    if (c?.keys) {
      c.keys()
        .then((names: string[]) => names.forEach((n: string) => c.delete(n)))
        .catch(() => {})
    }
  } catch { /* ignore */ }
  const url = new URL(window.location.href)
  url.searchParams.set('_oauth_recover', String(Date.now()))
  window.location.replace(url.toString())
  return true
}
