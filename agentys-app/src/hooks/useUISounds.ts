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
