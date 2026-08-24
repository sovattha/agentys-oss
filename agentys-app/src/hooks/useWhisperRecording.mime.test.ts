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

// Régression cross-browser (2026-06-11) : le fallback d'enregistrement était
// `audio/webm` codé en dur — Safari (< 18.4) ne sait pas enregistrer webm
// (il produit de l'AAC en conteneur mp4), donc `new MediaRecorder(stream,
// { mimeType: 'audio/webm' })` y levait NotSupportedError et la dictée ne
// démarrait jamais. De plus le fichier uploadé s'appelait toujours
// `recording.webm` : le fallback OpenAI Whisper côté backend infère le
// décodeur depuis l'extension et aurait rejeté un mp4 ainsi nommé.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { pickRecordingMimeType, transcribeFilename } from './useWhisperRecording'

vi.mock('../services/uiSounds', () => ({ playUISound: vi.fn() }))
vi.mock('../services/micPermission', () => ({
  queryMicPermissionState: vi.fn().mockResolvedValue('granted'),
  hasUserAcknowledgedMicSoftAsk: vi.fn().mockReturnValue(true),
  setUserAcknowledgedMicSoftAsk: vi.fn(),
}))

function stubMediaRecorder(supported: (type: string) => boolean) {
  vi.stubGlobal('MediaRecorder', {
    isTypeSupported: (type: string) => supported(type),
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('pickRecordingMimeType — choix du conteneur par navigateur', () => {
  it('Chrome/Edge/Firefox : webm+opus en premier choix', () => {
    stubMediaRecorder(() => true)
    expect(pickRecordingMimeType()).toBe('audio/webm;codecs=opus')
  })

  it('Safari ≤ 18.3 : aucun webm → bascule sur mp4/AAC au lieu de throw', () => {
    stubMediaRecorder(type => type.startsWith('audio/mp4'))
    expect(pickRecordingMimeType()).toBe('audio/mp4;codecs=mp4a.40.2')
  })

  it('aucun candidat supporté → undefined (le navigateur choisit son défaut natif)', () => {
    stubMediaRecorder(() => false)
    expect(pickRecordingMimeType()).toBeUndefined()
  })

  it('MediaRecorder absent (vieux webview) → undefined sans throw', () => {
    vi.stubGlobal('MediaRecorder', undefined)
    expect(pickRecordingMimeType()).toBeUndefined()
  })
})

describe('transcribeFilename — extension alignée sur le conteneur réel', () => {
  it('webm → recording.webm', () => {
    expect(transcribeFilename('audio/webm;codecs=opus')).toBe('recording.webm')
    expect(transcribeFilename('audio/webm')).toBe('recording.webm')
  })

  it('mp4 Safari → recording.mp4', () => {
    expect(transcribeFilename('audio/mp4')).toBe('recording.mp4')
    expect(transcribeFilename('audio/mp4;codecs=mp4a.40.2')).toBe('recording.mp4')
  })

  it('ogg Firefox natif → recording.ogg', () => {
    expect(transcribeFilename('audio/ogg;codecs=opus')).toBe('recording.ogg')
  })

  it('type vide ou inconnu → défaut webm (comportement historique)', () => {
    expect(transcribeFilename('')).toBe('recording.webm')
    expect(transcribeFilename('application/octet-stream')).toBe('recording.webm')
  })
})
