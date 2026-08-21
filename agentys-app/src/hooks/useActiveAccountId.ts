/**
 * Reactive read of the active account id.
 *
 * The id is stored in module state in `src/api/emails.ts` (`_activeAccountId`)
 * and mutated through `setActiveAccountId(...)`, which dispatches the
 * window event `agentys:account-changed`. This hook subscribes to that
 * event so query keys (`qk.labels(accountId)`, `qk.settings(accountId)`,
 * …) flip cleanly when the user switches accounts.
 *
 * Returns the raw string (`"1"`, hex hash, or `"default"`). Callers that
 * need a canonical cache-key segment must pipe through `canonicalAccountId()`
 * — usually transparently via the `qk.*` factories.
 */
import { useSyncExternalStore } from "react";
import { getActiveAccountId } from "../api/emails";

function subscribe(callback: () => void): () => void {
  window.addEventListener("agentys:account-changed", callback);
  return () => window.removeEventListener("agentys:account-changed", callback);
}

function getSnapshot(): string {
  return getActiveAccountId();
}

export function useActiveAccountId(): string {
  return useSyncExternalStore(subscribe, getSnapshot);
}
