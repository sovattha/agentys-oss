/**
 * Mode audio playback partagé — un seul endroit décide de
 * `staysActiveInBackground` (le « problème des trois acteurs sur
 * setAudioModeAsync » noté dans useEarcons.ts).
 *
 * #1122 : `staysActiveInBackground: true` pour que la lecture TTS du drive
 * mode survive au verrouillage de l'écran (téléphone en poche/support en
 * voiture). Couplé à `UIBackgroundModes: ["audio"]` dans app.json — les deux
 * doivent rester cohérents. Les modes ENREGISTREMENT restent volontairement
 * à false : on n'écoute jamais le micro en arrière-plan.
 *
 * `DoNotMix` : en voiture, la musique doit se TAIRE pendant la session, pas
 * se mélanger à la voix. Le défaut d'expo-av est `MixWithOthers` (iOS) /
 * `DuckOthers` (Android) — Spotify continuait en fond sonore par-dessus le
 * TTS. `DoNotMix` retire l'option `.mixWithOthers` de la category iOS, donc
 * l'activation de notre session INTERROMPT l'autre app.
 *
 * La reprise de la musique en fin de session ne vient PAS d'ici : expo-av
 * ne désactive plus jamais l'AVAudioSession (son `setActive:NO` est commenté
 * upstream, cf. expo/expo#15873). C'est `AgentysAudio.deactivateSession()`
 * qui la rend au système, appelé aux points de fin de session Drive.
 */
import { InterruptionModeAndroid, InterruptionModeIOS } from "expo-av";

/** Politique commune playback ET recording : on interrompt, on ne mixe pas. */
const EXCLUSIVE_AUDIO = {
  interruptionModeIOS: InterruptionModeIOS.DoNotMix,
  interruptionModeAndroid: InterruptionModeAndroid.DoNotMix,
  shouldDuckAndroid: false,
} as const;

export const PLAYBACK_AUDIO_MODE = {
  ...EXCLUSIVE_AUDIO,
  playsInSilentModeIOS: true,
  allowsRecordingIOS: false,
  staysActiveInBackground: true,
} as const;

/**
 * Mode enregistrement — même politique d'interruption que le playback.
 * Explicite plutôt qu'hérité du dernier `setAudioModeAsync` : expo-av fusionne
 * les modes partiels avec le précédent, donc un appel partiel dépendrait de
 * l'ordre de montage des hooks pour ne pas retomber sur `MixWithOthers`.
 */
export const RECORDING_AUDIO_MODE = {
  ...EXCLUSIVE_AUDIO,
  playsInSilentModeIOS: true,
  allowsRecordingIOS: true,
  staysActiveInBackground: false,
} as const;

/**
 * Mic décoratif (visualiseur de l'écran login) — SEUL mode qui garde
 * `MixWithOthers`. Ouvrir l'app ne doit pas tuer la musique de l'utilisateur :
 * ce micro n'alimente qu'une animation, pas une session de travail. La
 * politique exclusive est ré-appliquée par `useTts` avant chaque énoncé, donc
 * le démarrage d'une vraie session interrompt bien la musique.
 */
export const AMBIENT_MIC_AUDIO_MODE = {
  interruptionModeIOS: InterruptionModeIOS.MixWithOthers,
  interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
  shouldDuckAndroid: true,
  playsInSilentModeIOS: true,
  allowsRecordingIOS: true,
  staysActiveInBackground: false,
} as const;
