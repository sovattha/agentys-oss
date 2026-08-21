import { useState, useEffect, useCallback, useRef } from 'react'
import { apiClient, type Email } from '../services/api'
import { API_URL } from '../config'
import { getAuthHeaders, getStoredToken } from '../services/authToken'
import { cacheWrite } from '../api/cache'
import { ACCOUNT_INVALID_EVENT, setActiveAccountId, getEmailListCacheKey } from '../api/emails'
import { setAccountIdMap } from '../lib/accountIdMap'
import {
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
} from '../lib/storageKeys'
const INITIAL_RETRY_COUNT = 3
const INITIAL_RETRY_DELAY = 2000 // 2s, 4s, 8s (exponential)
// Reconnect backoff: starts at 2s, doubles each attempt, caps at 60s, ±20% jitter.
// Prevents thundering-herd when many clients reconnect after a backend restart.
const RECONNECT_BASE_DELAY = 2000
const RECONNECT_MAX_DELAY = 60000
// Post-OAuth race guard: if we land on the wizard without an accountId yet
// (fresh Google OAuth, backend still registering the account), poll /api/init
// until the account appears. Without this, the wizard shows "En attente des
// informations du compte..." indefinitely and forces a manual page refresh.
// Timeout is deliberately generous (2 min) because Google's consent screen
// can take 30-60s by itself — a shorter window caused users to get stuck
// before their OAuth round-trip finished.
const ACCOUNT_POLL_INTERVAL = 3000
const ACCOUNT_POLL_MAX_ATTEMPTS = 40 // 40 × 3s = 120s total

export interface BackendConnectionState {
  backendStatus: 'checking' | 'connected' | 'disconnected'
  version: string
  showWizard: boolean
  checkingOnboarding: boolean
  recentEmails: Email[]
  unreadCount: number
  spamCount: number
  accountEmail: string
  accountId: number | null
  needsAccountSetup: boolean
  setShowWizard: (v: boolean) => void
  setRecentEmails: React.Dispatch<React.SetStateAction<Email[]>>
  setUnreadCount: React.Dispatch<React.SetStateAction<number>>
  handleWizardComplete: () => void
  handleWizardSkip: () => void
  recheckConnection: () => void
  refreshAccountData: () => Promise<void>
}

