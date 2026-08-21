/**
 * useTts — pipeline chunké : contrats de l'audit mobile.
 *  - un échec de chargement de chunk (URL 404/expirée) → state "error",
 *    PAS une lecture silencieuse réussie (M-P2e) ;
 *  - succès multi-chunk → onDone appelé une seule fois, state "idle".
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { Audio } from 'expo-av';
import { useTts } from '../../src/hooks/useTts';

jest.mock('../../src/services/tts', () => ({
  speak: jest.fn(),
  audioAuthHeaders: jest.fn(),
  ensureVoiceId: jest.fn().mockResolvedValue('voice-test'),
}));

import { speak as speakBackend, audioAuthHeaders } from '../../src/services/tts';

const mockSpeakBackend = speakBackend as jest.Mock;
const mockAudioAuthHeaders = audioAuthHeaders as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockSpeakBackend.mockImplementation((text: string) =>
    Promise.resolve({ audioUrl: `https://srv/${encodeURIComponent(text).slice(0, 8)}.mp3`, cached: false, chars: text.length }),
  );
  mockAudioAuthHeaders.mockResolvedValue({ Authorization: 'Bearer t' });
});

describe('useTts chunked pipeline', () => {
  it('un chunk court se lit en un seul Sound et appelle onDone', async () => {
    (Audio.Sound.createAsync as jest.Mock).mockImplementation(
      async (_s: any, _o: any, cb?: (st: any) => void) => {
        setTimeout(() => cb?.({ isLoaded: true, didJustFinish: true }), 0);
        return { sound: { unloadAsync: jest.fn().mockResolvedValue(undefined), stopAsync: jest.fn().mockResolvedValue(undefined) } };
      },
    );
    const { result } = renderHook(() => useTts());
    const onDone = jest.fn();
    await act(async () => {
      await result.current.speak('Court message.', onDone);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(result.current.state).toBe('idle');
  });

  it('un échec de chargement de chunk → state "error" (pas de lecture silencieuse)', async () => {
    (Audio.Sound.createAsync as jest.Mock).mockRejectedValue(new Error('404 expired url'));
    const { result } = renderHook(() => useTts());
    const onDone = jest.fn();
    await act(async () => {
      await result.current.speak('Message.', onDone);
      await new Promise((r) => setTimeout(r, 20));
    });
    await waitFor(() => expect(result.current.state).toBe('error'));
    // onDone est toujours appelé (pour ne pas bloquer le Drive Mode)…
    expect(onDone).toHaveBeenCalledTimes(1);
    // …mais l'état "error" signale l'échec (vs un faux "idle" silencieux).
    expect(result.current.error).toBeTruthy();
  });

  it('fin naturelle SANS didJustFinish → onDone via la sonde getStatusAsync (#1134)', async () => {
    // Reproduit le bug Release : l'event didJustFinish ne fire JAMAIS. La fin de
    // lecture ne peut être détectée que par une requête directe de l'état.
    // La sonde renvoie "en lecture" puis, une fois avancée dans le temps,
    // "arrêtée en fin de piste" (position >= durée, !isPlaying).
    let finished = false;
    const getStatusAsync = jest.fn().mockImplementation(async () =>
      finished
        ? { isLoaded: true, isPlaying: false, positionMillis: 1000, durationMillis: 1000 }
        : { isLoaded: true, isPlaying: true, positionMillis: 0, durationMillis: 1000 },
    );
    (Audio.Sound.createAsync as jest.Mock).mockImplementation(
      async (_s: any, _o: any, _cb?: (st: any) => void) => {
        // NOTE: on n'appelle jamais _cb → didJustFinish absent (cas Release cassé).
        return {
          sound: {
            getStatusAsync,
            unloadAsync: jest.fn().mockResolvedValue(undefined),
            stopAsync: jest.fn().mockResolvedValue(undefined),
          },
        };
      },
    );

    const { result } = renderHook(() => useTts());
    const onDone = jest.fn();
    await act(async () => {
      const speaking = result.current.speak('Court message.', onDone);
      // Laisse la lecture démarrer et la sonde tourner au moins un tick.
      await new Promise((r) => setTimeout(r, 300));
      // La piste atteint sa fin : la prochaine sonde détecte position>=durée & !isPlaying.
      finished = true;
      await new Promise((r) => setTimeout(r, 300));
      await speaking;
    });

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(result.current.state).toBe('idle');
    expect(getStatusAsync).toHaveBeenCalled();
  });
});
