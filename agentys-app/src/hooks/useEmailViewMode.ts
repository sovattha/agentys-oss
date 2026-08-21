import { useCallback, useSyncExternalStore } from "react";

export type EmailViewMode = "compact" | "balanced" | "comfortable";

const STORAGE_KEY = "agentys_email_view_mode";

// Shared listeners for cross-component sync
const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot(): EmailViewMode {
  return (localStorage.getItem(STORAGE_KEY) as EmailViewMode) || "compact";
}
function notify() {
  listeners.forEach((cb) => cb());
}

export function useEmailViewMode() {
  const viewMode = useSyncExternalStore(subscribe, getSnapshot);

  const toggleViewMode = useCallback(() => {
    const current = getSnapshot();
    const cycle: Record<EmailViewMode, EmailViewMode> = {
      compact: "balanced",
      balanced: "comfortable",
      comfortable: "compact",
    };
    const newValue: EmailViewMode = cycle[current];
    localStorage.setItem(STORAGE_KEY, newValue);
    notify();
  }, []);

  const setViewMode = useCallback((mode: EmailViewMode) => {
    localStorage.setItem(STORAGE_KEY, mode);
    notify();
  }, []);

  return { viewMode, toggleViewMode, setViewMode };
}
