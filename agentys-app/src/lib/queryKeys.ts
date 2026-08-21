/**
 * Centralized TanStack Query key factories.
 *
 * Every query key in the app MUST be produced through one of these factories.
 * Inline tuples like `['settings', accountId]` are forbidden — they bypass
 * `canonicalAccountId()` and cause silent cache fragmentation when the same
 * account is referenced as `1` in one place and `"1"` in another.
 *
 * The factories return `readonly` arrays so consumers can't accidentally
 * mutate them after handing them to `useQuery`.
 *
 * Naming convention:
 *   [resource, accountId, ...specifiers]
 *
 * `accountId` is ALWAYS in position 1 (after the resource name). This lets
 * `queryClient.removeQueries({ predicate: q => q.queryKey[1] !== newId })`
 * work as a single uniform account-switch eviction.
 */
import { canonicalAccountId, type AccountIdInput } from "./canonicalAccountId";

export const qk = {
  /** Account-scoped settings (boolean toggles, prefs, …). */
  settings: (accountId: AccountIdInput) =>
    ["settings", canonicalAccountId(accountId)] as const,

  /** Full label list for an account. */
  labels: (accountId: AccountIdInput) =>
    ["labels", canonicalAccountId(accountId)] as const,

  /** Label counts (unread-only or total) for an account. */
  labelCounts: (accountId: AccountIdInput, unreadOnly: boolean) =>
    ["labelCounts", canonicalAccountId(accountId), unreadOnly] as const,
} as const;

export type QueryKey =
  | ReturnType<typeof qk.settings>
  | ReturnType<typeof qk.labels>
  | ReturnType<typeof qk.labelCounts>;
