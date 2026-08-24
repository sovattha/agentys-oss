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
 * Tests pour les utilitaires OAuth (Story 1.2 + 1.3)
 *
 * Couvre:
 * - generatePKCE() - Génération PKCE avec SHA-256
 * - buildGoogleAuthUrl() - Construction URL OAuth Google
 * - buildMicrosoftAuthUrl() - Construction URL OAuth Microsoft
 * - tokensNeedRefresh() - Vérification expiration tokens
 * - storeTokens/getTokens/deleteTokens - Stockage keyring
 * - exchangeCodeForTokens() - Échange code contre tokens (Google)
 * - exchangeMicrosoftCodeForTokens() - Échange code contre tokens (Microsoft)
 * - refreshAccessToken() - Rafraîchissement tokens (Google)
 * - refreshMicrosoftAccessToken() - Rafraîchissement tokens (Microsoft)
 * - getMicrosoftUserEmail() - Récupération email via Graph API
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  generatePKCE,
  buildGoogleAuthUrl,
  buildMicrosoftAuthUrl,
  tokensNeedRefresh,
  storeTokens,
  getTokens,
  deleteTokens,
  exchangeCodeForTokens,
  exchangeMicrosoftCodeForTokens,
  refreshAccessToken,
  refreshMicrosoftAccessToken,
  getGoogleUserEmail,
  getMicrosoftUserEmail,
  type OAuthTokens,
  type PKCEChallenge,
} from '../services/oauth'

// Mock tauri-plugin-keyring-api
vi.mock('tauri-plugin-keyring-api', () => ({
  setPassword: vi.fn(),
  getPassword: vi.fn(),
  deletePassword: vi.fn(),
}))

import * as keyring from 'tauri-plugin-keyring-api'

const mockFetch = vi.fn()

