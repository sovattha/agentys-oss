/**
 * F02 (HIGH) — silent failure regression guard, version act-then-undo.
 *
 * Historique : avant le premier fix, un échec d'`approveDraft` était avalé
 * (`catch {}`) et l'utilisateur entendait « Envoyé » pour un email jamais
 * parti. Le premier fix bloquait l'avance et parlait `tts.sendFailed`.
 *
 * Contrat ACTUEL (act-then-undo) : l'envoi réel est DIFFÉRÉ de SEND_UNDO_MS
 * (8 s, annulable à la voix). La session avance immédiatement — donc en cas
 * d'échec API différé, le « loud failure » passe par Haptics.Error + earcon
 * alert + toast persistant + recrédit des stats. Ce test verrouille :
 *   1. l'envoi N'EST PAS exécuté avant la fenêtre d'annulation ;
 *   2. il S'EXÉCUTE après ;
 *   3. l'échec différé déclenche le feedback d'erreur (jamais silencieux) ;
 *   4. le succès ne déclenche PAS le feedback d'erreur.
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { Audio } from 'expo-av';
import * as Haptics from 'expo-haptics';
import { useDriveMode } from '../../src/hooks/useDriveMode';
import { mockSpeakableEmail, mockVoiceDraftResponse } from '../support/mocks';

jest.mock('../../src/services/api', () => ({
  getEmailSpeakable: jest.fn(),
  createVoiceDraft: jest.fn(),
  approveDraft: jest.fn(),
  getPendingDraftByEmail: jest.fn(),
  archiveEmail: jest.fn(),
  deleteEmail: jest.fn(),
  transcribeAudio: jest.fn(),
  generateProcessDraftFast: jest.fn(),
  voiceAgent: jest.fn().mockResolvedValue({ actions: [], confidence: 0, source: 'unavailable' }),
  postVoiceMetrics: jest.fn().mockResolvedValue({ accepted: 0 }),
  DraftSkippedError: class DraftSkippedError extends Error {},
}));

jest.mock('../../src/services/tts', () => ({
  speak: jest.fn(),
  audioAuthHeaders: jest.fn(),
  ensureVoiceId: jest.fn().mockResolvedValue('voice-test'),
}));

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn().mockImplementation((key: string) =>
    Promise.resolve(key === 'voice_id' ? 'voice-test' : null),
  ),
  setItemAsync: jest.fn().mockResolvedValue(undefined),
  deleteItemAsync: jest.fn().mockResolvedValue(undefined),
}));

import {
  getEmailSpeakable,
  approveDraft,
  getPendingDraftByEmail,
} from '../../src/services/api';
import { speak as speakBackend, audioAuthHeaders } from '../../src/services/tts';

const mockGetEmailSpeakable = getEmailSpeakable as jest.Mock;
const mockApproveDraft = approveDraft as jest.Mock;
const mockGetPendingDraftByEmail = getPendingDraftByEmail as jest.Mock;
const mockSpeakBackend = speakBackend as jest.Mock;
const mockAudioAuthHeaders = audioAuthHeaders as jest.Mock;
const mockHapticsNotif = Haptics.notificationAsync as jest.Mock;

const MOCK_EMAILS = [
  { id: 'msg-abc123', sender: 'a@b.com', subject: 'A', received_at: '2026-01-01T10:00:00Z' },
  { id: 'msg-def456', sender: 'c@d.com', subject: 'B', received_at: '2026-01-01T09:00:00Z' },
];

// Le collector voiceMetrics est un singleton module-scope : startSession()
// arme un setInterval que seul endSession() clear. Sans ce teardown, le
// timer fuit entre les tests et Jest force-exit le worker (#1128).
afterEach(() => {
  const { voiceMetrics } = require('../../src/lib/voiceMetrics');
  voiceMetrics.endSession();
});

beforeEach(() => {
  jest.clearAllMocks();

  mockSpeakBackend.mockResolvedValue({
    audioUrl: 'https://srv/api/tts/audio/abc.mp3',
    cached: false,
    chars: 10,
  });
  mockAudioAuthHeaders.mockResolvedValue({ Authorization: 'Bearer token' });

  (Audio.Sound.createAsync as jest.Mock).mockImplementation(
    async (_src: any, _status: any, onUpdate?: (s: any) => void) => {
      const sound = {
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        setOnPlaybackStatusUpdate: jest.fn(),
      };
      setTimeout(() => onUpdate?.({ isLoaded: true, didJustFinish: true }), 0);
      return { sound };
    },
  );

  mockGetEmailSpeakable.mockResolvedValue(mockSpeakableEmail);
  // Un draft pré-existant sur l'email 1 pour atteindre approveDraftAndNext
  // sans rejouer tout le flow de dictée.
  mockGetPendingDraftByEmail.mockResolvedValue({
    id: 'draft-fail-1',
    draft_body: 'Some draft body',
  });
});

async function setupWithDraft() {
  const hook = renderHook(() => useDriveMode());
  await act(async () => {
    await hook.result.current.startSession(MOCK_EMAILS as any);
  });
  await waitFor(() => expect(hook.result.current.draftContent).toBe('Some draft body'));
  return hook;
}

describe('approveDraftAndNext — act-then-undo + F02 loud failure', () => {
  it("diffère l'envoi (fenêtre d'annulation) puis l'exécute, et AVANCE immédiatement", async () => {
    mockApproveDraft.mockResolvedValueOnce({ success: true });
    const { result, unmount } = await setupWithDraft();
    const indexBefore = result.current.currentIndex;

    jest.useFakeTimers();
    try {
      await act(async () => {
        await result.current.approveDraftAndNext();
      });

      // 1) Pas encore envoyé — la fenêtre d'annulation court.
      expect(mockApproveDraft).not.toHaveBeenCalled();
      // 2) Mais la session a déjà avancé (act-then-undo).
      expect(result.current.currentIndex).toBe(indexBefore + 1);
      // 3) Le feedback « envoyé » (Success haptic) a déjà joué.
      expect(mockHapticsNotif).toHaveBeenCalledWith('Success');

      // 4) La fenêtre expire → l'envoi part réellement.
      await act(async () => {
        jest.advanceTimersByTime(8000);
        await jest.runOnlyPendingTimersAsync();
      });
      expect(mockApproveDraft).toHaveBeenCalledTimes(1);
      expect(mockApproveDraft).toHaveBeenCalledWith('draft-fail-1');
      // Succès → pas de feedback d'erreur.
      expect(mockHapticsNotif).not.toHaveBeenCalledWith('Error');
    } finally {
      jest.useRealTimers();
      unmount();
    }
  });

  it("échec d'envoi différé → feedback BRUYANT (Haptics.Error), jamais silencieux", async () => {
    mockApproveDraft.mockRejectedValueOnce(new Error('Backend 500'));
    const { result, unmount } = await setupWithDraft();

    jest.useFakeTimers();
    try {
      await act(async () => {
        await result.current.approveDraftAndNext();
      });

      await act(async () => {
        jest.advanceTimersByTime(8000);
        await jest.runOnlyPendingTimersAsync();
      });

      expect(mockApproveDraft).toHaveBeenCalledTimes(1);
      // F02 : l'échec DOIT déclencher le feedback d'erreur.
      expect(mockHapticsNotif).toHaveBeenCalledWith('Error');
    } finally {
      jest.useRealTimers();
      unmount();
    }
  });
});
