/**
 * useEarcons — signaux audio non-verbaux pour le mode conduite.
 *
 * Pourquoi : dans un flow main-libres, chaque question PARLÉE de l'AI
 * ("J'envoie ?", "Tu veux l'écouter ?") est un aller-retour TTS que l'user
 * doit attendre, puis auquel répondre, puis re-attendre — c'est LE site de
 * collision "l'AI parle / l'user parle / l'AI parle". On remplace ces
 * questions de PROTOCOLE par un earcon de ~50-260ms : l'AI ne parle plus que
 * du CONTENU (résumé d'email, brouillon), et signale le tour par un ton.
 *
 * Vocabulaire (garder ≤ 4, distincts — au-delà ça redevient une charge
 * cognitive à apprendre) :
 *   - "turn" : montée 2-tons  → « à toi, j'écoute »   (remplace les prompts)
 *   - "tick" : blip court      → « c'est noté, je capture » (sur onVoiceStart)
 *   - "done" : accord majeur    → « fait / envoyé »
 *   - "alert": descente grave   → « erreur / destructif »
 *
 * Styles (réglages 2026-07) : 3 familles générées par scripts/gen-earcons.py —
 * "classic" (défaut), "soft" (plus grave/lent), "crisp" (plus aigu/court).
 * Le style courant vit au niveau module (pas d'état React) : le picker des
 * réglages appelle setEarconStyle() et les instances déjà montées (drive)
 * jouent la nouvelle famille au prochain play() sans remount. Persisté via
 * SecureStore ("earcon_style_v1").
 *
 * Coût : $0 (aucun appel ElevenLabs/réseau), latence < ~30ms (assets
 * pré-chargés). Ce hook NE TOUCHE PAS `setAudioModeAsync` — il joue sur la
 * session active pour ne pas entrer en course avec useTts/useVoiceDictation
 * (le problème des "trois acteurs sur setAudioModeAsync" déjà noté).
 *
 * NB device-verify (Step 0) : pendant une session d'enregistrement
 * (PlayAndRecord), un son peut router vers l'écouteur. Si les earcons sont
 * inaudibles en voiture, ajouter un chemin natif `playEarcon` via
 * AudioServicesPlaySystemSound (modules/agentys-audio) qui ignore la category.
 */

import { useCallback, useEffect, useRef } from "react";
import { Audio } from "expo-av";
import * as SecureStore from "expo-secure-store";
import { logEvent } from "../lib/eventLog";
import { reportError } from "../lib/errors";

export type EarconName = "turn" | "tick" | "done" | "alert";
export type EarconStyle = "classic" | "soft" | "crisp";

export const EARCON_STYLES: EarconStyle[] = ["classic", "soft", "crisp"];
export const EARCON_STYLE_KEY = "earcon_style_v1";

// `require` statique : Metro/jest résolvent l'asset au bundle. Ne pas
// dynamiser (require(variable) casse le bundler RN).
const SOURCES: Record<EarconStyle, Record<EarconName, number>> = {
  classic: {
    turn:  require("../../assets/earcons/turn.wav"),
    tick:  require("../../assets/earcons/tick.wav"),
    done:  require("../../assets/earcons/done.wav"),
    alert: require("../../assets/earcons/alert.wav"),
  },
  soft: {
    turn:  require("../../assets/earcons/turn_soft.wav"),
    tick:  require("../../assets/earcons/tick_soft.wav"),
    done:  require("../../assets/earcons/done_soft.wav"),
    alert: require("../../assets/earcons/alert_soft.wav"),
  },
  crisp: {
    turn:  require("../../assets/earcons/turn_crisp.wav"),
    tick:  require("../../assets/earcons/tick_crisp.wav"),
    done:  require("../../assets/earcons/done_crisp.wav"),
    alert: require("../../assets/earcons/alert_crisp.wav"),
  },
};

// Style courant — module-level pour que le picker des réglages affecte les
// hooks déjà montés (drive) sans remount ni event emitter.
let currentStyle: EarconStyle = "classic";
let styleLoaded = false;

/** Source asset (require id) d'un earcon — pour préversions (guide/réglages). */
export function getEarconSource(name: EarconName, style?: EarconStyle): number {
  return SOURCES[style ?? currentStyle][name];
}

export function getEarconStyle(): EarconStyle {
  return currentStyle;
}

