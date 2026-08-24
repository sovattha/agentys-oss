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
 * Filet de sécurité « langue épinglée → transcript vide → rejouer en auto ».
 *
 * C'est ce qui rend SÛR le défaut destinataire (2026-06-23) : un mauvais pin qui
 * fait rendre un transcript VIDE par Deepgram est rattrapé en auto-détection
 * (incident 2026-06-11 : pinné En, parlé Fr 23 s → vide, dictée perdue).
 * On teste la décision PURE ; cf. useVoiceLanguage.test.ts pour le défaut.
 * Limite assumée : le transcript NON-vide mais mal transcrit (charabia) n'est
 * PAS couvert — c'est ce que ce test verrouille explicitement.
 */
import { describe, it, expect } from 'vitest'
import { shouldRetryAutoDetectOnEmpty } from './useWhisperRecording'

describe('shouldRetryAutoDetectOnEmpty', () => {
  it('langue épinglée + parole + vide → rejoue en auto', () => {
    expect(shouldRetryAutoDetectOnEmpty('fr', true, '')).toBe(true)
    expect(shouldRetryAutoDetectOnEmpty('fr', true, '   ')).toBe(true)
    expect(shouldRetryAutoDetectOnEmpty('fr', true, undefined)).toBe(true)
    expect(shouldRetryAutoDetectOnEmpty('en', true, '')).toBe(true)
  })

  it("transcript NON-vide → ne rejoue pas (le charabia n'est volontairement PAS rattrapé)", () => {
    expect(shouldRetryAutoDetectOnEmpty('fr', true, 'you just got some of these')).toBe(false)
    expect(shouldRetryAutoDetectOnEmpty('fr', true, 'Bonjour')).toBe(false)
  })

  it("'auto' / '' / undefined ne sont pas des pins → jamais de rejoue, même si vide", () => {
    expect(shouldRetryAutoDetectOnEmpty('auto', true, '')).toBe(false)
    expect(shouldRetryAutoDetectOnEmpty('', true, '')).toBe(false)
    expect(shouldRetryAutoDetectOnEmpty(undefined, true, '')).toBe(false)
  })

  it('aucune parole détectée → ne rejoue pas (évite un aller-retour sur un vrai silence)', () => {
    expect(shouldRetryAutoDetectOnEmpty('fr', false, '')).toBe(false)
  })
})
