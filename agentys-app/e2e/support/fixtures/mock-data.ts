/**
 * Mock Data Fixtures for Agentys E2E Tests
 *
 * Realistic mock data for testing email functionality.
 */

// Type definitions inlined to avoid path issues
interface Attachment {
  id: string;
  filename: string;
  size: number;
  content_type: string;
}

interface Email {
  id: string;
  sender: string;
  sender_name: string | null;
  subject: string;
  received_at: string;
  has_attachments: boolean;
  conversation_id: string | null;
  is_read: boolean;
  body_preview?: string;
}

interface EmailDetail extends Email {
  body: string;
  body_html?: string;
  to?: string[];
  cc?: string[];
  attachments?: Attachment[];
}

// Helper to generate dates relative to now
const daysAgo = (days: number): string => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString();
};

const hoursAgo = (hours: number): string => {
  const date = new Date();
  date.setHours(date.getHours() - hours);
  return date.toISOString();
};

/**
 * Sample attachments
 */
export const mockAttachments: Attachment[] = [
  {
    id: 'att-1',
    filename: 'rapport-Q4-2025.pdf',
    size: 2458624,
    content_type: 'application/pdf',
  },
  {
    id: 'att-2',
    filename: 'presentation.pptx',
    size: 5242880,
    content_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  },
  {
    id: 'att-3',
    filename: 'photo.jpg',
    size: 1048576,
    content_type: 'image/jpeg',
  },
];

/**
 * Sample emails for list view
 */
export const mockEmails: Email[] = [
  {
    id: 'email-1',
    sender: 'marie.dupont@example.com',
    sender_name: 'Marie Dupont',
    subject: 'Rapport trimestriel Q4 2025',
    received_at: hoursAgo(1),
    has_attachments: true,
    conversation_id: 'conv-1',
    is_read: false,
    body_preview: 'Bonjour, veuillez trouver ci-joint le rapport trimestriel Q4 2025. Les résultats sont très encourageants...',
  },
  {
    id: 'email-2',
    sender: 'pierre.martin@example.com',
    sender_name: 'Pierre Martin',
    subject: 'Re: Réunion projet Alpha',
    received_at: hoursAgo(3),
    has_attachments: false,
    conversation_id: 'conv-2',
    is_read: false,
    body_preview: 'Parfait pour mardi 14h. Je réserve la salle de conférence B.',
  },
  {
    id: 'email-3',
    sender: 'support@saas-platform.com',
    sender_name: 'Support SaaS Platform',
    subject: 'Votre ticket #12345 a été résolu',
    received_at: hoursAgo(5),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    body_preview: 'Votre demande concernant la facturation a été traitée. Le remboursement sera effectué sous 5 jours...',
  },
  {
    id: 'email-4',
    sender: 'newsletter@tech-news.com',
    sender_name: 'Tech News Weekly',
    subject: 'Les tendances IA de 2026',
    received_at: daysAgo(1),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    body_preview: 'Cette semaine : les dernières avancées en intelligence artificielle, le nouveau framework qui fait sensation...',
  },
  {
    id: 'email-5',
    sender: 'jean.lefevre@client.com',
    sender_name: 'Jean Lefèvre',
    subject: 'Demande de devis urgent',
    received_at: daysAgo(1),
    has_attachments: true,
    conversation_id: 'conv-5',
    is_read: false,
    body_preview: 'Bonjour, suite à notre conversation téléphonique, pourriez-vous nous envoyer un devis pour...',
  },
  {
    id: 'email-6',
    sender: 'rh@entreprise.com',
    sender_name: 'Service RH',
    subject: 'Rappel: Entretien annuel',
    received_at: daysAgo(2),
    has_attachments: true,
    conversation_id: null,
    is_read: true,
    body_preview: 'Votre entretien annuel est prévu le 15 février. Merci de préparer votre auto-évaluation...',
  },
  {
    id: 'email-7',
    sender: 'alice.bernard@partner.com',
    sender_name: 'Alice Bernard',
    subject: 'Partenariat stratégique - Proposition',
    received_at: daysAgo(3),
    has_attachments: true,
    conversation_id: 'conv-7',
    is_read: false,
    body_preview: 'Suite à notre rencontre au salon, je vous envoie notre proposition de partenariat...',
  },
  {
    id: 'email-8',
    sender: 'no-reply@github.com',
    sender_name: 'GitHub',
    subject: '[agentys/agentys] Pull request merged: Fix memory leak',
    received_at: daysAgo(4),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    body_preview: 'The pull request #234 has been merged into main by @developer.',
  },
  {
    id: 'email-9',
    sender: 'facturation@fournisseur.com',
    sender_name: 'Comptabilité Fournisseur',
    subject: 'Facture #INV-2026-0042',
    received_at: daysAgo(5),
    has_attachments: true,
    conversation_id: null,
    is_read: true,
    body_preview: 'Veuillez trouver ci-joint la facture pour les services du mois de janvier 2026.',
  },
  {
    id: 'email-10',
    sender: 'thomas.garcia@example.com',
    sender_name: 'Thomas Garcia',
    subject: 'Feedback sur la démo',
    received_at: daysAgo(6),
    has_attachments: false,
    conversation_id: 'conv-10',
    is_read: true,
    body_preview: 'La démo était très impressionnante ! Quelques remarques cependant sur l\'interface...',
  },
];

