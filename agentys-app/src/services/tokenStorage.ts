/**
 * Token Storage Abstraction for Agentys
 *
 * Provides a unified interface for token storage that works in both:
 * - Web browser: Uses backend server-side storage via API
 * - Tauri app: Uses OS Keychain via tauri-plugin-keyring
 *
 * The abstraction automatically detects the runtime environment.
 */

import { API_URL } from '../config'
import { getAuthHeaders } from './authToken'

export interface TokenStatus {
  hasTokens: boolean
  isValid: boolean
  email?: string
  provider?: string
  expiresIn?: number
}

export interface TokenStorage {
  /**
   * Check if tokens exist and are valid for an account
   */
  getStatus(accountId: string): Promise<TokenStatus>

  /**
   * Trigger token refresh on the server
   */
  refresh(accountId: string): Promise<boolean>

  /**
   * Delete tokens for an account
   */
  delete(accountId: string): Promise<boolean>
}

/**
 * Detect if running inside Tauri (covers both Tauri 1's `__TAURI__` and Tauri 2's
 * `__TAURI_INTERNALS__`). Without this, `getTokenStorage()` always returned the
 * Web implementation under Tauri 2 and the OS keyring path was dead code (audit
 * Codex 2026-04-25 [F-INFO-14]).
 */
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  return '__TAURI__' in window || '__TAURI_INTERNALS__' in window
}

/**
 * Web-based token storage using backend API
 * Tokens are stored server-side, encrypted
 */
class WebTokenStorage implements TokenStorage {
  async getStatus(accountId: string): Promise<TokenStatus> {
    try {
      const response = await fetch(`${API_URL}/api/oauth/tokens/${accountId}/status`, {
        headers: { ...getAuthHeaders() },
      })
      if (!response.ok) {
        return { hasTokens: false, isValid: false }
      }

      const data = await response.json()
      return {
        hasTokens: data.has_tokens,
        isValid: data.is_valid,
        email: data.email,
        provider: data.provider,
        expiresIn: data.expires_in,
      }
    } catch (error) {
      console.error('[TokenStorage] Failed to get status:', error)
      return { hasTokens: false, isValid: false }
    }
  }

  async refresh(accountId: string): Promise<boolean> {
    try {
      const response = await fetch(`${API_URL}/api/oauth/tokens/${accountId}/refresh`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
      })
      return response.ok
    } catch (error) {
      console.error('[TokenStorage] Failed to refresh:', error)
      return false
    }
  }

  async delete(accountId: string): Promise<boolean> {
    try {
      const response = await fetch(`${API_URL}/api/oauth/${accountId}/disconnect`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
      })
      return response.ok
    } catch (error) {
      console.error('[TokenStorage] Failed to delete:', error)
      return false
    }
  }
}

/**
 * Tauri-based token storage using OS Keychain
 * Falls back to Web storage for token management
 */
class TauriTokenStorage implements TokenStorage {
  private webStorage = new WebTokenStorage()

  async getStatus(accountId: string): Promise<TokenStatus> {
    // Try local keyring first for faster check
    try {
      // Dynamic import to avoid bundler issues in web
      const keyring = await import('tauri-plugin-keyring-api')
      const providers = ['gmail', 'outlook']

      for (const provider of providers) {
        const key = `${provider}:${accountId}`
        try {
          const value = await keyring.getPassword('agentys', key)
          if (value) {
            const tokens = JSON.parse(value)
            const isValid = Date.now() < tokens.expires_at - 5 * 60 * 1000
            return {
              hasTokens: true,
              isValid,
              provider,
              expiresIn: Math.max(0, Math.floor((tokens.expires_at - Date.now()) / 1000)),
            }
          }
        } catch {
          // Key not found, continue
        }
      }

      // Fallback to server check
      return this.webStorage.getStatus(accountId)
    } catch {
      // Keyring not available, use web storage
      return this.webStorage.getStatus(accountId)
    }
  }

  async refresh(accountId: string): Promise<boolean> {
    // Server handles refresh, we just need to update local cache
    const success = await this.webStorage.refresh(accountId)
    if (success) {
      // Fetch new tokens and update local keyring
      // This is handled by the OAuth flow, not here
    }
    return success
  }

  async delete(accountId: string): Promise<boolean> {
    try {
      // Delete from local keyring
      const keyring = await import('tauri-plugin-keyring-api')
      const providers = ['gmail', 'outlook']

      for (const provider of providers) {
        const key = `${provider}:${accountId}`
        try {
          await keyring.deletePassword('agentys', key)
        } catch {
          // Key not found, continue
        }
      }
    } catch {
      // Keyring not available
    }

    // Also delete from server
    return this.webStorage.delete(accountId)
  }
}

/**
 * Get the appropriate token storage implementation
 * based on the current runtime environment
 */
let _tokenStorage: TokenStorage | null = null

export function getTokenStorage(): TokenStorage {
  if (!_tokenStorage) {
    _tokenStorage = isTauri() ? new TauriTokenStorage() : new WebTokenStorage()
  }
  return _tokenStorage
}

/**
 * Convenience function to check token status
 */
export async function checkTokenStatus(accountId: string): Promise<TokenStatus> {
  return getTokenStorage().getStatus(accountId)
}

/**
 * Convenience function to refresh tokens
 */
export async function refreshTokens(accountId: string): Promise<boolean> {
  return getTokenStorage().refresh(accountId)
}

/**
 * Convenience function to delete tokens
 */
export async function deleteTokens(accountId: string): Promise<boolean> {
  return getTokenStorage().delete(accountId)
}
