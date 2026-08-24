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
import i18n from "../i18n";
import { API_URL } from "../config";
import { useCurrentAccountId } from "./useCurrentAccountId";
import { getAuthHeaders, getStoredToken, handleAuthResponse } from "../services/authToken";
import { silentFailWithToast } from "../utils/silentFail";

const API_BASE = `${API_URL}/api`;
const STORAGE_PREFIX = "agentys-theme:";

// "Clarity" (default) est le seul thème. Les thèmes "dark-luxury" et "futurist"
// ont été retirés — il n'y a plus aucune CSS de thème à charger dynamiquement.
export type ThemeId = "default";

function storageKeyFor(accountId: string | null): string {
  // `null` = pas encore résolu — on stocke sous une clé "pending" qui sera
  // écrasée dès que l'accountId réel arrive.
  return `${STORAGE_PREFIX}${accountId ?? "__pending"}`;
}

/**
 * Porte de coercion : seul "default" est valide. Toute valeur legacy persistée
 * (localStorage OU backend) — y compris les thèmes retirés "dark-luxury" et
 * "futurist" — est rejetée ici, ce qui fait retomber l'utilisateur sur "default"
 * (Clarity). C'est le mécanisme qui débloque un compte resté sur un thème supprimé.
 */
export function isThemeId(val: string | null): val is ThemeId {
  return val === "default";
}

export function useTheme() {
  const accountId = useCurrentAccountId();
  const [theme, setTheme] = useState<ThemeId>(() => {
    const saved = localStorage.getItem(storageKeyFor(accountId));
    return isThemeId(saved) ? saved : "default";
  });

  // Applique le thème sur le document.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Re-sync avec le backend à chaque changement d'accountId (y compris le 1er chargement).
  // Le backend fait foi, mais une valeur legacy (thème retiré) est coercée vers "default".
  useEffect(() => {
    if (accountId === null) return; // pas encore résolu

    let cancelled = false;
    if (!getStoredToken()) return;

    fetch(`${API_BASE}/settings`, { headers: getAuthHeaders() })
      .then(handleAuthResponse)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/settings returned ${res.status}`);
        }
        return res;
      })
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        const backendTheme: ThemeId = isThemeId(data?.theme) ? data.theme : "default";
        setTheme(backendTheme);
        localStorage.setItem(storageKeyFor(accountId), backendTheme);
      })
      .catch((err) => console.error("[useTheme] load settings failed:", err));

    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const setThemeValue = useCallback(
    (newTheme: ThemeId) => {
      const previous = theme;
      const localKey = storageKeyFor(accountId);

      const applyTheme = () => {
        setTheme(newTheme);
        localStorage.setItem(localKey, newTheme);
        document.documentElement.setAttribute("data-theme", newTheme);
        fetch(`${API_BASE}/settings`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({ theme: newTheme }),
        })
          .then(handleAuthResponse)
          .then((res) => {
            if (!res.ok) {
              throw new Error(`PATCH /api/settings returned ${res.status}`);
            }
          })
          .catch((err) => {
            // Site 5 (audit toast-coverage 2026-06-11) : le thème « refusait »
            // de s'appliquer (rollback correct) sans aucun message.
            silentFailWithToast("theme-save", { message: i18n.t("settings:error_save") })(err);
            setTheme(previous);
            localStorage.setItem(localKey, previous);
            document.documentElement.setAttribute("data-theme", previous);
          });
      };

      // Use View Transitions API for smooth theme crossfade.
      // Wrap in try/catch: InvalidStateError is thrown if a transition is already
      // in progress (e.g. concurrent sidebar tab change). In that case apply directly.
      if (document.startViewTransition) {
        try {
          const vt = document.startViewTransition(applyTheme);
          // BUG-006 fix: absorb all async rejections (ready, updateCallbackDone, finished)
          vt.ready?.catch(() => {});
          vt.updateCallbackDone?.catch(() => {});
          vt.finished.catch(() => {});
        } catch {
          applyTheme();
        }
      } else {
        applyTheme();
      }
    },
    [theme, accountId]
  );

  return { theme, setTheme: setThemeValue };
}
