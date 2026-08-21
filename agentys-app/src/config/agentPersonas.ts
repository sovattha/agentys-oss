/**
 * Agent Personas — central registry mapping backend agent_id to UI identity.
 *
 * Each agent in the draft pipeline (DrafterAgent, CriticAgent, etc.) gets
 * a human name, role description, color accent, and SVG avatar path.
 *
 * `role`/`tagline` hold the French fallback strings; `roleKey`/`taglineKey`
 * point into the `agents` i18n namespace and must be resolved at render time
 * by consumers via `t(roleKey, role)` (module-level constants must not bake
 * translations at import time — the language can switch at runtime).
 *
 * Issue #160 (Epic #134, Sprint 4).
 */

export interface AgentPersona {
  id: string
  name: string
  role: string
  roleKey: string
  color: string
  initials: string
  tagline: string
  taglineKey: string
}

export const AGENT_PERSONAS: Record<string, AgentPersona> = {
  drafter: {
    id: 'drafter',
    name: 'Léa',
    role: 'Rédactrice',
    roleKey: 'persona_role_drafter',
    color: '#3b82f6',
    initials: 'LR',
    tagline: 'Rédige la première version du brouillon',
    taglineKey: 'persona_tagline_drafter',
  },
  critic: {
    id: 'critic',
    name: 'Marc',
    role: 'Relecteur',
    roleKey: 'persona_role_critic',
    color: '#f59e0b',
    initials: 'MR',
    tagline: 'Évalue la qualité et propose des améliorations',
    taglineKey: 'persona_tagline_critic',
  },
  classifier: {
    id: 'classifier',
    name: 'Zoé',
    role: 'Trieuse',
    roleKey: 'persona_role_classifier',
    color: '#8b5cf6',
    initials: 'ZT',
    tagline: 'Classifie les emails par catégorie et priorité',
    taglineKey: 'persona_tagline_classifier',
  },
  prioritization: {
    id: 'prioritization',
    name: 'Hugo',
    role: 'Planificateur',
    roleKey: 'persona_role_prioritization',
    color: '#10b981',
    initials: 'HP',
    tagline: 'Évalue l\'urgence et l\'importance de chaque email',
    taglineKey: 'persona_tagline_prioritization',
  },
  context_analyzer: {
    id: 'context_analyzer',
    name: 'Nina',
    role: 'Analyste',
    roleKey: 'persona_role_context_analyzer',
    color: '#ec4899',
    initials: 'NA',
    tagline: 'Analyse le contexte et l\'historique de la conversation',
    taglineKey: 'persona_tagline_context_analyzer',
  },
  task_extractor: {
    id: 'task_extractor',
    name: 'Théo',
    role: 'Extracteur',
    roleKey: 'persona_role_task_extractor',
    color: '#14b8a6',
    initials: 'TE',
    tagline: 'Identifie les tâches et engagements dans les emails',
    taglineKey: 'persona_tagline_task_extractor',
  },
  sensitive_data_detector: {
    id: 'sensitive_data_detector',
    name: 'Clara',
    role: 'Gardienne',
    roleKey: 'persona_role_sensitive_data_detector',
    color: '#ef4444',
    initials: 'CG',
    tagline: 'Détecte les données sensibles et personnelles',
    taglineKey: 'persona_tagline_sensitive_data_detector',
  },
  specialty: {
    id: 'specialty',
    name: 'Expert',
    role: 'Spécialiste',
    roleKey: 'persona_role_specialty',
    color: '#6366f1',
    initials: 'ES',
    tagline: 'Agent spécialisé dans un domaine métier',
    taglineKey: 'persona_tagline_specialty',
  },
  account: {
    id: 'account',
    name: 'Alix',
    role: 'Comptes',
    roleKey: 'persona_role_account',
    color: '#0ea5e9',
    initials: 'AC',
    tagline: 'Gère les demandes liées aux comptes utilisateurs',
    taglineKey: 'persona_tagline_account',
  },
  postprocessor: {
    id: 'postprocessor',
    name: 'Iris',
    role: 'Qualité',
    roleKey: 'persona_role_postprocessor',
    color: '#f97316',
    initials: 'IQ',
    tagline: 'Nettoie et affine le brouillon final',
    taglineKey: 'persona_tagline_postprocessor',
  },
}

/**
 * Get persona by agent id, with fallback for unknown agents.
 */
export function getAgentPersona(agentId: string): AgentPersona {
  return AGENT_PERSONAS[agentId] ?? {
    id: agentId,
    name: agentId,
    role: 'Agent',
    roleKey: 'persona_role_generic',
    color: '#6b7280',
    initials: agentId.slice(0, 2).toUpperCase(),
    tagline: '',
    taglineKey: '',
  }
}
