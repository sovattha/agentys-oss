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

import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { ContactStyleEditor } from './ContactStyleEditor';
import type { ContactStyleProfile } from '../types/training';
import type { ComponentProps } from 'react';

type EditorProps = ComponentProps<typeof ContactStyleEditor>;

// i18n is initialised to `fr` by src/__tests__/setup.ts, so label/button text
// renders in French ("Modifier", "Enregistrer", "Salutation", …).

function makeContact(over: Partial<ContactStyleProfile> = {}): ContactStyleProfile {
  return {
    email: 'alexandre.simon@hotmail.com',
    formality_override: 'mixed',
    preferred_greeting: 'Bonjour {first_name},',
    preferred_closing: null,
    langue_variante: 'fr-CA',
    langue: 'français',
    nickname: 'Alexandre',
    ...over,
  };
}

function expandCard() {
  // Clicking the email text bubbles to the header toggle button.
  fireEvent.click(screen.getByText('alexandre.simon@hotmail.com'));
}

describe('ContactStyleEditor — greeting↔nickname chip + re-sync', () => {
  let onSave: Mock<EditorProps['onSave']>;
  let onDelete: Mock<EditorProps['onDelete']>;

  beforeEach(() => {
    onSave = vi.fn<EditorProps['onSave']>().mockResolvedValue({});
    onDelete = vi.fn<EditorProps['onDelete']>();
  });

  it('read view renders the recipient name inside the greeting as a linked chip', () => {
    const { container } = render(
      <ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />
    );
    expandCard();

    const chip = container.querySelector('.greeting-name-chip');
    expect(chip).toBeInTheDocument();
    // The chip carries the resolved nickname, not a frozen literal.
    expect(chip).toHaveTextContent('Alexandre');
    // …and the greeting still reads naturally around it.
    const greetingRow = chip!.closest('.contact-card-view-row--content');
    expect(greetingRow).toHaveTextContent('Bonjour Alexandre,');
  });

  it('legacy literal greeting ("Bonjour Alexandre,") is still chipped in the read view', () => {
    const { container } = render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: 'Bonjour Alexandre,' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    expect(container.querySelector('.greeting-name-chip')).toHaveTextContent('Alexandre');
  });

  it('editing the nickname re-syncs the greeting instead of freezing the old name', () => {
    render(<ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    fireEvent.click(screen.getByRole('button', { name: 'Modifier' }));

    // Greeting input opens showing the expanded form…
    const greetingInput = screen.getByDisplayValue('Bonjour Alexandre,');
    const nicknameInput = screen.getByDisplayValue('Alexandre');

    // Change ONLY the nickname — the greeting must follow, not freeze.
    fireEvent.change(nicknameInput, { target: { value: 'Alex' } });
    expect(greetingInput).toHaveValue('Bonjour Alex,');
  });

  it('saves the greeting as a token template (not the stale literal) after a nickname change', async () => {
    render(<ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    fireEvent.click(screen.getByRole('button', { name: 'Modifier' }));

    fireEvent.change(screen.getByDisplayValue('Alexandre'), { target: { value: 'Alex' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const payload = onSave.mock.calls[0][0];
    expect(payload.contact_email).toBe('alexandre.simon@hotmail.com');
    expect(payload.nickname).toBe('Alex');
    // The greeting persists tokenised, so it stays bound to the new nickname.
    expect(payload.preferred_greeting).toBe('Bonjour {first_name},');
    expect(payload.formality_locked).toBe(true);
  });

  it('migrates a legacy literal greeting to a token template on edit + nickname change', async () => {
    render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: 'Bonjour Alexandre,' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    fireEvent.click(screen.getByRole('button', { name: 'Modifier' }));

    // Seed tokenised the literal → changing the nickname re-syncs the greeting.
    const greetingInput = screen.getByDisplayValue('Bonjour Alexandre,');
    fireEvent.change(screen.getByDisplayValue('Alexandre'), { target: { value: 'Alex' } });
    expect(greetingInput).toHaveValue('Bonjour Alex,');

    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));
    expect(onSave.mock.calls[0][0].preferred_greeting).toBe('Bonjour {first_name},');
  });

  it('keeps typing lossless — a trailing space after the name is not eaten', () => {
    render(<ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    fireEvent.click(screen.getByRole('button', { name: 'Modifier' }));

    const greetingInput = screen.getByDisplayValue('Bonjour Alexandre,');
    // Build a greeting with text after the name — the raw draft must survive
    // verbatim even though the name matches the nickname (no whitespace eat).
    fireEvent.change(greetingInput, { target: { value: 'Bonjour Alexandre et toi,' } });
    expect(greetingInput).toHaveValue('Bonjour Alexandre et toi,');

    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));
    // Persisted tokenised, with the trailing text preserved.
    expect(onSave.mock.calls[0][0].preferred_greeting).toBe('Bonjour {first_name} et toi,');
  });

  it('does not chip an unrelated name that is not the nickname', () => {
    const { container } = render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: 'Bonjour Marie,', nickname: 'Alexandre' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    // "Marie" isn't the nickname "Alexandre", so it stays plain text.
    expect(container.querySelector('.greeting-name-chip')).toBeNull();
    const row = within(container.querySelector('.contact-card-view') as HTMLElement);
    expect(row.getByText('Bonjour Marie,')).toBeInTheDocument();
  });
});

describe('ContactStyleEditor — trailing-punctuation tightening (chip)', () => {
  const onSave = vi.fn().mockResolvedValue({});
  const onDelete = vi.fn();

  it('tightens the chip when punctuation immediately follows the name', () => {
    const { container } = render(
      <ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />
    );
    expandCard();
    // "Bonjour Alexandre," → comma hugs the name.
    expect(container.querySelector('.greeting-name-chip')).toHaveClass('greeting-name-chip--tight-end');
  });

  it('does NOT tighten when text (not punctuation) follows the name', () => {
    const { container } = render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: 'Bonjour Alexandre et toi,' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    const chip = container.querySelector('.greeting-name-chip');
    expect(chip).toBeInTheDocument();
    expect(chip).not.toHaveClass('greeting-name-chip--tight-end');
  });
});

describe('ContactStyleEditor — language/variant display normalisation', () => {
  const onSave = vi.fn().mockResolvedValue({});
  const onDelete = vi.fn();

  it('normalises a learned lowercase language to the picker label', () => {
    // Isolate the language (no variant) so the row value is the language alone.
    render(<ContactStyleEditor contacts={[makeContact({ langue: 'français', langue_variante: null })]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    // Stored "français" (pipeline) renders as "Français" (picker canonical),
    // never the bare lowercase value.
    expect(screen.getByText('Français')).toBeInTheDocument();
    expect(screen.queryByText('français')).toBeNull();
  });

  it('renders a variant code with its country, matching the picker', () => {
    // Isolate the variant (no language) so the row value is the variant alone.
    render(<ContactStyleEditor contacts={[makeContact({ langue: null, langue_variante: 'fr-CA' })]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    expect(screen.getByText('Québec (fr-CA)')).toBeInTheDocument();
  });

  it('falls back to capitalised free-text for an unknown language', () => {
    render(<ContactStyleEditor contacts={[makeContact({ langue: 'klingon', langue_variante: null })]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    expect(screen.getByText('Klingon')).toBeInTheDocument();
  });

  it('merges language and regional variant into a single row value', () => {
    // Both set → one combined value, not two separate label→value pairs.
    render(<ContactStyleEditor contacts={[makeContact({ langue: 'français', langue_variante: 'fr-CA' })]} onSave={onSave} onDelete={onDelete} />);
    expandCard();
    expect(screen.getByText('Français · Québec (fr-CA)')).toBeInTheDocument();
    // The variant is no longer surfaced as its own standalone text node.
    expect(screen.queryByText('Québec (fr-CA)')).toBeNull();
  });
});

describe('ContactStyleEditor — nickname-row dedup vs greeting', () => {
  const onSave = vi.fn().mockResolvedValue({});
  const onDelete = vi.fn();

  // The standalone "Surnom" row's label is unique to that row in the read view.
  const NICK_LABEL = 'Surnom';

  it('hides the standalone nickname row when the greeting already chips it', () => {
    const { container } = render(
      <ContactStyleEditor contacts={[makeContact()]} onSave={onSave} onDelete={onDelete} />
    );
    expandCard();
    // Greeting "Bonjour {first_name}," surfaces "Alexandre" as a chip…
    expect(container.querySelector('.greeting-name-chip')).toHaveTextContent('Alexandre');
    // …so the redundant nickname row is gone.
    expect(screen.queryByText(NICK_LABEL)).toBeNull();
  });

  it('keeps the nickname row when the greeting does NOT contain the nickname', () => {
    render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: 'Bonjour Marie,', nickname: 'Alexandre' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    expect(screen.getByText(NICK_LABEL)).toBeInTheDocument();
  });

  it('keeps the nickname row when there is no greeting at all', () => {
    render(
      <ContactStyleEditor
        contacts={[makeContact({ preferred_greeting: null, nickname: 'Alexandre' })]}
        onSave={onSave}
        onDelete={onDelete}
      />
    );
    expandCard();
    expect(screen.getByText(NICK_LABEL)).toBeInTheDocument();
  });
});
