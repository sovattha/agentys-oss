/**
 * Client TTS — proxy ElevenLabs côté backend.
 *
 * La clé API ElevenLabs reste sur le serveur. Ici on ne fait que consommer
 * l'API interne : liste des voix, synthèse (retourne une URL MP3 authentifiée),
 * clonage de voix, suppression.
 */

import * as SecureStore from "expo-secure-store";
import { API_URL } from "../config";
import { getToken, clearToken } from "./auth";
import type { TtsVoice, TtsSpeakResponse } from "../types";

async function jsonHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Headers à passer à `Audio.Sound.createAsync({ uri, headers })` pour
 * que expo-av puisse télécharger le MP3 authentifié.
 */
export async function audioAuthHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handleJson<T>(res: Response, op: string): Promise<T> {
  if (res.status === 401) {
    await clearToken();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${op} HTTP ${res.status}`);
  }
  return res.json();
}

export async function listVoices(): Promise<TtsVoice[]> {
  const headers = await jsonHeaders();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${API_URL}/api/tts/voices`, {
      headers,
      signal: controller.signal,
    });
    const data = await handleJson<{ voices: TtsVoice[] }>(res, "listVoices");
    return data.voices ?? [];
  } finally {
    clearTimeout(timeout);
  }
}

export async function speak(
  text: string,
  voiceId: string,
  modelId?: string,
  languageCode?: string,
): Promise<{ audioUrl: string; cached: boolean; chars: number }> {
  const headers = await jsonHeaders();
  const controller = new AbortController();
  // 45s : cache miss ElevenLabs peut prendre 1-3s, mais on garde de la marge
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const res = await fetch(`${API_URL}/api/tts/speak`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        text,
        voice_id: voiceId,
        ...(modelId ? { model_id: modelId } : {}),
        ...(languageCode ? { language_code: languageCode } : {}),
      }),
      signal: controller.signal,
    });
    const data = await handleJson<TtsSpeakResponse>(res, "speak");
    return {
      audioUrl: `${API_URL}${data.audio_url}`,
      cached: data.cached,
      chars: data.chars,
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function cloneVoice(
  name: string,
  sampleUris: string[],
  description?: string,
): Promise<{ voiceId: string; name: string }> {
  const token = await getToken();
  const formData = new FormData();
  formData.append("name", name);
  if (description) formData.append("description", description);

  sampleUris.forEach((uri, idx) => {
    formData.append("files", {
      uri,
      name: `sample_${idx}.m4a`,
      type: "audio/m4a",
    } as any);
  });

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000); // 2min — cloning is slow
  try {
    const res = await fetch(`${API_URL}/api/tts/clone`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
      signal: controller.signal,
    });
    if (res.status === 401) {
      await clearToken();
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `cloneVoice HTTP ${res.status}`);
    }
    const data = await res.json();
    return { voiceId: data.voice_id, name: data.name };
  } catch (err: any) {
    if (err.name === "AbortError") {
      throw new Error("Timeout — le clonage prend trop de temps");
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Retourne le voice_id stocké. Si absent (premier lancement), auto-sélectionne
 * la première voix disponible et la persiste dans SecureStore.
 */
export async function ensureVoiceId(): Promise<string | null> {
  try {
    const stored = await SecureStore.getItemAsync("voice_id");
    if (stored) return stored;
    const voices = await listVoices();
    if (voices.length === 0) return null;
    const preferred = voices.find((v) => v.category === "cloned") ?? voices[0];
    await SecureStore.setItemAsync("voice_id", preferred.voice_id);
    return preferred.voice_id;
  } catch {
    // fallback légitime : pas de voix sélectionnable → l'appelant gère null
    return null;
  }
}

export async function deleteVoice(voiceId: string): Promise<void> {
  const headers = await jsonHeaders();
  const res = await fetch(`${API_URL}/api/tts/voices/${voiceId}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) {
    await clearToken();
    throw new Error("Unauthorized");
  }
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `deleteVoice HTTP ${res.status}`);
  }
}
