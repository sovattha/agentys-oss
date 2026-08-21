import type { SpeakableEmail, VoiceDraftResponse, Draft, Email } from '../../src/types';

export const mockSpeakableEmail: SpeakableEmail = {
  id: 'msg-abc123',
  subject: 'Rapport trimestriel Q4',
  sender_name: 'Marie Dupont',
  speakable_text:
    'Marie Dupont. Rapport trimestriel. Bonjour, veuillez trouver ci-joint le rapport.',
};

export const mockDraft: Draft = {
  id: 'draft-001',
  email_id: 'msg-abc123',
  email_sender: 'marie.dupont@example.com',
  email_sender_name: 'Marie Dupont',
  email_subject: 'Rapport trimestriel Q4',
  draft_subject: 'Re: Rapport trimestriel Q4',
  draft_body: 'Bonjour Marie, merci pour votre rapport. Je reviendrai vers vous.',
  status: 'pending',
  created_at: '2026-03-03T10:00:00Z',
};

export const mockDraft2: Draft = {
  id: 'draft-002',
  email_id: 'msg-def456',
  email_sender: 'pierre.martin@example.com',
  email_sender_name: 'Pierre Martin',
  email_subject: 'Réunion de demain',
  draft_subject: 'Re: Réunion de demain',
  draft_body: 'Bonjour Pierre, je confirme ma présence à la réunion.',
  status: 'pending',
  created_at: '2026-03-03T11:00:00Z',
};

export const mockVoiceDraftResponse: VoiceDraftResponse = {
  draft_id: 'vd-001',
  email_id: 'msg-abc123',
  content: 'Bonjour, je confirme la réunion pour demain à 14h.',
  status: 'generated',
};

export const mockEmail: Email = {
  id: 'msg-abc123',
  sender: 'marie.dupont@example.com',
  sender_name: 'Marie Dupont',
  subject: 'Rapport trimestriel Q4',
  body: 'Bonjour, veuillez trouver ci-joint le rapport.',
  received_at: '2026-03-03T09:00:00Z',
};
