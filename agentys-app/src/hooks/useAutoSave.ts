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

import { useCallback, useEffect, useRef, useState } from 'react';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface UseAutoSaveOptions<T> {
  data: T;
  onSave: (data: T) => Promise<void>;
  debounceMs?: number;
  enabled?: boolean;
}

interface UseAutoSaveResult {
  status: SaveStatus;
  save: () => Promise<void>;
  error: string | null;
}

export function useAutoSave<T>({
  data,
  onSave,
  debounceMs = 2000,
  enabled = true,
}: UseAutoSaveOptions<T>): UseAutoSaveResult {
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedDataRef = useRef<T>(data);
  const dataRef = useRef<T>(data);
  const isMountedRef = useRef(true);

  // Keep dataRef updated
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const save = useCallback(async () => {
    if (!isMountedRef.current) return;

    setStatus('saving');
    setError(null);

    try {
      await onSave(dataRef.current);
      if (isMountedRef.current) {
        lastSavedDataRef.current = dataRef.current;
        setStatus('saved');
      }
    } catch (err) {
      if (isMountedRef.current) {
        const message = err instanceof Error ? err.message : 'Erreur lors de la sauvegarde';
        setError(message);
        setStatus('error');
      }
    }
  }, [onSave]);

  // Track data version to avoid expensive JSON.stringify on every render
  const dataVersionRef = useRef(0);
  const prevDataRef = useRef(data);
  if (prevDataRef.current !== data) {
    prevDataRef.current = data;
    dataVersionRef.current += 1;
  }

  // Auto-save on data change (reacts to version bump, not deep comparison)
  useEffect(() => {
    if (!enabled) return;

    // Skip if data reference hasn't changed since last save
    if (data === lastSavedDataRef.current) {
      return;
    }

    // Clear existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Set status to indicate pending save
    setStatus('saving');

    // Debounce the save
    timeoutRef.current = setTimeout(() => {
      save();
    }, debounceMs);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [data, enabled, debounceMs, save]);

  return {
    status,
    save,
    error,
  };
}
