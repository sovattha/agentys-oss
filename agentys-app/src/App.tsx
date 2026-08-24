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

/* eslint-disable react-refresh/only-export-components, @typescript-eslint/no-explicit-any */
import { useState, useEffect, useCallback, useRef, useMemo, Suspense } from 'react'
import {
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
  FORCE_ONBOARDING_KEY,
} from './lib/storageKeys'
import { lazyWithRetry as lazy } from './utils/lazyWithRetry'
import { pushModalOpen, popModalOpen, resetModalOpen } from './utils/modalOpenFlag'
import { useTranslation } from 'react-i18next'
import { useAuth } from './hooks/useAuth'
import { LoginPage } from './components/LoginPage'
import { AriaLiveAnnouncer } from './components/AriaLiveAnnouncer'
import { GlobalToastHost } from './components/GlobalToastHost'
import { ConnectionBanner } from './components/ConnectionBanner'
import { useModals } from './hooks/useModals'
import { useResizePanel } from './hooks/useResizePanel'
import { useEmailDetailController } from './hooks/useEmailDetailController'
import { useBackendConnection } from './hooks/useBackendConnection'
import { useDraftController } from './hooks/useDraftController'
import { useUnviewedDraftCount } from './hooks/useUnviewedDraftCount'
import { useWebSocketSync } from './hooks/useWebSocketSync'
import { useActivityMonitor } from './hooks/useActivityMonitor'
import { isTauri } from './services/tokenStorage'
import { invalidateAuthMeCache } from './services/bootstrapCache'
import { fetchSettingsCached, invalidateSettingsCache } from './hooks/useSettingsCache'
import { getAuthHeaders, handleAuthResponse } from './services/authToken'
import { useActiveSpecialties } from './hooks/useActiveSpecialties'
import { stripeService } from './services/subscription'
import type { BillingEntitlement } from './services/subscription'
import { PlanStatusBanner } from './components/PlanStatusBanner'
// Critical path components - loaded synchronously
import { PendingDraftList } from './components/PendingDraftList'
const PendingDraftDetail = lazy(() => import('./components/PendingDraftDetail').then(m => ({ default: m.PendingDraftDetail })))
import { EmailList } from './components/EmailList'
import { useScheduledEmails } from './hooks/useScheduledEmails'
const SnoozedView = lazy(() => import('./components/SnoozedView').then(m => ({ default: m.SnoozedView })))
import { Sidebar, type SidebarTab } from './components/Sidebar'
import { useSnooze } from './hooks/useSnooze'
import { silentFailWithToast } from './utils/silentFail'
export type { AppMode } from './hooks/useNavigationController'
// Lazy-loaded modal components - only loaded when needed
const EmailDetailModal = lazy(() => import('./components/EmailDetailModal').then(m => ({ default: m.EmailDetailModal })))
const CalendarView = lazy(() => import('./components/CalendarView').then(m => ({ default: m.CalendarView })))
const Settings = lazy(() => import('./components/Settings').then(m => ({ default: m.Settings })))
const MyStyle = lazy(() => import('./components/MyStyle').then(m => ({ default: m.MyStyle })))
const AccountManager = lazy(() => import('./components/AccountManager').then(m => ({ default: m.AccountManager })))
const PremiumOnboarding = lazy(() => import('./components/onboarding').then(m => ({ default: m.PremiumOnboarding })))
const OAuthCallback = lazy(() => import('./components/OAuthCallback').then(m => ({ default: m.OAuthCallback })))
const ComposeEmailModal = lazy(() => import('./components/compose').then(m => ({ default: m.ComposeEmailModal })))
const NewMessageModal = lazy(() => import('./components/compose/NewMessageModal').then(m => ({ default: m.NewMessageModal })))
const ShortcutsHelpPanel = lazy(() => import('./components/ShortcutsHelpPanel').then(m => ({ default: m.ShortcutsHelpPanel })))
const LabelLibrary = lazy(() => import('./components/labels').then(m => ({ default: m.LabelLibrary })))
const SnippetLibrary = lazy(() => import('./components/snippets').then(m => ({ default: m.SnippetLibrary })))
const MonthlyRecapPage = lazy(() => import('./components/MonthlyRecapPage').then(m => ({ default: m.MonthlyRecapPage })))
const TrainingPage = lazy(() => import('./components/TrainingPage').then(m => ({ default: m.TrainingPage })))
const SupportPanel = lazy(() => import('./components/support/SupportPanel').then(m => ({ default: m.SupportPanel })))
const LearningDashboard = lazy(() => import('./components/LearningDashboard').then(m => ({ default: m.LearningDashboard })))
const GuidedTour = lazy(() => import('./components/GuidedTour').then(m => ({ default: m.GuidedTour })))
const OnboardingV2Overlay = lazy(() => import('./components/onboarding/OnboardingV2Overlay').then(m => ({ default: m.OnboardingV2Overlay })))
const MilestoneToast = lazy(() => import('./components/MilestoneToast').then(m => ({ default: m.MilestoneToast })))
import * as Sentry from '@sentry/react'
import { getNotificationService } from './services/notifications'
import { apiClient, type PendingDraft, type Email } from './services/api'
import { API_URL } from './config'
import { markEmailRead, markEmailUnread, invalidateEmailCache } from './api/emails'
import { deleteHoveredEmail, getEmailIdUnderCursor, getLastPendingDeleteId } from './components/SwipeableEmailItem'
import { ErrorBoundary } from './components/ErrorBoundary'
import { EmptyState } from './components/EmptyState'
import type { CommandAction } from './components/CommandPalette'
import type { Snippet } from './types/snippets'
const CommandPaletteContainer = lazy(() => import('./components/CommandPaletteContainer').then(m => ({ default: m.CommandPaletteContainer })))
const DeepWorkOverlay = lazy(() => import('./components/DeepWorkOverlay').then(m => ({ default: m.DeepWorkOverlay })))
const DeepWorkPanel = lazy(() => import('./components/DeepWorkPanel').then(m => ({ default: m.DeepWorkPanel })))
const DeepWorkRecapCard = lazy(() => import('./components/DeepWorkRecapCard').then(m => ({ default: m.DeepWorkRecapCard })))
import { useDeepWorkTimer } from './hooks/useDeepWorkTimer'
import { useGuidedTour } from './hooks/useGuidedTour'
import { useOnboardingV2 } from './hooks/useOnboardingV2'
import { useMilestones } from './hooks/useMilestones'
import { playUISound } from './services/uiSounds'
import { useTrayBadge } from './hooks/useTrayBadge'
import { useTrayMenu } from './hooks/useTrayMenu'
import { useMeetingReminders } from './hooks/useMeetingReminders'
import { useDraftWakeToasts } from './hooks/useDraftWakeToasts'
const MeetingImminentBanner = lazy(() => import('./components/MeetingImminentBanner').then(m => ({ default: m.MeetingImminentBanner })))
const MeetingRemindersPanel = lazy(() => import('./components/MeetingRemindersPanel').then(m => ({ default: m.MeetingRemindersPanel })))
const DraftWakeToast = lazy(() => import('./components/DraftWakeToast').then(m => ({ default: m.DraftWakeToast })))
import { useAppShortcuts } from './hooks/useAppShortcuts'
import { useNavigationController } from './hooks/useNavigationController'
import { useUpdateChecker } from './hooks/useUpdateChecker'
import { useTheme } from './hooks/useTheme'
import { useZoom } from './hooks/useZoom'
import { useOptimisticMutation } from './hooks/useOptimisticMutation'
import { ZoomIndicator } from './components/ZoomIndicator'
import { getSavedDrafts, deleteSavedDraft, deleteReplyDraftForEmail, subscribeDraftChange, type SavedDraft, type SavedComposeDraft } from './services/draftStorage'
import { KnowledgeSuggestionToast, type KnowledgeSuggestion } from './components/KnowledgeSuggestionToast'
import { RecapBanner } from './components/RecapBanner'
import { LabelsProvider } from './contexts/LabelsContext'
import { TriangleLogo } from './components/brand/TriangleLogo'
import { CloseIcon } from './components/icons/ActionIcons'
import { handleKeyboardClick } from '@/lib/utils'
import './App.css'

// Prefetch critical lazy components during browser idle time
// This ensures modals open instantly (~0ms) instead of waiting for chunk download
// Prefetch account signature so it's cached before any compose/reply opens
import { prefetchAccountSignature } from './hooks/useAccountSignature';
prefetchAccountSignature();

// QA 2026-05-18: auto-recover from stale SPA shells. After a redeploy the
// already-loaded index.html still references the OLD hashed chunk names
// (e.g. `MeetingImminentBanner-aMOzvcjM.js`). When React.lazy / dynamic
// import() tries to fetch one, the server returns the new index.html shell
// instead — which surfaces in Sentry as either:
//   • "Failed to fetch dynamically imported module: …/assets/<name>-<hash>.js"
//   • "'text/html' is not a valid JavaScript MIME type."
// Both indicate the user's tab is running stale code against a new deploy.
// Force a one-shot page reload so they pick up the fresh HTML pointing at
// the new chunk hashes. Guarded by sessionStorage to avoid a reload loop in
// case the failure is something else (genuine 404, blocked by extension…).
if (typeof window !== 'undefined') {
  const CHUNK_RELOAD_KEY = 'agentys:chunk-reload'
  const CHUNK_ERR_RE = /(Loading chunk \w+ failed)|(Failed to fetch dynamically imported module)|('text\/html' is not a valid JavaScript MIME type)|(Importing a module script failed)/i
  // BUG-AA002 fix (Session AA): in Vite dev mode an HMR refresh can briefly
  // emit a chunk error before HMR re-applies the new module. Reloading on
  // that transient error shows the user a flash of blank screen and wipes
  // every `window.__*` global (notably the QA tracker, but also any in-flight
  // promise that depended on a singleton). Skip the reload in dev — HMR
  // recovers naturally. The reload still fires in production builds, where
  // the chunk error is genuine (stale SPA shell after redeploy).
  const isDev = (typeof import.meta !== 'undefined') && !!(import.meta as { env?: { DEV?: boolean } }).env?.DEV
  const recoverFromStaleChunk = (msg: string): boolean => {
    if (!CHUNK_ERR_RE.test(msg)) return false
    if (isDev) {
      console.warn('[App] chunk load failed in dev (likely HMR transient) — letting HMR recover instead of reloading:', msg)
      return true // swallow so the global error handler stops here
    }
    // Already reloaded once this session — if the chunk STILL won't load,
    // it's a genuine problem (network down, extension blocking, real 404)
    // and we should let the error bubble up so Sentry / the error boundary
    // can surface it instead of looping forever.
    if (sessionStorage.getItem(CHUNK_RELOAD_KEY)) return false
    sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
    console.warn('[App] chunk load failed — reloading to refresh stale SPA shell:', msg)
    // Give the user a brief visual cue rather than a hard cut to blank.
    // The body stays in place for ~250 ms with a soft fade so the reload
    // doesn't read as a crash. After that we trigger the navigation.
    try {
      document.body.style.transition = 'opacity 200ms'
      document.body.style.opacity = '0.6'
    } catch { /* no-op: best effort cosmetic */ }
    setTimeout(() => window.location.reload(), 250)
    return true
  }
  window.addEventListener('error', (event) => {
    const msg = event.error?.message || event.message || ''
    recoverFromStaleChunk(msg)
  })
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    const msg = reason instanceof Error ? reason.message : typeof reason === 'string' ? reason : ''
    recoverFromStaleChunk(msg)
  })
  // Once the user has a clean load (no chunk error in the first 30 s after
  // boot), wipe the guard flag so future redeploys can trigger another
  // recovery cycle.
  setTimeout(() => {
    try { sessionStorage.removeItem(CHUNK_RELOAD_KEY) } catch { /* ignore */ }
  }, 30_000)
}

const prefetchModules = [
  () => import('./components/EmailDetailModal'),
  () => import('./components/PendingDraftDetail'),
  () => import('./components/SnoozedView'),
  () => import('./components/Settings'),
  () => import('./components/compose/NewMessageModal'),
  () => import('./components/compose'),
  () => import('./components/ShortcutsHelpPanel'),
  () => import('./components/labels'),
  () => import('./components/LearningDashboard'),
  () => import('./components/support/SupportPanel'),
  () => import('./components/onboarding/OnboardingV2Overlay'),
]

// QA 2026-05-19 — Bug #2 (login-bundle bloat): the prefetch above ran at
// module load, so every anonymous visitor on the sign-in screen used to
// download ~1 MB of post-auth JS/CSS (EmailDetailModal, RichTextEditor,
// CalendarView, Settings, OnboardingV2Overlay, …). Gate the prefetch on
// the presence of an auth token so logged-out visitors only get the
// LoginPage chunk. After a fresh login the App component calls
// `triggerPostAuthPrefetch()` (see useEffect below) to warm the same
// chunks so modals still open instantly.
let _prefetchTriggered = false
function runPrefetchModulesNow() {
  if (_prefetchTriggered) return
  _prefetchTriggered = true
  if (typeof window === 'undefined') return
  if ('requestIdleCallback' in window) {
    (window as Window).requestIdleCallback(() => {
      prefetchModules.forEach(load => load().catch(() => { /* fire-and-forget */ }))
    }, { timeout: 500 })
  } else {
    setTimeout(() => {
      prefetchModules.forEach(load => load().catch(() => { /* fire-and-forget */ }))
    }, 500)
  }
}
export function triggerPostAuthPrefetch(): void {
  runPrefetchModulesNow()
}
// Self-trigger at module load IF the user is already authenticated when the
// app shell boots (returning user with a valid stored JWT). This preserves
// the original "instant modal" UX for authenticated visitors without paying
// the cost on the login screen. Storage key mirrors services/authToken.ts.
if (typeof window !== 'undefined') {
  try {
    if (window.localStorage.getItem('agentys_jwt') !== null) {
      runPrefetchModulesNow()
    }
  } catch {
    /* localStorage unavailable — defer prefetch until post-login */
  }
}

// FOLDER_LABELS is now computed inside the component using t() — see getFolderLabel() below
// QA 2026-05-19 — Bug #6: align document.title with the sidebar tooltip.
// Previously sidebar said "Later" (inbox.later) and the tab title said
// "Waiting" (inbox.waiting); now both use inbox.later, matching the empty
// state "Nothing scheduled for later".
const FOLDER_LABELS_KEYS: Record<string, string> = {
  inbox: 'title',
  drafts: 'drafts',
  snoozed: 'later',
  sent: 'sent',
  archived: 'archive',
  spam: 'spam',
  trash: 'trash',
}

// Dynamic Tauri imports for web compatibility
async function getTauriEvent() {
  if (!isTauri()) return null
  try {
    return await import('@tauri-apps/api/event')
  } catch {
    return null
  }
}

async function getTauriWindow() {
  if (!isTauri()) return null
  try {
    return await import('@tauri-apps/api/window')
  } catch {
    return null
  }
}

async function focusAppWindow(): Promise<void> {
  const windowModule = await getTauriWindow()
  if (!windowModule) return
  try {
    const window = windowModule.getCurrentWindow()
    await window.unminimize()
    await window.show()
    await window.setFocus()
  } catch (err) {
    console.error('Failed to focus window:', err)
  }
}

