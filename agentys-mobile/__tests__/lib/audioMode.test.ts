/**
 * Politique d'interruption audio — verrou de régression.
 *
 * Le défaut d'expo-av est `MixWithOthers` : une session Drive laissait donc la
 * musique de l'utilisateur jouer PAR-DESSUS la voix. Ces assertions échouent
 * si quelqu'un retire la surcharge ou repasse un mode en partiel (expo-av
 * fusionne les modes partiels avec le précédent → la politique dépendrait
 * alors de l'ordre de montage des hooks).
 */

import { InterruptionModeAndroid, InterruptionModeIOS } from "expo-av";
import {
  AMBIENT_MIC_AUDIO_MODE,
  PLAYBACK_AUDIO_MODE,
  RECORDING_AUDIO_MODE,
} from "../../src/lib/audioMode";

describe("politique d'interruption audio", () => {
  test.each([
    ["playback", PLAYBACK_AUDIO_MODE],
    ["recording", RECORDING_AUDIO_MODE],
  ])("le mode %s interrompt les autres apps au lieu de se mélanger", (_name, mode) => {
    expect(mode.interruptionModeIOS).toBe(InterruptionModeIOS.DoNotMix);
    expect(mode.interruptionModeAndroid).toBe(InterruptionModeAndroid.DoNotMix);
    expect(mode.shouldDuckAndroid).toBe(false);
  });

  test("le mic décoratif du login laisse la musique jouer", () => {
    // Ouvrir l'app ne doit pas couper la musique : ce micro n'alimente qu'une
    // animation, il n'y a pas de session de travail en cours.
    expect(AMBIENT_MIC_AUDIO_MODE.interruptionModeIOS).toBe(InterruptionModeIOS.MixWithOthers);
    expect(AMBIENT_MIC_AUDIO_MODE.allowsRecordingIOS).toBe(true);
  });

  test("seul le playback survit à l'arrière-plan (#1122)", () => {
    // TTS écran verrouillé oui ; micro en arrière-plan jamais.
    expect(PLAYBACK_AUDIO_MODE.staysActiveInBackground).toBe(true);
    expect(RECORDING_AUDIO_MODE.staysActiveInBackground).toBe(false);
    expect(AMBIENT_MIC_AUDIO_MODE.staysActiveInBackground).toBe(false);
  });
});