/**
 * Full email details (with body)
 */
export const mockEmailDetails: Record<string, EmailDetail> = {
  'email-1': {
    ...mockEmails[0],
    body: `
      <div>
        <p>Bonjour,</p>
        <p>Veuillez trouver ci-joint le rapport trimestriel Q4 2025. Les résultats sont très encourageants avec une croissance de 15% par rapport au trimestre précédent.</p>
        <p>Points clés :</p>
        <ul>
          <li>Chiffre d'affaires : +15%</li>
          <li>Nouveaux clients : 47</li>
          <li>Taux de rétention : 94%</li>
        </ul>
        <p>Je reste disponible pour en discuter lors de notre prochaine réunion.</p>
        <p>Cordialement,<br>Marie Dupont</p>
      </div>
    `,
    to: ['vous@example.com'],
    cc: ['direction@example.com'],
    attachments: [mockAttachments[0]],
  },
  'email-2': {
    ...mockEmails[1],
    body: `
      <div>
        <p>Parfait pour mardi 14h. Je réserve la salle de conférence B.</p>
        <p>Ordre du jour proposé :</p>
        <ol>
          <li>Point sur l'avancement (15 min)</li>
          <li>Revue des risques (20 min)</li>
          <li>Planning phase 2 (25 min)</li>
        </ol>
        <p>À mardi !</p>
        <p>Pierre</p>
      </div>
    `,
    to: ['vous@example.com', 'equipe@example.com'],
    cc: [],
    attachments: [],
  },
  'email-5': {
    ...mockEmails[4],
    body: `
      <div>
        <p>Bonjour,</p>
        <p>Suite à notre conversation téléphonique de ce matin, pourriez-vous nous envoyer un devis pour :</p>
        <ul>
          <li>Licence Enterprise (50 utilisateurs)</li>
          <li>Support Premium 24/7</li>
          <li>Formation initiale (2 jours)</li>
        </ul>
        <p>Nous avons besoin de ce devis avant vendredi pour validation par notre direction.</p>
        <p>Merci d'avance,<br>Jean Lefèvre<br>Directeur des Achats</p>
      </div>
    `,
    to: ['commercial@example.com'],
    cc: ['vous@example.com'],
    attachments: [mockAttachments[1], mockAttachments[2]],
  },

  // Email with CID inline image in signature (tests CID resolution fix)
  'email-cid': {
    id: 'email-cid',
    sender: 'camille.tremblay@hydrotech.example',
    sender_name: 'Camille Tremblay',
    subject: 'Contrat de service — révision 3',
    received_at: hoursAgo(2),
    has_attachments: false,
    conversation_id: null,
    is_read: false,
    body_html: `<div>
      <p>Bonjour,</p>
      <p>Veuillez trouver ci-joint la révision 3 du contrat de service.</p>
      <p>Cordialement,</p>
      <div class="signature">
        <p>Camille Tremblay</p>
        <p>Cell : 514-555-0142 | Courriel : camille.tremblay@hydrotech.example</p>
        <p>1200 rue de l'Exemple, bureau 100, Montréal, QC, H0H 0H0, Canada</p>
        <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="Hydrotech logo" width="200" />
      </div>
    </div>`,
    body: 'Bonjour, Veuillez trouver ci-joint la révision 3 du contrat de service. Cordialement, Camille Tremblay',
    to: ['vous@example.com'],
    cc: [],
  },

  // Email with UNRESOLVED cid: reference (simulates backend bug — should NOT happen after fix)
  'email-cid-broken': {
    id: 'email-cid-broken',
    sender: 'test@example.com',
    sender_name: 'Test Sender',
    subject: 'Email avec cid: non résolu',
    received_at: hoursAgo(1),
    has_attachments: false,
    conversation_id: null,
    is_read: false,
    body_html: `<div><p>Message test</p><img src="cid:image001.png@01D12345.67890" alt="logo" /></div>`,
    body: 'Message test',
    to: ['vous@example.com'],
    cc: [],
  },
};

/**
 * Email thread/conversation
 */
