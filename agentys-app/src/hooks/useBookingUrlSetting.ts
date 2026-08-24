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

import { useState, useCallback, useEffect } from "react";
import { API_URL } from "../config";
import { fetchSettingsCached, patchSettingsCache } from "./useSettingsCache";
import { getAuthHeaders, handleAuthResponse } from "../services/authToken";

const API_BASE = `${API_URL}/api`;

export function useBookingUrlSetting(accountId?: number) {
  const [bookingUrl, setBookingUrlState] = useState<string>("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSettingsCached(accountId)
      .then((data) => {
        if (cancelled) return;
        if (typeof data.booking_url === "string") {
          setBookingUrlState(data.booking_url);
        }
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => { cancelled = true; };
  }, [accountId]);

  const setBookingUrl = useCallback(async (url: string): Promise<{ ok: boolean; error?: string }> => {
    const trimmed = url.trim();
    setBookingUrlState(trimmed);
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ booking_url: trimmed }),
      });
      handleAuthResponse(res);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        return { ok: false, error: body?.error || `HTTP ${res.status}` };
      }
      patchSettingsCache({ booking_url: trimmed }, accountId);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "Network error" };
    }
  }, [accountId]);

  return { bookingUrl, setBookingUrl, loaded };
}

/**
 * Pattern-match the URL against well-known booking tools.
 * Returns null if it looks like a known tool, otherwise a short
 * provider-name hint or "unknown" — used to soft-warn the user.
 *
 * The backend already enforces "must start with http(s)://"; this
 * function is purely about *recognizing* common booking platforms,
 * not blocking unknown ones.
 */
export function classifyBookingUrl(url: string):
  | { kind: 'google' }
  | { kind: 'microsoft' }
  | { kind: 'calendly' }
  | { kind: 'cal_com' }
  | { kind: 'savvycal' }
  | { kind: 'tidycal' }
  | { kind: 'youcanbookme' }
  | { kind: 'hubspot' }
  | { kind: 'chilipiper' }
  | { kind: 'unknown' }
  | null {
  if (!url) return null;
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return { kind: 'unknown' };
  }
  if (host === 'calendar.app.google' || host === 'calendar.google.com') return { kind: 'google' };
  if (host === 'outlook.office.com' || host === 'outlook.office365.com' || host === 'outlook.live.com') return { kind: 'microsoft' };
  if (host === 'calendly.com' || host.endsWith('.calendly.com')) return { kind: 'calendly' };
  if (host === 'cal.com' || host.endsWith('.cal.com')) return { kind: 'cal_com' };
  if (host === 'savvycal.com' || host.endsWith('.savvycal.com')) return { kind: 'savvycal' };
  if (host === 'tidycal.com' || host.endsWith('.tidycal.com')) return { kind: 'tidycal' };
  if (host.endsWith('.youcanbook.me') || host === 'youcanbook.me') return { kind: 'youcanbookme' };
  if (host.endsWith('.hubspot.com') && url.includes('/meetings/')) return { kind: 'hubspot' };
  if (host.endsWith('.chilipiper.com')) return { kind: 'chilipiper' };
  return { kind: 'unknown' };
}