describe('OAuth Utilities', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch)
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // ============================================================================
  // Tests generatePKCE
  // ============================================================================

  describe('generatePKCE', () => {
    it('genere un code verifier de longueur correcte', async () => {
      const pkce = await generatePKCE()

      // Code verifier doit être 64 caractères hex (32 bytes * 2)
      expect(pkce.codeVerifier).toHaveLength(64)
      expect(pkce.codeVerifier).toMatch(/^[0-9a-f]+$/)
    })

    it('genere un code challenge base64url valide', async () => {
      const pkce = await generatePKCE()

      // Code challenge doit être base64url sans padding
      expect(pkce.codeChallenge).toMatch(/^[A-Za-z0-9_-]+$/)
      expect(pkce.codeChallenge).not.toContain('=')
      expect(pkce.codeChallenge).not.toContain('+')
      expect(pkce.codeChallenge).not.toContain('/')
    })

    it('genere un state aleatoire', async () => {
      const pkce = await generatePKCE()

      // State doit être 32 caractères hex (16 bytes * 2)
      expect(pkce.state).toHaveLength(32)
      expect(pkce.state).toMatch(/^[0-9a-f]+$/)
    })

    it('genere des valeurs differentes a chaque appel', async () => {
      const pkce1 = await generatePKCE()
      const pkce2 = await generatePKCE()

      expect(pkce1.codeVerifier).not.toBe(pkce2.codeVerifier)
      expect(pkce1.codeChallenge).not.toBe(pkce2.codeChallenge)
      expect(pkce1.state).not.toBe(pkce2.state)
    })

    it('produit un hash SHA-256 correct pour le code challenge', async () => {
      const pkce = await generatePKCE()

      // Recalculer le hash pour vérifier
      const encoder = new TextEncoder()
      const data = encoder.encode(pkce.codeVerifier)
      const hash = await crypto.subtle.digest('SHA-256', data)

      // Convertir en base64url
      const bytes = new Uint8Array(hash)
      let binary = ''
      bytes.forEach((byte) => {
        binary += String.fromCharCode(byte)
      })
      const expected = btoa(binary)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '')

      expect(pkce.codeChallenge).toBe(expected)
    })
  })

  // ============================================================================
  // Tests buildGoogleAuthUrl
  // ============================================================================

  describe('buildGoogleAuthUrl', () => {
    const mockPKCE: PKCEChallenge = {
      codeVerifier: 'test_verifier_123',
      codeChallenge: 'test_challenge_abc',
      state: 'test_state_xyz',
    }

    it('construit une URL OAuth valide', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('https://accounts.google.com/o/oauth2/v2/auth')
      expect(url).toContain('client_id=client_id_123')
    })

    it('inclut les parametres PKCE', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('code_challenge=test_challenge_abc')
      expect(url).toContain('code_challenge_method=S256')
      expect(url).toContain('state=test_state_xyz')
    })

    it('inclut les scopes Gmail requis', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('gmail.readonly')
      expect(url).toContain('gmail.send')
      expect(url).toContain('gmail.compose')
      expect(url).toContain('userinfo.email')
    })

    it('does not request Google Contacts scopes', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)
      const scopes = new URL(url).searchParams.get('scope') || ''

      expect(scopes).not.toContain('contacts.readonly')
      expect(scopes).not.toContain('contacts.other.readonly')
    })

    it('utilise access_type=offline pour refresh token', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('access_type=offline')
    })

    it('utilise prompt=consent pour forcer re-consentement', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('prompt=consent')
    })

    it('utilise redirect_uri par defaut si non fourni', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      // In dev/test mode API_URL is empty (Vite proxy), so redirect_uri is a relative path
      expect(url).toContain('redirect_uri=')
      expect(url).toContain('gmail')
    })

    it('accepte un redirect_uri personnalise', () => {
      const url = buildGoogleAuthUrl(
        'client_id_123',
        mockPKCE,
        'http://custom.localhost:3000/callback'
      )

      expect(url).toContain(
        'redirect_uri=http%3A%2F%2Fcustom.localhost%3A3000%2Fcallback'
      )
    })

    it('encode correctement les parametres', () => {
      const url = buildGoogleAuthUrl('client_id_123', mockPKCE)

      // Les espaces dans les scopes doivent être encodés
      expect(url).toContain('scope=')
      // Vérifier que l'URL est bien formée (pas de caractères non échappés)
      expect(() => new URL(url)).not.toThrow()
    })
  })

  // ============================================================================
  // Tests tokensNeedRefresh
  // ============================================================================

  describe('tokensNeedRefresh', () => {
    const baseTokens: OAuthTokens = {
      access_token: 'test_access',
      refresh_token: 'test_refresh',
      expires_at: Date.now() + 3600 * 1000, // 1 heure
      scope: 'gmail.readonly',
      token_type: 'Bearer',
    }

    it('retourne false si les tokens expirent dans plus de 5 minutes', () => {
      const tokens = {
        ...baseTokens,
        expires_at: Date.now() + 10 * 60 * 1000, // 10 minutes
      }

      expect(tokensNeedRefresh(tokens)).toBe(false)
    })

    it('retourne true si les tokens expirent dans moins de 5 minutes', () => {
      const tokens = {
        ...baseTokens,
        expires_at: Date.now() + 4 * 60 * 1000, // 4 minutes
      }

      expect(tokensNeedRefresh(tokens)).toBe(true)
    })

    it('retourne true si les tokens sont expires', () => {
      const tokens = {
        ...baseTokens,
        expires_at: Date.now() - 1000, // 1 seconde dans le passé
      }

      expect(tokensNeedRefresh(tokens)).toBe(true)
    })

    it('retourne false exactement a 5 minutes avant expiration', () => {
      const tokens = {
        ...baseTokens,
        expires_at: Date.now() + 5 * 60 * 1000, // Exactement 5 minutes
      }

      // À la limite exacte, pas encore besoin de rafraîchir (condition >)
      expect(tokensNeedRefresh(tokens)).toBe(false)
    })

    it('retourne false a 5 minutes + 1ms avant expiration', () => {
      const tokens = {
        ...baseTokens,
        expires_at: Date.now() + 5 * 60 * 1000 + 1, // 5 minutes + 1ms
      }

      expect(tokensNeedRefresh(tokens)).toBe(false)
    })
  })

  // ============================================================================
  // Tests Token Storage (keyring)
  // ============================================================================

  describe('storeTokens', () => {
    const mockTokens: OAuthTokens = {
      access_token: 'ya29.test_access',
      refresh_token: '1//test_refresh',
      expires_at: Date.now() + 3600 * 1000,
      scope: 'gmail.readonly gmail.send',
      token_type: 'Bearer',
    }

    it('stocke les tokens dans le keyring', async () => {
      await storeTokens('gmail', 'account_123', mockTokens)

      expect(keyring.setPassword).toHaveBeenCalledWith(
        'agentys',
        'gmail:account_123',
        JSON.stringify(mockTokens)
      )
    })

    it('utilise le bon format de cle', async () => {
      await storeTokens('outlook', 'acc_456', mockTokens)

      expect(keyring.setPassword).toHaveBeenCalledWith(
        'agentys',
        'outlook:acc_456',
        expect.any(String)
      )
    })
  })

  describe('getTokens', () => {
    const mockTokens: OAuthTokens = {
      access_token: 'ya29.stored',
      refresh_token: '1//stored',
      expires_at: Date.now() + 3600 * 1000,
      scope: 'gmail.readonly',
      token_type: 'Bearer',
    }

    it('recupere les tokens du keyring', async () => {

      vi.mocked(keyring.getPassword).mockResolvedValue(JSON.stringify(mockTokens) as any)

      const result = await getTokens('gmail', 'account_123')

      expect(keyring.getPassword).toHaveBeenCalledWith(
        'agentys',
        'gmail:account_123'
      )
      expect(result).toEqual(mockTokens)
    })

    it('retourne null si aucun token stocke', async () => {
      vi.mocked(keyring.getPassword).mockResolvedValue(null)

      const result = await getTokens('gmail', 'unknown_account')

      expect(result).toBeNull()
    })

    it('retourne null en cas d erreur keyring', async () => {
      vi.mocked(keyring.getPassword).mockRejectedValue(new Error('Keyring error'))

      const result = await getTokens('gmail', 'error_account')

      expect(result).toBeNull()
    })
  })

  describe('deleteTokens', () => {
    it('supprime les tokens du keyring', async () => {
      await deleteTokens('gmail', 'account_to_delete')

      expect(keyring.deletePassword).toHaveBeenCalledWith(
        'agentys',
        'gmail:account_to_delete'
      )
    })

    it('ignore les erreurs si la cle n existe pas', async () => {
      vi.mocked(keyring.deletePassword).mockRejectedValue(
        new Error('Key not found')
      )

      // Ne doit pas lever d'erreur
      await expect(
        deleteTokens('gmail', 'nonexistent')
      ).resolves.toBeUndefined()
    })
  })

  // ============================================================================
  // Tests exchangeCodeForTokens
  // ============================================================================

  // TODO: update for new architecture — token exchange now happens server-side
  describe.skip('exchangeCodeForTokens', () => {
    it('echange le code contre des tokens', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'ya29.new_access',
          refresh_token: '1//new_refresh',
          expires_in: 3600,
          scope: 'gmail.readonly',
          token_type: 'Bearer',
        }),
      })

      const result = await exchangeCodeForTokens(
        'auth_code_123',
        'code_verifier_xyz',
        'client_id',
        'client_secret'
      )

      expect(mockFetch).toHaveBeenCalledWith(
        'https://oauth2.googleapis.com/token',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        })
      )
      expect(result.access_token).toBe('ya29.new_access')
      expect(result.refresh_token).toBe('1//new_refresh')
    })

    it('calcule expires_at correctement', async () => {
      const now = Date.now()
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'test',
          refresh_token: 'test',
          expires_in: 3600,
          scope: 'test',
          token_type: 'Bearer',
        }),
      })

      const result = await exchangeCodeForTokens(
        'code',
        'verifier',
        'id',
        'secret'
      )

      // expires_at doit être environ now + 3600 * 1000
      expect(result.expires_at).toBeGreaterThan(now)
      expect(result.expires_at).toBeLessThanOrEqual(now + 3600 * 1000 + 1000)
    })

    it('lance une erreur si l echange echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          error: 'invalid_grant',
          error_description: 'Code has expired',
        }),
      })

      await expect(
        exchangeCodeForTokens('expired_code', 'verifier', 'id', 'secret')
      ).rejects.toThrow('Code has expired')
    })

    it('utilise error si error_description absent', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          error: 'invalid_client',
        }),
      })

      await expect(
        exchangeCodeForTokens('code', 'verifier', 'bad_id', 'bad_secret')
      ).rejects.toThrow('invalid_client')
    })
  })

  // ============================================================================
  // Tests refreshAccessToken
  // ============================================================================

  // TODO: update for new architecture — token refresh now happens server-side
  describe.skip('refreshAccessToken', () => {
    it('rafraichit le token avec le refresh_token', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'ya29.refreshed',
          expires_in: 3600,
          scope: 'gmail.readonly',
          token_type: 'Bearer',
        }),
      })

      const result = await refreshAccessToken(
        '1//old_refresh',
        'client_id',
        'client_secret'
      )

      expect(mockFetch).toHaveBeenCalledWith(
        'https://oauth2.googleapis.com/token',
        expect.objectContaining({
          method: 'POST',
        })
      )
      expect(result.access_token).toBe('ya29.refreshed')
    })

    it('conserve l ancien refresh_token si Google n en retourne pas', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'ya29.refreshed',
          expires_in: 3600,
          scope: 'gmail.readonly',
          token_type: 'Bearer',
          // Pas de refresh_token dans la réponse
        }),
      })

      const result = await refreshAccessToken(
        '1//original_refresh',
        'client_id',
        'client_secret'
      )

      expect(result.refresh_token).toBe('1//original_refresh')
    })

    it('utilise le nouveau refresh_token si fourni', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'ya29.refreshed',
          refresh_token: '1//new_refresh',
          expires_in: 3600,
          scope: 'gmail.readonly',
          token_type: 'Bearer',
        }),
      })

      const result = await refreshAccessToken(
        '1//old_refresh',
        'client_id',
        'client_secret'
      )

      expect(result.refresh_token).toBe('1//new_refresh')
    })

    it('lance une erreur si le refresh echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          error: 'invalid_grant',
          error_description: 'Token has been revoked',
        }),
      })

      await expect(
        refreshAccessToken('revoked_token', 'id', 'secret')
      ).rejects.toThrow('Token has been revoked')
    })
  })

  // ============================================================================
  // Tests getGoogleUserEmail
  // ============================================================================

  describe('getGoogleUserEmail', () => {
    it('recupere l email de l utilisateur', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          email: 'user@gmail.com',
          verified_email: true,
        }),
      })

      const email = await getGoogleUserEmail('ya29.valid_token')

      expect(mockFetch).toHaveBeenCalledWith(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        {
          headers: { Authorization: 'Bearer ya29.valid_token' },
        }
      )
      expect(email).toBe('user@gmail.com')
    })

    it('lance une erreur si la requete echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
      })

      await expect(getGoogleUserEmail('invalid_token')).rejects.toThrow(
        'Failed to get user info'
      )
    })
  })

  // ============================================================================
  // Tests Microsoft / Outlook OAuth (Story 1.3)
  // ============================================================================

  describe('buildMicrosoftAuthUrl', () => {
    const mockPKCE: PKCEChallenge = {
      codeVerifier: 'test_verifier_123',
      codeChallenge: 'test_challenge_abc',
      state: 'test_state_xyz',
    }

    it('construit une URL OAuth Microsoft valide', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain(
        'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
      )
      expect(url).toContain('client_id=client_id_123')
    })

    it('inclut les parametres PKCE', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('code_challenge=test_challenge_abc')
      expect(url).toContain('code_challenge_method=S256')
      expect(url).toContain('state=test_state_xyz')
    })

    it('inclut les scopes Microsoft Graph requis', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('Mail.Read')
      expect(url).toContain('Mail.Send')
      expect(url).toContain('Mail.ReadWrite')
      expect(url).toContain('User.Read')
      expect(url).toContain('offline_access')
    })

    it('inclut openid pour recevoir un id_token Microsoft', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)
      const scopes = new URL(url).searchParams.get('scope')?.split(' ') ?? []

      expect(scopes).toContain('openid')
    })

    it('utilise response_mode=query', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)

      expect(url).toContain('response_mode=query')
    })

    it('utilise redirect_uri par defaut si non fourni', () => {
      const url = buildMicrosoftAuthUrl('client_id_123', mockPKCE)

      // In dev/test mode API_URL is empty (Vite proxy), so redirect_uri is a relative path
      expect(url).toContain('redirect_uri=')
      expect(url).toContain('outlook')
    })

    it('accepte un redirect_uri personnalise', () => {
      const url = buildMicrosoftAuthUrl(
        'client_id_123',
        mockPKCE,
        'http://custom.localhost:3000/callback'
      )

      expect(url).toContain(
        'redirect_uri=http%3A%2F%2Fcustom.localhost%3A3000%2Fcallback'
      )
    })
  })

  // TODO: update for new architecture — token exchange now happens server-side
  describe.skip('exchangeMicrosoftCodeForTokens', () => {
    it('echange le code Microsoft contre des tokens', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'eyJ0eXAiOi.microsoft.access',
          refresh_token: 'eyJ0eXAiOi.microsoft.refresh',
          expires_in: 3600,
          scope: 'Mail.Read Mail.Send',
          token_type: 'Bearer',
        }),
      })

      const result = await exchangeMicrosoftCodeForTokens(
        'auth_code_123',
        'code_verifier_xyz',
        'client_id',
        'client_secret'
      )

      expect(mockFetch).toHaveBeenCalledWith(
        'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        })
      )
      expect(result.access_token).toBe('eyJ0eXAiOi.microsoft.access')
      expect(result.refresh_token).toBe('eyJ0eXAiOi.microsoft.refresh')
    })

    it('lance une erreur si l echange Microsoft echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          error: 'invalid_grant',
          error_description: 'Microsoft: Code has expired',
        }),
      })

      await expect(
        exchangeMicrosoftCodeForTokens(
          'expired_code',
          'verifier',
          'id',
          'secret'
        )
      ).rejects.toThrow('Microsoft: Code has expired')
    })
  })

  // TODO: update for new architecture — token refresh now happens server-side
  describe.skip('refreshMicrosoftAccessToken', () => {
    it('rafraichit le token Microsoft avec le refresh_token', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'eyJ0eXAiOi.microsoft.refreshed',
          expires_in: 3600,
          scope: 'Mail.Read',
          token_type: 'Bearer',
        }),
      })

      const result = await refreshMicrosoftAccessToken(
        'old_refresh',
        'client_id',
        'client_secret'
      )

      expect(mockFetch).toHaveBeenCalledWith(
        'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        expect.objectContaining({
          method: 'POST',
        })
      )
      expect(result.access_token).toBe('eyJ0eXAiOi.microsoft.refreshed')
    })

    it('conserve l ancien refresh_token si Microsoft n en retourne pas', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'eyJ0eXAiOi.refreshed',
          expires_in: 3600,
          scope: 'Mail.Read',
          token_type: 'Bearer',
        }),
      })

      const result = await refreshMicrosoftAccessToken(
        'original_refresh',
        'client_id',
        'client_secret'
      )

      expect(result.refresh_token).toBe('original_refresh')
    })

    it('lance une erreur si le refresh Microsoft echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({
          error: 'invalid_grant',
          error_description: 'Microsoft token has been revoked',
        }),
      })

      await expect(
        refreshMicrosoftAccessToken('revoked_token', 'id', 'secret')
      ).rejects.toThrow('Microsoft token has been revoked')
    })
  })

  describe('getMicrosoftUserEmail', () => {
    it('recupere l email via Microsoft Graph API (mail)', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          mail: 'user@outlook.com',
          displayName: 'Test User',
        }),
      })

      const email = await getMicrosoftUserEmail('valid_microsoft_token')

      expect(mockFetch).toHaveBeenCalledWith(
        'https://graph.microsoft.com/v1.0/me',
        {
          headers: { Authorization: 'Bearer valid_microsoft_token' },
        }
      )
      expect(email).toBe('user@outlook.com')
    })

    it('recupere l email via userPrincipalName si mail absent', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          userPrincipalName: 'user@company.onmicrosoft.com',
          displayName: 'Test User',
        }),
      })

      const email = await getMicrosoftUserEmail('valid_token')

      expect(email).toBe('user@company.onmicrosoft.com')
    })

    it('lance une erreur si la requete Graph API echoue', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
      })

      await expect(getMicrosoftUserEmail('invalid_token')).rejects.toThrow(
        'Failed to get Microsoft user info'
      )
    })
  })
})