export function useBackendConnection(): BackendConnectionState {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking')
  const [version, setVersion] = useState('')
  const [showWizard, setShowWizard] = useState(false)
  const [checkingOnboarding, setCheckingOnboarding] = useState(true)
  const [recentEmails, setRecentEmails] = useState<Email[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [accountEmail, setAccountEmail] = useState('')
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [accountId, setAccountId] = useState<any>(null)
  const [needsAccountSetup, setNeedsAccountSetup] = useState(false)
  const [spamCount, setSpamCount] = useState(0)

  const handleWizardComplete = useCallback(() => {
    localStorage.setItem(ONBOARDING_COMPLETE_KEY, 'true')
    setShowWizard(false)
  }, [])

  const handleWizardSkip = useCallback(() => {
    localStorage.setItem(ONBOARDING_COMPLETE_KEY, 'true')
    setShowWizard(false)
  }, [])

  // Retry-aware ping: tries up to INITIAL_RETRY_COUNT with exponential backoff
  const pingWithRetry = useCallback(async (): Promise<Response | null> => {
    for (let attempt = 0; attempt <= INITIAL_RETRY_COUNT; attempt++) {
      try {
        const res = await fetch(`${API_URL}/api/ping`, { signal: AbortSignal.timeout(5000) })
        if (res.ok) return res
      } catch { /* retry */ }
      if (attempt < INITIAL_RETRY_COUNT) {
        await new Promise(r => setTimeout(r, INITIAL_RETRY_DELAY * Math.pow(2, attempt)))
      }
    }
    return null
  }, [])

  const checkBackendAndOnboarding = useCallback(async () => {
    const localOnboardingComplete = localStorage.getItem(ONBOARDING_COMPLETE_KEY) === 'true'
    // Capture the token before any async work. If the user reconnects while
    // pingWithRetry is retrying (up to 15s), the token in localStorage will
    // change. We use this snapshot to avoid dispatching auth:unauthorized from
    // a stale check that used an old (expired) token.
    const tokenAtCallTime = getStoredToken()

    try {
      // Ping with retry (handles slow backend startup)
      const pingResponse = await pingWithRetry()

      if (!pingResponse) {
        setBackendStatus('disconnected')
        setCheckingOnboarding(false)
        return
      }

      // Success — fetch wizard + init in parallel (with auth headers for cloud mode).
      // IMPORTANT: raw fetch() with .catch(()=>null) previously swallowed 401 silently,
      // leaving the user stuck on the "En attente des informations du compte" screen
      // when the JWT expired. We now inspect the 401 status and dispatch the same
      // auth:unauthorized event the apiClient uses, so App.tsx can logout + redirect.
      const authHeaders = getAuthHeaders()
      // Skip authed endpoints when there's no JWT yet — without this, every
      // first-paint in incognito / fresh tab fires /api/init + /api/wizard/status
      // unauthenticated → the backend returns 401 → console fills with red errors
      // before the user has even clicked "Connect Gmail". The auth:login_success
      // listener below re-runs this whole function the moment a JWT lands, so
      // skipping here is safe — we just defer the real fetches.
      const hasJwt = !!tokenAtCallTime
      const check401 = (r: Response | null) => {
        if (r?.status === 401) {
          // Only logout if the token hasn't changed since this check started.
          // If the user reconnected while pingWithRetry was retrying, their new
          // JWT is valid — dispatching auth:unauthorized would incorrectly flash
          // the login page right after a successful login.
          if (getStoredToken() === tokenAtCallTime) {
            window.dispatchEvent(new CustomEvent('auth:unauthorized'))
          }
          return null
        }
        return r
      }
      const [wizardResponse, initResponse] = await Promise.all([
        !localOnboardingComplete && hasJwt
          ? fetch(`${API_URL}/api/wizard/status`, { headers: authHeaders }).then(check401).catch(() => null)
          : Promise.resolve(null),
        hasJwt
          ? fetch(`${API_URL}/api/init`, { headers: authHeaders }).then(check401).catch(() => null)
          : Promise.resolve(null),
      ])

      const [pingData, wizardData, initData] = await Promise.all([
        pingResponse.json().catch(() => ({ version: '0.1.0' })),
        wizardResponse?.ok ? wizardResponse.json().catch(() => null) : Promise.resolve(null),
        initResponse?.ok ? initResponse.json().catch(() => null) : Promise.resolve(null),
      ])

      setVersion(pingData.version || '0.1.0')
      setBackendStatus('connected')

      // Wizard check — when there's no JWT yet (hasJwt=false), we deliberately
      // skipped both authed calls above. Don't decide wizard state here: defer
      // to the auth:login_success listener which will re-run this function
      // with a real JWT. Without this guard we'd default `setShowWizard(true)`
      // and then immediately get bounced to LoginPage by the auth gate, but
      // the leftover wizard state would briefly flash if auth resolves later.
      if (localOnboardingComplete) {
        setShowWizard(false)
        // Ensure KB onboarding flag is also set when main onboarding is already done.
        // Prevents the PremiumOnboarding (po-shell) from re-appearing on every boot
        // for users whose agentys_onboarding_kb_complete was never persisted (BUG-H002).
        if (localStorage.getItem(ONBOARDING_KB_COMPLETE_KEY) !== 'true') {
          localStorage.setItem(ONBOARDING_KB_COMPLETE_KEY, 'true')
        }
      } else if (wizardData) {
        if (wizardData.onboarding_complete) {
          localStorage.setItem(ONBOARDING_COMPLETE_KEY, 'true')
          localStorage.setItem(ONBOARDING_KB_COMPLETE_KEY, 'true')
          setShowWizard(false)
        } else {
          setShowWizard(true)
        }
      } else if (hasJwt) {
        // We DID call /api/wizard/status but got null — assume wizard needed.
        setShowWizard(true)
      }
      // else: no JWT → don't touch showWizard, wait for re-run after login.

      setCheckingOnboarding(false)

      if (initData) {
        const accounts: { id: number; hash_id?: string | null; email: string; status: string }[] = initData.accounts ?? []
        if (accounts.length === 0) {
          setNeedsAccountSetup(true)
        } else {
          setNeedsAccountSetup(false)
        }
        // Audit F-03 (2026-05-17): /api/init carries both int id + hash_id;
        // register the pairs so background hooks (e.g. useWebSocketSync)
        // can normalize hex-form active-account ids planted by
        // AccountManager back to the int form the WS payload uses.
        setAccountIdMap(accounts)
        // Prefer the backend's current_account_id (persisted across restarts).
        // It is usually the multi-account hash id, so match against hash_id first.
        const currentId = initData.current_account_id
        const active = (currentId
          ? accounts.find(a => a.hash_id && a.hash_id === currentId)
            ?? accounts.find(a => String(a.id) === String(currentId))
          : null
        ) ?? accounts.find(a => a.status === 'active')
        if (active?.email) setAccountEmail(active.email)
        if (active?.id) {
          setAccountId(active.id)
          setActiveAccountId(String(active.id))
        }

        const emailsData = initData.emails
        if (emailsData?.emails?.length > 0) {
          void cacheWrite(getEmailListCacheKey(String(active?.id ?? ''), 'inbox', 0, 50, 'all'), emailsData)
        }
        if (typeof initData.spam_count === 'number') {
          setSpamCount(initData.spam_count)
        }
      } else if (hasJwt) {
        // /api/init returned null despite us having a JWT (e.g., backend hiccup).
        // Try the dedicated accounts endpoint as a secondary path. We deliberately
        // skip this when hasJwt=false to avoid a doomed authed call → 401.
        const accountsResponse = await apiClient.listAccounts().catch(() => null)
        if (accountsResponse) {
          if (accountsResponse.accounts.length === 0) {
            setNeedsAccountSetup(true)
          }
          const active = accountsResponse.accounts.find((a: { status: string }) => a.status === 'active')
          if (active?.email) setAccountEmail(active.email)
          if (active?.id) {
            setAccountId(active.id)
            setActiveAccountId(String(active.id))
          }
        }
      }
    } catch {
      setBackendStatus('disconnected')
    } finally {
      setCheckingOnboarding(false)
    }
  }, [pingWithRetry])

  // Initial check on mount
  useEffect(() => {
    checkBackendAndOnboarding()
  }, [checkBackendAndOnboarding])

  // Re-run the full check whenever auth state transitions to authenticated.
  // Without this, the initial check fires before the OAuth JWT arrives (401
  // silently swallowed), and the wizard stays stuck because no later call
  // re-fetches /api/init with the new Authorization header. Fixes the
  // "En attente des informations du compte..." lock-out after Google OAuth.
  useEffect(() => {
    const onLoginSuccess = () => {
      checkBackendAndOnboarding()
    }
    window.addEventListener('auth:login_success', onLoginSuccess as EventListener)
    return () => window.removeEventListener('auth:login_success', onLoginSuccess as EventListener)
  }, [checkBackendAndOnboarding])

  // Auto-reconnect: exponential backoff with jitter when disconnected.
  // Delay schedule: 2s → 4s → 8s → 16s → 30s → 60s (capped).
  // ±20% jitter prevents thundering-herd when many clients reconnect simultaneously.
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)
  useEffect(() => {
    const clear = () => {
      if (reconnectRef.current) {
        clearTimeout(reconnectRef.current)
        reconnectRef.current = null
      }
    }
    if (backendStatus !== 'disconnected') {
      reconnectAttemptsRef.current = 0
      clear()
      return
    }

    const scheduleNext = () => {
      const attempt = reconnectAttemptsRef.current
      const base = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, attempt), RECONNECT_MAX_DELAY)
      // ±20% jitter
      const jitter = base * 0.2 * (Math.random() * 2 - 1)
      const delay = Math.round(base + jitter)
      reconnectRef.current = setTimeout(() => {
        reconnectAttemptsRef.current += 1
        fetch(`${API_URL}/api/ping`, { signal: AbortSignal.timeout(3000) })
          .then(res => {
            if (res.ok) {
              reconnectAttemptsRef.current = 0
              checkBackendAndOnboarding()
            } else {
              scheduleNext()
            }
          })
          .catch(() => scheduleNext())
      }, delay)
    }

    scheduleNext()
    return clear
  }, [backendStatus, checkBackendAndOnboarding])

  // Expose manual recheck (for Retry button)
  const recheckConnection = useCallback(() => {
    setBackendStatus('checking')
    checkBackendAndOnboarding()
  }, [checkBackendAndOnboarding])

  // Refresh account data only (after OAuth success during wizard).
  // Does NOT re-evaluate wizard status — avoids remounting the wizard mid-flow.
  const refreshAccountData = useCallback(async () => {
    try {
      const initResponse = await fetch(`${API_URL}/api/init`, { headers: getAuthHeaders() }).catch(() => null)
      // JWT dead → escalade comme les autres fetchs (checkBackendAndOnboarding
      // fait déjà ça). Sans ça, le polling account toutes les 3s re-tirait
      // /api/init → 401 → silence → user bloqué sur l'onboarding avec 38
      // erreurs 401 qui s'empilent sans redirect login.
      if (initResponse?.status === 401) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized'))
        return
      }
      const initData = initResponse?.ok ? await initResponse.json().catch(() => null) : null
      if (initData) {
        const accounts: { id: number; hash_id?: string | null; email: string; status: string }[] = initData.accounts ?? []
        if (accounts.length > 0) {
          setNeedsAccountSetup(false)
        }
        const currentId = initData.current_account_id
        const active = (currentId
          ? accounts.find(a => a.hash_id && a.hash_id === currentId)
            ?? accounts.find(a => String(a.id) === String(currentId))
          : null
        ) ?? accounts.find(a => a.status === 'active')
        if (active?.email) setAccountEmail(active.email)
        if (active?.id) {
          setAccountId(active.id)
          setActiveAccountId(String(active.id))
        }
      }
    } catch {
      // Non-critical — wizard will continue without updated account data
    }
  }, [])

  useEffect(() => {
    let refreshInFlight = false
    const onInvalidAccount = () => {
      if (refreshInFlight) return
      refreshInFlight = true
      refreshAccountData().finally(() => {
        refreshInFlight = false
      })
    }
    window.addEventListener(ACCOUNT_INVALID_EVENT, onInvalidAccount)
    return () => window.removeEventListener(ACCOUNT_INVALID_EVENT, onInvalidAccount)
  }, [refreshAccountData])

  // Refresh account data when the tab regains focus — catches the case where
  // the user came back from an OAuth tab that completed after our polling
  // window expired. Cheap: 1 /api/init call per focus event, no-op if the
  // account is already loaded.
  useEffect(() => {
    if (!showWizard || accountId) return
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void refreshAccountData()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [showWizard, accountId, refreshAccountData])

  // Post-OAuth account polling: when the wizard is showing but accountId
  // is still null (backend may not yet have registered the fresh OAuth account),
  // poll /api/init until the account appears or we hit the max attempts.
  // Without this, the wizard gets stuck on "En attente des informations du
  // compte..." and forces a manual page refresh.
  const accountPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    const clear = () => {
      if (accountPollRef.current) {
        clearInterval(accountPollRef.current)
        accountPollRef.current = null
      }
    }
    if (checkingOnboarding) return clear
    if (!showWizard || accountId || backendStatus !== 'connected') {
      clear()
      return clear
    }
    // Gate on JWT presence — sans token, /api/init 401 et le polling
    // tournerait en boucle, empilant les 401 dans la console au lieu de
    // laisser l'auto-logout (handleAuthResponse) rediriger vers login.
    if (!getStoredToken()) {
      clear()
      return clear
    }
    let attempts = 0
    accountPollRef.current = setInterval(() => {
      // Re-gate on JWT presence CHAQUE tick : sans ça, si le token est nuké
      // mid-polling (useAuth qui clear sur erreur transiente, auth:unauthorized
      // qui déclenche logout), l'intervalle continuait à taper /api/init sans
      // token → 40 × 401 dans la console. Observé le 2026-04-22 pendant un
      // cutover Railway : une CORS failure sur /api/auth/me clearait le JWT,
      // puis ce polling inondait la console pendant 120s.
      if (!getStoredToken()) {
        clear()
        return
      }
      attempts += 1
      if (attempts > ACCOUNT_POLL_MAX_ATTEMPTS) {
        clear()
        return
      }
      void refreshAccountData()
    }, ACCOUNT_POLL_INTERVAL)
    return clear
  }, [showWizard, accountId, backendStatus, checkingOnboarding, refreshAccountData])

  return {
    backendStatus, version, showWizard, checkingOnboarding,
    recentEmails, unreadCount, spamCount, accountEmail, accountId, needsAccountSetup,
    setShowWizard, setRecentEmails, setUnreadCount,
    handleWizardComplete, handleWizardSkip, recheckConnection, refreshAccountData,
  }
}
