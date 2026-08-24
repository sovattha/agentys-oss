/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

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
