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

import { useCallback, useRef, useEffect, type RefCallback } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

/**
 * Traps focus within a container element while active.
 * Uses a callback ref to handle lazy-loaded/Suspense content correctly.
 * Tab cycles through focusable children; Shift+Tab cycles backward.
 * Restores focus to the previously-focused element on deactivation.
 */
export function useFocusTrap(active: boolean): RefCallback<HTMLDivElement> {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  const setup = useCallback((container: HTMLDivElement) => {
    // Save focus to restore later
    if (!previousFocus.current) {
      previousFocus.current = document.activeElement as HTMLElement;
    }

    // Focus first focusable child, with rAF retry for lazy content
    let cancelled = false;
    const focusFirst = () => {
      const first = container.querySelector<HTMLElement>(FOCUSABLE);
      if (first) { first.focus(); return true; }
      return false;
    };

    if (!focusFirst()) {
      let retries = 0;
      const retry = () => {
        if (cancelled || focusFirst() || retries++ > 30) return;
        requestAnimationFrame(retry);
      };
      requestAnimationFrame(retry);
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;

      // Si le focus est dans un overlay opt-out, on le laisse gérer son propre Tab.
      const active = document.activeElement as HTMLElement | null;
      if (active?.closest('.smart-search-bar, .search-suggestions-dropdown, [role="dialog"], [data-radix-popper-content-wrapper], .ai-cmd-popover, [data-focus-trap-ignore]')) {
        return;
      }

      const elements = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (elements.length === 0) { e.preventDefault(); return; }

      e.preventDefault();
      const idx = elements.indexOf(active as HTMLElement);

      if (e.shiftKey) {
        elements[idx <= 0 ? elements.length - 1 : idx - 1].focus();
      } else {
        elements[idx >= elements.length - 1 ? 0 : idx + 1].focus();
      }
    };

    const handleFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement;
      if (!container.contains(target)) {
        // Don't steal focus from search bars, dropdowns, popovers portalées à body,
        // ou tout overlay qui opt-out via `data-focus-trap-ignore`.
        if (target.closest('.smart-search-bar, .search-suggestions-dropdown, [role="dialog"], [data-radix-popper-content-wrapper], .ai-cmd-popover, [data-focus-trap-ignore]')) {
          return;
        }
        container.querySelector<HTMLElement>(FOCUSABLE)?.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('focusin', handleFocusIn);

    return () => {
      cancelled = true;
      document.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('focusin', handleFocusIn);
    };
  }, []);

  const teardown = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    previousFocus.current?.focus();
    previousFocus.current = null;
  }, []);

  // Callback ref: fires when DOM element is attached/detached
  const callbackRef = useCallback((node: HTMLDivElement | null) => {
    containerRef.current = node;
    if (node && active) {
      teardown(); // clean any previous
      cleanupRef.current = setup(node);
    } else if (!node) {
      teardown();
    }
  }, [active, setup, teardown]);

  // Also handle active changing while node is already mounted
  useEffect(() => {
    if (active && containerRef.current) {
      teardown();
      cleanupRef.current = setup(containerRef.current);
    } else if (!active) {
      teardown();
    }
    return teardown;
  }, [active, setup, teardown]);

  return callbackRef;
}
