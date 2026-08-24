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

// Keep this import: it is the only path that augments `Assertion<HTMLElement>`
// with the jest-dom matcher types — without it, every `.toBeInTheDocument()` /
// `.toHaveClass()` call type-errors. The runtime `expect.extend(matchers)` it
// also performs doesn't survive into vitest 4's runner expect (see audit
// 2026-05-13 below), so we do it again explicitly two lines down.
import "@testing-library/jest-dom/vitest";
import React from 'react';
import { expect, vi, beforeEach } from 'vitest';
import * as jestDomMatchers from '@testing-library/jest-dom/matchers';

// Vitest 4 compat (2026-05-13): the `@testing-library/jest-dom/vitest`
// side-effect entrypoint above calls `expect.extend(matchers)` against the
// vitest package's expect, but with vitest 4 that extension doesn't survive
// into the runner's test-scoped expect — every `toBeInTheDocument` /
// `toHaveClass` call fails with "Invalid Chai property". Re-extending
// explicitly here, from the same module that the runner loads, works.
expect.extend(jestDomMatchers as unknown as Parameters<typeof expect.extend>[0]);
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

// Test-only: bundle all locales synchronously so component tests that call
// `i18n.changeLanguage('en' | 'es')` get the actual translated text
// instead of falling back to FR. Production code uses lazy chunks via
// `src/i18n/index.ts` (Vite glob + custom backend); that path is bypassed
// in tests because setup.ts initializes i18n first and the runtime module
// short-circuits on `isInitialized`.
const localeModules = import.meta.glob('../i18n/locales/*/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Record<string, unknown>>;

const NS = ['common', 'inbox', 'drafts', 'compose', 'settings', 'search', 'deepfocus', 'onboarding', 'agents', 'calendar', 'errors', 'support', 'availability'];
const TEST_LANGS = ['fr', 'en', 'es'];

const resources: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, mod] of Object.entries(localeModules)) {
  const m = path.match(/locales\/([a-z]{2})\/(\w+)\.json$/);
  if (!m) continue;
  const [, lng, ns] = m;
  if (!resources[lng]) resources[lng] = {};
  resources[lng][ns] = mod;
}

i18n
  .use(initReactI18next)
  .init({
    lng: 'fr',
    fallbackLng: 'fr',
    supportedLngs: TEST_LANGS,
    ns: NS,
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    resources,
    initAsync: false,
  });

// Create localStorage mock
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value.toString(); },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    get length() { return Object.keys(store).length; },
    key: (index: number) => Object.keys(store)[index] || null,
  };
})();

// Apply mock if localStorage is not available or override it for tests
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true });

// Clear localStorage before each test
beforeEach(() => {
  localStorageMock.clear();
});

// Mock IntersectionObserver (not available in jsdom)
class MockIntersectionObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor() {}
}
Object.defineProperty(globalThis, 'IntersectionObserver', {
  value: MockIntersectionObserver,
  writable: true,
});

// Mock HTMLElement.scrollIntoView (not available in jsdom)
Element.prototype.scrollIntoView = vi.fn();

// Mock react-virtualized-auto-sizer which requires actual dimensions
vi.mock('react-virtualized-auto-sizer', () => ({
  default: ({ children }: { children: (size: { height: number; width: number }) => React.ReactNode }) =>
    children({ height: 600, width: 400 }),
}));

// Mock react-window for testing
vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount, itemSize }: {
    children: (props: { index: number; style: React.CSSProperties }) => React.ReactNode;
    itemCount: number;
    itemSize: number;
    height: number;
    width: number;
    className?: string;
  }) => {
    const items = Array.from({ length: itemCount }, (_, index) =>
      React.createElement('li', { key: index, style: { height: itemSize } },
        children({ index, style: { height: itemSize } })
      )
    );
    return React.createElement('ul', { style: { height: itemCount * itemSize } }, items);
  },
}));
