import { useState, useCallback, useEffect } from "react";
import i18n from "../i18n";
import { API_URL } from "../config";
import { fetchSettingsCached } from "./useSettingsCache";
import { getAuthHeaders, getStoredToken, handleAuthResponse } from "../services/authToken";
import { silentFailWithToast } from "../utils/silentFail";

const API_BASE = `${API_URL}/api`;

export interface CheckSlot {
  start: string   // "HH:MM"
  duration: number // minutes (15-120)
}

export interface WorkBlock {
  start: string    // "HH:MM"
  duration: number // minutes (15-480)
  label: string
}

export interface DeepWorkSettings {
  enabled: boolean
  emailsEnabled: boolean
  workEnabled: boolean
  checkSlots: CheckSlot[]
  vipContacts: string[]
  weekdays: number[]  // ISO: 1=Mon, 7=Sun
  personalBlocks: WorkBlock[]
}

const DEFAULT_CHECK_SLOTS: CheckSlot[] = [
  { start: "08:00", duration: 30 },
  { start: "12:30", duration: 30 },
  { start: "17:30", duration: 30 },
];

const DEFAULT_SETTINGS: DeepWorkSettings = {
  // OFF by default — both sub-modes start disabled (mirrors the backend
  // DEFAULT_SETTINGS). A fresh user sees both toggles off and no "Activé" badge.
  enabled: false,
  emailsEnabled: false,
  workEnabled: false,
  checkSlots: DEFAULT_CHECK_SLOTS,
  vipContacts: [],
  weekdays: [1, 2, 3, 4, 5],
  personalBlocks: [],
};

/** Preset check slot templates by count */
export const CHECK_SLOT_PRESETS: Record<number, CheckSlot[]> = {
  1: [{ start: "08:00", duration: 30 }],
  2: [{ start: "08:00", duration: 30 }, { start: "17:30", duration: 30 }],
  3: [{ start: "08:00", duration: 30 }, { start: "12:30", duration: 30 }, { start: "17:30", duration: 30 }],
  4: [{ start: "08:00", duration: 30 }, { start: "11:00", duration: 30 }, { start: "14:00", duration: 30 }, { start: "17:30", duration: 30 }],
  5: [{ start: "08:00", duration: 30 }, { start: "10:30", duration: 30 }, { start: "13:00", duration: 30 }, { start: "15:30", duration: 30 }, { start: "17:30", duration: 30 }],
};

/** Preset work block templates by count */
export const WORK_BLOCK_PRESETS: Record<number, WorkBlock[]> = {
  1: [{ start: "09:00", duration: 120, label: "Travail personnel" }],
  2: [
    { start: "09:00", duration: 120, label: "Travail personnel" },
    { start: "14:00", duration: 120, label: "Travail personnel" },
  ],
  3: [
    { start: "09:00", duration: 90, label: "Travail personnel" },
    { start: "13:00", duration: 90, label: "Travail personnel" },
    { start: "15:30", duration: 90, label: "Travail personnel" },
  ],
  4: [
    { start: "08:30", duration: 90, label: "Travail personnel" },
    { start: "10:30", duration: 60, label: "Travail personnel" },
    { start: "13:30", duration: 90, label: "Travail personnel" },
    { start: "16:00", duration: 60, label: "Travail personnel" },
  ],
  5: [
    { start: "08:00", duration: 60, label: "Travail personnel" },
    { start: "09:30", duration: 60, label: "Travail personnel" },
    { start: "11:00", duration: 60, label: "Travail personnel" },
    { start: "14:00", duration: 60, label: "Travail personnel" },
    { start: "16:00", duration: 60, label: "Travail personnel" },
  ],
};

// Site 1 (audit toast-coverage 2026-06-11) : chaque setter optimiste faisait
// console.error + rollback muet — le switch « ressautait » sans explication.
// Même classe que les toggles Settings (#316/#324), jamais migrée ici.
// Le message est résolu au moment de l'erreur (langue courante de l'UI).
function notifySaveFailed(err: unknown): void {
  silentFailWithToast("deep-work-save", { message: i18n.t("settings:error_save") })(err);
}

