/**
 * Shim pour expo-speech-recognition dans Expo Go.
 * Le module natif ExpoSpeechRecognition n'existe pas dans Expo Go —
 * ce shim fournit des no-ops silencieux pour que le tab Drive reste accessible.
 */

let _nativeAvailable: boolean | null = null;

function isNativeAvailable(): boolean {
  if (_nativeAvailable !== null) return _nativeAvailable;
  try {
    // Tenter d'accéder au module natif
    require("expo-speech-recognition");
    _nativeAvailable = true;
  } catch {
    _nativeAvailable = false;
  }
  return _nativeAvailable;
}

export const SpeechRecognitionModule = {
  start: (_opts?: any) => {
    if (!isNativeAvailable()) return;
    try {
      const { ExpoSpeechRecognitionModule } = require("expo-speech-recognition");
      ExpoSpeechRecognitionModule.start(_opts);
    } catch {}
  },
  stop: () => {
    if (!isNativeAvailable()) return;
    try {
      const { ExpoSpeechRecognitionModule } = require("expo-speech-recognition");
      ExpoSpeechRecognitionModule.stop();
    } catch {}
  },
};

export function useSpeechEvent(
  event: string,
  handler: (e: any) => void
): void {
  // Dans Expo Go, importer useSpeechRecognitionEvent crasherait au niveau module.
  // On n'appelle donc jamais le vrai hook — les boutons servent de fallback.
  if (!isNativeAvailable()) return;
  try {
    const { useSpeechRecognitionEvent } = require("expo-speech-recognition");
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useSpeechRecognitionEvent(event, handler);
  } catch {}
}

export const STT_AVAILABLE = isNativeAvailable();
