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

/**
 * Types liés aux spécialités (réel-estate-qc, legal-qc, …) exposées par le
 * moteur `SpecialtyEngine` côté backend.
 *
 * Retourné par `POST /api/refine-text` quand `use_specialty=true` et qu'une
 * spécialité active match les notes de l'utilisateur.
 */

export type RiskLevel = 'low' | 'medium' | 'high'

export type SpecialtyWarning =
  | 'no_active_specialty'   // use_specialty=true mais aucune spécialité activée dans les paramètres
  | 'specialty_unavailable' // spécialité active introuvable sur disque (fichiers supprimés)
  | 'classification_error'  // erreur technique pendant la classification
  | 'plan_empty_fallback'   // Sonnet a renvoyé un plan vide, fallback sur injection directe
  | 'plan_failed_fallback'  // Sonnet a planté, fallback sur injection directe

/**
 * Match complet retourné par SpecialtyEngine après classification réussie.
 * Les champs `applied_sources` et `plan_preview` ne sont présents que si
 * Sonnet a produit un plan exploitable (cas nominal expert-mode).
 */
export interface SpecialtyMatchInfo {
  specialty_id: string
  specialty_name: string
  category: string
  expert_ids: string[]
  expert_names: string[]
  risk_level: RiskLevel
  confidence: number
  keyword_hits: number
  applied_sources?: string[]
  plan_preview?: string
  warning?: SpecialtyWarning
}

/**
 * Warning seul (pas de match). Retourné quand `use_specialty=true` mais
 * la classification n'a rien à exploiter.
 */
export interface SpecialtyWarningInfo {
  warning: SpecialtyWarning
}

/**
 * Union pratique : soit un match (avec éventuellement warning de fallback),
 * soit uniquement un warning.
 */
export type SpecialtyInfo = SpecialtyMatchInfo | SpecialtyWarningInfo

/**
 * Type guard pour distinguer un match complet d'un simple warning.
 */
export function isSpecialtyMatch(info: SpecialtyInfo): info is SpecialtyMatchInfo {
  return 'specialty_id' in info
}
