import * as SecureStore from 'expo-secure-store';
import {
  getEmails,
  getEmailSpeakable,
  createVoiceDraft,
  getDrafts,
  approveDraft,
  rejectDraft,
} from '../../src/services/api';
import { mockSpeakableEmail, mockDraft, mockVoiceDraftResponse, mockEmail } from '../support/mocks';

const mockFetch = global.fetch as jest.Mock;

function mockResponse(data: unknown, status = 200) {
  mockFetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(data),
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  (SecureStore.getItemAsync as jest.Mock).mockResolvedValue('test-token-abc');
});

describe('authHeaders', () => {
  it('ajoute Authorization: Bearer à chaque requête', async () => {
    mockResponse({ emails: [mockEmail] });
    await getEmails();
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/emails'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token-abc' }),
      })
    );
  });

  it("n'ajoute pas d'Authorization si pas de token", async () => {
    (SecureStore.getItemAsync as jest.Mock).mockResolvedValue(null);
    mockResponse({ emails: [] });
    await getEmails();
    const callArgs = mockFetch.mock.calls[0][1];
    expect(callArgs.headers.Authorization).toBeUndefined();
  });
});

describe('401 → confirmation puis clearToken + throw Unauthorized', () => {
  // Depuis #1121 le 401 est confirmé par un probe GET /api/auth/me avant purge.
  it('purge le token quand le probe confirme le 401', async () => {
    mockResponse({}, 401); // appel API
    mockResponse({}, 401); // probe /api/auth/me → invalide confirmé
    await expect(getEmails()).rejects.toThrow('Unauthorized');
    expect(SecureStore.deleteItemAsync).toHaveBeenCalled();
  });
});

describe('getEmails', () => {
  it('retourne { emails: Email[] }', async () => {
    mockResponse({ emails: [mockEmail] });
    const result = await getEmails();
    expect(result).toEqual({ emails: [mockEmail] });
  });
});

describe('getEmailSpeakable', () => {
  it('retourne un SpeakableEmail', async () => {
    mockResponse(mockSpeakableEmail);
    const result = await getEmailSpeakable('msg-abc123');
    expect(result).toEqual(mockSpeakableEmail);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/emails/msg-abc123/speakable'),
      expect.anything()
    );
  });
});

describe('createVoiceDraft', () => {
  it('POST avec transcription et retourne VoiceDraftResponse', async () => {
    mockResponse(mockVoiceDraftResponse);
    const result = await createVoiceDraft('msg-abc123', 'Oui, je confirme.');
    expect(result).toEqual(mockVoiceDraftResponse);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/emails/msg-abc123/voice-draft'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      })
    );
  });
});

describe('getDrafts', () => {
  it('retourne { drafts: Draft[] }', async () => {
    mockResponse({ drafts: [mockDraft] });
    const result = await getDrafts();
    expect(result).toEqual({ drafts: [mockDraft] });
  });
});

describe('approveDraft', () => {
  // Bug live 2026-04-28 : ancien endpoint `/api/drafts/<id>/approve` n'existe
  // PAS côté backend (404 silencieux dans drive mode). Le bon est
  // `/api/pending-drafts/<id>/validate` (cohérent avec la webapp).
  it('POST /api/pending-drafts/:id/validate (et NON /drafts/:id/approve)', async () => {
    mockResponse({ success: true });
    const result = await approveDraft('draft-001');
    expect(result).toEqual({ success: true });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/pending-drafts/draft-001/validate'),
      expect.objectContaining({ method: 'POST' }),
    );
    // S'assurer qu'on ne retombe JAMAIS sur l'ancien endpoint fantôme.
    const calledUrls = mockFetch.mock.calls.map((c: any[]) => c[0] as string);
    expect(calledUrls.some((u) => u.includes('/api/drafts/') && u.includes('/approve'))).toBe(false);
  });
});

describe('rejectDraft', () => {
  it('PATCH /api/drafts/:id/feedback', async () => {
    mockResponse({ success: true });
    await rejectDraft('draft-001', 'Trop formel');
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/drafts/draft-001/feedback'),
      expect.objectContaining({ method: 'PATCH' })
    );
  });
});

describe('erreur HTTP générique', () => {
  it("lève l'erreur du corps JSON sur 500 (après retries pour GET idempotent)", async () => {
    // F01: GET fait 3 tentatives sur 5xx. Mock 3 réponses pour atteindre l'échec final.
    const mock500 = {
      ok: false,
      status: 500,
      json: jest.fn().mockResolvedValue({ error: 'Internal Server Error' }),
    };
    mockFetch
      .mockResolvedValueOnce(mock500)
      .mockResolvedValueOnce(mock500)
      .mockResolvedValueOnce(mock500);
    await expect(getDrafts()).rejects.toThrow('Internal Server Error');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });
});
