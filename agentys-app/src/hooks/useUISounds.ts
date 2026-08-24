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
import { isUISoundsEnabled, setUISoundsEnabled } from "../services/uiSounds";
import { API_URL } from "../config";
import { fetchSettingsCached } from "./useSettingsCache";
import { getAuthHeaders, handleAuthResponse } from "../services/authToken";

const API_BASE = `${API_URL}/api`;

export function useUISounds() {
  const [enabled, setEnabled] = useState(isUISoundsEnabled);

  useEffect(() => {
    fetchSettingsCached()
      .then((data) => {
        if (typeof data.ui_sounds_enabled === "boolean") {
          setEnabled(data.ui_sounds_enabled);
          setUISoundsEnabled(data.ui_sounds_enabled);
        }
      })
      .catch(err => console.error('[useUISounds] load settings failed:', err));
  }, []);

  const toggle = useCallback(() => {
    const newValue = !enabled;
    setEnabled(newValue);
    setUISoundsEnabled(newValue);
    fetch(`${API_BASE}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify({ ui_sounds_enabled: newValue }),
    })
      .then(handleAuthResponse)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`PATCH /api/settings returned ${res.status}`);
        }
      })
      .catch(err => {
        console.error('[useUISounds] patch failed:', err);
        setEnabled(!newValue);
        setUISoundsEnabled(!newValue);
      });
  }, [enabled]);

  return { enabled, toggle };
}
