/**
 * Fetch the count of items a bulk action would affect, without doing it.
 *
 * Calls the same endpoint with `?count_only=true`, which short-circuits
 * server-side and returns `{count, will_be_async}`. Used to surface
 * counts in confirmation dialogs ("Delete 1,247 emails permanently?")
 * and the "queued in background — track progress in Settings ›
 * Background tasks" affordance when the wave exceeds INLINE_THRESHOLD.
 *
 * Refetches whenever `enabled` flips true (e.g. dialog opens), so the
 * count stays fresh between dialog instances.
 */
import { useEffect, useState } from 'react';
import { API_URL } from '../config';
import { getAuthHeaders } from '../services/authToken';

export interface BulkActionCount {
  count: number | null;
  willBeAsync: boolean;
  loading: boolean;
  error: Error | null;
}

interface UseBulkActionCountOptions {
  /** Endpoint path WITHOUT the `/api` prefix, e.g. `/emails/empty-trash`. */
  endpoint: string;
  /** When false, the hook stays idle. Flip to true to trigger a fetch. */
  enabled: boolean;
  /** Optional POST body forwarded to the endpoint (e.g. older_than_days). */
  body?: Record<string, unknown>;
}

export function useBulkActionCount({
  endpoint,
  enabled,
  body,
}: UseBulkActionCountOptions): BulkActionCount {
  const [count, setCount] = useState<number | null>(null);
  const [willBeAsync, setWillBeAsync] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Serialize `body` to a stable key so changes in the object identity
  // alone don't re-fire the effect — only real value changes do.
  const bodyKey = body ? JSON.stringify(body) : '';

  useEffect(() => {
    if (!enabled) {
      setCount(null);
      setWillBeAsync(false);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetch(`${API_URL}/api${endpoint}?count_only=true`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setCount(typeof data?.count === 'number' ? data.count : 0);
        setWillBeAsync(Boolean(data?.will_be_async));
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError') return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setCount(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // bodyKey captures `body` content changes; explicitly excluded `body`
    // identity from deps to avoid spurious re-fetches.

  }, [endpoint, enabled, bodyKey]);

  return { count, willBeAsync, loading, error };
}
