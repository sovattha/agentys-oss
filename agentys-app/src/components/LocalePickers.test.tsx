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

import { describe, it, expect, vi, afterEach, type Mock } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LanguagePicker } from './LocalePickers';

// Keys are returned verbatim; the picker takes its labels via props anyway.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

/**
 * Regression: editing a per-contact writing style closed the whole Settings
 * panel "tout seul". The Training/Settings modal closes on a document-level
 * Escape keydown, and its listener is registered first (on mount). The
 * language/variant dropdown only called setOpen(false) on Escape — it did NOT
 * stop the event — so the modal's handler still fired and closed everything.
 * The dropdown now intercepts Escape in the capture phase and stops it.
 */
describe('LocalePickers — Escape stays inside the open dropdown', () => {
  let modalClose: Mock<() => void>;
  let modalHandler: (e: KeyboardEvent) => void;

  // Mimic the modal's document keydown listener: bubble phase, installed
  // before the picker is ever opened (just like TrainingPage on mount).
  function installModalEscape() {
    modalClose = vi.fn<() => void>();
    modalHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') modalClose();
    };
    document.addEventListener('keydown', modalHandler);
  }

  afterEach(() => {
    if (modalHandler) document.removeEventListener('keydown', modalHandler);
  });

  it('closes only the open dropdown on Escape, leaving the modal open', () => {
    installModalEscape();
    render(
      <LanguagePicker value="" onChange={() => {}} autoLabel="auto" ariaLabel="Language" />
    );

    const trigger = screen.getByRole('button', { name: 'Language' });
    fireEvent.click(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');

    fireEvent.keyDown(trigger, { key: 'Escape' });

    // Dropdown collapsed…
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    // …and the surrounding modal was never asked to close.
    expect(modalClose).not.toHaveBeenCalled();
  });

  it('still lets Escape reach the modal when the dropdown is closed', () => {
    installModalEscape();
    render(
      <LanguagePicker value="" onChange={() => {}} autoLabel="auto" ariaLabel="Language" />
    );

    const trigger = screen.getByRole('button', { name: 'Language' });
    // No capture interceptor is installed while closed, so the modal keeps its
    // normal "Escape closes Settings" behaviour.
    fireEvent.keyDown(trigger, { key: 'Escape' });

    expect(modalClose).toHaveBeenCalledTimes(1);
  });
});
