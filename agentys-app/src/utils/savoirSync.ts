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

import type { SavoirEntry } from '../types/training';
import {
  type KnowledgeEntry as KnowledgeEntryAPI,
  getKnowledgeEntries,
  createKnowledgeEntry,
  updateKnowledgeEntry,
  deleteKnowledgeEntry,
} from '../services/api';

/**
 * Sync savoir entries from training data to the KnowledgeEntry SQLite table.
 * Creates missing entries, updates changed ones, deletes orphans.
 *
 * Delete semantics:
 *  - FAQ category: delete ANY orphan (regardless of source) — the UI is the
 *    source of truth because PillarSavoir now loads FAQs from SQLite on mount.
 *  - Other categories: only delete orphans whose source is "manual" — protects
 *    entries created by background agents / imports that the UI doesn't show.
 */
export async function syncSavoirToKnowledgeEntries(savoir: SavoirEntry[]): Promise<void> {
  const existing: KnowledgeEntryAPI[] = await getKnowledgeEntries();
  const existingByTitle = new Map(existing.map(e => [e.title, e]));
  const savoirTitles = new Set(savoir.filter(s => s.question.trim()).map(s => s.question.trim()));

  for (const entry of savoir) {
    const title = entry.question.trim();
    if (!title) continue;
    const match = existingByTitle.get(title);
    if (match) {
      if (match.content !== entry.answer || match.category !== entry.category) {
        await updateKnowledgeEntry(match.id, { content: entry.answer, category: entry.category });
      }
    } else {
      await createKnowledgeEntry({ title, content: entry.answer, category: entry.category });
    }
  }

  for (const entry of existing) {
    if (savoirTitles.has(entry.title)) continue;
    const isFaq = (entry.category || '').toUpperCase() === 'FAQ';
    if (isFaq || entry.source === 'manual') {
      await deleteKnowledgeEntry(entry.id);
    }
  }
}
