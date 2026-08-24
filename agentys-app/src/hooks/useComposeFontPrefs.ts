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

export type ComposeFontFamily = "sans" | "helvetica" | "georgia" | "mono";
export type ComposeFontSize = "small" | "medium" | "large" | "xlarge";

export const FONT_FAMILY_OPTIONS: { id: ComposeFontFamily; label: string; group: string }[] = [
  { id: "sans",      label: "Instrument Sans",   group: "Sans-serif" },
  { id: "helvetica", label: "Helvetica", group: "Sans-serif" },
  { id: "georgia",   label: "Georgia",   group: "Serif" },
  { id: "mono",      label: "Monospace", group: "Mono" },
];

export const FONT_FAMILY_MAP: Record<ComposeFontFamily, string> = {
  sans: "var(--font-sans)",
  helvetica: "'Helvetica Neue', 'Helvetica', 'Arial', sans-serif",
  georgia: "'Georgia', serif",
  mono: "var(--font-mono)",
};

const VALID_FAMILIES = new Set<ComposeFontFamily>(["sans", "helvetica", "georgia", "mono"]);

export const FONT_SIZE_MAP: Record<ComposeFontSize, string> = {
  small: "14px",
  medium: "16px",
  large: "18px",
  xlarge: "22px",
};

const FAMILY_KEY = "agentys_compose_font_family";
const SIZE_KEY = "agentys_compose_font_size";

// --- Font Family store ---
const familyListeners = new Set<() => void>();
function subscribeFamily(cb: () => void) {
  familyListeners.add(cb);
  return () => familyListeners.delete(cb);
}
function getFamilySnapshot(): ComposeFontFamily {
  const stored = localStorage.getItem(FAMILY_KEY) as ComposeFontFamily | null;
  return stored && VALID_FAMILIES.has(stored) ? stored : "sans";
}
function notifyFamily() {
  familyListeners.forEach((cb) => cb());
}

// --- Font Size store ---
const sizeListeners = new Set<() => void>();
function subscribeSize(cb: () => void) {
  sizeListeners.add(cb);
  return () => sizeListeners.delete(cb);
}
function getSizeSnapshot(): ComposeFontSize {
  return (localStorage.getItem(SIZE_KEY) as ComposeFontSize) || "medium";
}
function notifySize() {
  sizeListeners.forEach((cb) => cb());
}

export function useComposeFontPrefs() {
  const fontFamily = useSyncExternalStore(subscribeFamily, getFamilySnapshot);
  const fontSize = useSyncExternalStore(subscribeSize, getSizeSnapshot);

  const setFontFamily = useCallback((f: ComposeFontFamily) => {
    localStorage.setItem(FAMILY_KEY, f);
    notifyFamily();
  }, []);

  const setFontSize = useCallback((s: ComposeFontSize) => {
    localStorage.setItem(SIZE_KEY, s);
    notifySize();
  }, []);

  return {
    fontFamily,
    fontSize,
    setFontFamily,
    setFontSize,
    fontFamilyCss: FONT_FAMILY_MAP[fontFamily],
    fontSizeCss: FONT_SIZE_MAP[fontSize],
  };
}
