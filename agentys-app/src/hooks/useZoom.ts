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

import { useState, useCallback, useEffect, useRef } from "react";
import { useCurrentAccountId } from "./useCurrentAccountId";

const STORAGE_PREFIX = "agentys-zoom:";

/** Event dispatché UNIQUEMENT lors d'un changement initié par l'utilisateur
 * (zoomIn/zoomOut/resetZoom/setZoom depuis Settings). Pas dispatché lors de
 * l'hydration depuis localStorage — ce qui évite que le HUD apparaisse au refresh. */
export const ZOOM_USER_CHANGE_EVENT = "agentys:zoom-user-change";

/** Niveaux discrets, familiers au comportement Ctrl+/Ctrl- des navigateurs. */
export const ZOOM_LEVELS = [0.9, 1, 1.15, 1.3, 1.5] as const;
export type ZoomLevel = (typeof ZOOM_LEVELS)[number];
export const DEFAULT_ZOOM: ZoomLevel = 1.15;

function storageKeyFor(accountId: string | null): string {
  return `${STORAGE_PREFIX}${accountId ?? "__pending"}`;
}

function isZoomLevel(val: unknown): val is ZoomLevel {
  return typeof val === "number" && (ZOOM_LEVELS as readonly number[]).includes(val);
}

function parseStored(raw: string | null): ZoomLevel {
  if (!raw) return DEFAULT_ZOOM;
  const parsed = parseFloat(raw);
  return isZoomLevel(parsed) ? parsed : DEFAULT_ZOOM;
}

function applyZoom(zoom: ZoomLevel) {
  document.documentElement.style.setProperty("--app-zoom", String(zoom));
  document.documentElement.dataset.zoom = String(Math.round(zoom * 100));
}

/**
 * Pré-applique le zoom sauvegardé avant le 1er render pour éviter un flash.
 * Scan best-effort : 1re clé `agentys-zoom:*` non-défaut trouvée.
 */
export function preloadSavedZoom(): void {
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(STORAGE_PREFIX)) continue;
      const parsed = parseStored(localStorage.getItem(key));
      if (parsed !== DEFAULT_ZOOM) {
        applyZoom(parsed);
        return;
      }
    }
  } catch {
    /* localStorage indispo — ignorer */
  }
  applyZoom(DEFAULT_ZOOM);
}

function clampToLevel(target: number): ZoomLevel {
  let closest: ZoomLevel = ZOOM_LEVELS[0];
  let bestDelta = Math.abs(target - closest);
  for (const lvl of ZOOM_LEVELS) {
    const delta = Math.abs(target - lvl);
    if (delta < bestDelta) {
      bestDelta = delta;
      closest = lvl;
    }
  }
  return closest;
}

function nextLevel(current: ZoomLevel, direction: 1 | -1): ZoomLevel {
  const idx = ZOOM_LEVELS.indexOf(current);
  const target = idx + direction;
  if (target < 0) return ZOOM_LEVELS[0];
  if (target >= ZOOM_LEVELS.length) return ZOOM_LEVELS[ZOOM_LEVELS.length - 1];
  return ZOOM_LEVELS[target];
}

export interface UseZoomResult {
  zoom: ZoomLevel;
  zoomPercent: number;
  setZoom: (z: ZoomLevel) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  canZoomIn: boolean;
  canZoomOut: boolean;
  levels: readonly ZoomLevel[];
}

export function useZoom(): UseZoomResult {
  const accountId = useCurrentAccountId();
  const [zoom, setZoomState] = useState<ZoomLevel>(() =>
    parseStored(localStorage.getItem(storageKeyFor(accountId)))
  );
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  useEffect(() => {
    applyZoom(zoom);
  }, [zoom]);

  useEffect(() => {
    const stored = parseStored(localStorage.getItem(storageKeyFor(accountId)));
    if (stored !== zoomRef.current) setZoomState(stored);
  }, [accountId]);

  const persist = useCallback(
    (next: ZoomLevel) => {
      try {
        localStorage.setItem(storageKeyFor(accountId), String(next));
      } catch {
        /* quota/private mode — ignorer */
      }
    },
    [accountId]
  );

  const setZoom = useCallback(
    (next: ZoomLevel) => {
      const safe = isZoomLevel(next) ? next : clampToLevel(next);
      if (safe === zoomRef.current) return;
      setZoomState(safe);
      persist(safe);
      // Émet uniquement sur action utilisateur — pas lors de l'hydration async
      // depuis localStorage (cf. useEffect [accountId] qui setZoomState direct).
      try {
        window.dispatchEvent(new CustomEvent(ZOOM_USER_CHANGE_EVENT, { detail: { zoom: safe } }));
      } catch {
        /* SSR / no window — ignorer */
      }
    },
    [persist]
  );

  const zoomIn = useCallback(() => {
    const next = nextLevel(zoomRef.current, 1);
    if (next !== zoomRef.current) setZoom(next);
  }, [setZoom]);

  const zoomOut = useCallback(() => {
    const next = nextLevel(zoomRef.current, -1);
    if (next !== zoomRef.current) setZoom(next);
  }, [setZoom]);

  const resetZoom = useCallback(() => setZoom(DEFAULT_ZOOM), [setZoom]);

  return {
    zoom,
    zoomPercent: Math.round(zoom * 100),
    setZoom,
    zoomIn,
    zoomOut,
    resetZoom,
    canZoomIn: zoom < ZOOM_LEVELS[ZOOM_LEVELS.length - 1],
    canZoomOut: zoom > ZOOM_LEVELS[0],
    levels: ZOOM_LEVELS,
  };
}
