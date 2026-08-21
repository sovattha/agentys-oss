/**
 * Mock Data for Agentys Drafts E2E Tests
 *
 * These mocks match the actual /api/drafts endpoint format.
 */

// Draft record format matching backend API
export interface DraftRecord {
  id: string
  email_id: string
  email_sender: string
  email_sender_name: string | null
  email_subject: string
  email_body: string | null
  draft_body: string
  draft_v1: string | null
  critique: string | null
  status: 'pending' | 'validated' | 'rejected' | 'modified'
  created_at: string
  updated_at: string
}

// Response format from /api/drafts
export interface DraftsResponse {
  drafts: DraftRecord[]
  pending_count: number
}

// Helper to generate dates
const daysAgo = (days: number): string => {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString()
}

/**
 * Sample drafts matching real app data structure
 */
export const mockDrafts: DraftRecord[] = [
  {
    id: 'draft-1',
    email_id: 'email-1',
    email_sender: 'marie.dupont@example.com',
    email_sender_name: 'Marie Dupont',
    email_subject: 'Rapport trimestriel Q4 2025',
    email_body: 'Bonjour, veuillez trouver ci-joint le rapport...',
    draft_body: 'Bonjour Marie, Merci pour ce rapport détaillé...',
    draft_v1: 'Merci pour le rapport.',
    critique: 'La réponse pourrait être plus détaillée.',
    status: 'pending',
    created_at: daysAgo(0),
    updated_at: daysAgo(0),
  },
  {
    id: 'draft-2',
    email_id: 'email-2',
    email_sender: 'pierre.martin@example.com',
    email_sender_name: 'Pierre Martin',
    email_subject: 'Re: Réunion projet Alpha',
    email_body: 'Parfait pour mardi 14h.',
    draft_body: 'Parfait, je serai présent mardi à 14h.',
    draft_v1: null,
    critique: null,
    status: 'validated',
    created_at: daysAgo(1),
    updated_at: daysAgo(1),
  },
  {
    id: 'draft-3',
    email_id: 'email-3',
    email_sender: 'jean.lefevre@client.com',
    email_sender_name: 'Jean Lefèvre',
    email_subject: 'Demande de devis urgent',
    email_body: 'Suite à notre conversation...',
    draft_body: 'Bonjour M. Lefèvre, voici notre proposition...',
    draft_v1: 'Voici le devis.',
    critique: 'Ton trop direct, ajouter formules de politesse.',
    status: 'pending',
    created_at: daysAgo(2),
    updated_at: daysAgo(2),
  },
  {
    id: 'draft-4',
    email_id: 'email-4',
    email_sender: 'support@saas.com',
    email_sender_name: 'Support SaaS',
    email_subject: 'Ticket #12345 résolu',
    email_body: 'Votre demande a été traitée.',
    draft_body: 'Merci pour votre réactivité.',
    draft_v1: null,
    critique: null,
    status: 'validated',
    created_at: daysAgo(3),
    updated_at: daysAgo(3),
  },
  {
    id: 'draft-5',
    email_id: 'email-5',
    email_sender: 'alice.bernard@partner.com',
    email_sender_name: 'Alice Bernard',
    email_subject: 'Partenariat stratégique',
    email_body: 'Suite à notre rencontre...',
    draft_body: 'Bonjour Alice, nous sommes très intéressés...',
    draft_v1: null,
    critique: null,
    status: 'rejected',
    created_at: daysAgo(4),
    updated_at: daysAgo(4),
  },
]

/**
 * Mock response for /api/drafts
 */
export const mockDraftsResponse: DraftsResponse = {
  drafts: mockDrafts,
  pending_count: mockDrafts.filter(d => d.status === 'pending').length,
}

/**
 * Empty drafts response
 */
export const mockEmptyDrafts: DraftsResponse = {
  drafts: [],
  pending_count: 0,
}

/**
 * Health check response
 */
export const mockHealthResponse = {
  status: 'ok',
  version: '1.0.0',
}

/**
 * Wizard status - onboarding complete
 */
export const mockWizardStatus = {
  onboarding_complete: true,
  has_email_provider: true,
  has_llm_configured: true,
}