// Check if we're on an OAuth callback route. Matches the canonical
// `/oauth/callback` plus the provider-prefixed legacy paths
// `/oauth/gmail/callback` and `/oauth/outlook/callback` so a stray redirect
// (or a manually crafted URL with `?error=…`) still surfaces a friendly error
// instead of falling through to the login page.
export function isOAuthCallback(): boolean {
  const p = window.location.pathname
  return p === '/oauth/callback' ||
    p.startsWith('/oauth/callback') ||
    p === '/oauth/gmail/callback' ||
    p === '/oauth/outlook/callback'
}

export function shouldRenderOAuthCallback(showOAuthCallback: boolean): boolean {
  return showOAuthCallback && isOAuthCallback()
}

function isBillingReturnRoute(): boolean {
  return window.location.pathname === '/settings/billing' ||
    new URLSearchParams(window.location.search).has('billing')
}

function ShortcutKeys({ combo }: { combo: string }) {
  const parts = combo.split('+')
  return (
    <span className="shortcut-keys">
      {parts.map((k, i) => <span key={i} className="shortcut-key">{k}</span>)}
    </span>
  )
}

// Expert mode (Ctrl+Shift+G) is hidden from the UI for now. Flip to `true` to
// restore the "Expert" chip in the compose/reply shortcut ribbons. The
// Ctrl+Shift+G key handlers in NewMessageModal/ReplyComposer are intentionally
// left wired, so re-surfacing the feature is a one-line change here.
const SHOW_EXPERT_SHORTCUT_HINT: boolean = false

type BillingUserShape = {
  ai_enabled?: boolean
  billing?: { ai_enabled?: boolean } | null
} | null | undefined

export function getBillingAiEnabled(user: BillingUserShape): boolean | undefined {
  return user?.billing?.ai_enabled ?? user?.ai_enabled
}

export function shouldBypassPaidOnboardingForFreeUser(
  aiEnabled: boolean | undefined,
  accountId: number | null | undefined,
  accountEmail: string | null | undefined,
): boolean {
  return aiEnabled === false && (!!accountId || !!accountEmail)
}

