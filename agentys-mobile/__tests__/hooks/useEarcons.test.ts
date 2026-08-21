/**
 * Step 1 — useEarcons : précharge les clips (4 noms × 3 familles de style,
 * 2026-07) et expose un `play` stable. On vérifie qu'il charge les assets,
 * que play() rejoue le bon son, et qu'un play() avant chargement (ou sur un
 * nom inconnu) ne throw pas (no-op).
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { Audio } from 'expo-av';
import { useEarcons } from '../../src/hooks/useEarcons';

// 4 earcons × 3 styles (classic/soft/crisp) — tous préchargés pour que le
// changement de style dans les réglages soit instantané.
const EXPECTED_PRELOADS = 12;

describe('useEarcons', () => {
  beforeEach(() => jest.clearAllMocks());

  it('précharge les 12 earcons (4 noms × 3 styles) au mount', async () => {
    renderHook(() => useEarcons());
    await waitFor(() =>
      expect((Audio.Sound.createAsync as jest.Mock).mock.calls.length).toBe(EXPECTED_PRELOADS),
    );
    // Préchargés sans jouer (shouldPlay:false)
    for (const call of (Audio.Sound.createAsync as jest.Mock).mock.calls) {
      expect(call[1]).toMatchObject({ shouldPlay: false });
    }
  });

  it('play(name) rejoue le son chargé', async () => {
    const created: any[] = [];
    (Audio.Sound.createAsync as jest.Mock).mockImplementation(async () => {
      const s = {
        replayAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
      };
      created.push(s);
      return { sound: s };
    });

    const { result } = renderHook(() => useEarcons());
    await waitFor(() => expect(created.length).toBe(EXPECTED_PRELOADS));
    act(() => result.current.play('turn'));
    // Exactement un son rejoué (le 'turn' du style courant), pas les autres.
    const replayed = created.filter((s) => s.replayAsync.mock.calls.length > 0);
    expect(replayed).toHaveLength(1);
  });

  it('play() ne throw pas si le son est absent', () => {
    const { result } = renderHook(() => useEarcons());
    // Appelé immédiatement (sounds pas encore résolus) → no-op silencieux
    expect(() => result.current.play('done')).not.toThrow();
  });
});
