import { renderHook, act } from '@testing-library/react-native';
import { Audio } from 'expo-av';
import { useAudio } from '../../src/hooks/useAudio';

beforeEach(() => {
  jest.clearAllMocks();
  (Audio.requestPermissionsAsync as jest.Mock).mockResolvedValue({ status: 'granted' });
  (Audio.setAudioModeAsync as jest.Mock).mockResolvedValue(undefined);

  const mockRecording = {
    stopAndUnloadAsync: jest.fn().mockResolvedValue(undefined),
    getURI: jest.fn().mockReturnValue('file:///recording.m4a'),
  };
  (Audio.Recording.createAsync as jest.Mock).mockResolvedValue({ recording: mockRecording });
});

describe('startRecording', () => {
  it('demande les permissions et passe en state "recording"', async () => {
    const { result } = renderHook(() => useAudio());
    await act(async () => {
      await result.current.startRecording();
    });
    expect(Audio.requestPermissionsAsync).toHaveBeenCalled();
    expect(result.current.audioState).toBe('recording');
  });

  it('reste en "idle" si les permissions sont refusées', async () => {
    (Audio.requestPermissionsAsync as jest.Mock).mockRejectedValueOnce(new Error('denied'));
    const { result } = renderHook(() => useAudio());
    await act(async () => {
      await result.current.startRecording();
    });
    expect(result.current.audioState).toBe('idle');
  });
});

describe('stopRecording', () => {
  it('retourne un URI et passe en state "stopped"', async () => {
    const { result } = renderHook(() => useAudio());

    await act(async () => {
      await result.current.startRecording();
    });

    let uri: string | null = null;
    await act(async () => {
      uri = await result.current.stopRecording();
    });

    expect(uri).toBe('file:///recording.m4a');
    expect(result.current.audioState).toBe('stopped');
  });

  it('retourne null si aucun enregistrement actif', async () => {
    const { result } = renderHook(() => useAudio());
    const uri = await result.current.stopRecording();
    expect(uri).toBeNull();
  });
});