function App() {
  // Apply saved theme on mount (before any render) so the correct CSS vars are active
  useTheme()
  const { zoomIn, zoomOut, resetZoom, zoom: currentZoom } = useZoom()
  const { t } = useTranslation('inbox')
  const { t: tCommon } = useTranslation('common')
  const { t: tErrors } = useTranslation('errors')
  const { t: tDrafts } = useTranslation('drafts')
  const { t: tCompose } = useTranslation('compose')
  const { t: tCalendar } = useTranslation('calendar')
  const { t: tSearch } = useTranslation('search')
  const getFolderLabel = (folder: string) => t(FOLDER_LABELS_KEYS[folder] || 'title')
  const auth = useAuth()
  const [llmError, setLlmError] = useState<string | null>(null)
  const [authExpired, setAuthExpired] = useState<{ email: string; provider: string } | null>(null)
  const [accountReconnectTarget, setAccountReconnectTarget] = useState<{ email: string; provider: string } | null>(null)
  // Drives the conditional display of the Ctrl+Shift+G shortcut hint in the
  // compose/reply shortcut ribbons — shown only when the user has at least
  // one specialty activated.
  const activeSpecialties = useActiveSpecialties()

  // Listen for 401 responses → auto-logout
  useEffect(() => {
    const handler = () => auth.logout()
    window.addEventListener('auth:unauthorized', handler)
    return () => window.removeEventListener('auth:unauthorized', handler)
  }, [auth.logout])

  // QA 2026-06-10: pressing N showed the compose footer instantly but the
  // NewMessageModal itself appeared 3-4s later — the lazy chunk (modal +
  // ContactAutocomplete + TipTap) was only fetched/compiled on first open.
  // Warm the two compose chunks during idle time after mount so the first
  // open is instant. Failures are ignored: lazyWithRetry still covers the
  // on-demand path.
  useEffect(() => {
    const warm = () => {
      import('./components/compose/NewMessageModal').catch(() => {})
      import('./components/compose').catch(() => {})
    }
    const w = window as Window & { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number }
    if (typeof w.requestIdleCallback === 'function') {
      w.requestIdleCallback(warm, { timeout: 5000 })
    } else {
      const t = setTimeout(warm, 2500)
      return () => clearTimeout(t)
    }
  }, [])

  // Listen for LLM processing errors → show banner with link to settings
  useEffect(() => {
    const handler = (e: Event) => {
      const error = (e as CustomEvent).detail?.error || 'Unknown AI error'
      setLlmError(error)
    }
    window.addEventListener('llm:error', handler)
    return () => window.removeEventListener('llm:error', handler)
  }, [setLlmError])

  // Listen for OAuth token expiry (invalid_grant) → show reconnect banner
  useEffect(() => {
    const handler = (e: Event) => {
      const { email, provider } = (e as CustomEvent).detail || {}
      setAuthExpired({ email: email || '', provider: provider || 'gmail' })
    }
    window.addEventListener('auth:token_expired', handler)
    return () => window.removeEventListener('auth:token_expired', handler)
  }, [setAuthExpired])

  const {
    backendStatus, showWizard, checkingOnboarding,
    recentEmails, setRecentEmails, unreadCount, setUnreadCount,
    spamCount, accountEmail, accountId, handleWizardComplete, recheckConnection, refreshAccountData,
  } = useBackendConnection()

  const { detailPanelWidth, isDragging, handleResizeStart } = useResizePanel()
  const {
    selectedDraft, setSelectedDraft,
    selectedDraftId, setSelectedDraftId,
    isLoadingDraft,
    selectedDraftIndex, setSelectedDraftIndex,
    draftsRef, draftDetailReady, draftCount, setDraftCount,
    handleDraftSelect,
  } = useDraftController()
  const unviewedDraftCount = useUnviewedDraftCount(auth.isAuthenticated)
  const modals = useModals()
  const {
    showSettings, setShowSettings,
    showMyStyle, setShowMyStyle,
    showAccounts, setShowAccounts,
    showShortcutsHelp, setShowShortcutsHelp,
    showLabelLibrary, setShowLabelLibrary,
    showSnippetLibrary, setShowSnippetLibrary,
    showCommandPalette, setShowCommandPalette,
    showComposeModal, setShowComposeModal,
    showNewMessage, setShowNewMessage,
    showMonthlyRecap, setShowMonthlyRecap,
    showTraining, setShowTraining,
    showSupportPanel, setShowSupportPanel,
    showLearningDashboard, setShowLearningDashboard,
    showMeetingReminders, setShowMeetingReminders,
    closingModal, closeWithAnimation,
    settingsTrapRef, myStyleTrapRef, accountsTrapRef, trainingTrapRef, learningTrapRef,
  } = modals

  // Deep-link intent: when Settings is opened from the inbox padlock (free
  // plan) the user wants the plan-chooser, not the default Account section.
  // Reset on close so a normal gear-icon open never auto-pops billing.
  const [openBillingOnSettings, setOpenBillingOnSettings] = useState(false)
  useEffect(() => {
    if (!showSettings) setOpenBillingOnSettings(false)
  }, [showSettings])

  useEffect(() => {
    if (!isBillingReturnRoute()) return
    invalidateAuthMeCache()
    setShowSettings(true)
  }, [setShowSettings])


  // QA 2026-05-19 — Bug #2: post-auth chunk prefetch.
  // The module-load prefetch (see top of file) self-triggers only when an
  // auth token is already present at boot; for fresh logins we kick it here
  // once auth flips true so modals still open instantly post-login.
  useEffect(() => {
    if (!auth.isAuthenticated) return
    triggerPostAuthPrefetch()
  }, [auth.isAuthenticated])

  // Mobile navigation state
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 768px)').matches)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const handler = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches)
      if (!e.matches) setMobileNavOpen(false)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  const handleMobileNavToggle = useCallback(() => setMobileNavOpen(prev => !prev), [])

  const oauthCallbackSearchRef = useRef(isOAuthCallback() ? window.location.search : '')
  const [showOAuthCallback, setShowOAuthCallback] = useState(isOAuthCallback())
  // Stable callback for OAuthCallback.onComplete — uses synchronous loginWithToken
  // to guarantee React batches auth state update with setShowOAuthCallback
  const handleOAuthComplete = useCallback((authData?: { email: string; token: string; accountId: string }) => {
    if (authData) {
      auth.loginWithToken(authData.email, authData.token)
    }
    setShowOAuthCallback(false)
    window.history.replaceState({}, document.title, '/')
  }, [auth.loginWithToken])
  const [pendingDraftId, setPendingDraftId] = useState<string | null>(null)
  const pendingDraftIdRef = useRef(pendingDraftId)
  pendingDraftIdRef.current = pendingDraftId
  const selectedDraftIdRef = useRef(selectedDraftId)
  selectedDraftIdRef.current = selectedDraftId
  const {
    activeTab, setActiveTab, appMode, setAppMode,
    activeLabel, setActiveLabel, activeFolderId, setActiveFolderId,
    refreshKey, setRefreshKey,
  } = useNavigationController(accountId)
  const [createEventTrigger, setCreateEventTrigger] = useState(0)
  const updateInfo = useUpdateChecker()
  const snoozeState = useSnooze()
  const { count: scheduledEmailsCount } = useScheduledEmails()
  const {
    selectedEmail, setSelectedEmail, emailDraft, setEmailDraft,
    isLoadingEmailDraft, selectedEmailIdRef,
    detailReady, isEmailExpanded, setIsEmailExpanded,
    replyTriggerType, setReplyTriggerType, replyComposerOpen, setReplyComposerOpen,
    handleEmailSelect, handleCloseEmailDetail,
  } = useEmailDetailController()
  const [savedDrafts, setSavedDrafts] = useState<SavedDraft[]>([])
  const [composeInitialDraft, setComposeInitialDraft] = useState<SavedComposeDraft | undefined>()
  const onboardingV2 = useOnboardingV2()
  const { t: tV2 } = useTranslation('onboarding')

  // Refs so `handleOpenNewMessage` can branch on the tour phase without
  // being rebuilt on every render (which would break downstream callbacks).
  const v2PhaseRef = useRef(onboardingV2.phase)
  v2PhaseRef.current = onboardingV2.phase
  const v2NextRef = useRef(onboardingV2.next)
  v2NextRef.current = onboardingV2.next
  const v2SkipRef = useRef(onboardingV2.skip)
  v2SkipRef.current = onboardingV2.skip

  // Onboarding V2 — close + discard demo draft when celebrate card fires "Fermer"
  useEffect(() => {
    const onFinish = () => {
      setShowNewMessage(false)
      setComposeInitialDraft(undefined)
    }
    window.addEventListener('onboarding-v2:finish', onFinish)
    return () => window.removeEventListener('onboarding-v2:finish', onFinish)
  }, [setShowNewMessage])

  const [knowledgeSuggestion, setKnowledgeSuggestion] = useState<KnowledgeSuggestion | null>(null)
  const [recapBannerMonth, setRecapBannerMonth] = useState<string | null>(null)
  const [showKbOnboarding, setShowKbOnboarding] = useState(() => {
    return localStorage.getItem(ONBOARDING_COMPLETE_KEY) === 'true'
      && localStorage.getItem(ONBOARDING_KB_COMPLETE_KEY) !== 'true'
  })
  const authBillingAiEnabled = getBillingAiEnabled(auth.user)
  const [billingAiEnabledOverride, setBillingAiEnabledOverride] = useState<boolean | undefined>(undefined)
  const [billingStatus, setBillingStatus] = useState<BillingEntitlement | null>(null)
  const billingAiEnabled = billingAiEnabledOverride ?? authBillingAiEnabled
  const aiFeaturesEnabled = billingAiEnabled !== false
  const isFreeMode = auth.isAuthenticated && billingAiEnabled === false
  const bypassPaidOnboarding = shouldBypassPaidOnboardingForFreeUser(
    billingAiEnabled,
    accountId,
    accountEmail,
  )
  // Premium onboarding: shown when wizard says incomplete, KB onboarding needed,
  // or user explicitly reset via FORCE_ONBOARDING_KEY
  const showPremiumOnboarding = !bypassPaidOnboarding && (
    showWizard || showKbOnboarding || localStorage.getItem(FORCE_ONBOARDING_KEY) === 'true'
  )
  const showMainShell = !checkingOnboarding && !showPremiumOnboarding && backendStatus !== 'disconnected'
  const [appLoaded, setAppLoaded] = useState(false)
  const [showDeepWorkPanel, setShowDeepWorkPanel] = useState(false)
  const [deepWorkRecapData, setDeepWorkRecapData] = useState<{ focusMinutes: number; emailsProcessed: number; streakDays: number } | null>(null)
  const onSlotEndRef = useRef<(() => void) | undefined>(undefined)
  const deepWorkTimer = useDeepWorkTimer({
    onSlotEnd: () => onSlotEndRef.current?.(),
    accountId: accountId ?? undefined,
  })
  const guidedTour = useGuidedTour()
  const milestones = useMilestones()
  const inboxEmailsRef = useRef<Email[]>([])
  const displayedEmailsRef = useRef<Email[]>([])
  // displayedEmailsState mirrors displayedEmailsRef as React state so that
  // emailNavInfo (useMemo) recomputes whenever the visible list changes.
  const [displayedEmailsState, setDisplayedEmailsState] = useState<Email[]>([])
  const [ribbonVisible, setRibbonVisible] = useState(() => localStorage.getItem('agentys_ribbon_visible') !== '0')

  // Ribbon always visible (spacebar is now reserved for push-to-talk)
  useEffect(() => {
    setRibbonVisible(true);
    localStorage.setItem('agentys_ribbon_visible', '1');
  }, []);

  useEffect(() => {
    if (!auth.isAuthenticated) {
      setBillingAiEnabledOverride(undefined)
      return
    }

    let cancelled = false
    stripeService.getBilling()
      .then((billing) => {
        if (!cancelled) {
          setBillingAiEnabledOverride(billing.ai_enabled)
          setBillingStatus(billing)
        }
      })
      .catch((err) => {
        console.warn('[App] failed to load billing entitlement:', err)
      })

    const handleBillingUpdated = (event: Event) => {
      const billing = (event as CustomEvent<{ ai_enabled?: boolean }>).detail
      if (typeof billing?.ai_enabled === 'boolean') {
        setBillingAiEnabledOverride(billing.ai_enabled)
      }
    }
    window.addEventListener('agentys:billing-updated', handleBillingUpdated)
    return () => {
      cancelled = true
      window.removeEventListener('agentys:billing-updated', handleBillingUpdated)
    }
  }, [auth.isAuthenticated, auth.user?.id, auth.user?.email])

  // Allow any component to open settings via a custom event (avoids prop-drilling)
  useEffect(() => {
    const handler = () => setShowSettings(true)
    window.addEventListener('open-settings', handler)
    return () => window.removeEventListener('open-settings', handler)
  }, [])

  // Audit 2026-05-18: namespaced variant used by the booking-link affordance
  // in InsertAvailabilityButton — fires with `{section: 'productivite'}` so
  // the settings modal opens directly on the relevant section instead of the
  // default landing tab.
  useEffect(() => {
    const handler = () => setShowSettings(true)
    window.addEventListener('agentys:open-settings', handler)
    return () => window.removeEventListener('agentys:open-settings', handler)
  }, [])

  // Allow any component (e.g. ContactGroupsManager → "Compose to group") to
  // open the New Message modal pre-filled with recipients via a custom event.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ to?: string; cc?: string; bcc?: string; subject?: string; body?: string; groupId?: string }>).detail || {}
      setComposeInitialDraft({
        type: 'compose',
        id: `compose_${Date.now()}`,
        to: detail.to ?? '',
        cc: detail.cc ?? '',
        bcc: detail.bcc ?? '',
        subject: detail.subject ?? '',
        body: detail.body ?? '',
        savedAt: new Date().toISOString(),
      })
      setShowSettings(false)
      setShowNewMessage(true)
    }
    window.addEventListener('agentys:open-compose', handler as EventListener)
    return () => window.removeEventListener('agentys:open-compose', handler as EventListener)
  }, [setShowNewMessage, setShowSettings])

  // Refresh email list when a pending draft becomes stale (refine 410)
  // — see PendingDraftDetail.tsx audit fix Reply-HIGH-3.
  useEffect(() => {
    const onStale = () => setRefreshKey(k => k + 1)
    window.addEventListener('agentys:pending-draft-stale', onStale as EventListener)
    return () => window.removeEventListener('agentys:pending-draft-stale', onStale as EventListener)
  }, [setRefreshKey])

  // F-01 (audit regressions 2026-05-17 batch4): EmailList dispatches
  // `agentys:email-action-failed` when the backend bg delete/archive returns
  // failure via WS `email_updated`. The user-facing toast is dispatched by
  // EmailList (it owns the inbox namespace); here we just bump refreshKey
  // so the row reappears via a fresh fetch — the prior B-02 fix wired the
  // WS emit but never the refetch, leaving the user with a vanished email.
  useEffect(() => {
    const onActionFailed = () => setRefreshKey(k => k + 1)
    window.addEventListener('agentys:email-action-failed', onActionFailed as EventListener)
    return () => window.removeEventListener('agentys:email-action-failed', onActionFailed as EventListener)
  }, [setRefreshKey])

  // Dynamic browser tab title: "Boîte de réception - user@email.com"
  // BUG-S007 fix (2026-05-16): include `appMode` so calendar-mode shows
  // "Calendrier - …" instead of being stuck on the previous mail folder name.
  // Previously the effect only depended on `activeTab` (mail folder) and
  // re-rendering with appMode='calendar' had no effect on the document.title.
  useEffect(() => {
    const folder = appMode === 'calendar'
      ? tCalendar('title')
      : (getFolderLabel(activeTab) || 'Agentys')
    document.title = accountEmail ? `${folder} - ${accountEmail}` : folder
  }, [activeTab, accountEmail, appMode, tCalendar])

  // Mark app as loaded immediately on mount
  useEffect(() => {
    setAppLoaded(true)
  }, [])

  // Check for recap banner on mount
  useEffect(() => {
    if (backendStatus !== 'connected') return
    // Gate on auth — without a JWT /api/settings returns 401 and the
    // 401 dispatcher would spuriously try to logout during boot races.
    if (!auth.isAuthenticated) return
    fetchSettingsCached()
      .then(settings => {
        const month = settings.monthly_recap_banner_month as string | undefined
        if (month && !settings.monthly_recap_banner_dismissed) {
          // Auto-dismiss after 7 days
          const shownDate = localStorage.getItem('recap_banner_shown_date')
          if (shownDate) {
            const daysSince = (Date.now() - new Date(shownDate).getTime()) / (1000 * 60 * 60 * 24)
            if (daysSince > 7) {
              setRecapBannerMonth(null)
              return
            }
          } else {
            localStorage.setItem('recap_banner_shown_date', new Date().toISOString())
          }
          setRecapBannerMonth(month)
        }
      })
      .catch(err => console.error('[App] fetch recap banner settings failed:', err))
  }, [backendStatus, auth.isAuthenticated])

  // Load saved drafts from localStorage
  const refreshSavedDrafts = useCallback(() => {
    setSavedDrafts(getSavedDrafts())
  }, [])

  useEffect(() => {
    refreshSavedDrafts()
    const unsub = subscribeDraftChange(refreshSavedDrafts)
    return unsub
  }, [refreshSavedDrafts])

  // Derive set of email IDs that have local reply drafts (for badge display)
  const localDraftEmailIds = useMemo(() => {
    const ids = new Set<string>()
    for (const d of savedDrafts) {
      if (d.type === 'reply' && d.emailId) ids.add(d.emailId)
    }
    return ids
  }, [savedDrafts])

  // Determine if any modal is open (for disabling shortcuts).
  // Declared up here (not next to the other shortcut handlers) because
  // handleOpenNewMessage below needs the ref — N must not open the compose
  // modal while Settings / Quick Actions / etc. are open.
  const isModalOpen = showSettings || showMyStyle || showAccounts || showComposeModal || showShortcutsHelp || showCommandPalette || showMonthlyRecap || showTraining || showSupportPanel || showLearningDashboard || showDeepWorkPanel || showMeetingReminders
  const isModalOpenRef = useRef(isModalOpen)
  isModalOpenRef.current = isModalOpen

  // Mirror the in-memory ref to a body dataset flag so other global keydown
  // listeners (e.g. QuickStepsListHotkeys, mounted inside EmailList) can
  // defer when any app-level modal is open without having to subscribe to
  // App state. Same pattern as `body.dataset.emailDetailOpen` set by
  // EmailDetailModal.
  useEffect(() => {
    if (!isModalOpen) return
    pushModalOpen()
    return popModalOpen
  }, [isModalOpen])

  // Self-heal on mount: clear any stale `data-modal-open` left from a prior
  // session / HMR that didn't unwind cleanly. Safe to do at App level —
  // App is the root, so no other pusher (QuickEventPopover, Dialog) can be
  // mounted before this effect runs. Prevents the recurring "Del shortcut
  // silently broken after a hot-reload" symptom (debug trace from 7d78d97a).
  //
  // BUG-X002 fix (2026-05-17): self-heal also fires whenever isModalOpen
  // transitions to false, in case an external pusher (QuickEventPopover,
  // shadcn Dialog, …) failed to pop. Symptom was N/E/Del going silently
  // dead after a popover crash mid-session, which only a full reload fixed.
  useEffect(() => {
    if (!isModalOpen && !document.querySelector('[role=dialog]') &&
        document.body.dataset.modalOpen === 'true') {
      resetModalOpen()
    }
  }, [isModalOpen])

  const handleOpenNewMessage = useCallback(() => {
    // Skip when any modal is open — N is a global shortcut and we don't
    // want it firing while the user is inside Settings, Quick Actions, etc.
    if (isModalOpenRef.current) return
    // Onboarding V2 — pre-fill the composer with demo notes when the tour is
    // at the "press N" step, so the user immediately sees the keyword shape
    // that Ctrl+G will transform into a full email.
    if (v2PhaseRef.current === 'shortcutBar') {
      setComposeInitialDraft({
        type: 'compose',
        id: `v2-demo-${Date.now()}`,
        to: '',
        cc: '',
        bcc: '',
        subject: '',
        body: tV2('v2_demo_body'),
        savedAt: new Date().toISOString(),
      })
      setShowNewMessage(true)
      v2NextRef.current()
      return
    }
    // "New message" ouvre TOUJOURS un modal vide — comportement Gmail/Outlook.
    // Les brouillons sauvegardés restent accessibles via la liste des drafts
    // (onSavedDraftClick → handleSavedDraftClick pré-remplit le modal).
    // Historique : issue #312 avait introduit un auto-restore silencieux du
    // dernier draft à chaque ouverture pour protéger contre la perte de
    // données après Escape/fermeture accidentelle. En pratique c'était surpre-
    // nant (« pourquoi Nathan.sok est déjà dans le To alors que j'ouvre un
    // NOUVEAU message ? ») et le flow de récupération passe par la drafts
    // list, pas par le bouton "New message".
    setComposeInitialDraft(undefined)
    setShowNewMessage(true)
  }, [tV2])

  const handleDeleteSavedDraft = useCallback((draftId: string) => {
    deleteSavedDraft(draftId)
    refreshSavedDrafts()
  }, [refreshSavedDrafts])

  const handleSavedDraftClick = useCallback((draft: SavedDraft) => {
    if (draft.type === 'compose') {
      setComposeInitialDraft(draft)
      setShowNewMessage(true)
    } else {
      // For reply drafts: open the compose modal pre-filled with reply data
      // so the user stays on the current view (no inbox navigation / view transition conflict).
      const replySubject = draft.emailSubject.startsWith('Re:') ? draft.emailSubject : `Re: ${draft.emailSubject}`
      setComposeInitialDraft({
        type: 'compose',
        id: draft.id,
        to: draft.emailSender,
        cc: '',
        bcc: '',
        subject: replySubject,
        body: draft.body,
        savedAt: draft.savedAt,
      })
      setShowNewMessage(true)
    }
  }, [])

  // Swipe archive handler (right swipe)
  const handleSwipeArchive = useCallback(async (email: Email) => {
    try {
      await apiClient.archiveEmail(email.id)
      setRefreshKey(k => k + 1)
      playUISound('archive')
    } catch (err) {
      // Silent-failure fix (issue #313) : offline / 500 → l'utilisateur ne
      // voyait aucune erreur. L'email n'est pas rollback ici parce que la
      // liste n'est pas sous notre contrôle direct (autres composants gèrent
      // l'UI optimiste), mais le toast global signale l'échec.
      console.error('Failed to archive email:', err)
      const message = err instanceof Error ? err.message : 'unknown error'
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: tCommon('toasts.archive_failed', { detail: message }), type: 'error', duration: 6000 },
      }))
    }
  }, [tCommon])

  // Swipe delete handler (left swipe)
  const handleSwipeDelete = useCallback(async (email: Email) => {
    try {
      await apiClient.deleteEmail(email.id)
      setRefreshKey(k => k + 1)
      playUISound('delete')
    } catch (err) {
      console.error('Failed to delete email:', err)
      const message = err instanceof Error ? err.message : 'unknown error'
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: tCommon('toasts.delete_failed', { detail: message }), type: 'error', duration: 6000 },
      }))
    }
  }, [tCommon])

  // Audit Cluster D (2026-05-17) Toast Site 5 / #330: chained calls with
  // top-level console.error and no user feedback. If either step failed
  // the draft could remain server-side AND the refresh might re-fetch it,
  // making the click look broken.
  const runDeleteDraftFromList = useOptimisticMutation<void>({
    scope: 'app-delete-draft-from-list',
    i18nKey: 'toasts.draft_delete_failed',
  })
  const handleDeleteDraftFromList = useCallback(async (email: Email) => {
    await runDeleteDraftFromList(async () => {
      const draft = await apiClient.getPendingDraftByEmailId(email.id, email.subject)
      if (draft) {
        await apiClient.deletePendingDraft(draft.id)
      }
      deleteReplyDraftForEmail(email.id)
      setRefreshKey(k => k + 1)
    })
  }, [runDeleteDraftFromList])

  // Update system tray badge with unread email count (Story 7-1 AC4)
  useTrayBadge(unreadCount)

  // Meeting reminders — OS notifications + sidebar countdown + imminent banner
  const meetingReminders = useMeetingReminders(accountId != null ? String(accountId) : undefined, auth.isAuthenticated)

  // Follow-up draft wake-time toast — surfaces snoozed follow-up drafts
  // (routing_tier=followup) once their wake date has elapsed server-side.
  // Polls the same /api/pending-drafts endpoint that useUnviewedDraftCount
  // already uses, plus the draft_ready/draft_complete WebSocket channel.
  const draftWakeToasts = useDraftWakeToasts(auth.isAuthenticated)
  const handleDraftWakeSend = useCallback(async (draft: PendingDraft) => {
    // Match the contract PendingDraftDetail uses: validate (which sends).
    // The toast hook will refetch and remove the draft on its next poll;
    // we call refresh() eagerly so the user sees the toast disappear
    // immediately instead of after the 60s tick.
    await apiClient.validatePendingDraft(draft.id)
    await draftWakeToasts.refresh()
  }, [draftWakeToasts])
  const handleDraftWakeOpen = useCallback((draft: PendingDraft) => {
    // Navigate the user to the draft detail view (Drafts tab + selected).
    // The toast component dismisses the visible entry itself after firing
    // this callback, so we don't need to mark fired here.
    setActiveTab('drafts')
    setSelectedDraft(draft)
    setSelectedDraftId(draft.id)
  }, [setActiveTab, setSelectedDraft, setSelectedDraftId])
  const handleDraftWakeReviewAll = useCallback(() => {
    setActiveTab('drafts')
  }, [setActiveTab])

  // Handle tray menu sync action (Story 7-2 AC4)
  const handleTraySync = useCallback(async () => {
    // Trigger a refresh of the drafts list
    setRefreshKey((k) => k + 1)
    // Optionally trigger backend sync - for now just refresh the UI
    try {
      // Fetch latest emails for recent emails submenu and unread count (Story 7-1 AC4)
      const response = await apiClient.listEmails(50)
      setRecentEmails(response.emails.slice(0, 3))
      // Count unread emails for tray badge
      const unread = response.emails.filter((e: Email) => !e.is_read).length
      setUnreadCount(unread)
    } catch (error) {
      console.warn('Failed to sync emails:', error)
    }
  }, [])

  // Handle navigation from tray menu
  const handleTrayNavigate = useCallback((path: string) => {
    if (path === '/settings') {
      setShowSettings(true)
    } else if (path === '/my-style') {
      setShowMyStyle(true)
    } else if (path === '/accounts') {
      setShowAccounts(true)
    } else if (path === '/compose') {
      setShowComposeModal(true)
    }
  }, [])

  // Handle open email from tray menu (Story 7-2 AC3)
  const handleTrayOpenEmail = useCallback(
    async (emailId: string) => {
      // Bring window to front
      await focusAppWindow()

      // Find draft associated with this email
      const draft = draftsRef.current.find((d) => d.email_id === emailId)
      if (draft) {
        setSelectedDraft(draft)
        setSelectedDraftId(draft.id)
      }
    },
    []
  )

  // Connect tray menu to app state (Story 7-2)
  useTrayMenu(draftCount, recentEmails, {
    onSync: handleTraySync,
    onNavigate: handleTrayNavigate,
    onOpenEmail: handleTrayOpenEmail,
  })

  // Refs for shortcut handlers — always synchronously up-to-date, no stale closures.
  // isModalOpen / isModalOpenRef live above handleOpenNewMessage (~line 495)
  // because that handler also needs to skip while a modal is open.
  const activeTabRef = useRef(activeTab)
  activeTabRef.current = activeTab
  const selectedDraftIndexRef = useRef(selectedDraftIndex)
  const bulkArchiveRef = useRef<(() => void) | null>(null)
  const bulkDeleteRef = useRef<(() => void) | null>(null)
  const bulkNotSpamRef = useRef<(() => void) | null>(null)
  const bulkRestoreRef = useRef<(() => void) | null>(null)
  const deselectAllRef = useRef<(() => void) | null>(null)
  // Ferme un overlay « settings-modal » seulement si le clic a COMMENCÉ sur le
  // fond lui-même : sinon une sélection de texte démarrée dans un champ et
  // relâchée sur le fond (le `click` natif vise alors l'overlay, ancêtre commun)
  // ferme la fenêtre en pleine édition. Cf. fix per-contact 2026-06-23.
  const overlayMouseDownOnSelfRef = useRef(false)
  const selectAllRef = useRef<(() => void) | null>(null)
  const selectAllFromHereRef = useRef<(() => void) | null>(null)

  const deleteEmailOptimisticRef = useRef<((email: any) => void) | null>(null) as React.MutableRefObject<((email: any) => void) | null>

  const archiveEmailOptimisticRef = useRef<((email: any) => void) | null>(null) as React.MutableRefObject<((email: any) => void) | null>
  selectedDraftIndexRef.current = selectedDraftIndex

  // Close any open modal or inline detail (Story 7-4 Task 4.3)
  // Deep Focus: first Escape closes detail panel, second Escape exits Deep Focus
  // Wrapped in try-catch: a crash here causes blank screen (BUG-001/002 — QA 2026-04-10)
  const handleCloseModal = useCallback(() => {
    try {
      if (deselectAllRef.current) {
        deselectAllRef.current()
        return
      }
      // NB 2026-06-23 : Training n'est PLUS fermé ici. Ce handler global
      // (useAppShortcuts) écoute Escape en phase CAPTURE sur `window`, donc il
      // tournait AVANT le handler Escape propre à TrainingPage — qui, lui, ignore
      // Escape quand le focus est dans un champ. Résultat : Escape dans un champ
      // du formulaire « Ajouter un contact » fermait toute la fenêtre Entraînement
      // avant de pouvoir sauvegarder. On laisse désormais TrainingPage gérer son
      // propre Escape (input-guardé) ; un Escape hors champ ferme toujours.
      if (showMonthlyRecap) {
        setShowMonthlyRecap(false)
      } else if (showCommandPalette) {
        setShowCommandPalette(false)
      } else if (showShortcutsHelp) {
        setShowShortcutsHelp(false)
      } else if (showDeepWorkPanel) {
        setShowDeepWorkPanel(false)
      } else if (showMeetingReminders) {
        setShowMeetingReminders(false)
      } else if (showComposeModal) {
        setShowComposeModal(false)
      } else if (showLearningDashboard) {
        setShowLearningDashboard(false)
      } else if (showSettings) {
        setShowSettings(false)
      } else if (showMyStyle) {
        setShowMyStyle(false)
      } else if (showAccounts) {
        setShowAccounts(false)
      } else if (selectedEmail) {
        handleCloseEmailDetail()
      }
    } catch (err) {
      console.error('[App] handleCloseModal crashed — recovering:', err)
    }
  }, [showMonthlyRecap, showCommandPalette, showShortcutsHelp, showDeepWorkPanel, showMeetingReminders, showComposeModal, showSettings, showMyStyle, showAccounts, showLearningDashboard, selectedEmail, handleCloseEmailDetail])

  // Navigate up — works for email list tabs (inbox, sent, archived, spam, trash) and drafts
  const handleNavigateUp = useCallback(() => {
    if (isModalOpenRef.current) return
    if (activeTabRef.current === 'drafts') {
      const drafts = draftsRef.current
      if (drafts.length === 0) return
      const currentIndex = selectedDraftIndexRef.current >= 0 ? selectedDraftIndexRef.current : drafts.length
      const newIndex = Math.max(0, currentIndex - 1)
      setSelectedDraftIndex(newIndex)
      selectedDraftIndexRef.current = newIndex
      const draft = drafts[newIndex]
      // Update the rendered draft object too — without this the header
      // counter advanced but the detail panel kept showing the old draft.
      if (draft) { setSelectedDraft(draft); setSelectedDraftId(draft.id) }
    } else {
      const emails = displayedEmailsRef.current
      if (emails.length === 0) return
      const curId = selectedEmailIdRef.current
      const currentIdx = curId ? emails.findIndex(e => e.id === curId) : -1
      const newIdx = currentIdx <= 0 ? 0 : currentIdx - 1
      handleEmailSelect(emails[newIdx])
    }
  }, [handleEmailSelect])

  // Navigate down — works for email list tabs (inbox, sent, archived, spam, trash) and drafts
  const handleNavigateDown = useCallback(() => {
    if (isModalOpenRef.current) return
    if (activeTabRef.current === 'drafts') {
      const drafts = draftsRef.current
      if (drafts.length === 0) return
      const currentIndex = selectedDraftIndexRef.current
      const newIndex = Math.min(drafts.length - 1, currentIndex + 1)
      setSelectedDraftIndex(newIndex)
      selectedDraftIndexRef.current = newIndex
      const draft = drafts[newIndex]
      // Update the rendered draft object too (see handleNavigateUp).
      if (draft) { setSelectedDraft(draft); setSelectedDraftId(draft.id) }
    } else {
      const emails = displayedEmailsRef.current
      if (emails.length === 0) return
      const curId = selectedEmailIdRef.current
      const currentIdx = curId ? emails.findIndex(e => e.id === curId) : -1
      const newIdx = Math.min(emails.length - 1, currentIdx + 1)
      handleEmailSelect(emails[newIdx])
    }
  }, [handleEmailSelect])

  // Open selected email (Story 7-4 Task 4.4)
  const handleOpenSelected = useCallback(() => {
    if (isModalOpenRef.current) return
    if (activeTabRef.current === 'drafts') {
      const drafts = draftsRef.current
      const idx = selectedDraftIndexRef.current
      if (idx >= 0 && idx < drafts.length) {
        const draft = drafts[idx]
        if (draft) handleDraftSelect(draft)
      }
    }
  }, [handleDraftSelect])

  // Email navigation info for detail panel arrows.
  // Depends on both selectedEmail AND displayedEmailsState so it recomputes
  // whenever the visible email list changes (displayedEmailsRef alone would not
  // trigger a recompute because refs are mutable and not tracked by React).
  const emailNavInfo = useMemo(() => {
    const emails = displayedEmailsState
    if (!selectedEmail || emails.length === 0) return null
    const idx = emails.findIndex(e => e.id === selectedEmail.id)
    if (idx === -1) return null
    return { current: idx + 1, total: emails.length, hasPrev: idx > 0, hasNext: idx < emails.length - 1 }
  }, [selectedEmail, displayedEmailsState])

  // Drafts list size — kept in sync by `handleDraftsLoaded` on every
  // PendingDraftList re-fetch. Declared before `draftNavInfo` so the
  // useMemo factory doesn't hit it in the TDZ during render.
  const [draftsTotal, setDraftsTotal] = useState(0)

  // Parity with `emailNavInfo` for the Drafts tab — drives the up/down
  // nav arrows in PendingDraftDetail's header.
  const draftNavInfo = useMemo(() => {
    if (draftsTotal === 0 || selectedDraftIndex < 0 || !selectedDraft) return null
    return {
      current: selectedDraftIndex + 1,
      total: draftsTotal,
      hasPrev: selectedDraftIndex > 0,
      hasNext: selectedDraftIndex < draftsTotal - 1,
    }
  }, [selectedDraft, selectedDraftIndex, draftsTotal])

  const handleNavigatePrevEmail = useCallback(() => {
    const emails = displayedEmailsRef.current
    if (!selectedEmail || emails.length === 0) return
    const idx = emails.findIndex(e => e.id === selectedEmail.id)
    if (idx > 0) handleEmailSelect(emails[idx - 1])
  }, [selectedEmail, handleEmailSelect])

  const handleNavigateNextEmail = useCallback(() => {
    const emails = displayedEmailsRef.current
    if (!selectedEmail || emails.length === 0) return
    const idx = emails.findIndex(e => e.id === selectedEmail.id)
    if (idx >= 0 && idx < emails.length - 1) handleEmailSelect(emails[idx + 1])
  }, [selectedEmail, handleEmailSelect])

  // Helper: find current selected email from ref
  const getSelectedEmail = useCallback((): Email | null => {
    const id = selectedEmailIdRef.current
    if (!id) return null
    return displayedEmailsRef.current.find(e => e.id === id) || null
  }, [])

  // Shortcut handlers for email actions — all use refs, no stale closures
  const handleShortcutReply = useCallback(() => {
    if (isModalOpenRef.current || !selectedEmailIdRef.current) return
    setReplyTriggerType('reply')
  }, [])

  const handleShortcutForward = useCallback(() => {
    if (isModalOpenRef.current || !selectedEmailIdRef.current) return
    setReplyTriggerType('forward')
  }, [])

  const handleShortcutReplyAll = useCallback(() => {
    if (isModalOpenRef.current || !selectedEmailIdRef.current) return
    setReplyTriggerType('reply_all')
  }, [])

  const handleShortcutArchive = useCallback(() => {
    if (isModalOpenRef.current) return
    // Spam folder bulk mode: "Not Spam" takes priority over generic archive
    if (bulkNotSpamRef.current) { bulkNotSpamRef.current(); return }
    // Trash folder bulk mode: "Restore" takes priority over generic archive
    if (bulkRestoreRef.current) { bulkRestoreRef.current(); return }
    // Regular bulk mode: delegate to EmailList's bulk handler
    if (bulkArchiveRef.current) { bulkArchiveRef.current(); return }
    // A removal animation is in progress (rapid 2nd E within the 260ms slide):
    // archive the NEXT email after the pending one. Mirrors handleShortcutDelete —
    // _lastPendingDeleteId is the shared "last row whose removal we started" and is
    // set by both the delete AND archive optimistic handlers. Checked before the
    // cursor below because CSS shift animations fire spurious mouseenter events that
    // make the under-cursor row unreliable mid-animation, so a rapid second press
    // would otherwise re-target the still-animating row and no-op.
    const pendingId = getLastPendingDeleteId()
    if (pendingId) {
      const emails = displayedEmailsRef.current
      const idx = emails.findIndex(e => e.id === pendingId)
      const next = emails[idx + 1] || emails[idx - 1] || null
      if (next && archiveEmailOptimisticRef.current) { archiveEmailOptimisticRef.current(next); return }
    }
    // Cursor / hover fallback — use optimistic handler for immediate animation + toast
    const cursorEmailId = getEmailIdUnderCursor()
    if (cursorEmailId) {
      const cursorEmail = displayedEmailsRef.current.find(e => e.id === cursorEmailId)
      if (cursorEmail) {
        if (archiveEmailOptimisticRef.current) { archiveEmailOptimisticRef.current(cursorEmail) } else { handleSwipeArchive(cursorEmail) }
        return
      }
    }
    const email = getSelectedEmail()
    if (!email) return
    // Select next before removing
    const emails = displayedEmailsRef.current
    const idx = emails.findIndex(e => e.id === email.id)
    const next = emails[idx + 1] || emails[idx - 1] || null
    if (next) {
      handleEmailSelect(next)
    } else {
      selectedEmailIdRef.current = null
      setSelectedEmail(null)
      setEmailDraft(null)
    }
    if (archiveEmailOptimisticRef.current) { archiveEmailOptimisticRef.current(email) } else { handleSwipeArchive(email) }
  }, [getSelectedEmail, handleEmailSelect, handleSwipeArchive])

  const handleShortcutDelete = useCallback(() => {
    if (isModalOpenRef.current) return
    // Later view (Snoozed/Scheduled) owns Delete via SnoozedView's own window
    // listener (per-row remove, with a confirm on the irreversible scheduled /
    // draft cases). Bail here so a stray Del in Later doesn't also delete a
    // stale inbox selection.
    if (activeTab === 'snoozed' || activeTab === 'scheduled') return
    // Bulk mode: delegate to EmailList's bulk handler
    if (bulkDeleteRef.current) { bulkDeleteRef.current(); return }
    // Hover mode: delegate to per-item handler for optimistic UI + animation.
    // If the tracked hovered email is still animating (pendingOps), fall back to
    // elementFromPoint so rapid successive Del presses still target the right row.
    if (deleteHoveredEmail()) return
    // A delete animation is in progress — find the next email after the pending one.
    // Use _lastPendingDeleteId (set synchronously on delete) rather than the hover ref,
    // because CSS shift animations fire spurious mouseenter events that can change the
    // hovered email reference between two rapid keypresses.
    const pendingId = getLastPendingDeleteId()
    if (pendingId) {
      const emails = displayedEmailsRef.current
      const idx = emails.findIndex(e => e.id === pendingId)
      const next = emails[idx + 1] || emails[idx - 1] || null
      if (next && deleteEmailOptimisticRef.current) { deleteEmailOptimisticRef.current(next); return }
    }
    const cursorEmailId = getEmailIdUnderCursor()
    if (cursorEmailId) {
      const cursorEmail = displayedEmailsRef.current.find(e => e.id === cursorEmailId)
      if (cursorEmail) {
        if (deleteEmailOptimisticRef.current) { deleteEmailOptimisticRef.current(cursorEmail) } else { handleSwipeDelete(cursorEmail) }
        return
      }
    }
    // Keyboard-selected mode
    const email = getSelectedEmail()
    if (!email) return
    // Select next before removing
    const emails = displayedEmailsRef.current
    const idx = emails.findIndex(e => e.id === email.id)
    const next = emails[idx + 1] || emails[idx - 1] || null
    if (next) {
      handleEmailSelect(next)
    } else {
      selectedEmailIdRef.current = null
      setSelectedEmail(null)
      setEmailDraft(null)
    }
    if (deleteEmailOptimisticRef.current) { deleteEmailOptimisticRef.current(email) } else { handleSwipeDelete(email) }
  }, [getSelectedEmail, handleEmailSelect, handleSwipeDelete, activeTab])

  const handleShortcutToggleRead = useCallback(async () => {
    if (isModalOpenRef.current) return
    const email = getSelectedEmail()
    if (!email) return
    const newIsRead = !email.is_read
    // Optimistic update in the emails ref
    displayedEmailsRef.current = displayedEmailsRef.current.map(e =>
      e.id === email.id ? { ...e, is_read: newIsRead } : e
    )
    setSelectedEmail(prev => prev ? { ...prev, is_read: newIsRead } : prev)
    try {
      if (newIsRead) {
        await markEmailRead(email.id)
      } else {
        await markEmailUnread(email.id)
      }
      invalidateEmailCache()
      setRefreshKey(k => k + 1)
    } catch {
      // Rollback on error
      displayedEmailsRef.current = displayedEmailsRef.current.map(e =>
        e.id === email.id ? { ...e, is_read: !newIsRead } : e
      )
      setSelectedEmail(prev => prev ? { ...prev, is_read: !newIsRead } : prev)
    }
  }, [getSelectedEmail])

  const searchInputRef = useRef<(() => void) | null>(null)
  // Stable callbacks for EmailList (avoid re-renders on every App render)
  const handleEmailsLoaded = useCallback((emails: Email[]) => {
    const unread = emails.filter((e: Email) => !e.is_read).length
    setUnreadCount(unread)
    setRecentEmails(emails.slice(0, 3))
    inboxEmailsRef.current = emails
  }, [setUnreadCount, setRecentEmails])

  const handleDisplayedEmailsChange = useCallback((emails: Email[]) => {
    displayedEmailsRef.current = emails
    setDisplayedEmailsState(emails)
  }, [])

  onSlotEndRef.current = () => {
    setDeepWorkRecapData({
      focusMinutes: deepWorkTimer.focusMinutes,
      emailsProcessed: deepWorkTimer.emailsSummary,
      streakDays: deepWorkTimer.streakDays,
    })
  }

  const handleShortcutSearch = useCallback(() => {
    if (isModalOpenRef.current) return
    // NEW-C fix: use both the ref (primary) and a custom event (reliable fallback).
    // The ref can be null when there's a timing race between mount and shortcut fire.
    if (searchInputRef.current) {
      searchInputRef.current()
    } else {
      // BUG-G004 fix: on Calendar/Settings views EmailList is not mounted,
      // so neither the ref nor the event listener exists.
      // Switch to inbox first, then fire the toggle event after EmailList mounts.
      // BUG-N003 fix: extended retry ladder (0 / 200 / 450 ms) so slower mounts
      // (large email lists, throttled CPU) still receive the event reliably.
      setActiveTab('inbox')
      const fire = () => {
        // If the ref is now available, call it directly for guaranteed delivery
        if (searchInputRef.current) {
          searchInputRef.current()
        } else {
          window.dispatchEvent(new CustomEvent('agentys:toggle-search'))
        }
      }
      setTimeout(fire, 0)
      setTimeout(fire, 200)
      setTimeout(fire, 450)
    }
  }, [setActiveTab])

  const handleShortcutSelectAll = useCallback(() => {
    if (isModalOpenRef.current) return
    selectAllRef.current?.()
  }, [])

  const handleShortcutSelectAllFromHere = useCallback(() => {
    if (isModalOpenRef.current) return
    selectAllFromHereRef.current?.()
  }, [])

  // Lazy-mount the command palette on first open so its snippet fetch is
  // deferred until the user actually invokes Ctrl+K. Stays mounted afterwards
  // so the close animation can play.
  const [commandPaletteMounted, setCommandPaletteMounted] = useState(false)
  useEffect(() => { if (showCommandPalette) setCommandPaletteMounted(true) }, [showCommandPalette])

  // Command palette entity actions \u2014 filter the inbox to a label, compose to a
  // contact, or open a new message pre-filled from a snippet.
  const handleCommandFilterLabel = useCallback((labelName: string) => {
    setActiveTab('inbox')
    setActiveLabel(labelName)
  }, [setActiveTab, setActiveLabel])

  const handleCommandComposeTo = useCallback((email: string) => {
    setComposeInitialDraft({
      type: 'compose', id: `cmd-to-${Date.now()}`,
      to: email, cc: '', bcc: '', subject: '', body: '',
      savedAt: new Date().toISOString(),
    })
    setShowNewMessage(true)
  }, [])

  const handleCommandUseSnippet = useCallback((snippet: Snippet) => {
    setComposeInitialDraft({
      type: 'compose', id: `cmd-snip-${snippet.id}`,
      to: (snippet.to ?? []).join(', '),
      cc: (snippet.cc ?? []).join(', '),
      bcc: (snippet.bcc ?? []).join(', '),
      subject: snippet.subject ?? '', body: snippet.content,
      savedAt: new Date().toISOString(),
    })
    setShowNewMessage(true)
  }, [])

  // Build command palette actions (must be after all handler declarations)
  const commandActions: CommandAction[] = useMemo(() => {
    const quickActions = tSearch('cmd_section_quick_actions')
    const tools = tSearch('cmd_section_tools')
    return [
      { id: 'reply', label: tCompose('reply'), section: quickActions, shortcut: 'R', action: handleShortcutReply },
      { id: 'archive', label: t('archive_action'), section: quickActions, shortcut: 'E', action: handleShortcutArchive },
      { id: 'delete', label: tCommon('delete'), section: quickActions, shortcut: 'Del', action: handleShortcutDelete },
      { id: 'forward', label: tCompose('forward'), section: quickActions, shortcut: 'F', action: handleShortcutForward },
      // Direct open, NOT handleOpenNewMessage: that handler refuses to fire
      // while a modal is open and the palette IS still open (isModalOpen) at
      // the instant the action executes — the click silently did nothing.
      // A palette action is an explicit intent; the N-shortcut guard doesn't apply.
      { id: 'new-message', label: tCommon('new_message'), section: tools, shortcut: 'N', action: () => { setComposeInitialDraft(undefined); setShowNewMessage(true) } },
      { id: 'settings', label: tCommon('settings_tooltip'), section: tools, shortcut: 'Ctrl+,', action: () => setShowSettings(true) },
      { id: 'shortcuts', label: tCommon('keyboard_shortcuts'), section: tools, shortcut: 'Ctrl+/', action: () => setShowShortcutsHelp(true) },
    ]
  }, [t, tCommon, tCompose, tSearch, setComposeInitialDraft, setShowNewMessage, setShowSettings, setShowShortcutsHelp, handleShortcutReply, handleShortcutArchive, handleShortcutDelete, handleShortcutForward])

  // App-wide keyboard shortcuts (Story 7-4)
  useAppShortcuts({
    onShowShortcutsHelp: () => setShowShortcutsHelp(true),
    onOpenSettings: () => setShowSettings(true),
    onRefreshEmails: handleTraySync,
    onCloseModal: handleCloseModal,
    onNavigateUp: handleNavigateUp,
    onNavigateDown: handleNavigateDown,
    onOpenSelected: handleOpenSelected,
    onNewMessage: handleOpenNewMessage,
    onCommandPalette: () => setShowCommandPalette(prev => !prev),
    onReply: handleShortcutReply,
    onReplyAll: handleShortcutReplyAll,
    onForward: handleShortcutForward,
    onArchive: handleShortcutArchive,
    onDelete: handleShortcutDelete,
    onToggleRead: handleShortcutToggleRead,
    onSearch: handleShortcutSearch,
    onSelectAll: handleShortcutSelectAll,
    onSelectAllFromHere: handleShortcutSelectAllFromHere,
    onZoomIn: zoomIn,
    onZoomOut: zoomOut,
    onZoomReset: resetZoom,
    enabled: !checkingOnboarding && !showPremiumOnboarding,
    detailPanelVisible: !!selectedEmail,
  })

  const handleDraftsLoaded = useCallback((drafts: PendingDraft[]) => {
    draftsRef.current = drafts
    const pendingCount = drafts.filter(d => d.status === 'pending').length
    setDraftCount(pendingCount)
    setDraftsTotal(drafts.length)
    // pendingDraftId now stores email_id from notification click
    const _pendingDraftId = pendingDraftIdRef.current
    if (_pendingDraftId) {
      const draft = drafts.find((d) => d.email_id === _pendingDraftId)
      if (draft) {
        setSelectedDraft(draft)
        setSelectedDraftId(draft.id)
        setPendingDraftId(null)
        // Update selected index for keyboard navigation
        const index = drafts.findIndex((d) => d.id === draft.id)
        setSelectedDraftIndex(index)
      }
    }
    // Sync selectedDraftIndex with selectedDraftId
    const _selectedDraftId = selectedDraftIdRef.current
    if (_selectedDraftId) {
      const index = drafts.findIndex((d) => d.id === _selectedDraftId)
      if (index >= 0) {
        setSelectedDraftIndex(index)
      }
    }
  }, [])

  const selectDraftByEmailId = useCallback(async (emailId: string) => {
    // Bring window to front when notification is clicked (AC1, AC4)
    await focusAppWindow()

    // Navigate to the draft by email_id (AC2, AC3)
    // Notifications send emailId, so we search drafts by their associated email_id
    const draft = draftsRef.current.find((d) => d.email_id === emailId)
    if (draft) {
      setSelectedDraft(draft)
      setSelectedDraftId(draft.id)
    } else {
      // Store emailId for later lookup when drafts are loaded
      setPendingDraftId(emailId)
    }
  }, [])

  const handleDraftUpdated = useCallback((updatedDraft: PendingDraft) => {
    setSelectedDraft(updatedDraft)
    setRefreshKey(k => k + 1)
  }, [])

  const sentCountRef = useRef(0)
  const handleDraftValidated = useCallback(() => {
    setSelectedDraft(null)
    setSelectedDraftId(null)
    setRefreshKey(k => k + 1)
    // Delayed refresh: archive happens in bg thread after send response
    setTimeout(() => setRefreshKey(k => k + 1), 4000)
    // Onboarding: first draft celebration + milestones
    sentCountRef.current += 1
    milestones.checkMilestones(sentCountRef.current)
  }, [milestones])

  const handleDraftScheduled = useCallback(() => {
    setSelectedDraft(null)
    setSelectedDraftId(null)
    setRefreshKey(k => k + 1)
  }, [])

  const handleDraftRejected = useCallback(() => {
    setSelectedDraft(null)
    setSelectedDraftId(null)
    setRefreshKey(k => k + 1)
  }, [])

  useEffect(() => {
    const notificationService = getNotificationService()
    notificationService.registerNotificationActions().catch(console.error)

    const setupClickListener = async () => {
      const unsubscribe = await notificationService.onNotificationClick(selectDraftByEmailId)
      return unsubscribe
    }

    const unsubscribePromise = setupClickListener()

    return () => {
      unsubscribePromise.then((fn) => fn()).catch(console.error)
    }
  }, [selectDraftByEmailId])

  useEffect(() => {
    let unsubscribe: (() => void) | undefined

    const setupListener = async () => {
      const eventModule = await getTauriEvent()
      if (!eventModule) return

      unsubscribe = await eventModule.listen('navigate', (event) => {
        if (event.payload === '/settings') {
          setShowSettings(true)
        } else if (event.payload === '/my-style') {
          setShowMyStyle(true)
        } else if (event.payload === '/accounts') {
          setShowAccounts(true)
        } else if (event.payload === '/compose') {
          setShowComposeModal(true)
        }
      })
    }

    setupListener()

    return () => {
      unsubscribe?.()
    }
  }, [])

  // WebSocket sync — auto-refreshes drafts/emails list on WS events (debounced)
  const wsRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleWsRefresh = useCallback(() => {
    if (wsRefreshTimer.current) clearTimeout(wsRefreshTimer.current)
    wsRefreshTimer.current = setTimeout(() => setRefreshKey(k => k + 1), 500)
  }, [])
  useWebSocketSync({ backendStatus, onRefresh: handleWsRefresh, isAuthenticated: auth.isAuthenticated })
  const activityState = useActivityMonitor(backendStatus)

  // Sidebar callbacks — extracted from inline lambdas to preserve React.memo
  // MUST be before early returns to respect Rules of Hooks
  const handleSidebarTabChange = useCallback((tab: SidebarTab) => {
    const applyChange = () => {
      setAppMode('mail')
      setActiveTab(tab)
      setActiveLabel(null)
      setActiveFolderId(null)
      setSelectedEmail(null)
      setEmailDraft(null)
      // Réinitialiser le brouillon sélectionné pour afficher la liste complète lors du retour
      setSelectedDraft(null)
      setSelectedDraftId(null)
      setRefreshKey(k => k + 1)
      // BUG-X003 fix (2026-05-17): close any compose modal that was open
      // before the tab change — otherwise it floats over Calendar / Drafts /
      // Sent etc. and can stack on top of view-specific popovers (event
      // creation, etc.). Symptom observed Session X: pressing N in Inbox
      // then navigating to Calendar made the compose modal pop up later
      // overlapping with the calendar "create event" dialog.
      setShowNewMessage(false)
    }
    if (document.startViewTransition) {
      try {
        const vt = document.startViewTransition(applyChange)
        // BUG-006 fix: absorber TOUS les rejets async de la ViewTransition.
        // Lorsqu'une transition est interrompue par une nouvelle transition (concurrent nav),
        // .ready, .updateCallbackDone et .finished rejettent tous avec InvalidStateError.
        // Sans ces catch, ils remontent comme unhandled rejections dans window.__bugLog.
        vt.ready?.catch(() => {})
        vt.updateCallbackDone?.catch(() => {})
        vt.finished.catch(() => {})
      } catch {
        // InvalidStateError synchrone: une transition était déjà en cours — appliquer directement
        applyChange()
      }
    } else {
      applyChange()
    }
  }, [])
  const handleOpenSettings = useCallback(() => setShowSettings(true), [])
  const handleOpenBillingSettings = useCallback(() => {
    setOpenBillingOnSettings(true)
    setShowSettings(true)
  }, [setShowSettings])
  // Audit 2026-05-18: sidebar button now toggles instead of unconditionally
  // opening — the previous behaviour stranded the panel visible after a
  // second click and the user had to hunt for the close button.
  const handleOpenSupport = useCallback(() => setShowSupportPanel(v => !v), [])
  const handleDeepWorkClick = useCallback(() => setShowDeepWorkPanel(v => !v), [])
  const handleCreateCalendarEvent = useCallback(() => setCreateEventTrigger(n => n + 1), [])
  // Stable callbacks for EmailList inline props (prevent re-renders on every App state change)
  const handleOpenAccounts = useCallback(() => setShowAccounts(true), [])
  // Stable callbacks for CalendarView props (prevent re-render storm when App re-renders)
  const handleCalendarClose = useCallback(() => setAppMode('mail'), [setAppMode])
  const handleCalendarShowRibbon = useCallback(() => {
    setRibbonVisible(true);
    localStorage.setItem('agentys_ribbon_visible', '1');
  }, [])
  const handleCalendarComposeToAttendees = useCallback((to: string, subject: string, body?: string) => {
    setComposeInitialDraft({ type: 'compose', id: `cal_${Date.now()}`, to, cc: '', bcc: '', subject, body: body || '', savedAt: new Date().toISOString() });
    setShowNewMessage(true);
  }, [])

  // Auth gate: loading → login → main app
  if (auth.isLoading) {
    return (
      <div className="loading-screen" role="status" aria-live="polite">
        <div className="loading-brand-mark"><TriangleLogo /></div>
        <div className="loading-bar-track"><div className="loading-bar-fill" /></div>
        <div className="loading-hint">{tErrors('session_checking')}</div>
      </div>
    )
  }

  // Handle OAuth callback route — BEFORE auth gate so popup works when not yet authenticated
  if (shouldRenderOAuthCallback(showOAuthCallback)) {
    return (
      <Suspense fallback={
        <div className="loading-screen">
          <div className="loading-brand-mark"><TriangleLogo /></div>
          <div className="loading-bar-track"><div className="loading-bar-fill" /></div>
          <div className="loading-hint">Authentification</div>
        </div>
      }>
        <OAuthCallback
          onComplete={handleOAuthComplete}
          initialSearch={oauthCallbackSearchRef.current}
        />
      </Suspense>
    )
  }

  if (!auth.isAuthenticated) {
    return <LoginPage onOAuthLogin={auth.loginWithOAuth} />
  }

  return (
    <LabelsProvider>
    <div className={`app${appLoaded ? ' app-loaded' : ''}`} data-testid="app-container">
      <a className="skip-link" href="#app-main">{tCommon('skip_to_content')}</a>
      <ZoomIndicator zoom={currentZoom} />
      <GlobalToastHost />
      <ConnectionBanner onRetry={recheckConnection} />
      {auth.isAuthenticated && (
        <PlanStatusBanner billing={billingStatus} onOpenBilling={handleOpenBillingSettings} />
      )}
      {meetingReminders.imminentEvent && (
        <Suspense fallback={null}>
          <MeetingImminentBanner
            event={meetingReminders.imminentEvent}
            onDismiss={meetingReminders.dismissImminent}
            onSnooze={meetingReminders.snoozeImminent}
            autoDismissMs={0}
          />
        </Suspense>
      )}
      {draftWakeToasts.visibleDrafts.length > 0 && (
        <Suspense fallback={null}>
          <DraftWakeToast
            drafts={draftWakeToasts.visibleDrafts}
            onSend={handleDraftWakeSend}
            onOpen={handleDraftWakeOpen}
            onReviewAll={handleDraftWakeReviewAll}
            onSnoozeOne={draftWakeToasts.snoozeOne}
            onSnoozeAll={draftWakeToasts.snoozeAll}
            onDismissOne={draftWakeToasts.dismissOne}
            onDismissAll={draftWakeToasts.dismissAll}
          />
        </Suspense>
      )}
      <div className="app-body">
        {showMainShell && (
          <>
            {isMobile && mobileNavOpen && (
              <div
                className="sidebar-mobile-backdrop"
                aria-hidden="true"
                onClick={() => setMobileNavOpen(false)}
              />
            )}
            <Sidebar
              activeTab={activeTab}
              onTabChange={handleSidebarTabChange}
              onCompose={handleOpenNewMessage}
              onOpenSettings={handleOpenSettings}
              billingMode={isFreeMode ? 'free' : billingAiEnabled === true ? 'paid' : 'unknown'}
              onOpenBilling={handleOpenBillingSettings}
              onOpenSupport={handleOpenSupport}
              unreadCount={unreadCount}
              draftCount={draftCount}
              unviewedDraftCount={unviewedDraftCount}
              snoozedCount={snoozeState.sleepingIds.size}
              scheduledCount={scheduledEmailsCount}
              spamCount={spamCount}
              appMode={appMode}
              onAppModeChange={setAppMode}
              activeLabel={activeLabel}
              onLabelChange={setActiveLabel}
              activeFolderId={activeFolderId}
              onFolderSelect={setActiveFolderId}
              hasUpdate={updateInfo.hasUpdate}
              deepWorkActive={deepWorkTimer.isActive && !deepWorkTimer.isManualOverride}
              onDeepWorkClick={handleDeepWorkClick}
              onCreateCalendarEvent={handleCreateCalendarEvent}
              activityState={activityState}
              isMobile={isMobile}
              isOpen={mobileNavOpen}
              onClose={handleMobileNavToggle}
              nextMeetingMinutes={meetingReminders.minutesUntilNext}
            />
          </>
        )}
        {showDeepWorkPanel && (
          <Suspense fallback={null}>
            <DeepWorkPanel
              timer={deepWorkTimer}
              onClose={() => setShowDeepWorkPanel(false)}
              onBack={() => { setShowDeepWorkPanel(false); setShowSettings(true); }}
            />
          </Suspense>
        )}
        <main className={`app-main${appMode === 'calendar' ? ' app-main--calendar' : ''}`} id="app-main" role="main" aria-label={tCommon('main_content_aria')} data-testid="app-main">
          {/* A11Y-1 fix: visually-hidden heading anchors the page landmark for screen readers.
              Audit 2026-06-11 U-07 : le h1 restait « Inbox » sur Drafts/Sent/Trash… —
              il suit maintenant l'onglet actif avec les mêmes clés que la Sidebar. */}
          <h1 className="sr-only">
            {appMode === 'calendar'
              ? tCommon('calendar')
              : t(({
                  inbox: 'title',
                  drafts: 'drafts',
                  scheduled: 'later',
                  snoozed: 'later',
                  sent: 'sent',
                  archived: 'archive',
                  spam: 'spam',
                  trash: 'trash',
                } as Record<SidebarTab, string>)[activeTab] ?? 'title')}
          </h1>
          {/* A11Y-2 fix: aria-live regions pour annoncer les événements dynamiques (nouveau draft, archivage…).
              Autres composants peuvent pousser via window.dispatchEvent(new CustomEvent('agentys:announce', { detail: { message: 'Nouveau brouillon prêt', priority: 'polite' } })) */}
          <AriaLiveAnnouncer />
          <AriaLiveAnnouncer priority="assertive" />
        {llmError && (
          <div className="llm-error-banner" role="alert">
            <span className="llm-error-banner-icon">&#9888;</span>
            <span className="llm-error-banner-text">
              AI Error: {llmError.length > 120 ? llmError.slice(0, 120) + '…' : llmError}
            </span>
            <button
              className="llm-error-banner-btn"
              onClick={() => { setLlmError(null); setShowSettings(true) }}
            >
              Configure model
            </button>
            <button
              className="llm-error-banner-close"
              onClick={() => setLlmError(null)}
              aria-label={tCommon('close')}
            >
              <CloseIcon size={16} />
            </button>
          </div>
        )}
        {authExpired && (
          <div className="llm-error-banner llm-error-banner--auth" role="alert">
            <span className="llm-error-banner-icon">&#9888;</span>
            <span className="llm-error-banner-text">
              {tCommon(authExpired.email ? 'auth_reconnect_banner' : 'auth_reconnect_banner_no_email', {
                email: authExpired.email,
              })}
            </span>
            <button
              className="llm-error-banner-btn"
              onClick={() => {
                setAccountReconnectTarget(authExpired)
                setAuthExpired(null)
                setShowAccounts(true)
              }}
            >
              {tCommon('reconnect')}
            </button>
            <button
              className="llm-error-banner-close"
              onClick={() => setAuthExpired(null)}
              aria-label={tCommon('close')}
            >
              <CloseIcon size={16} />
            </button>
          </div>
        )}
        {recapBannerMonth && !showMonthlyRecap && (
          <RecapBanner
            month={recapBannerMonth}
            onOpenRecap={() => {
              setRecapBannerMonth(null)
              setShowMonthlyRecap(true)
            }}
            onDismiss={() => {
              setRecapBannerMonth(null)
              fetch(`${API_URL}/api/settings`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ monthly_recap_banner_dismissed: true }),
              })
                .then(handleAuthResponse)
                .then(() => invalidateSettingsCache())
                // Audit 2026-06-11 toast site 4 : en échec, la bannière
                // ressuscite à la prochaine session — prévenir l'utilisateur
                // (pas de rollback : le re-affichage différé est acceptable).
                .catch(silentFailWithToast('recap-dismiss', {
                  message: tCommon('toasts.recap_dismiss_failed'),
                }))
            }}
          />
        )}
        {checkingOnboarding ? (
          <div className="loading-screen" role="status" aria-live="polite" data-testid="loading-screen">
            <div className="loading-brand-mark"><TriangleLogo /></div>
              <div className="loading-bar-track"><div className="loading-bar-fill" /></div>
            <div className="loading-hint">{tCommon('loading')}</div>
          </div>
        ) : showPremiumOnboarding && backendStatus === 'connected' ? (
          <Suspense fallback={
            <div className="loading-screen">
              <div className="loading-brand-mark"><TriangleLogo /></div>
                  <div className="loading-bar-track"><div className="loading-bar-fill" /></div>
              <div className="loading-hint">{tCommon('loading')}</div>
            </div>
          }>
            <PremiumOnboarding
              accountId={accountId ?? 0}
              accountEmail={accountEmail}
              onAccountConnected={refreshAccountData}
              onComplete={() => {
                localStorage.removeItem(FORCE_ONBOARDING_KEY)
                // Persist KB completion so the training page never re-appears after reboot (BUG-H002)
                localStorage.setItem(ONBOARDING_KB_COMPLETE_KEY, 'true')
                handleWizardComplete()
                setShowKbOnboarding(false)
              }}
            />
          </Suspense>
        ) : backendStatus === 'disconnected' || backendStatus === 'checking' ? (
          <div className="status-card">
            <div className="status-card-icon"><TriangleLogo /></div>
            <h2>{backendStatus === 'checking' ? t('connecting') : t('server_unavailable')}</h2>
            <p style={{ color: '#6b7280', fontSize: '14px', margin: '8px 0 16px' }}>
              {backendStatus === 'disconnected' ? t('auto_reconnect') : ''}
            </p>
            <button
              className="retry-button"
              onClick={recheckConnection}
              disabled={backendStatus === 'checking'}
              style={{
                padding: '8px 24px', borderRadius: '8px', border: 'none',
                background: backendStatus === 'checking' ? '#d1d5db' : 'var(--accent-primary, #0d9488)',
                color: '#fff', cursor: backendStatus === 'checking' ? 'default' : 'pointer',
                fontSize: '14px', fontWeight: 500,
              }}
            >
              {backendStatus === 'checking' ? t('connecting') + '...' : tCommon('retry')}
            </button>
          </div>
        ) : appMode === 'calendar' ? (
          <ErrorBoundary>
            <Suspense fallback={
              <div className="loading-screen">
                <div className="loading-brand-mark"><TriangleLogo /></div>
                    <div className="loading-bar-track"><div className="loading-bar-fill" /></div>
                <div className="loading-hint">{tCommon('loading')}</div>
              </div>
            }>
              <CalendarView accountId={accountId != null ? String(accountId) : undefined} onOpenSettings={handleOpenSettings} onOpenAccounts={handleOpenAccounts} onClose={handleCalendarClose} deepWorkSettings={deepWorkTimer.settings} createEventTrigger={createEventTrigger} ribbonVisible={ribbonVisible} onShowRibbon={handleCalendarShowRibbon} userEmail={accountEmail ?? undefined} onComposeToAttendees={handleCalendarComposeToAttendees} imminentEventIds={meetingReminders.imminentEventIds} />
            </Suspense>
          </ErrorBoundary>
        ) : (
          <div key={activeTab} className="tab-content-animated">
            {/* Tab content */}
            {activeTab === 'inbox' && (
              deepWorkTimer.isActive && !deepWorkTimer.isManualOverride ? (
                <div className="inbox-layout">
                  <div className="email-list-panel">
                    <Suspense fallback={null}>
                      <DeepWorkOverlay
                        slotLabel={deepWorkTimer.slotLabel}
                        nextCheckLabel={deepWorkTimer.nextCheckLabel}
                        progress={deepWorkTimer.slotProgress}
                        focusMinutes={deepWorkTimer.focusMinutes}
                        onBypass={deepWorkTimer.bypassOverlay}
                        onSnoozeDay={deepWorkTimer.snoozeForDay}
                        accountId={accountId != null ? String(accountId) : undefined}
                      />
                    </Suspense>
                  </div>
                </div>
              ) : (
              <div
                className={`inbox-layout ${selectedEmail ? 'has-detail' : ''}`}
                style={selectedEmail ? { '--detail-panel-width': `${detailPanelWidth}px` } as React.CSSProperties : undefined}
              >
                <div className="email-list-panel">
                  <ErrorBoundary>
                  <EmailList
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    onSwipeArchive={handleSwipeArchive as any}
                    onSwipeDelete={handleSwipeDelete as any}
                    onEmailsLoaded={handleEmailsLoaded as any}
                    onDisplayedEmailsChange={handleDisplayedEmailsChange as any}
                    activeLabel={activeLabel}
                    onLabelChange={setActiveLabel}
                    providerLabel={activeFolderId}
                    refreshTrigger={refreshKey}
                    localDraftEmailIds={localDraftEmailIds}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onReply={handleShortcutReply}
                    onForward={handleShortcutForward}
                    onArchive={handleShortcutArchive}
                    onDelete={handleShortcutDelete}
                    onToggleRead={handleShortcutToggleRead}
                    onSearch={handleShortcutSearch}
                    onNewMessage={handleOpenNewMessage}
                    onReplyAll={handleShortcutReplyAll}
                    onSearchRef={searchInputRef}
                    bulkArchiveRef={bulkArchiveRef}
                    bulkDeleteRef={bulkDeleteRef}
                    bulkNotSpamRef={bulkNotSpamRef}
                    bulkRestoreRef={bulkRestoreRef}
                    deselectAllRef={deselectAllRef}
                    selectAllRef={selectAllRef}
                    selectAllFromHereRef={selectAllFromHereRef}
                    deleteEmailOptimisticRef={deleteEmailOptimisticRef}
                    archiveEmailOptimisticRef={archiveEmailOptimisticRef}
                    onOpenAccounts={handleOpenAccounts}
                    accountEmail={accountEmail}
                    onDeleteDraft={handleDeleteDraftFromList as any}
                    accountId={accountId ?? undefined}
                  />
                  </ErrorBoundary>
                </div>
                {selectedEmail && (
                  <>
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                  <section className={`email-detail-panel${detailReady ? ' detail-ready' : ''}`} aria-label={t('email_detail_aria')}>
                    {isLoadingEmailDraft ? (
                      <div className="email-detail-loading">
                        <div className="skeleton-header">
                          <div className="skeleton-bar title" />
                          <div className="skeleton-bar sender" />
                          <div className="skeleton-bar date" />
                        </div>
                        <div className="skeleton-body">
                          <div className="skeleton-bar line" />
                          <div className="skeleton-bar line" />
                          <div className="skeleton-bar line" />
                          <div className="skeleton-bar line" />
                          <div className="skeleton-bar line" />
                        </div>
                      </div>
                    ) : emailDraft ? (
                      <Suspense fallback={null}>
                        <PendingDraftDetail
                          key={emailDraft.id}
                          draft={emailDraft}
                          aiEnabled={aiFeaturesEnabled}
                          onUpgradeRequired={handleOpenBillingSettings}
                          onDraftUpdated={(updated) => setEmailDraft(updated)}
                          onDraftValidated={() => {
                            handleCloseEmailDetail()
                            setRefreshKey(k => k + 1)
                            setTimeout(() => setRefreshKey(k => k + 1), 4000)
                            sentCountRef.current += 1
                            milestones.checkMilestones(sentCountRef.current)
                          }}
                          onDraftScheduled={() => {
                            handleCloseEmailDetail()
                            setRefreshKey(k => k + 1)
                          }}
                          onDraftRejected={() => {
                            handleCloseEmailDetail()
                            setRefreshKey(k => k + 1)
                          }}
                          onKnowledgeSuggestion={setKnowledgeSuggestion}
                          onClose={handleCloseEmailDetail}
                          navInfo={emailNavInfo}
                          onNavigatePrev={handleNavigatePrevEmail}
                          onNavigateNext={handleNavigateNextEmail}
                          triggerReplyType={replyTriggerType}
                          onTriggerReplyHandled={() => setReplyTriggerType(null)}
                          onComposerStateChange={setReplyComposerOpen}
                        />
                      </Suspense>
                    ) : (
                      <EmailDetailModal
                        emailId={selectedEmail.id}
                        isOpen={!!selectedEmail}
                        onClose={handleCloseEmailDetail}
                        onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
                        folderName={getFolderLabel(activeTab)}
                        inline={true}
                        emailLabels={selectedEmail.labels}
                        accountEmail={accountEmail ?? undefined}
                        aiEnabled={aiFeaturesEnabled}
                        onUpgradeRequired={handleOpenBillingSettings}
                        onDraftGenerated={() => {
                          setRefreshKey(k => k + 1)
                          if (selectedEmail && selectedEmailIdRef.current === selectedEmail.id) {
                            apiClient.getPendingDraftByEmailId(selectedEmail.id).then(draft => {
                              if (draft && selectedEmailIdRef.current === selectedEmail.id) setEmailDraft(draft)
                            })
                          }
                        }}
                        onReplySent={() => {
                          setRefreshKey(k => k + 1)
                          // Delayed refresh: archive happens in bg thread after send response
                          setTimeout(() => setRefreshKey(k => k + 1), 4000)
                        }}
                        navInfo={emailNavInfo}
                        onNavigatePrev={handleNavigatePrevEmail}
                        onNavigateNext={handleNavigateNextEmail}
                        onExpand={() => setIsEmailExpanded(true)}
                        triggerReplyType={replyTriggerType}
                        onTriggerReplyHandled={() => setReplyTriggerType(null)}
                        onComposerStateChange={setReplyComposerOpen}
                      />
                    )}
                  </section>
                  </>
                )}
              </div>
              )
            )}

            {activeTab === 'drafts' && (
              <div
                className={`inbox-layout${selectedDraft ? ' has-detail' : ''}`}
                style={selectedDraft ? { '--detail-panel-width': `${detailPanelWidth}px` } as React.CSSProperties : undefined}
              >
                <div className="email-list-panel">
                  <PendingDraftList
                    refreshTrigger={refreshKey}
                    onDraftSelect={handleDraftSelect}
                    selectedDraftId={selectedDraftId}
                    onDraftsLoaded={handleDraftsLoaded}
                    savedDrafts={savedDrafts}
                    onSavedDraftClick={handleSavedDraftClick}
                    onSavedDraftDelete={handleDeleteSavedDraft}
                    onCompose={handleOpenNewMessage}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onSearch={handleShortcutSearch}
                    accountId={accountId ?? undefined}
                  />
                </div>
                {selectedDraft && (
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                )}
                <div className={`email-detail-panel${draftDetailReady ? ' detail-ready' : ''}`}>
                  {isLoadingDraft ? (
                    <div className="email-detail-loading">
                      <div className="skeleton-header">
                        <div className="skeleton-bar title" />
                        <div className="skeleton-bar sender" />
                        <div className="skeleton-bar date" />
                      </div>
                      <div className="skeleton-body">
                        <div className="skeleton-bar line" />
                        <div className="skeleton-bar line" />
                        <div className="skeleton-bar line" />
                        <div className="skeleton-bar line" />
                        <div className="skeleton-bar line" />
                      </div>
                    </div>
                  ) : selectedDraft ? (
                    <Suspense fallback={null}>
                      <PendingDraftDetail
                        // Remount on every draft swap (matches the inbox/Snoozed
                        // pattern). Without this, an in-place setSelectedDraft
                        // (nav arrows / notification / tray / wake) keeps the
                        // panel mounted and leaks the prior draft's cc/bcc/
                        // attachments/to into the next draft's send.
                        key={selectedDraft.id}
                        draft={selectedDraft}
                        aiEnabled={aiFeaturesEnabled}
                        onUpgradeRequired={handleOpenBillingSettings}
                        onDraftUpdated={handleDraftUpdated}
                        onDraftValidated={handleDraftValidated}
                        onDraftScheduled={handleDraftScheduled}
                        onDraftRejected={handleDraftRejected}
                        onKnowledgeSuggestion={setKnowledgeSuggestion}
                        onClose={() => { setSelectedDraft(null); setSelectedDraftId(null); }}
                        navInfo={draftNavInfo}
                        onNavigatePrev={handleNavigateUp}
                        onNavigateNext={handleNavigateDown}
                      />
                    </Suspense>
                  ) : (
                    <EmptyState
                      icon={"\u2709"}
                      title={tDrafts('select_draft')}
                      subtitle={tCommon('ai_prepare_reply')}
                    />
                  )}
                </div>
              </div>
            )}

            {(activeTab === 'snoozed' || activeTab === 'scheduled') && (
              <div className="inbox-layout">
                <Suspense fallback={null}>
                  <SnoozedView
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    defaultFilter={activeTab === 'scheduled' ? 'scheduled' : 'all'}
                  />
                </Suspense>
              </div>
            )}

            {activeTab === 'sent' && (
              <div className={`inbox-layout ${selectedEmail ? 'has-detail' : ''}`}>
                <div className="email-list-panel">
                  <EmailList
                    folder="sent"
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    onSwipeArchive={handleSwipeArchive as any}
                    onSwipeDelete={handleSwipeDelete as any}
                    refreshTrigger={refreshKey}
                    onDisplayedEmailsChange={handleDisplayedEmailsChange as any}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onSearch={handleShortcutSearch}
                    onSearchRef={searchInputRef}
                    bulkArchiveRef={bulkArchiveRef}
                    bulkDeleteRef={bulkDeleteRef}
                    bulkNotSpamRef={bulkNotSpamRef}
                    bulkRestoreRef={bulkRestoreRef}
                    deselectAllRef={deselectAllRef}
                    selectAllRef={selectAllRef}
                    selectAllFromHereRef={selectAllFromHereRef}
                    accountId={accountId ?? undefined}
                  />
                </div>
                {selectedEmail && (
                  <>
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                  <div className={`email-detail-panel${detailReady ? ' detail-ready' : ''}`}>
                    <EmailDetailModal
                      emailId={selectedEmail.id}
                      isOpen={!!selectedEmail}
                      onClose={handleCloseEmailDetail}
                      onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
                      folderName={getFolderLabel(activeTab)}
                      inline={true}
                      emailLabels={selectedEmail.labels}
                      accountEmail={accountEmail ?? undefined}
                      aiEnabled={aiFeaturesEnabled}
                      onUpgradeRequired={handleOpenBillingSettings}
                      navInfo={emailNavInfo}
                      onNavigatePrev={handleNavigatePrevEmail}
                      onNavigateNext={handleNavigateNextEmail}
                    />
                  </div>
                  </>
                )}
              </div>
            )}

            {activeTab === 'archived' && (
              <div className={`inbox-layout ${selectedEmail ? 'has-detail' : ''}`}>
                <div className="email-list-panel">
                  <ErrorBoundary>
                  <EmailList
                    folder="archived"
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    onSwipeArchive={handleSwipeArchive as any}
                    onSwipeDelete={handleSwipeDelete as any}
                    refreshTrigger={refreshKey}
                    onDisplayedEmailsChange={handleDisplayedEmailsChange as any}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onSearch={handleShortcutSearch}
                    onSearchRef={searchInputRef}
                    bulkArchiveRef={bulkArchiveRef}
                    bulkDeleteRef={bulkDeleteRef}
                    bulkNotSpamRef={bulkNotSpamRef}
                    bulkRestoreRef={bulkRestoreRef}
                    deselectAllRef={deselectAllRef}
                    selectAllRef={selectAllRef}
                    selectAllFromHereRef={selectAllFromHereRef}
                    accountId={accountId ?? undefined}
                  />
                  </ErrorBoundary>
                </div>
                {selectedEmail && (
                  <>
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                  <div className={`email-detail-panel${detailReady ? ' detail-ready' : ''}`}>
                    <EmailDetailModal
                      emailId={selectedEmail.id}
                      isOpen={!!selectedEmail}
                      onClose={handleCloseEmailDetail}
                      onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
                      folderName={getFolderLabel(activeTab)}
                      inline={true}
                      emailLabels={selectedEmail.labels}
                      accountEmail={accountEmail ?? undefined}
                      aiEnabled={aiFeaturesEnabled}
                      onUpgradeRequired={handleOpenBillingSettings}
                      navInfo={emailNavInfo}
                      onNavigatePrev={handleNavigatePrevEmail}
                      onNavigateNext={handleNavigateNextEmail}
                    />
                  </div>
                  </>
                )}
              </div>
            )}

            {activeTab === 'spam' && (
              <div className={`inbox-layout ${selectedEmail ? 'has-detail' : ''}`}>
                <div className="email-list-panel">
                  <ErrorBoundary>
                  <EmailList
                    folder="spam"
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    onSwipeArchive={handleSwipeArchive as any}
                    onSwipeDelete={handleSwipeDelete as any}
                    refreshTrigger={refreshKey}
                    onDisplayedEmailsChange={handleDisplayedEmailsChange as any}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onSearch={handleShortcutSearch}
                    onSearchRef={searchInputRef}
                    bulkArchiveRef={bulkArchiveRef}
                    bulkDeleteRef={bulkDeleteRef}
                    bulkNotSpamRef={bulkNotSpamRef}
                    bulkRestoreRef={bulkRestoreRef}
                    deselectAllRef={deselectAllRef}
                    selectAllRef={selectAllRef}
                    selectAllFromHereRef={selectAllFromHereRef}
                    accountId={accountId ?? undefined}
                  />
                  </ErrorBoundary>
                </div>
                {selectedEmail && (
                  <>
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                  <div className={`email-detail-panel${detailReady ? ' detail-ready' : ''}`}>
                    <EmailDetailModal
                      emailId={selectedEmail.id}
                      isOpen={!!selectedEmail}
                      onClose={handleCloseEmailDetail}
                      onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
                      folderName={getFolderLabel(activeTab)}
                      inline={true}
                      emailLabels={selectedEmail.labels}
                      accountEmail={accountEmail ?? undefined}
                      aiEnabled={aiFeaturesEnabled}
                      onUpgradeRequired={handleOpenBillingSettings}
                      navInfo={emailNavInfo}
                      onNavigatePrev={handleNavigatePrevEmail}
                      onNavigateNext={handleNavigateNextEmail}
                    />
                  </div>
                  </>
                )}
              </div>
            )}

            {activeTab === 'trash' && (
              <div className={`inbox-layout ${selectedEmail ? 'has-detail' : ''}`}>
                <div className="email-list-panel">
                  <ErrorBoundary>
                  <EmailList
                    folder="trash"
                    onEmailSelect={handleEmailSelect as any}
                    selectedEmailId={selectedEmail?.id}
                    onSwipeArchive={handleSwipeArchive as any}
                    onSwipeDelete={handleSwipeDelete as any}
                    refreshTrigger={refreshKey}
                    onDisplayedEmailsChange={handleDisplayedEmailsChange as any}
                    onNavigateUp={handleNavigateUp}
                    onNavigateDown={handleNavigateDown}
                    onSearch={handleShortcutSearch}
                    onSearchRef={searchInputRef}
                    bulkArchiveRef={bulkArchiveRef}
                    bulkDeleteRef={bulkDeleteRef}
                    bulkNotSpamRef={bulkNotSpamRef}
                    bulkRestoreRef={bulkRestoreRef}
                    deselectAllRef={deselectAllRef}
                    selectAllRef={selectAllRef}
                    selectAllFromHereRef={selectAllFromHereRef}
                    accountId={accountId ?? undefined}
                  />
                  </ErrorBoundary>
                </div>
                {selectedEmail && (
                  <>
                  <div
                    className={`resize-handle${isDragging ? ' dragging' : ''}`}
                    onMouseDown={handleResizeStart}
                  />
                  <div className={`email-detail-panel${detailReady ? ' detail-ready' : ''}`}>
                    <EmailDetailModal
                      emailId={selectedEmail.id}
                      isOpen={!!selectedEmail}
                      onClose={handleCloseEmailDetail}
                      onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
                      folderName={getFolderLabel(activeTab)}
                      inline={true}
                      emailLabels={selectedEmail.labels}
                      accountEmail={accountEmail ?? undefined}
                      aiEnabled={aiFeaturesEnabled}
                      onUpgradeRequired={handleOpenBillingSettings}
                      navInfo={emailNavInfo}
                      onNavigatePrev={handleNavigatePrevEmail}
                      onNavigateNext={handleNavigateNextEmail}
                    />
                  </div>
                  </>
                )}
              </div>
            )}

            {/* Shortcuts ribbon — full width at bottom of tab content.
                Hidden while focus mode is active: the overlay is a calm,
                distraction-free surface and the keyboard hints there don't
                apply. Also hidden while the New message modal is open — the
                modal embarks its own hints row (.nm-shortcut-hints), the
                ribbon on the backdrop was ~250px below it, disconnected.
                showComposeModal (ComposeEmailModal, tray/deep-link) is hidden
                too: its old hints advertised Ctrl+Enter/Ctrl+G handlers that
                this modal never had. */}
            <div className={`shortcuts-ribbon ${ribbonVisible && !(deepWorkTimer.isActive && !deepWorkTimer.isManualOverride) && !showNewMessage && !showComposeModal ? 'shortcuts-ribbon--visible' : 'shortcuts-ribbon--hidden'}`}>
              {activeTab === 'inbox' && replyComposerOpen ? (<>
                <div className="shortcut-group">
                  {/* Ctrl+Enter in reply context now sends, matching NewMessageModal.
                      AI pipeline is reachable via Ctrl+G (compose) or W (regenerate),
                      so we no longer surface "AI Process" as the Ctrl+Enter label. */}
                  <div className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', ctrlKey:true, bubbles:true}))} onKeyDown={handleKeyboardClick(() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', ctrlKey:true, bubbles:true})))}><ShortcutKeys combo={navigator.platform?.includes('Mac') ? '⌘+Enter' : 'Ctrl+Enter'} /><span className="shortcut-label">{tCommon('send')}</span></div>
                  <div className="shortcut-item shortcut-item--highlighted"><ShortcutKeys combo={navigator.platform?.includes('Mac') ? '⌘+G' : 'Ctrl+G'} /><span className="shortcut-label">{tCompose('action_compose')}</span></div>
                  {SHOW_EXPERT_SHORTCUT_HINT && activeSpecialties.length > 0 && (
                    <div className="shortcut-item" title={tCompose('expert_shortcut_tooltip')}>
                      <ShortcutKeys combo={navigator.platform?.includes('Mac') ? '⇧+⌘+G' : 'Ctrl+Shift+G'} />
                      <span className="shortcut-label">Expert</span>
                    </div>
                  )}
                  <div className="shortcut-item"><ShortcutKeys combo={navigator.platform?.includes('Mac') ? '⇧+⌘+,' : 'Ctrl+Shift+,'} /><span className="shortcut-label">{tDrafts('delete_draft_short')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item"><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>) : activeTab === 'inbox' && selectedEmail ? (<>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateUp} onKeyDown={handleKeyboardClick(handleNavigateUp)}><span className="shortcut-key">&uarr;</span><span className="shortcut-label">{tCommon('previous')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateDown} onKeyDown={handleKeyboardClick(handleNavigateDown)}><span className="shortcut-key">&darr;</span><span className="shortcut-label">{tCommon('next')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={handleShortcutReply} onKeyDown={handleKeyboardClick(handleShortcutReply)}><span className="shortcut-key">R</span><span className="shortcut-label">{tCompose('reply')}</span></div>
                  <div className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={handleShortcutReplyAll} onKeyDown={handleKeyboardClick(handleShortcutReplyAll)}><span className="shortcut-key">A</span><span className="shortcut-label">{tCompose('reply_all_short')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutForward} onKeyDown={handleKeyboardClick(handleShortcutForward)}><span className="shortcut-key">F</span><span className="shortcut-label">{tCompose('forward')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutArchive} onKeyDown={handleKeyboardClick(handleShortcutArchive)}><span className="shortcut-key">E</span><span className="shortcut-label">{t('archive_action')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutDelete} onKeyDown={handleKeyboardClick(handleShortcutDelete)}><span className="shortcut-key">Del</span><span className="shortcut-label">{tCommon('delete')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item"><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>) : activeTab === 'inbox' ? (<>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateUp} onKeyDown={handleKeyboardClick(handleNavigateUp)}><span className="shortcut-key">&uarr;</span><span className="shortcut-label">{tCommon('previous')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateDown} onKeyDown={handleKeyboardClick(handleNavigateDown)}><span className="shortcut-key">&darr;</span><span className="shortcut-label">{tCommon('next')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div data-onboarding-target="new-message" className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={handleOpenNewMessage} onKeyDown={handleKeyboardClick(handleOpenNewMessage)}><span className="shortcut-key">N</span><span className="shortcut-label">{tCommon('new_message')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutArchive} onKeyDown={handleKeyboardClick(handleShortcutArchive)}><span className="shortcut-key">E</span><span className="shortcut-label">{t('archive_action')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutDelete} onKeyDown={handleKeyboardClick(handleShortcutDelete)}><span className="shortcut-key">Del</span><span className="shortcut-label">{tCommon('delete')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutSearch} onKeyDown={handleKeyboardClick(handleShortcutSearch)}><span className="shortcut-key">/</span><span className="shortcut-label">{tCommon('search')}</span></div>
                  <div className="shortcut-item"><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>) : (activeTab === 'snoozed' || activeTab === 'scheduled') ? (<>
                {/* Later view — ↑/↓ navigate, Del removes the open item, Esc
                    closes. The buttons dispatch raw KeyboardEvents that
                    SnoozedView's window listener picks up; Del maps to the row's
                    primary action per kind (unsnooze / mark-done / cancel-send /
                    delete-draft), with a confirm on the irreversible scheduled +
                    draft cases. */}
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowUp', bubbles:true}))} onKeyDown={handleKeyboardClick(() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowUp', bubbles:true})))}><span className="shortcut-key">&uarr;</span><span className="shortcut-label">{tCommon('previous')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowDown', bubbles:true}))} onKeyDown={handleKeyboardClick(() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowDown', bubbles:true})))}><span className="shortcut-key">&darr;</span><span className="shortcut-label">{tCommon('next')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Delete', bubbles:true}))} onKeyDown={handleKeyboardClick(() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Delete', bubbles:true})))}><span className="shortcut-key">Del</span><span className="shortcut-label">{tCommon('remove')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}))} onKeyDown={handleKeyboardClick(() => window.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})))}><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>) : activeTab === 'drafts' ? (<>
                {/* Audit 2026-06-11 U-02 : la vue Drafts héritait du catch-all
                    dont les hints mentaient — Del n'a AUCUN handler côté
                    brouillons (pas de suppression clavier, volontaire) et ↑/↓
                    ne naviguent que les brouillons IA (les brouillons locaux
                    s'ouvrent en modale, pas de sélection). On n'affiche donc
                    ↑/↓ que s'il y a des brouillons IA, et jamais Del. */}
                {draftsTotal > 0 && (
                  <div className="shortcut-group">
                    <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateUp} onKeyDown={handleKeyboardClick(handleNavigateUp)}><span className="shortcut-key">&uarr;</span><span className="shortcut-label">{tCommon('previous')}</span></div>
                    <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateDown} onKeyDown={handleKeyboardClick(handleNavigateDown)}><span className="shortcut-key">&darr;</span><span className="shortcut-label">{tCommon('next')}</span></div>
                  </div>
                )}
                <div className="shortcut-group">
                  <div className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={handleOpenNewMessage} onKeyDown={handleKeyboardClick(handleOpenNewMessage)}><span className="shortcut-key">N</span><span className="shortcut-label">{tCommon('new_message')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutSearch} onKeyDown={handleKeyboardClick(handleShortcutSearch)}><span className="shortcut-key">/</span><span className="shortcut-label">{tCommon('search')}</span></div>
                  <div className="shortcut-item"><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>) : (<>
                {/* Catch-all: Sent / Archive / Spam / Trash / Search-results.
                    BUG-#17 (2026-05-17): `N New message` was previously missing
                    from these views even though the shortcut itself worked
                    everywhere — surface it so users discover it from the
                    footer like they do on Inbox. Reply/forward hints stay
                    inbox-only because they're not meaningful here. */}
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateUp} onKeyDown={handleKeyboardClick(handleNavigateUp)}><span className="shortcut-key">&uarr;</span><span className="shortcut-label">{tCommon('previous')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleNavigateDown} onKeyDown={handleKeyboardClick(handleNavigateDown)}><span className="shortcut-key">&darr;</span><span className="shortcut-label">{tCommon('next')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item shortcut-item--highlighted" role="button" tabIndex={0} onClick={handleOpenNewMessage} onKeyDown={handleKeyboardClick(handleOpenNewMessage)}><span className="shortcut-key">N</span><span className="shortcut-label">{tCommon('new_message')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutSearch} onKeyDown={handleKeyboardClick(handleShortcutSearch)}><span className="shortcut-key">/</span><span className="shortcut-label">{tCommon('search')}</span></div>
                  <div className="shortcut-item" role="button" tabIndex={0} onClick={handleShortcutDelete} onKeyDown={handleKeyboardClick(handleShortcutDelete)}><span className="shortcut-key">Del</span><span className="shortcut-label">{tCommon('delete')}</span></div>
                </div>
                <div className="shortcut-group">
                  <div className="shortcut-item"><span className="shortcut-key">Esc</span><span className="shortcut-label">{tCommon('close')}</span></div>
                </div>
              </>)}
            </div>
          </div>
        )}
      </main>
      </div>

      {/* Lazy-loaded modals wrapped in ErrorBoundary + Suspense */}
      <ErrorBoundary>
      <Suspense fallback={null}>
        {showSettings && (
          <div ref={settingsTrapRef} className={`settings-modal-overlay${closingModal === 'settings' ? ' closing' : ''}`} data-testid="settings-overlay" role="dialog" aria-modal="true" aria-label={tCommon('settings_aria')} onMouseDown={(e) => { if (e.target === e.currentTarget) closeWithAnimation(setShowSettings, 'settings'); }}>
            <div className="settings-modal" data-testid="settings-modal" onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
              <Settings
                openBilling={openBillingOnSettings}
                onClose={() => closeWithAnimation(setShowSettings, 'settings')}
                onOpenAccounts={() => {
                  setShowSettings(false)
                  setShowAccounts(true)
                }}
                onOpenLabelLibrary={() => {
                  setShowSettings(false)
                  setShowLabelLibrary(true)
                }}
                onOpenSnippets={() => {
                  setShowSettings(false)
                  setShowSnippetLibrary(true)
                }}
                onOpenRecap={() => {
                  setShowSettings(false)
                  setShowMonthlyRecap(true)
                }}
                onOpenTraining={() => {
                  setShowSettings(false)
                  setShowTraining(true)
                }}
                onOpenShortcuts={() => {
                  setShowShortcutsHelp(true)
                }}
                onOpenDeepWork={() => {
                  setShowDeepWorkPanel(true)
                }}
                onOpenMeetingReminders={() => {
                  setShowMeetingReminders(true)
                }}
                onOpenLearning={() => {
                  setShowSettings(false)
                  setShowLearningDashboard(true)
                }}
                onStartGuidedTour={() => {
                  guidedTour.start()
                }}
                onLogout={auth.logout}
                accountId={accountId ?? undefined}
                /* Badge "Activé" sur Productivité → Mode concentration. Dérivé
                   du timer canonique (la même instance que le DeepWorkPanel
                   mute) : configuré = au moins un sous-mode ON, OU une session
                   focus en cours. Avant, Settings lisait sa PROPRE instance
                   useDeepWorkSetting (cache 30 s, sans abonnement) qui restait
                   périmée après un toggle dans le panneau → badge fantôme. */
                deepWorkActive={
                  (deepWorkTimer.isActive && !deepWorkTimer.isManualOverride)
                  || deepWorkTimer.settings.emailsEnabled
                  || deepWorkTimer.settings.workEnabled
                }
              />
            </div>
          </div>
        )}

        {showMyStyle && (
          <div ref={myStyleTrapRef} className={`settings-modal-overlay${closingModal === 'myStyle' ? ' closing' : ''}`} role="dialog" aria-modal="true" aria-label={tCommon('my_style')} onMouseDown={(e) => { if (e.target === e.currentTarget) closeWithAnimation(setShowMyStyle, 'myStyle'); }}>
            <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
              <MyStyle onClose={() => closeWithAnimation(setShowMyStyle, 'myStyle')} />
            </div>
          </div>
        )}

        {showLearningDashboard && (
          <div ref={learningTrapRef} className={`settings-modal-overlay${closingModal === 'learning' ? ' closing' : ''}`} role="dialog" aria-modal="true" aria-label={tCommon('learning_dashboard')} onMouseDown={(e) => { if (e.target === e.currentTarget) closeWithAnimation(setShowLearningDashboard, 'learning'); }}>
            <div className="settings-modal settings-modal-wide" onClick={(e) => e.stopPropagation()}>
              <LearningDashboard onClose={() => closeWithAnimation(setShowLearningDashboard, 'learning')} onBack={() => { setShowLearningDashboard(false); setShowSettings(true); }} />
            </div>
          </div>
        )}


        {showAccounts && (
          <div ref={accountsTrapRef} className={`settings-modal-overlay${closingModal === 'accounts' ? ' closing' : ''}`} role="dialog" aria-modal="true" aria-label={tCommon('email_accounts')} onMouseDown={(e) => { if (e.target === e.currentTarget) { setAccountReconnectTarget(null); closeWithAnimation(setShowAccounts, 'accounts'); } }}>
            <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
              <AccountManager
                initialReconnect={accountReconnectTarget}
                onClose={() => {
                  setAccountReconnectTarget(null)
                  closeWithAnimation(setShowAccounts, 'accounts')
                }}
                onBack={() => {
                  setAccountReconnectTarget(null)
                  setShowAccounts(false)
                  setShowSettings(true)
                }}
                onAccountChanged={() => {
                  invalidateEmailCache()
                  // Force un hard-refresh (pas soft) pour que le backend re-check les comptes
                  setRefreshKey(k => k + 1)
                  // Dispatch un event pour que EmailList puisse réagir immédiatement
                  window.dispatchEvent(new CustomEvent('agentys:account-changed'))
                }}
              />
            </div>
          </div>
        )}

        {showComposeModal && (
          <ComposeEmailModal
            isOpen={showComposeModal}
            onClose={() => setShowComposeModal(false)}
          />
        )}

        {showNewMessage && (
          <NewMessageModal
            isOpen={showNewMessage}
            accountId={accountId ?? undefined}
            onClose={() => {
              setShowNewMessage(false)
              setComposeInitialDraft(undefined)
              // If the V2 tour was mid-demo, closing the composer exits the tour
              if (v2PhaseRef.current === 'compose') v2SkipRef.current()
            }}
            initialDraft={composeInitialDraft}
            onDraftSaved={refreshSavedDrafts}
            aiEnabled={aiFeaturesEnabled}
            onUpgradeRequired={handleOpenBillingSettings}
          />
        )}

        {showShortcutsHelp && (
          <ShortcutsHelpPanel
            isOpen={showShortcutsHelp}
            onClose={() => setShowShortcutsHelp(false)}
            onBack={() => { setShowShortcutsHelp(false); setShowSettings(true); }}
          />
        )}

        {showMeetingReminders && (
          <Suspense fallback={null}>
            <MeetingRemindersPanel
              isOpen={showMeetingReminders}
              onClose={() => setShowMeetingReminders(false)}
              onBack={() => { setShowMeetingReminders(false); setShowSettings(true); }}
            />
          </Suspense>
        )}

        {showLabelLibrary && (
          <LabelLibrary
            isOpen={showLabelLibrary}
            onClose={() => setShowLabelLibrary(false)}
            onBack={() => { setShowLabelLibrary(false); setShowSettings(true); }}
            onOpenEmail={(emailId) => {
              setShowLabelLibrary(false)

              setSelectedEmail({ id: emailId } as any)
            }}
          />
        )}

        {showSnippetLibrary && (
          <SnippetLibrary
            isOpen={showSnippetLibrary}
            onClose={() => setShowSnippetLibrary(false)}
            onBack={() => { setShowSnippetLibrary(false); setShowSettings(true); }}
            accountId={accountId ?? undefined}
          />
        )}

        {showMonthlyRecap && (
          <div className="settings-modal-overlay" role="dialog" aria-modal="true" aria-label={tCommon('monthly_recap')} onClick={() => setShowMonthlyRecap(false)}>
            <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
              <MonthlyRecapPage onClose={() => setShowMonthlyRecap(false)} onBack={() => { setShowMonthlyRecap(false); setShowSettings(true); }} />
            </div>
          </div>
        )}

        {showTraining && (
          <div ref={trainingTrapRef} className="settings-modal-overlay" role="dialog" aria-modal="true" aria-label={tCommon('agentys_training')} onMouseDown={(e) => { overlayMouseDownOnSelfRef.current = e.target === e.currentTarget }} onClick={(e) => { if (e.target === e.currentTarget && overlayMouseDownOnSelfRef.current) setShowTraining(false) }}>
            <div className="settings-modal training-page-modal" onClick={(e) => e.stopPropagation()}>
              <TrainingPage onClose={() => setShowTraining(false)} onBack={() => { setShowTraining(false); setShowSettings(true); }} accountId={accountId ?? undefined} accountEmail={accountEmail ?? undefined} />
            </div>
          </div>
        )}

        {/* Email detail now rendered inline in split-view layout */}

        {/* Expanded fullscreen email modal */}
        {isEmailExpanded && selectedEmail && (
          <EmailDetailModal
            emailId={selectedEmail.id}
            isOpen={true}
            onClose={() => setIsEmailExpanded(false)}
            onDraftSaved={refreshSavedDrafts}
                        onDraftDiscarded={() => setRefreshKey(k => k + 1)}
            folderName={getFolderLabel(activeTab)}
            expanded={true}
            navInfo={emailNavInfo}
            onNavigatePrev={handleNavigatePrevEmail}
            onNavigateNext={handleNavigateNextEmail}
            emailLabels={selectedEmail.labels}
            accountEmail={accountEmail ?? undefined}
            aiEnabled={aiFeaturesEnabled}
            onUpgradeRequired={handleOpenBillingSettings}
          />
        )}
      </Suspense>
      </ErrorBoundary>

      {showSupportPanel && (
        <Suspense fallback={null}>
          <SupportPanel
            isOpen={showSupportPanel}
            onClose={() => setShowSupportPanel(false)}
            accountEmail={accountEmail}
          />
        </Suspense>
      )}

      {commandPaletteMounted && (
        <Suspense fallback={null}>
          <CommandPaletteContainer
            isOpen={showCommandPalette}
            onClose={() => setShowCommandPalette(false)}
            baseActions={commandActions}
            accountId={accountId ?? undefined}
            onFilterLabel={handleCommandFilterLabel}
            onComposeTo={handleCommandComposeTo}
            onUseSnippet={handleCommandUseSnippet}
          />
        </Suspense>
      )}

      {knowledgeSuggestion && (
        <KnowledgeSuggestionToast
          suggestion={knowledgeSuggestion}
          onDismiss={() => setKnowledgeSuggestion(null)}
        />
      )}

      {deepWorkRecapData && (
        <Suspense fallback={null}>
          <DeepWorkRecapCard
            focusMinutes={deepWorkRecapData.focusMinutes}
            emailsProcessed={deepWorkRecapData.emailsProcessed}
            streakDays={deepWorkRecapData.streakDays}
            onDismiss={() => setDeepWorkRecapData(null)}
          />
        </Suspense>
      )}


      {/* Onboarding v2 — Guided Tour */}
      {guidedTour.isActive && (
        <Suspense fallback={null}>
          <GuidedTour tour={guidedTour} />
        </Suspense>
      )}

      {/* Onboarding V2 — mini-tour N → Ctrl+G
          Suppressed while PremiumOnboarding is mounted so the user never sees
          the two onboardings stacked at first launch. The v2 overlay re-arms
          itself from localStorage once the premium wizard completes. */}
      {onboardingV2.isActive && !showPremiumOnboarding && (
        <Suspense fallback={null}>
          <OnboardingV2Overlay
            phase={onboardingV2.phase}
            onNext={onboardingV2.next}
            onSkip={onboardingV2.skip}
            isMobile={isMobile}
            onOpenNewMessage={handleOpenNewMessage}
          />
        </Suspense>
      )}

      {/* Milestone Toast */}
      {milestones.pendingMilestone && (
        <Suspense fallback={null}>
          <MilestoneToast
            milestone={milestones.pendingMilestone}
            onDismiss={milestones.dismissMilestone}
          />
        </Suspense>
      )}

    </div>
    </LabelsProvider>
  )
}

export default Sentry.withProfiler(App)
