import { useState, useCallback, useEffect } from "react";
import i18n from "../i18n";
import { API_URL } from "../config";
import { fetchSettingsCached } from "./useSettingsCache";
import { getAuthHeaders, handleAuthResponse } from "../services/authToken";
import { silentFailWithToast } from "../utils/silentFail";

const API_BASE = `${API_URL}/api`;

interface BatchSchedule {
  batchEnabled: boolean;
  activeHoursStart: string;
  activeHoursEnd: string;
  weekendAllDay: boolean;
  activityTimeoutMin: number;
}

const DEFAULTS: BatchSchedule = {
  batchEnabled: true,
  activeHoursStart: "07:00",
  activeHoursEnd: "20:00",
  weekendAllDay: true,
  activityTimeoutMin: 15,
};

export function useBatchScheduleSetting(accountId?: number) {
  const [schedule, setSchedule] = useState<BatchSchedule>(DEFAULTS);

  useEffect(() => {
    fetchSettingsCached(accountId)
      .then((data) => {
        setSchedule({
          batchEnabled: (data.batch_enabled as boolean) ?? DEFAULTS.batchEnabled,
          activeHoursStart: (data.batch_active_hours_start as string) ?? DEFAULTS.activeHoursStart,
          activeHoursEnd: (data.batch_active_hours_end as string) ?? DEFAULTS.activeHoursEnd,
          weekendAllDay: (data.batch_weekend_all_day as boolean) ?? DEFAULTS.weekendAllDay,
          activityTimeoutMin: (data.batch_activity_timeout_min as number) ?? DEFAULTS.activityTimeoutMin,
        });
      })
      .catch(err => console.error('[useBatchScheduleSetting] load settings failed:', err));
  }, [accountId]);

  const patch = useCallback(
    (fields: Record<string, unknown>, rollback: BatchSchedule) => {
      fetch(`${API_BASE}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(fields),
      })
        .then(handleAuthResponse)
        .then((res) => {
          if (!res.ok) {
            throw new Error(`PATCH /api/settings returned ${res.status}`);
          }
        })
        .catch(err => {
          // Site 9 (audit toast-coverage 2026-06-11) : rollback muet — même
          // classe que useDeepWorkSetting. UI « Heures creuses » masquée
          // aujourd'hui, mais le hook reste branché.
          silentFailWithToast("batch-schedule-save", { message: i18n.t("settings:error_save") })(err);
          setSchedule(rollback);
        });
    },
    [],
  );

  const toggleBatchEnabled = useCallback(() => {
    setSchedule((prev) => {
      const next = { ...prev, batchEnabled: !prev.batchEnabled };
      patch({ batch_enabled: next.batchEnabled }, prev);
      return next;
    });
  }, [patch]);

  const setActiveHoursStart = useCallback(
    (value: string) => {
      setSchedule((prev) => {
        const next = { ...prev, activeHoursStart: value };
        patch({ batch_active_hours_start: value }, prev);
        return next;
      });
    },
    [patch],
  );

  const setActiveHoursEnd = useCallback(
    (value: string) => {
      setSchedule((prev) => {
        const next = { ...prev, activeHoursEnd: value };
        patch({ batch_active_hours_end: value }, prev);
        return next;
      });
    },
    [patch],
  );

  const toggleWeekendAllDay = useCallback(() => {
    setSchedule((prev) => {
      const next = { ...prev, weekendAllDay: !prev.weekendAllDay };
      patch({ batch_weekend_all_day: next.weekendAllDay }, prev);
      return next;
    });
  }, [patch]);

  const setActivityTimeout = useCallback(
    (value: number) => {
      setSchedule((prev) => {
        const next = { ...prev, activityTimeoutMin: value };
        patch({ batch_activity_timeout_min: value }, prev);
        return next;
      });
    },
    [patch],
  );

  return {
    ...schedule,
    toggleBatchEnabled,
    setActiveHoursStart,
    setActiveHoursEnd,
    toggleWeekendAllDay,
    setActivityTimeout,
  };
}
