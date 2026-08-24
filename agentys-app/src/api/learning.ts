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

import i18n from '../i18n'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'
import type { DraftRuleItem, LearnedCategory } from '../types/training'

export async function fetchDraftRules(): Promise<DraftRuleItem[]> {
  const response = await fetch(`${API_URL}/api/learning/rules`, {
    headers: getAuthHeaders(),
  })

  if (!response.ok) return []

  const data = await response.json() as { rules?: DraftRuleItem[] }
  return Array.isArray(data.rules) ? data.rules : []
}

export async function fetchUserLearningCategories(): Promise<LearnedCategory[]> {
  const rules = await fetchDraftRules()

  return [
    {
      id: 'draft-rules',
      // Resolved at call time (not module load) so a language switch is honoured.
      name: i18n.t('common:learning_draft_rules_title'),
      description: i18n.t('common:learning_draft_rules_desc'),
      count: rules.length,
      items: rules,
    },
  ]
}