export const mockEmailThread = {
  'conv-2': [
    {
      id: 'email-2-thread-1',
      sender: 'vous@example.com',
      sender_name: 'Vous',
      subject: 'Réunion projet Alpha',
      received_at: daysAgo(1),
      has_attachments: false,
      conversation_id: 'conv-2',
      is_read: true,
      body: '<p>Bonjour Pierre, es-tu disponible mardi pour faire le point sur le projet Alpha ?</p>',
    },
    {
      id: 'email-2',
      sender: 'pierre.martin@example.com',
      sender_name: 'Pierre Martin',
      subject: 'Re: Réunion projet Alpha',
      received_at: hoursAgo(3),
      has_attachments: false,
      conversation_id: 'conv-2',
      is_read: false,
      body: '<p>Parfait pour mardi 14h. Je réserve la salle de conférence B.</p>',
    },
  ],
};

/**
 * Search result item (different from Email)
 */
interface SearchResult {
  id: number;
  email_id: string;
  subject: string;
  sender: string;
  date: string;
  snippet: string;
  relevance_score: number;
  is_read: boolean;
  is_starred: boolean;
}

/**
 * Search response format
 */
interface SearchResponse {
  success: boolean;
  query: string;
  total: number;
  results: SearchResult[];
  duration_ms: number;
  has_more: boolean;
}

/**
 * Emails response format (for /api/emails)
 */
interface EmailsResponse {
  count: number;
  emails: Email[];
}

/**
 * Search results - returns proper SearchResponse format
 */
export const mockSearchResults = (query: string): SearchResponse => {
  const lowerQuery = query.toLowerCase();
  const filtered = mockEmails.filter(
    (email) =>
      email.subject.toLowerCase().includes(lowerQuery) ||
      email.sender.toLowerCase().includes(lowerQuery) ||
      email.sender_name?.toLowerCase().includes(lowerQuery) ||
      email.body_preview?.toLowerCase().includes(lowerQuery)
  );

  const results: SearchResult[] = filtered.map((email, index) => ({
    id: index + 1,
    email_id: email.id,
    subject: email.subject,
    sender: email.sender,
    date: email.received_at,
    snippet: email.body_preview || '',
    relevance_score: 1.0 - (index * 0.1),
    is_read: email.is_read,
    is_starred: false,
  }));

  return {
    success: true,
    query,
    total: results.length,
    results,
    duration_ms: 15,
    has_more: false,
  };
};

/**
 * Filtered emails by status - returns EmailsResponse format
 */
export const mockEmailsByStatus = (status: string): EmailsResponse => {
  let emails: Email[];
  switch (status) {
    case 'unread':
      emails = mockEmails.filter((e) => !e.is_read);
      break;
    case 'read':
      emails = mockEmails.filter((e) => e.is_read);
      break;
    case 'all':
    default:
      emails = mockEmails;
  }
  return { count: emails.length, emails };
};

/**
 * Get emails response in correct format
 */
export const mockEmailsResponse: EmailsResponse = {
  count: mockEmails.length,
  emails: mockEmails,
};

/**
 * Empty state data
 */
export const mockEmptyEmails: EmailsResponse = { count: 0, emails: [] };

/**
 * Wizard status - complete onboarding so app shows inbox
 */
export const mockWizardStatus = {
  onboarding_complete: true,
  has_email_provider: true,
  has_llm_configured: true,
  has_writing_style: true,
};

/**
 * Error response
 */
export const mockApiError = {
  error: 'Internal server error',
  message: 'Unable to fetch emails',
  status: 500,
};

/**
 * Draft ready response
 */
export const mockDraftReady = {
  email_id: 'email-5',
  draft_id: 'draft-1',
  draft_body: `
    <p>Bonjour M. Lefèvre,</p>
    <p>Merci pour votre demande. Voici notre proposition :</p>
    <ul>
      <li>Licence Enterprise (50 utilisateurs) : 15 000 €/an</li>
      <li>Support Premium 24/7 : 3 000 €/an</li>
      <li>Formation initiale (2 jours) : 2 400 €</li>
    </ul>
    <p>Total : 20 400 € HT</p>
    <p>Ce devis est valable 30 jours.</p>
    <p>Cordialement</p>
  `,
  status: 'ready',
};

/**
 * Compose email payload
 */
export const mockComposePayload = {
  to: 'client@example.com',
  subject: 'Re: Demande de devis',
  instructions: 'Répondre poliment avec le devis demandé',
  useHistory: true,
};

/**
 * Health check response
 */
export const mockHealthResponse = {
  status: 'ok',
  version: '1.0.0',
  services: {
    database: 'connected',
    email_provider: 'connected',
    ai_service: 'available',
  },
};
