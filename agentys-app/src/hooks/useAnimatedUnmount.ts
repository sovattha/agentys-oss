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

import { useState, useCallback, useMemo, useRef, useEffect } from 'react';

/**
 * Hook for smooth exit animations on modals/panels.
 * Returns `shouldRender` (keep in DOM during exit) and `isClosing` (apply exit CSS class).
 *
 * Usage:
 *   const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose, 180);
 *   if (!shouldRender) return null;
 *   return <div className={`modal ${isClosing ? 'closing' : ''}`}>...</div>
 */
export function useAnimatedUnmount(
  isOpen: boolean,
  onClose: () => void,
  duration = 180
) {
  const [isClosing, setIsClosing] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear any pending close-animation timer on unmount so the callback can't
  // fire against a torn-down tree. Without this the setTimeout below survived
  // the component (and, in tests, the jsdom environment) — firing setIsClosing/
  // onClose after teardown threw "ReferenceError: window is not defined" and
  // leaked an unhandled error into the vitest run (CommandPalette.test.tsx).
  useEffect(() => () => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
  }, []);

  // Render when open OR during the closing animation
  const shouldRender = useMemo(() => isOpen || isClosing, [isOpen, isClosing]);

  const handleClose = useCallback(() => {
    setIsClosing(true);
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setIsClosing(false);
      onClose();
    }, duration);
  }, [onClose, duration]);

  return { shouldRender, isClosing, handleClose };
}
