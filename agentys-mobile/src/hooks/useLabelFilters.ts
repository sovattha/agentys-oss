/**
 * Hook pour gérer les filtres de labels — priorisation des emails par label.
 * Persiste les labels activés dans SecureStore.
 */

import { useState, useEffect, useCallback } from "react";
import * as SecureStore from "expo-secure-store";
import { getLabels, type LabelInfo } from "../services/api";

const STORE_KEY = "label_filters_enabled";

export interface LabelFilter {
  label: LabelInfo;
  enabled: boolean;
}

export interface UseLabelFilters {
  filters: LabelFilter[];
  loading: boolean;
  toggle: (labelName: string) => void;
  enableAll: () => void;
  disableAll: () => void;
  enabledLabels: string[];
}

export function useLabelFilters(): UseLabelFilters {
  const [allLabels, setAllLabels] = useState<LabelInfo[]>([]);
  const [enabledSet, setEnabledSet] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);

  // Load labels from API + persisted enabled set
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [res, stored] = await Promise.all([
          getLabels(),
          SecureStore.getItemAsync(STORE_KEY),
        ]);

        if (cancelled) return;

        const labels = res.labels || [];
        // Sort: defaults first, then custom, alphabetical within each group
        labels.sort((a, b) => {
          if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;
          return a.name.localeCompare(b.name);
        });
        setAllLabels(labels);

        if (stored) {
          try {
            const parsed = JSON.parse(stored) as string[];
            setEnabledSet(new Set(parsed));
          } catch {
            // First time — enable all defaults
            setEnabledSet(new Set(labels.filter((l) => l.is_default).map((l) => l.name)));
          }
        } else {
          // First time — enable all defaults
          setEnabledSet(new Set(labels.filter((l) => l.is_default).map((l) => l.name)));
        }
        setLoaded(true);
      } catch {
        // API down — use empty
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  // Persist on change
  useEffect(() => {
    if (!loaded) return;
    SecureStore.setItemAsync(STORE_KEY, JSON.stringify([...enabledSet])).catch(() => {}); // no-op légitime : cache best-effort
  }, [enabledSet, loaded]);

  const toggle = useCallback((labelName: string) => {
    setEnabledSet((prev) => {
      const next = new Set(prev);
      if (next.has(labelName)) {
        next.delete(labelName);
      } else {
        next.add(labelName);
      }
      return next;
    });
  }, []);

  const enableAll = useCallback(() => {
    setEnabledSet(new Set(allLabels.map((l) => l.name)));
  }, [allLabels]);

  const disableAll = useCallback(() => {
    setEnabledSet(new Set());
  }, []);

  const filters: LabelFilter[] = allLabels.map((label) => ({
    label,
    enabled: enabledSet.has(label.name),
  }));

  return {
    filters,
    loading,
    toggle,
    enableAll,
    disableAll,
    enabledLabels: [...enabledSet],
  };
}
