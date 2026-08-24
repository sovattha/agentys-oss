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

import { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { CommandPalette, type CommandAction } from './CommandPalette';
import { useSharedLabelsData } from '../contexts/LabelsContext';
import { useSnippets } from '../hooks/useSnippets';
import { apiClient } from '../services/api';
import { getLabelDisplayName } from '../types/labels';
import type { Snippet } from '../types/snippets';

interface ContactHit {
  name: string;
  email: string;
}

interface CommandPaletteContainerProps {
  isOpen: boolean;
  onClose: () => void;
  /** Static, always-present actions (email actions + tools) built by the parent. */
  baseActions: CommandAction[];
  accountId?: number;
  /** Filter the inbox to a label. */
  onFilterLabel: (labelName: string) => void;
  /** Open a new message addressed to a contact. */
  onComposeTo: (email: string, name?: string) => void;
  /** Open a new message pre-filled from a snippet. */
  onUseSnippet: (snippet: Snippet) => void;
}

// The contacts endpoint is search-only (there is no "list all"), so contacts
// surface only once the user types. Labels and snippets are small finite lists
// and are always present in the palette.
const CONTACT_MIN_CHARS = 2;
const CONTACT_LIMIT = 6;
const CONTACT_DEBOUNCE_MS = 220;

/**
 * Data layer for the command palette. Mounted lazily on first open (so its
 * snippet fetch is deferred) and rendered inside <LabelsProvider> so it can
 * read labels from context without a second fetch. Turns labels / snippets /
 * contacts into CommandActions and merges them with the parent's base actions.
 */
export function CommandPaletteContainer({
  isOpen, onClose, baseActions, accountId, onFilterLabel, onComposeTo, onUseSnippet,
}: CommandPaletteContainerProps) {
  const { t } = useTranslation('search');
  const { labels } = useSharedLabelsData();
  const { snippets } = useSnippets(accountId);

  const [query, setQuery] = useState('');
  const [contacts, setContacts] = useState<ContactHit[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const fetchTokenRef = useRef(0);

  // Clear the contact search when the palette closes so a stale list doesn't
  // flash on the next open. CommandPalette resets its own input on open.
  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setContacts([]);
      setContactsLoading(false);
    }
  }, [isOpen]);

  // Debounced contact autocomplete. The token guard suppresses out-of-order
  // responses; `cancelled` blocks state writes after the effect tears down.
  useEffect(() => {
    const q = query.trim();
    if (q.length < CONTACT_MIN_CHARS) {
      setContacts([]);
      setContactsLoading(false);
      return;
    }
    let cancelled = false;
    setContactsLoading(true);
    const handle = setTimeout(() => {
      const token = ++fetchTokenRef.current;
      apiClient
        .searchContacts(q, accountId != null ? String(accountId) : undefined, { limit: CONTACT_LIMIT })
        .then(hits => {
          if (cancelled || token !== fetchTokenRef.current) return;
          // A malformed response (error JSON, proxy page) must not crash the
          // palette render — contacts.map() below assumes an array.
          setContacts(Array.isArray(hits) ? hits : []);
        })
        .catch(() => {
          if (cancelled || token !== fetchTokenRef.current) return;
          setContacts([]);
        })
        .finally(() => {
          if (!cancelled && token === fetchTokenRef.current) setContactsLoading(false);
        });
    }, CONTACT_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [query, accountId]);

  const labelActions = useMemo<CommandAction[]>(() =>
    labels.map(label => ({
      id: `label-${label.name}`,
      label: getLabelDisplayName(label.name),
      section: t('cmd_section_labels'),
      keywords: label.name,
      action: () => onFilterLabel(label.name),
    })),
    [labels, t, onFilterLabel],
  );

  const snippetActions = useMemo<CommandAction[]>(() =>
    snippets.map(snippet => ({
      id: `snippet-${snippet.id}`,
      label: snippet.name,
      section: t('cmd_section_snippets'),
      sublabel: snippet.subject || undefined,
      keywords: [snippet.subject, snippet.category].filter(Boolean).join(' ') || undefined,
      action: () => onUseSnippet(snippet),
    })),
    [snippets, t, onUseSnippet],
  );

  const contactActions = useMemo<CommandAction[]>(() =>
    contacts.map(contact => ({
      id: `contact-${contact.email}`,
      label: contact.name || contact.email,
      section: t('cmd_section_contacts'),
      sublabel: contact.name ? contact.email : undefined,
      keywords: contact.email,
      action: () => onComposeTo(contact.email, contact.name || undefined),
    })),
    [contacts, t, onComposeTo],
  );

  const actions = useMemo<CommandAction[]>(
    () => [...baseActions, ...labelActions, ...snippetActions, ...contactActions],
    [baseActions, labelActions, snippetActions, contactActions],
  );

  // Only "searching" once the query is long enough to trigger a fetch, so short
  // no-match queries still show the normal empty state.
  const searching = contactsLoading && query.trim().length >= CONTACT_MIN_CHARS;

  return (
    <CommandPalette
      isOpen={isOpen}
      onClose={onClose}
      actions={actions}
      onQueryChange={setQuery}
      searching={searching}
    />
  );
}
