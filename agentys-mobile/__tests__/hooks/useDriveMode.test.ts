/**
 * Tests unitaires pour useDriveMode 4.0 (ElevenLabs TTS).
 *
 * Flow: speaking → choosing (reply/next/prev) → listening → generating → reviewing
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { Audio } from 'expo-av';
import { useDriveMode } from '../../src/hooks/useDriveMode';
import { mockSpeakableEmail, mockVoiceDraftResponse } from '../support/mocks';

// Mock API
jest.mock('../../src/services/api', () => ({
  getEmailSpeakable: jest.fn(),
  createVoiceDraft: jest.fn(),
  approveDraft: jest.fn(),
  getPendingDraftByEmail: jest.fn(),
}));

// Mock TTS service (ElevenLabs proxy)
jest.mock('../../src/services/tts', () => ({
  speak: jest.fn(),
  audioAuthHeaders: jest.fn(),
}));

// Mock expo-speech-recognition
jest.mock('expo-speech-recognition', () => ({
  ExpoSpeechRecognitionModule: {
    start: jest.fn(),
    stop: jest.fn(),
  },
  useSpeechRecognitionEvent: jest.fn(),
}));

// Mock expo-secure-store — retourne un voice_id par défaut pour que la TTS tente de jouer
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn().mockImplementation((key: string) =>
    Promise.resolve(key === 'voice_id' ? 'voice-test' : null),
  ),
  setItemAsync: jest.fn().mockResolvedValue(undefined),
  deleteItemAsync: jest.fn().mockResolvedValue(undefined),
}));

import { getEmailSpeakable, createVoiceDraft, approveDraft, getPendingDraftByEmail } from '../../src/services/api';
import { speak as speakBackend, audioAuthHeaders } from '../../src/services/tts';

const mockGetEmailSpeakable = getEmailSpeakable as jest.Mock;
const mockCreateVoiceDraft = createVoiceDraft as jest.Mock;
const mockApproveDraft = approveDraft as jest.Mock;
const mockGetPendingDraftByEmail = getPendingDraftByEmail as jest.Mock;
const mockSpeakBackend = speakBackend as jest.Mock;
const mockAudioAuthHeaders = audioAuthHeaders as jest.Mock;

const MOCK_EMAILS = [
  { id: 'msg-abc123', sender: 'test@test.com', subject: 'Test', received_at: '2026-01-01T10:00:00Z' },
  { id: 'msg-def456', sender: 'other@test.com', subject: 'Autre', received_at: '2026-01-01T09:00:00Z' },
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

  // Audio.Sound.createAsync : simule un playback qui se termine immédiatement
  (Audio.Sound.createAsync as jest.Mock).mockImplementation(
    async (_source: any, _status: any, onPlaybackStatusUpdate?: (s: any) => void) => {
      const mockSound = {
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        setOnPlaybackStatusUpdate: jest.fn(),
        replayAsync: jest.fn().mockResolvedValue(undefined),
        playAsync: jest.fn().mockResolvedValue(undefined),
        setPositionAsync: jest.fn().mockResolvedValue(undefined),
      };
      // Firer didJustFinish au prochain tick (setImmediate ne marche pas partout → setTimeout)
      setTimeout(() => {
        onPlaybackStatusUpdate?.({ isLoaded: true, didJustFinish: true });
      }, 0);
      return { sound: mockSound };
    },
  );

  mockGetEmailSpeakable.mockResolvedValue(mockSpeakableEmail);
  mockCreateVoiceDraft.mockResolvedValue(mockVoiceDraftResponse);
  mockApproveDraft.mockResolvedValue({ success: true });
  mockGetPendingDraftByEmail.mockResolvedValue(null);
});

describe('état initial', () => {
  it('commence en "idle"', () => {
    const { result } = renderHook(() => useDriveMode());
    expect(result.current.state).toBe('idle');
    expect(result.current.currentEmail).toBeNull();
    expect(result.current.draftContent).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.replyMode).toBeNull();
  });
});

describe('startSession', () => {
  it('charge et lit le premier email (après intro TTS)', async () => {
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });

    await waitFor(() =>
      expect(mockGetEmailSpeakable).toHaveBeenCalledWith('msg-abc123', true),
    );
    await waitFor(() =>
      expect(mockGetPendingDraftByEmail).toHaveBeenCalledWith('msg-abc123'),
    );
    expect(result.current.currentEmail).toEqual(mockSpeakableEmail);
  });

  it('passe en reviewing si un draft existe déjà', async () => {
    mockGetPendingDraftByEmail.mockResolvedValueOnce({
      id: 'draft-123',
      draft_body: 'Brouillon existant.',
    });
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });

    await waitFor(() =>
      expect(result.current.draftContent).toBe('Brouillon existant.'),
    );
  });
});

describe('chooseReply', () => {
  it('passe en listening après sélection reply', async () => {
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });
    await waitFor(() => expect(mockGetEmailSpeakable).toHaveBeenCalled());

    act(() => {
      result.current.chooseReply('reply');
    });

    expect(result.current.state).toBe('listening');
    expect(result.current.replyMode).toBe('reply');
  });
});

describe('next / previous', () => {
  it('avance au prochain email', async () => {
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });
    await waitFor(() =>
      expect(mockGetEmailSpeakable).toHaveBeenCalledWith('msg-abc123', true),
    );

    await act(async () => {
      result.current.next();
    });

    await waitFor(() =>
      expect(mockGetEmailSpeakable).toHaveBeenCalledWith('msg-def456', true),
    );
  });
});

describe('rejectAndRelisten', () => {
  it('remet en listening et efface le draft', async () => {
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });

    act(() => {
      result.current.rejectAndRelisten();
    });

    expect(result.current.state).toBe('listening');
    expect(result.current.draftContent).toBeNull();
  });
});

describe('reset', () => {
  it('remet tout à zéro', async () => {
    const { result } = renderHook(() => useDriveMode());

    await act(async () => {
      await result.current.startSession(MOCK_EMAILS as any);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.state).toBe('idle');
    expect(result.current.currentEmail).toBeNull();
    expect(result.current.draftContent).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.replyMode).toBeNull();
  });
});