function patchSetting(field: string, value: unknown): Promise<Response> {
  return fetch(`${API_BASE}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ [field]: value }),
  }).then((res) => {
    handleAuthResponse(res);
    if (!res.ok) {
      throw new Error(`PATCH /api/settings returned ${res.status}`);
    }
    return res;
  });
}

export function useDeepWorkSetting(accountId?: number) {
  const [settings, setSettings] = useState<DeepWorkSettings>(DEFAULT_SETTINGS);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    // Skip the fetch entirely when no JWT — login page would otherwise
    // trigger a 401 storm on /api/settings that pollutes the console
    // (audit 2026-05-01 P1 finding #5).
    if (!getStoredToken()) {
      setIsLoaded(true);
      return;
    }
    fetchSettingsCached(accountId)
      .then((data) => {
        const rawSlots = Array.isArray(data.deep_work_check_slots)
          ? data.deep_work_check_slots
          : DEFAULT_CHECK_SLOTS;
        const checkSlots: CheckSlot[] = rawSlots.map((s: Record<string, unknown>) => ({
          start: (s.start as string) || "08:00",
          duration: typeof s.duration === "number" ? s.duration : 30,
        }));
        const rawBlocks = Array.isArray(data.deep_work_personal_blocks)
          ? data.deep_work_personal_blocks
          : [];
        const personalBlocks: WorkBlock[] = rawBlocks.map((b: Record<string, unknown>) => ({
          start: (b.start as string) || "09:00",
          duration: typeof b.duration === "number" ? b.duration : 60,
          label: (b.label as string) || "Travail personnel",
        }));
        const rawEnabled = typeof data.deep_work_enabled === "boolean" ? data.deep_work_enabled : false;
        const emailsEnabled = typeof data.deep_work_emails_enabled === "boolean" ? data.deep_work_emails_enabled : false;
        const workEnabled = typeof data.deep_work_work_enabled === "boolean" ? data.deep_work_work_enabled : false;
        // Master switch is derived from the sub-modes: ON iff at least one is ON,
        // OFF when both are OFF. Keeps `deep_work_enabled` consistent in BOTH
        // directions and reconciles legacy rows — an earlier build force-healed
        // master to True and never back, so accounts with both sub-modes off but
        // master still True now self-correct to False on load. The runtime gates
        // (isActive, calendar blocks, auto-accept) all require a sub-mode anyway,
        // so a master that disagreed with the sub-modes only ever misled the UI.
        const enabled = emailsEnabled || workEnabled;
        if (enabled !== rawEnabled) {
          patchSetting("deep_work_enabled", enabled).catch(err => {
            console.warn('[useDeepWorkSetting] sync master switch failed:', err);
          });
        }
        setSettings({
          enabled,
          emailsEnabled,
          workEnabled,
          checkSlots,
          vipContacts: Array.isArray(data.deep_work_vip_contacts) ? data.deep_work_vip_contacts : [],
          weekdays: Array.isArray(data.deep_work_weekdays) ? data.deep_work_weekdays : [1, 2, 3, 4, 5],
          personalBlocks,
        });
        setIsLoaded(true);
      })
      .catch(err => {
        const msg = err instanceof Error ? err.message : String(err);
        if (!/\b401\b/.test(msg)) {
          console.warn('[useDeepWorkSetting] load settings failed:', err);
        }
        setIsLoaded(true);
      });
  }, [accountId]);

  const setEnabled = useCallback((val: boolean) => {
    setSettings((prev) => ({ ...prev, enabled: val }));
    patchSetting("deep_work_enabled", val).catch(err => {
      notifySaveFailed(err);
      setSettings((prev) => ({ ...prev, enabled: !val }));
    });
  }, []);

  const setEmailsEnabled = useCallback((val: boolean) => {
    setSettings((prev) => {
      // Activer un sous-mode active aussi le master pour que le runtime fire.
      if (val && !prev.enabled) {
        patchSetting("deep_work_enabled", true).catch(notifySaveFailed);
        return { ...prev, emailsEnabled: val, enabled: true };
      }
      // Couper le dernier sous-mode actif coupe aussi le master (symétrique).
      if (!val && prev.enabled && !prev.workEnabled) {
        patchSetting("deep_work_enabled", false).catch(notifySaveFailed);
        return { ...prev, emailsEnabled: val, enabled: false };
      }
      return { ...prev, emailsEnabled: val };
    });
    patchSetting("deep_work_emails_enabled", val).catch(err => {
      notifySaveFailed(err);
      setSettings((prev) => ({ ...prev, emailsEnabled: !val }));
    });
  }, []);

  const setWorkEnabled = useCallback((val: boolean) => {
    setSettings((prev) => {
      if (val && !prev.enabled) {
        patchSetting("deep_work_enabled", true).catch(notifySaveFailed);
        return { ...prev, workEnabled: val, enabled: true };
      }
      // Couper le dernier sous-mode actif coupe aussi le master (symétrique).
      if (!val && prev.enabled && !prev.emailsEnabled) {
        patchSetting("deep_work_enabled", false).catch(notifySaveFailed);
        return { ...prev, workEnabled: val, enabled: false };
      }
      return { ...prev, workEnabled: val };
    });
    patchSetting("deep_work_work_enabled", val).catch(err => {
      notifySaveFailed(err);
      setSettings((prev) => ({ ...prev, workEnabled: !val }));
    });
  }, []);

  const setCheckSlots = useCallback((slots: CheckSlot[]) => {
    setSettings((prev) => {
      const old = prev.checkSlots;
      patchSetting("deep_work_check_slots", slots).catch(err => {
        notifySaveFailed(err);
        setSettings((p) => ({ ...p, checkSlots: old }));
      });
      return { ...prev, checkSlots: slots };
    });
  }, []);

  const setVipContacts = useCallback((val: string[]) => {
    setSettings((prev) => {
      const old = prev.vipContacts;
      const cleaned = val.map((c) => c.toLowerCase().trim()).filter(Boolean).slice(0, 50);
      patchSetting("deep_work_vip_contacts", cleaned).catch(err => {
        notifySaveFailed(err);
        setSettings((p) => ({ ...p, vipContacts: old }));
      });
      return { ...prev, vipContacts: cleaned };
    });
  }, []);

  const setWeekdays = useCallback((val: number[]) => {
    setSettings((prev) => {
      const old = prev.weekdays;
      const cleaned = [...new Set(val.filter((d) => d >= 1 && d <= 7))].sort();
      patchSetting("deep_work_weekdays", cleaned).catch(err => {
        notifySaveFailed(err);
        setSettings((p) => ({ ...p, weekdays: old }));
      });
      return { ...prev, weekdays: cleaned };
    });
  }, []);

  const setPersonalBlocks = useCallback((val: WorkBlock[]) => {
    setSettings((prev) => {
      const old = prev.personalBlocks;
      patchSetting("deep_work_personal_blocks", val).catch(err => {
        notifySaveFailed(err);
        setSettings((p) => ({ ...p, personalBlocks: old }));
      });
      return { ...prev, personalBlocks: val };
    });
  }, []);

  return {
    settings,
    isLoaded,
    setEnabled,
    setEmailsEnabled,
    setWorkEnabled,
    setCheckSlots,
    setVipContacts,
    setWeekdays,
    setPersonalBlocks,
  };
}
