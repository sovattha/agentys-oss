import { useEffect, useState } from "react";
import {
  ensureCurrentAccountId,
  getCurrentAccountId,
  isCurrentAccountLoaded,
  subscribeCurrentAccountId,
} from "../lib/currentAccountId";

/**
 * Wrapper React autour du module `lib/currentAccountId`.
 * Retourne `null` tant que le compte actif n'a pas été résolu.
 */
export function useCurrentAccountId(): string | null {
  const [id, setId] = useState<string | null>(getCurrentAccountId());

  useEffect(() => {
    if (isCurrentAccountLoaded()) {
      setId(getCurrentAccountId());
    }
    const unsub = subscribeCurrentAccountId(setId);
    ensureCurrentAccountId();
    return unsub;
  }, []);

  return id;
}
