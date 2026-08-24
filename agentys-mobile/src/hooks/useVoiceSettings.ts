/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * Gestion des paramètres voix TTS (ElevenLabs).
 *
 * Persistance SecureStore (mêmes clés que l'ancien hook expo-speech pour
 * continuité) :
 *   - voice_id                  → voice_id ElevenLabs sélectionné
 *   - voice_rate                → playback rate 0.5 … 1.5
 *   - voice_auto_advance        → bool
 *   - voice_auto_advance_delay  → seconds
 *
 * La liste des voix est fetch depuis le backend (`GET /api/tts/voices`).
 * Le preview appelle `/api/tts/speak` avec un texte court, lecture via expo-av.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Audio } from "expo-av";
import * as SecureStore from "expo-secure-store";
import {
  listVoices as listVoicesBackend,
  speak as speakBackend,
  cloneVoice as cloneVoiceBackend,
  deleteVoice as deleteVoiceBackend,
  audioAuthHeaders,
} from "../services/tts";
import type { TtsVoice } from "../types";
import i18n from "../i18n";

const PREVIEW_TEXTS: Record<string, string> = {
  fr: "Bonjour, voici un aperçu de cette voix.",
  en: "Hello, here is a preview of this voice.",
};

function getPreviewText(): string {
  const lang = (i18n.language || "en").split(/[-_]/)[0];
  return PREVIEW_TEXTS[lang] ?? PREVIEW_TEXTS.en;
}

export interface VoiceSettings {
  availableVoices: TtsVoice[];
  voicesLoading: boolean;
  voicesError: string | null;
  selectedVoice: string | null;
  speechRate: number;
  autoAdvance: boolean;
  autoAdvanceDelay: number;
  ttsAccent: string | undefined;
  setVoice: (id: string) => Promise<void>;
  setSpeechRate: (rate: number) => Promise<void>;
  setAutoAdvance: (val: boolean) => Promise<void>;
  setAutoAdvanceDelay: (seconds: number) => Promise<void>;
  setTtsAccent: (accent: string | undefined) => Promise<void>;
  previewVoice: (voiceId: string) => Promise<void>;
  refreshVoices: () => Promise<void>;
  cloneVoice: (name: string, sampleUris: string[], description?: string) => Promise<TtsVoice>;
  deleteVoice: (voiceId: string) => Promise<void>;
}

