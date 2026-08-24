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
 * Langue de dictée : défaut = langue préférée du destinataire (2026-06-23),
 * sinon AUTO-détection.
 *
 * Historique : le hint destinataire avait été retiré le 2026-06-11 (incident
 * prod : badge « En » pendant une dictée FR de 23 s → Deepgram épinglé en →
 * transcript vide). Il est RÉTABLI à la demande utilisateur (« le contact est
 * en français, le micro devrait déjà être en fr »), le risque d'origine étant
 * neutralisé en amont par le fallback auto-détection de useWhisperRecording
 * (re-essai en détection quand une langue épinglée renvoie un transcript vide
 * malgré de la parole). Le choix explicite du picker reste prioritaire.
 */
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { useVoiceLanguage } from './useVoiceLanguage'

describe('useVoiceLanguage — défaut', () => {
  it('sans défaut destinataire → auto', () => {
    const { result } = renderHook(() => useVoiceLanguage())
    expect(result.current.language).toBe('auto')
    expect(result.current.languageParam).toBe('auto')
  })

  it('défaut destinataire null → auto', () => {
    const { result } = renderHook(() => useVoiceLanguage(null))
    expect(result.current.language).toBe('auto')
  })

  it('le choix explicite du picker épingle la langue', () => {
    const { result } = renderHook(() => useVoiceLanguage())
    act(() => result.current.setLanguage('fr'))
    expect(result.current.language).toBe('fr')
    expect(result.current.languageParam).toBe('fr')
  })
})

describe('useVoiceLanguage — défaut destinataire (2026-06-23)', () => {
  it('un destinataire en français → micro démarre en fr', () => {
    const { result } = renderHook(() => useVoiceLanguage('fr'))
    expect(result.current.language).toBe('fr')
    expect(result.current.languageParam).toBe('fr')
  })

  it('le choix explicite du picker bat le défaut destinataire', () => {
    const { result } = renderHook(() => useVoiceLanguage('fr'))
    act(() => result.current.setLanguage('en'))
    expect(result.current.language).toBe('en')
  })

  it("choisir 'auto' explicitement force la détection malgré un destinataire pinné", () => {
    const { result } = renderHook(() => useVoiceLanguage('fr'))
    act(() => result.current.setLanguage('auto'))
    expect(result.current.language).toBe('auto')
    expect(result.current.languageParam).toBe('auto')
  })
})
