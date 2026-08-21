import { useState, useEffect, useCallback } from 'react'
import { API_URL } from '../config'

const UPDATE_CHECK_KEY = 'agentys_last_update_check'
const UPDATE_DISMISSED_KEY = 'agentys_update_dismissed_version'
const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000 // 4 hours

interface UpdateInfo {
  hasUpdate: boolean
  currentVersion: string
  latestVersion: string
  releaseUrl: string
  releaseNotes: string
  checkingForUpdate: boolean
}

// __APP_VERSION__ is injected by Vite's `define` at build time.
// Guard for test environments where the define may not be applied.
const CURRENT_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0-dev'

/**
 * Check for updates by comparing current version with /api/ping version
 * or a remote update endpoint.
 */
export function useUpdateChecker(): UpdateInfo & { checkNow: () => void; dismissUpdate: () => void } {
  const [hasUpdate, setHasUpdate] = useState(false)
  const [latestVersion, setLatestVersion] = useState('')
  const [releaseUrl, setReleaseUrl] = useState('')
  const [releaseNotes, setReleaseNotes] = useState('')
  const [checkingForUpdate, setCheckingForUpdate] = useState(false)

  const checkForUpdate = useCallback(async () => {
    setCheckingForUpdate(true)
    try {
      // Check backend /api/update-check endpoint
      const response = await fetch(`${API_URL}/api/update-check`)
      if (response.ok) {
        const data = await response.json()
        const dismissed = localStorage.getItem(UPDATE_DISMISSED_KEY)
        if (data.has_update && data.latest_version !== dismissed) {
          setHasUpdate(true)
          setLatestVersion(data.latest_version || '')
          setReleaseUrl(data.release_url || '')
          setReleaseNotes(data.release_notes || '')
        } else {
          setHasUpdate(false)
        }
      }
      localStorage.setItem(UPDATE_CHECK_KEY, Date.now().toString())
    } catch {
      // Silently fail - update check is non-critical
    } finally {
      setCheckingForUpdate(false)
    }
  }, [])

  const dismissUpdate = useCallback(() => {
    if (latestVersion) {
      localStorage.setItem(UPDATE_DISMISSED_KEY, latestVersion)
    }
    setHasUpdate(false)
  }, [latestVersion])

  useEffect(() => {
    // Check if enough time has passed since last check
    const lastCheck = parseInt(localStorage.getItem(UPDATE_CHECK_KEY) || '0', 10)
    const now = Date.now()
    if (now - lastCheck > CHECK_INTERVAL_MS) {
      checkForUpdate()
    }
  }, [checkForUpdate])

  return {
    hasUpdate,
    currentVersion: CURRENT_VERSION,
    latestVersion,
    releaseUrl,
    releaseNotes,
    checkingForUpdate,
    checkNow: checkForUpdate,
    dismissUpdate,
  }
}