function sortVoices(voices: TtsVoice[]): TtsVoice[] {
  return [...voices].sort((a, b) => {
    // clonées > premade > autre, puis tri alphabétique
    const rank = (v: TtsVoice) =>
      v.category === "cloned" ? 0 : v.category === "premade" ? 1 : 2;
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
}

export function useVoiceSettings(): VoiceSettings {
  const [availableVoices, setAvailableVoices] = useState<TtsVoice[]>([]);
  const [voicesLoading, setVoicesLoading] = useState(true);
  const [voicesError, setVoicesError] = useState<string | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string | null>(null);
  const [speechRate, setSpeechRateState] = useState(1.0);
  const [autoAdvance, setAutoAdvanceState] = useState(true);
  const [autoAdvanceDelay, setAutoAdvanceDelayState] = useState(2);
  const [ttsAccent, setTtsAccentState] = useState<string | undefined>(undefined);

  const previewSoundRef = useRef<Audio.Sound | null>(null);
  const speechRateRef = useRef(1.0);

  const refreshVoices = useCallback(async () => {
    setVoicesLoading(true);
    setVoicesError(null);
    try {
      const voices = await listVoicesBackend();
      const sorted = sortVoices(voices);
      setAvailableVoices(sorted);

      // Auto-sélection si aucune voix persistée : on prend la 1ère clonée sinon la 1ère premade
      const stored = await SecureStore.getItemAsync("voice_id");
      if (stored) {
        if (sorted.some((v) => v.voice_id === stored)) {
          setSelectedVoice(stored);
        } else {
          // La voix persistée n'existe plus (supprimée) → reset
          await SecureStore.deleteItemAsync("voice_id");
          setSelectedVoice(null);
        }
      }
      if (!stored && sorted.length > 0) {
        const preferred = sorted.find((v) => v.category === "cloned") ?? sorted[0];
        setSelectedVoice(preferred.voice_id);
        await SecureStore.setItemAsync("voice_id", preferred.voice_id);
      }
    } catch (err: any) {
      setVoicesError(err?.message || i18n.t("voice:errors.cannotLoadVoices") as string);
    } finally {
      setVoicesLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshVoices().catch(() => {}); // no-op légitime : refresh best-effort, l'UI garde la liste courante
    Promise.all([
      SecureStore.getItemAsync("voice_rate"),
      SecureStore.getItemAsync("voice_auto_advance"),
      SecureStore.getItemAsync("voice_auto_advance_delay"),
      SecureStore.getItemAsync("voice_accent"),
    ])
      .then(([rate, advance, delay, accent]) => {
        if (rate) {
          const parsed = parseFloat(rate);
          setSpeechRateState(parsed);
          speechRateRef.current = parsed;
        }
        if (advance !== null) setAutoAdvanceState(advance === "true");
        if (delay) setAutoAdvanceDelayState(parseInt(delay, 10));
        if (accent) setTtsAccentState(accent);
      })
      .catch(() => {}); // no-op légitime : chargement voix best-effort

    return () => {
      previewSoundRef.current?.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
      previewSoundRef.current = null;
    };
  }, [refreshVoices]);

  const setVoice = useCallback(async (id: string) => {
    setSelectedVoice(id);
    await SecureStore.setItemAsync("voice_id", id);
  }, []);

  const setSpeechRate = useCallback(async (rate: number) => {
    setSpeechRateState(rate);
    speechRateRef.current = rate;
    await SecureStore.setItemAsync("voice_rate", String(rate));
  }, []);

  const setAutoAdvance = useCallback(async (val: boolean) => {
    setAutoAdvanceState(val);
    await SecureStore.setItemAsync("voice_auto_advance", String(val));
  }, []);

  const setAutoAdvanceDelay = useCallback(async (seconds: number) => {
    setAutoAdvanceDelayState(seconds);
    await SecureStore.setItemAsync("voice_auto_advance_delay", String(seconds));
  }, []);

  const setTtsAccent = useCallback(async (accent: string | undefined) => {
    setTtsAccentState(accent);
    if (accent) await SecureStore.setItemAsync("voice_accent", accent);
    else await SecureStore.deleteItemAsync("voice_accent");
  }, []);

  const previewVoice = useCallback(
    async (voiceId: string) => {
      // Arrêter un preview précédent
      if (previewSoundRef.current) {
        await previewSoundRef.current.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
        previewSoundRef.current = null;
      }
      try {
        const stored = await SecureStore.getItemAsync("voice_accent");
        const baseLang = (i18n.language || "").split(/[-_]/)[0] || undefined;
        const languageCode = stored ?? (baseLang === "fr" ? "fr-FR" : baseLang);
        const { audioUrl } = await speakBackend(getPreviewText(), voiceId, undefined, languageCode);
        const headers = await audioAuthHeaders();
        const { sound } = await Audio.Sound.createAsync(
          { uri: audioUrl, headers },
          { shouldPlay: true, rate: speechRateRef.current, shouldCorrectPitch: true },
        );
        previewSoundRef.current = sound;
        sound.setOnPlaybackStatusUpdate((status) => {
          if ("isLoaded" in status && status.isLoaded && status.didJustFinish) {
            sound.unloadAsync().catch(() => {}); // no-op légitime : son déjà libéré
            if (previewSoundRef.current === sound) previewSoundRef.current = null;
          }
        });
      } catch (err) {
        // silencieux — le preview ne doit pas casser l'UI
        console.warn("[tts] preview failed:", err);
      }
    },
    [],
  );

  const cloneVoice = useCallback(
    async (name: string, sampleUris: string[], description?: string): Promise<TtsVoice> => {
      const { voiceId } = await cloneVoiceBackend(name, sampleUris, description);
      await refreshVoices();
      // Sélectionner automatiquement la nouvelle voix
      await SecureStore.setItemAsync("voice_id", voiceId);
      setSelectedVoice(voiceId);
      return {
        voice_id: voiceId,
        name,
        category: "cloned",
        preview_url: null,
        labels: null,
        language: null,
      };
    },
    [refreshVoices],
  );

  const deleteVoice = useCallback(
    async (voiceId: string) => {
      await deleteVoiceBackend(voiceId);
      if (selectedVoice === voiceId) {
        await SecureStore.deleteItemAsync("voice_id");
        setSelectedVoice(null);
      }
      await refreshVoices();
    },
    [refreshVoices, selectedVoice],
  );

  return {
    availableVoices,
    voicesLoading,
    voicesError,
    selectedVoice,
    speechRate,
    autoAdvance,
    autoAdvanceDelay,
    ttsAccent,
    setVoice,
    setSpeechRate,
    setAutoAdvance,
    setAutoAdvanceDelay,
    setTtsAccent,
    previewVoice,
    refreshVoices,
    cloneVoice,
    deleteVoice,
  };
}
