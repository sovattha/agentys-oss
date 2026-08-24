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

import { useEffect, useRef, useState } from 'react'
import type { SidebarTab } from '../components/Sidebar'

export type AppMode = 'mail' | 'calendar'

// ---------------------------------------------------------------------------
// URL routing (QA 2026-05-19 - Bugs #3 and #14)
//
// Before this change, all navigation was held in React state and the URL bar
// stayed at "/" forever. That broke browser back/forward, refresh, sharing,
// bookmarking specific views, and deep links from notifications. Unknown
// paths silently rendered the sign-in screen while leaving the bogus URL in
// the address bar - there was no 404.
//
// Rather than pull in react-router-dom (which would require rewriting every
// setActiveTab call site through a hook), we sync the existing
// activeTab/appMode state with location.pathname via the History API.
// ---------------------------------------------------------------------------

type RouteState = { appMode: AppMode; activeTab: SidebarTab }

const PATH_TO_ROUTE: Record<string, RouteState> = {
  '/': { appMode: 'mail', activeTab: 'inbox' },
  '/inbox': { appMode: 'mail', activeTab: 'inbox' },
  '/settings/billing': { appMode: 'mail', activeTab: 'inbox' },
  '/drafts': { appMode: 'mail', activeTab: 'drafts' },
  '/later': { appMode: 'mail', activeTab: 'snoozed' },
  '/snoozed': { appMode: 'mail', activeTab: 'snoozed' },
  '/scheduled': { appMode: 'mail', activeTab: 'scheduled' },
  '/sent': { appMode: 'mail', activeTab: 'sent' },
  '/archive': { appMode: 'mail', activeTab: 'archived' },
  '/archived': { appMode: 'mail', activeTab: 'archived' },
  '/spam': { appMode: 'mail', activeTab: 'spam' },
  '/trash': { appMode: 'mail', activeTab: 'trash' },
  '/calendar': { appMode: 'calendar', activeTab: 'inbox' },
}

const TAB_TO_PATH: Record<SidebarTab, string> = {
  inbox: '/inbox',
  drafts: '/drafts',
  snoozed: '/later',
  scheduled: '/scheduled',
  sent: '/sent',
  archived: '/archive',
  spam: '/spam',
  trash: '/trash',
}

function routeFromPath(pathname: string): { route: RouteState; matched: boolean } {
  const normalised = pathname.length > 1 && pathname.endsWith('/')
    ? pathname.slice(0, -1)
    : pathname
  const hit = PATH_TO_ROUTE[normalised]
  if (hit) return { route: hit, matched: true }
  return { route: PATH_TO_ROUTE['/'], matched: false }
}

function pathForState(appMode: AppMode, activeTab: SidebarTab): string {
  if (appMode === 'calendar') return '/calendar'
  return TAB_TO_PATH[activeTab] ?? '/inbox'
}

function readInitialRoute(): { route: RouteState; matched: boolean } {
  if (typeof window === 'undefined') {
    return { route: PATH_TO_ROUTE['/'], matched: true }
  }
  return routeFromPath(window.location.pathname)
}

// F-03 (audit regressions 2026-05-17 batch4): per-account activeLabel scoping
// so a filter set in account A doesn't leak into account B.
const ACTIVE_LABEL_KEY_PREFIX = 'agentys-inbox-active-label'

function buildLabelKey(accountId: string | number | null | undefined): string {
  return `${ACTIVE_LABEL_KEY_PREFIX}:${accountId ?? '__none__'}`
}

function readPersistedLabel(key: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writePersistedLabel(key: string, value: string | null): void {
  if (typeof window === 'undefined') return
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch {
    /* localStorage unavailable / quota - degrade gracefully */
  }
}

export interface NavigationController {
  activeTab: SidebarTab
  setActiveTab: React.Dispatch<React.SetStateAction<SidebarTab>>
  appMode: AppMode
  setAppMode: React.Dispatch<React.SetStateAction<AppMode>>
  activeLabel: string | null
  setActiveLabel: React.Dispatch<React.SetStateAction<string | null>>
  activeFolderId: string | null
  setActiveFolderId: React.Dispatch<React.SetStateAction<string | null>>
  refreshKey: number
  setRefreshKey: React.Dispatch<React.SetStateAction<number>>
}

export function useNavigationController(
  accountId?: string | number | null,
): NavigationController {
  // Bug #3 / #14: seed state from window.location so a refresh / deep link
  // / unknown URL lands on the right view. For unknown paths, canonicalize
  // the URL via replaceState so the address bar stops showing the bogus path.
  const initial = readInitialRoute()
  if (typeof window !== 'undefined' && !initial.matched) {
    try {
      window.history.replaceState({ agentys: true }, '', '/inbox')
    } catch {
      /* SecurityError in sandboxed contexts - ignore */
    }
  }

  const [activeTab, setActiveTab] = useState<SidebarTab>(initial.route.activeTab)
  const [appMode, setAppMode] = useState<AppMode>(initial.route.appMode)
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // URL <-> state sync (Bug #3): pushState on state change, listen to popstate
  // for browser back/forward. A guard ref prevents echo-loops.
  const suppressNextPushRef = useRef(false)
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (suppressNextPushRef.current) {
      suppressNextPushRef.current = false
      return
    }
    const target = pathForState(appMode, activeTab)
    if (window.location.pathname === '/settings/billing') return
    if (window.location.pathname === target) return
    try {
      window.history.pushState({ agentys: true }, '', target)
    } catch {
      /* ignore - state is already updated, URL just won't reflect */
    }
  }, [appMode, activeTab])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = () => {
      const next = routeFromPath(window.location.pathname)
      if (!next.matched) {
        try { window.history.replaceState({ agentys: true }, '', '/inbox') } catch { /* ignore */ }
      }
      suppressNextPushRef.current = true
      setAppMode(next.route.appMode)
      setActiveTab(next.route.activeTab)
    }
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  const labelKey = buildLabelKey(accountId)
  const [activeLabel, setActiveLabel] = useState<string | null>(() => readPersistedLabel(labelKey))

  const prevLabelKeyRef = useRef(labelKey)
  useEffect(() => {
    if (prevLabelKeyRef.current !== labelKey) {
      prevLabelKeyRef.current = labelKey
      setActiveLabel(readPersistedLabel(labelKey))
    }
  }, [labelKey])

  useEffect(() => {
    writePersistedLabel(labelKey, activeLabel)
  }, [activeLabel, labelKey])

  return {
    activeTab, setActiveTab,
    appMode, setAppMode,
    activeLabel, setActiveLabel,
    activeFolderId, setActiveFolderId,
    refreshKey, setRefreshKey,
  }
}
