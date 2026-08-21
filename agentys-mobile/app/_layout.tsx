/**
 * Root layout — AuthProvider + fonts + navigation.
 */

import { useEffect, type ReactNode } from "react";
import { Slot } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { Audio } from "expo-av";
import {
  InstrumentSans_400Regular,
  InstrumentSans_500Medium,
  InstrumentSans_600SemiBold,
  InstrumentSans_700Bold,
} from "@expo-google-fonts/instrument-sans";
import {
  JetBrainsMono_400Regular,
  JetBrainsMono_500Medium,
  JetBrainsMono_700Bold,
} from "@expo-google-fonts/jetbrains-mono";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AuthContext, useAuth, useAuthProvider } from "../src/hooks/useAuth";
import { useOutboxFlush } from "../src/hooks/useOutboxFlush";
import { LanguageContext, useLanguageSync } from "../src/hooks/useLanguageSync";
import { initI18n } from "../src/i18n";
import { registerErrorSink } from "../src/lib/errors";

// ── Sentry (Phase 1 fondations §1.4) ─────────────────────────────────────────
// Crash reporting + erreurs reportError() en prod. DSN via env (vide = OFF,
// défaut dev). `require` PARESSEUX : sans DSN, le module JS Sentry n'est
// jamais chargé (zéro impact jest/dev). Le pod natif est linké dans tous les
// cas (autolinking) — validé au boot device le 2026-07-18. Pas de config
// plugin (upload de sourcemaps) pour ne pas toucher au prebuild patché.
const SENTRY_DSN = process.env.EXPO_PUBLIC_SENTRY_DSN;
if (SENTRY_DSN) {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const Sentry = require("@sentry/react-native");
  Sentry.init({ dsn: SENTRY_DSN, tracesSampleRate: 0 });
  registerErrorSink((err, ctx) => {
    try {
      Sentry.captureException(err instanceof Error ? err : new Error(String(err)), {
        tags: { domain: ctx.domain, op: ctx.op },
        extra: { state: ctx.state, ...ctx.extra },
      });
    } catch { /* no-op légitime : le sink ne doit jamais masquer l'erreur d'origine */ }
  });
}
import { ToastHost } from "../src/components/ToastHost";
import { PLAYBACK_AUDIO_MODE } from "../src/lib/audioMode";

// Seed i18n synchronously so the very first render has a `t()` function that works.
// The real language is applied asynchronously by useLanguageSync (cache → backend).
initI18n();

/** Flush de la file d'envoi au boot + sur foreground, scopé à l'auth. */
function OutboxFlusher() {
  const { isAuthenticated } = useAuth();
  useOutboxFlush({
    onFlushed: ({ sent }) => {
      // Best-effort log — pas de toast pour ne pas casser le flow vocal
      console.log(`[outbox] ${sent} message(s) envoyé(s) depuis la file`);
    },
  });
  // On ne déclenche réellement que quand authentifié (le hook est toujours monté
  // pour garder l'AppState listener, mais le flush fail-fast sur 401).
  void isAuthenticated;
  return null;
}

/** Bridge between AuthContext (provides the token) and LanguageContext
 *  (pulls /api/user/preferences once authenticated). Must live inside the
 *  AuthContext.Provider subtree. */
function LanguageProvider({ children }: { children: ReactNode }) {
  const lang = useLanguageSync();
  // #1134 : ne rien rendre (~10-30 ms) tant que la langue du cache n'est pas
  // appliquée — sinon le brief vocal du drive mode part avec le défaut "en"
  // puis bascule fr en cours de phrase. Couvre TOUS les chemins de 1er speak.
  if (!lang.isReady) return null;
  return (
    <LanguageContext.Provider value={lang}>{children}</LanguageContext.Provider>
  );
}

export default function RootLayout() {
  const auth = useAuthProvider();

  const [fontsLoaded] = useFonts({
    InstrumentSans_400Regular,
    InstrumentSans_500Medium,
    InstrumentSans_600SemiBold,
    InstrumentSans_700Bold,
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium,
    JetBrainsMono_700Bold,
  });

  // Initialiser le mode audio pour la lecture vocale (TTS).
  // #1122 : staysActiveInBackground:true — le TTS drive mode continue écran
  // verrouillé (cohérent avec UIBackgroundModes:["audio"] dans app.json).
  useEffect(() => {
    Audio.setAudioModeAsync(PLAYBACK_AUDIO_MODE);
  }, []);

  // Ne pas bloquer le rendu si les fonts ne se chargent pas (Expo Go fallback)
  if (!fontsLoaded) {
    return null;
  }

  return (
    <SafeAreaProvider>
      <AuthContext.Provider value={auth}>
        <LanguageProvider>
          <StatusBar style="light" />
          <OutboxFlusher />
          <Slot />
          {/* Toast host : monté à la racine pour que toast.error() depuis
              n'importe où dans l'app affiche un message au user. */}
          <ToastHost />
        </LanguageProvider>
      </AuthContext.Provider>
    </SafeAreaProvider>
  );
}