/** Change le style courant et le persiste. Effet immédiat sur tous les play(). */
export function setEarconStyle(style: EarconStyle): void {
  currentStyle = style;
  SecureStore.setItemAsync(EARCON_STYLE_KEY, style).catch(() => {}); // no-op légitime : cache best-effort
}

/** Charge le style persisté (1× par process — idempotent). */
export async function loadEarconStyle(): Promise<EarconStyle> {
  if (styleLoaded) return currentStyle;
  styleLoaded = true;
  try {
    const saved = await SecureStore.getItemAsync(EARCON_STYLE_KEY);
    if (saved === "classic" || saved === "soft" || saved === "crisp") {
      currentStyle = saved;
    }
  } catch { /* défaut "classic" */ }
  return currentStyle;
}

export interface UseEarcons {
  /** Joue un earcon depuis le début. Fire-and-forget, ne throw jamais. */
  play: (name: EarconName) => void;
}

export function useEarcons(): UseEarcons {
  // Toutes les familles préchargées (12 clips, ~200KB) : le changement de
  // style dans les réglages est instantané, sans reload ni remount.
  const soundsRef = useRef<Partial<Record<EarconStyle, Partial<Record<EarconName, Audio.Sound>>>>>({});
  const loadedRef = useRef(false);
  /** Promesse du préchargement — play() s'y suspend (borné) à froid. */
  const loadPromiseRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadPromiseRef.current = (async () => {
      await loadEarconStyle();
      const jobs: Promise<void>[] = [];
      for (const style of EARCON_STYLES) {
        soundsRef.current[style] = {};
        for (const [name, src] of Object.entries(SOURCES[style]) as [EarconName, number][]) {
          jobs.push((async () => {
            try {
              // shouldPlay:false → on précharge sans jouer ; volume modéré.
              const { sound } = await Audio.Sound.createAsync(src, {
                shouldPlay: false,
                volume: 0.9,
              });
              if (cancelled) {
                sound.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
                return;
              }
              soundsRef.current[style]![name] = sound;
            } catch (e) {
              // Décodage/chargement échoué (vu iOS 26.6 : erreurs AVAsset
              // isPlayable au boot) → play(name) serait un no-op DÉFINITIF.
              // Loud : sans cette trace, « pas de earcon » est indiagnosticable.
              reportError(e, { domain: "audio", op: "earconLoad", extra: { style, name } }, { userFacing: "silent" });
            }
          })());
        }
      }
      await Promise.all(jobs);
      loadedRef.current = true;
    })();
    return () => {
      cancelled = true;
      const families = soundsRef.current;
      soundsRef.current = {};
      for (const fam of Object.values(families)) {
        for (const s of Object.values(fam ?? {})) {
          s?.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
        }
      }
    };
  }, []);

  const play = useCallback((name: EarconName) => {
    const fire = () => {
      const sound = soundsRef.current[currentStyle]?.[name];
      // Trace ring buffer : corréler un bip avec la fenêtre de grâce d'un
      // listen, et `loaded:false` = son jamais chargé (bip logué mais MUET).
      logEvent("audio", { op: "earcon", name, loaded: !!sound });
      if (!sound || typeof sound.replayAsync !== "function") return;
      // replayAsync rejoue depuis 0 même si déjà en cours — idéal pour des
      // earcons rapides rapprochés (ex. "tick" puis "done"). Fire-and-forget.
      sound.replayAsync().catch((e) =>
        reportError(e, { domain: "audio", op: "earconPlay", extra: { name } }, { userFacing: "silent" }));
    };
    if (!loadedRef.current && loadPromiseRef.current) {
      // Ouverture d'écran à froid : le préchargement des clips est encore en
      // cours — différer (borné) au lieu de skipper, sinon le TOUT PREMIER
      // earcon d'une surface est muet (device 2026-08-03, tick d'ouverture
      // du compose jamais entendu).
      // Le timer de secours est annulé dès que la course est tranchée : sans
      // ça, chaque earcon joué à froid laisse un handle vivant 1,5 s après
      // coup — inoffensif en prod, mais il maintient le worker Jest en vie
      // au-delà du teardown (« worker process failed to exit gracefully »).
      let fallbackId: ReturnType<typeof setTimeout> | undefined;
      Promise.race([
        loadPromiseRef.current,
        new Promise<void>((r) => { fallbackId = setTimeout(r, 1500); }),
      ]).then(fire, fire).finally(() => clearTimeout(fallbackId));
      return;
    }
    fire();
  }, []);

  return { play };
}
