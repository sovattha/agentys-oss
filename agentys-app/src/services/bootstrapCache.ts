/**
 * Bootstrap cache — deduplicates endpoints hit at app boot.
 *
 * Problem: at boot, several independent hooks/components fetch the same
 * endpoints (/api/auth/me in particular). React StrictMode double-mount and
 * staggered consumer mounts turn that into 3-4 redundant HTTP calls.
 *
 * Solution: a module-scoped cache with in-flight request deduplication.
 * Callers share the same pending promise; the result is cached briefly to
 * absorb staggered late mounts.
 *
 * Settings have their own cache in `hooks/useSettingsCache.ts`. This file
 * handles `/api/auth/me`. Keep them split so ownership stays clear.
 */
import { API_URL } from "../config";
import { getAuthHeaders, getStoredToken } from "./authToken";

const API_BASE = `${API_URL}/api`;

// ── /api/auth/me ──────────────────────────────────────────────────────────

export interface AuthMeResponse {
  user?: {
    id?: number;
    email?: string;
    is_admin?: boolean;
    plan?: string;
    subscription_status?: string;
    ai_enabled?: boolean;
    billing?: {
      plan: string;
      subscription_status: string;
      ai_enabled: boolean;
      reason: string;
      current_period_end?: string | null;
      cancel_at_period_end?: boolean;
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface AuthMeCacheEntry {
  data: AuthMeResponse | null;
  timestamp: number;
  pending: Promise<AuthMeResponse> | null;
  token: string | null;
}

// Keyed by token so a logout/login swap invalidates naturally.
let _authMeCache: AuthMeCacheEntry = {
  data: null,
  timestamp: 0,
  pending: null,
  token: null,
};

const AUTH_ME_TTL_MS = 30_000; // 30s — covers staggered boot mounts

/**
 * Fetch /api/auth/me with in-flight deduplication and a short cache.
 *
 * The caller is responsible for the auth token being present in
 * `getAuthHeaders()` (we forward it as usual). The cache keys on the raw
 * token so token rotation invalidates automatically.
 *
 * @throws if the fetch fails (caller should handle — typically logout path).
 */
export async function fetchAuthMeCached(): Promise<AuthMeResponse> {
  // No JWT → caller is on the login page and the server would 401.
  // Throw the same shape useAuth's catch path expects so its branching
  // (transient vs fatal) keeps working uniformly. (Audit 2026-05-01 #5
  // follow-up — App.tsx:271 admin-check ignored token presence and was the
  // last caller still hitting /api/auth/me on each unauth page load.)
  if (!getStoredToken()) {
    throw new Error("auth/me failed: 401");
  }
  const headers = getAuthHeaders();
  const authHeader =
    (headers as Record<string, string>).Authorization ??
    (headers as Record<string, string>).authorization ??
    null;
  const now = Date.now();

  // Fresh cache hit for the same token
  if (
    _authMeCache.data &&
    _authMeCache.token === authHeader &&
    now - _authMeCache.timestamp < AUTH_ME_TTL_MS
  ) {
    return _authMeCache.data;
  }

  // In-flight dedup (same token)
  if (_authMeCache.pending && _authMeCache.token === authHeader) {
    return _authMeCache.pending;
  }

  // Token changed or no entry — start a fresh fetch
  const pending = fetch(`${API_BASE}/auth/me`, { headers })
    .then(async (res) => {
      if (!res.ok) {
        // Reset pending so a retry can fire; do not cache the failure.
        if (_authMeCache.pending === pending) {
          _authMeCache = { data: null, timestamp: 0, pending: null, token: null };
        }
        throw new Error(`auth/me failed: ${res.status}`);
      }
      const data = (await res.json()) as AuthMeResponse;
      _authMeCache = {
        data,
        timestamp: Date.now(),
        pending: null,
        token: authHeader,
      };
      return data;
    })
    .catch((err: unknown) => {
      if (_authMeCache.pending === pending) {
        _authMeCache = { data: null, timestamp: 0, pending: null, token: null };
      }
      throw err;
    });

  _authMeCache = {
    data: _authMeCache.token === authHeader ? _authMeCache.data : null,
    timestamp: _authMeCache.token === authHeader ? _authMeCache.timestamp : 0,
    pending,
    token: authHeader,
  };
  return pending;
}

/** Invalidate the cached /api/auth/me response (e.g., after logout). */
export function invalidateAuthMeCache(): void {
  _authMeCache = { data: null, timestamp: 0, pending: null, token: null };
}
