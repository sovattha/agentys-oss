/**
 * useLanguageSync — pull the user's preferred language from the backend
 * and keep the local i18n instance in sync.
 *
 * Flow:
 *   1. On mount: read SecureStore cache → seed i18n synchronously (no FR/EN flash).
 *   2. When authenticated: GET /api/user/preferences → apply + cache.
 *   3. Expose `setLanguage(lang)` to let the user override locally; the change
 *      is pushed to the backend (fire-and-forget) so the web app stays in sync.
 *
 * Default: 'en' if the backend returns null or the call fails.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { AppState, type AppStateStatus } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as Localization from "expo-localization";
import {
  initI18n,
  normalizeLanguage,
  setLanguage as applyLanguage,
  SUPPORTED_LANGUAGES,
  type SupportedLanguage,
  DEFAULT_LANGUAGE,
} from "../i18n";
import { getUserPreferences, updateUserPreferences } from "../services/api";
import { useAuth } from "./useAuth";

const CACHE_KEY = "agentys_mobile_language";

/** Langue du device (synchrone), normalisée vers une langue supportée. #1134 :
 *  sans ce fallback, un cache vide (1er lancement) seedait i18n en `en` →
 *  le briefing de démarrage du drive mode était lu en anglais avant que le
 *  backend ne renvoie la vraie préférence. On préfère le locale iOS. */
function deviceLanguage(): SupportedLanguage {
  try {
    return normalizeLanguage(Localization.getLocales()?.[0]?.languageCode);
  } catch {
    // fallback légitime : locale device illisible → langue par défaut
    return DEFAULT_LANGUAGE;
  }
}

async function readCached(): Promise<SupportedLanguage | null> {
  try {
    const raw = await SecureStore.getItemAsync(CACHE_KEY);
    if (!raw) return null;
    return (SUPPORTED_LANGUAGES as readonly string[]).includes(raw)
      ? (raw as SupportedLanguage)
      : null;
  } catch {
    // fallback légitime : cache langue illisible → resync backend
    return null;
  }
}

async function writeCached(lang: SupportedLanguage): Promise<void> {
  try {
    await SecureStore.setItemAsync(CACHE_KEY, lang);
  } catch {
    // no-op légitime : écriture du cache langue best-effort
  }
}

export interface LanguageSyncState {
  language: SupportedLanguage;
  isSyncing: boolean;
  /** True dès que le seed depuis le cache SecureStore est terminé (#1134 :
   *  gater le premier speak dessus — sinon le brief part en anglais puis
   *  bascule fr quand la langue backend atterrit). */
  isReady: boolean;
  /** True après la PREMIÈRE tentative de sync backend (succès ou échec) —
   *  gate de l'annonce/auto-start drive (#1134 : brief parti en anglais). */
  isSynced: boolean;
  setLanguage: (lang: SupportedLanguage) => Promise<void>;
}

export const LanguageContext = createContext<LanguageSyncState>({
  language: DEFAULT_LANGUAGE,
  isSyncing: false,
  isReady: false,
  isSynced: false,
  setLanguage: async () => {},
});

export function useLanguage(): LanguageSyncState {
  return useContext(LanguageContext);
}

export function useLanguageSync(): LanguageSyncState {
  const { isAuthenticated } = useAuth();
  const [language, setLanguageState] = useState<SupportedLanguage>(DEFAULT_LANGUAGE);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [isSynced, setIsSynced] = useState(false);
  const seededRef = useRef(false);
  // F15 (LOW): if a backend push of the language preference fails (offline,
  // Railway cold start abort), remember the unsynced value so we can retry
  // when the app returns to foreground (network typically wakes up too).
  // This prevents the silent web↔mobile language drift.
  const pendingPushRef = useRef<SupportedLanguage | null>(null);

  // Seed from cache once at mount (synchronous-ish — no network).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cached = await readCached();
      if (cancelled) return;
      const lang = cached ?? deviceLanguage();
      initI18n(lang);
      setLanguageState(lang);
      seededRef.current = true;
      setIsReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // When auth is ready, pull the canonical value from backend.
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    setIsSyncing(true);
    getUserPreferences()
      .then(async (resp) => {
        if (cancelled) return;
        const lang = normalizeLanguage(resp.preferred_language);
        await applyLanguage(lang);
        await writeCached(lang);
        if (!cancelled) setLanguageState(lang);
      })
      .catch(() => {
        /* network/401: keep whatever we seeded from cache */
      })
      .finally(() => {
        if (!cancelled) {
          setIsSyncing(false);
          setIsSynced(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const setLanguage = useCallback(async (lang: SupportedLanguage) => {
    const next = normalizeLanguage(lang);
    await applyLanguage(next);
    await writeCached(next);
    setLanguageState(next);
    // Push to backend so the web app sees the change too. Fire-and-forget —
    // cache locale + UI déjà à jour, on log pour diagnostic mais pas de toast
    // (pas de regressions utilisateur si la sync backend échoue).
    // F15 (LOW): on failure, stash the unsynced lang so the AppState
    // foreground listener below can replay it when network returns.
    pendingPushRef.current = next;
    updateUserPreferences({ preferred_language: next })
      .then(() => {
        // Only clear if this is still the latest pending value (no race with
        // a quick second toggle).
        if (pendingPushRef.current === next) pendingPushRef.current = null;
      })
      .catch((err) => {
        console.warn('[useLanguageSync] backend push failed:', err?.message || err);
        // Keep `next` in pendingPushRef → retry on foreground.
      });
  }, []);

  // F15 (LOW): replay the last failed lang push when the app comes back
  // to foreground. Network usually wakes up at the same time, and we
  // would otherwise drift silently from the web app. Pure side effect —
  // no UI feedback, no toast (consistent with the fire-and-forget contract).
  useEffect(() => {
    const onAppStateChange = (next: AppStateStatus) => {
      if (next !== 'active') return;
      const pending = pendingPushRef.current;
      if (!pending) return;
      updateUserPreferences({ preferred_language: pending })
        .then(() => {
          if (pendingPushRef.current === pending) pendingPushRef.current = null;
        })
        .catch((err) => {
          console.warn('[useLanguageSync] foreground retry failed:', err?.message || err);
          // Leave `pending` in the ref for the next foreground tick.
        });
    };
    const sub = AppState.addEventListener('change', onAppStateChange);
    return () => {
      sub.remove();
    };
  }, []);

  return { language, isSyncing, isReady, isSynced, setLanguage };
}
