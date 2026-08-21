/**
 * Agentys Mobile — Écran d'accueil (Voice Inbox landing).
 *
 * IDLE  : BreathingTriangle (triangle avec rubans clippés) + Greeting +
 *         grande carte ACTION + row de 2 cartes (INFO / LES DEUX).
 * ACTIVE: DrivePlayer (session vocale).
 * END   : SessionSummary.
 *
 * Compteurs : /api/labels/counts (agrégat SQL, account-scoped).
 * Emails    : /api/emails?label=X — fetch on-demand quand l'utilisateur choisit un mode.
 *
 * Long-press le triangle → Settings.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  RefreshControl,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { useTranslation } from "react-i18next";
import { useAuth } from "../src/hooks/useAuth";
import { useLanguage } from "../src/hooks/useLanguageSync";
import { useDriveMode } from "../src/hooks/useDriveMode";
import { useTts } from "../src/hooks/useTts";
import { useWebSocket } from "../src/hooks/useWebSocket";
import { getEmails, getLabelCounts, getEmailIdsByLabel, getVoiceBriefing } from "../src/services/api";
import i18n from "../src/i18n";
import { BreathingTriangle } from "../src/components/BreathingTriangle";
import { Greeting } from "../src/components/Greeting";
import { DrivePlayer } from "../src/components/DrivePlayer";
import { SessionSummary } from "../src/components/SessionSummary";
import { EmptyState } from "../src/components/EmptyState";
import { OnboardingTour, ONBOARDING_KEY } from "../src/components/OnboardingTour";
import { theme } from "../src/theme";
import type { Email, SessionMode } from "../src/types";
import { getEmailClassification } from "../src/types";

export default function DriveHomeScreen() {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { isSynced: langSynced } = useLanguage();
  const langSyncedRef = useRef(langSynced);
  useEffect(() => { langSyncedRef.current = langSynced; }, [langSynced]);
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const drive = useDriveMode();
  const tts = useTts();
  const { t } = useTranslation(["inbox", "common", "drive"]);
  // Entrée zéro-toucher : `agentys://?autostart=mixed|actions|infos` (Siri
  // Shortcut « Hey Siri, fais mes emails », Raccourci d'app, Action Button).
  const params = useLocalSearchParams<{ autostart?: string }>();

  const [counts, setCounts] = useState<{ action: number; fyi: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [starting, setStarting] = useState<SessionMode | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const countsRef = useRef<{ action: number; fyi: number } | null>(null);

  // Auto-start direct : une seule session lancée automatiquement par ouverture
  // d'app. Garde-fou anti-boucle « fin de session → idle → relance » : une fois
  // vrai, l'idle affiche l'écran repos au lieu de redémarrer une session.
  const autoStartedOnceRef = useRef(false);

  // Cache counts SecureStore pour cold start instant + badge ⚡.
  const [showCacheBadge, setShowCacheBadge] = useState(false);

  // Onboarding tour 1× au premier launch après login.
  // null = pas encore checké, false = jamais vu (afficher), true = déjà vu.
  const [onboardingSeen, setOnboardingSeen] = useState<boolean | null>(null);

  // ── WebSocket — rafraîchir compteurs en temps réel ────────────────────────
  useWebSocket({
    enabled: isAuthenticated,
    onNewEmail: useCallback(() => {
      getLabelCounts()
        .then((data) => {
          const c = { action: data.counts?.Action ?? 0, fyi: data.counts?.FYI ?? 0 };
          setCounts(c);
          countsRef.current = c;
        })
        .catch(() => {}); // no-op légitime : compteurs rafraîchis au prochain événement
    }, []),
    onEmailArchived: useCallback(() => {
      getLabelCounts()
        .then((data) => {
          const c = { action: data.counts?.Action ?? 0, fyi: data.counts?.FYI ?? 0 };
          setCounts(c);
          countsRef.current = c;
        })
        .catch(() => {}); // no-op légitime : compteurs rafraîchis au prochain événement
    }, []),
  });

  // ── Auth guard ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace("/login");
  }, [isAuthenticated, authLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Onboarding seen check ─────────────────────────────────────────────────
  useEffect(() => {
    if (!isAuthenticated) return;
    SecureStore.getItemAsync(ONBOARDING_KEY)
      .then((v) => setOnboardingSeen(v === "true"))
      .catch(() => setOnboardingSeen(true));  // sur erreur, on assume vu (fail-open)
  }, [isAuthenticated]);

  // ── Fetch counts ──────────────────────────────────────────────────────────
  // Audit UX 2026-04-28 : cache SecureStore pour cold start instant. Lit le
  // cache d'abord (~10ms), affiche les counts immédiatement avec le badge ⚡,
  // puis rafraîchit en background. Le badge disparaît après 1.5s pour rester
  // discret. TTL implicite : on rafraîchit toujours, donc le cache n'est pas
  // utilisé "stale" — c'est juste un primer pour le 1er paint.
  const fetchCounts = useCallback(async (skipCache = false) => {
    try {
      const data = await getLabelCounts();
      const c = { action: data.counts?.Action ?? 0, fyi: data.counts?.FYI ?? 0 };
      setCounts(c);
      countsRef.current = c;
      setLoadError(null);
      // Persister pour le cold start suivant.
      SecureStore.setItemAsync("counts_cache_v1", JSON.stringify({ counts: c, ts: Date.now() })).catch(() => {}); // no-op légitime : cache best-effort
    } catch (err: any) {
      if (err?.message !== "Unauthorized") setLoadError(t("loadCountsError"));
    }
  }, [t]);

  useEffect(() => {
    if (!isAuthenticated) return;
    setLoading(true);
    let cancelled = false;
    // Path 1 (instant) : cache SecureStore
    SecureStore.getItemAsync("counts_cache_v1")
      .then((raw) => {
        if (!raw || cancelled) return;
        try {
          const parsed = JSON.parse(raw);
          // Cache utile seulement si < 5min (au-delà, c'est probablement
          // périmé et on attend le fresh fetch).
          if (parsed?.counts && Date.now() - (parsed.ts || 0) < 5 * 60 * 1000) {
            setCounts(parsed.counts);
            countsRef.current = parsed.counts;
            setLoading(false);  // ← cold start instant, plus de spinner
            setShowCacheBadge(true);
            setTimeout(() => setShowCacheBadge(false), 1500);
          }
        } catch { /* JSON parse fail — ignore cache */ }
      })
      .catch(() => {}); // no-op légitime : compteurs rafraîchis au prochain événement
    // Path 2 (background) : fetch fresh
    fetchCounts().finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isAuthenticated, fetchCounts]);

  // ── Pull-to-refresh ───────────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchCounts();
    setRefreshing(false);
  }, [fetchCounts]);

  // ── Arrêter idle STT quand une session est active ─────────────────────────
  useEffect(() => {
    if (drive.state !== "idle") drive.stopIdleSTT();
  }, [drive.state]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Helpers ───────────────────────────────────────────────────────────────
  const handleSettings = useCallback(async () => {
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    router.push("/settings");
  }, [router]);

  /** Charge les emails pour un label avec 3 stratégies en cascade :
   *
   *   1. Primaire     : /api/emails?label=X          (backend filter, rapide si OK)
   *   2. Parallèle    : /api/emails + filter client  (course avec #1, gagne si #1 timeout)
   *   3. Dernier recours : /api/labels/emails/X      (IDs only, si tout le reste échoue)
   *
   *   #1 et #2 courent EN PARALLÈLE via Promise.any → le premier qui répond gagne.
   *   Ça rend l'app résiliente : même si le backend plante le label filter,
   *   on récupère les emails via l'endpoint generic + filter côté frontend. */
  const loadEmailsForLabel = useCallback(async (label: string): Promise<Email[]> => {
    // Filter helper : trouve les emails avec ce label (dans labels[] ou classification)
    const matchesLabel = (e: Email): boolean => {
      if ((e as any).classification === label) return true;
      return (e.labels || []).some((l) => l?.name === label);
    };

    // Stratégie 1 : endpoint avec label filter (normalement le + rapide)
    const primary = (async () => {
      const data = await getEmails(label);
      const emails = data?.emails ?? [];
      if (emails.length === 0) throw new Error("empty-primary"); // force race winner si vide
      return emails;
    })();

    // Stratégie 2 : fetch tout l'inbox + filter côté client — démarre avec un délai
    // pour laisser la primaire gagner la course sans charger 100 emails inutilement.
    const fallbackClientFilter = (async () => {
      await new Promise((r) => setTimeout(r, 1500));
      const data = await getEmails(undefined, 100);
      const emails = data?.emails ?? [];
      const filtered = emails.filter(matchesLabel);
      if (filtered.length === 0 && emails.length > 0) {
        throw new Error("empty-clientfilter"); // tous les emails n'ont pas ce label, mais au moins inbox répond
      }
      return filtered;
    })();

    // Course : on prend le premier qui succeed (avec des emails non-vides)
    try {
      const emails = await Promise.any([primary, fallbackClientFilter]);
      console.log(`[home] loaded ${emails.length} emails for ${label}`);
      return emails;
    } catch (aggregateErr: any) {
      const errors: string[] = aggregateErr?.errors?.map((e: any) => e?.message || String(e)) || [];
      console.warn(`[home] both primary and client-filter failed for ${label}:`, errors);

      // Si l'erreur est "empty" des deux côtés, c'est juste qu'il n'y a pas d'emails avec ce label
      if (errors.every((e) => e.startsWith("empty-"))) {
        return [];
      }

      // Stratégie 3 : endpoint IDs seulement (JSON store, parfois plus rapide)
      try {
        const res = await getEmailIdsByLabel(label);
        const ids = res?.email_ids || [];
        if (ids.length === 0) return [];
        console.warn(`[home] last-resort IDs: ${ids.length} for ${label}`);
        return ids.map<Email>((id) => ({
          id,
          sender: "",
          subject: "",
          received_at: new Date().toISOString(),
          labels: [{ name: label, color: "" }],
        }));
      } catch (idsErr: any) {
        console.warn(`[home] last-resort IDs failed:`, idsErr?.message);
        const unique = Array.from(new Set(errors.filter(Boolean)));
        throw new Error(unique.join(" · ") || idsErr?.message || "all-strategies-failed");
      }
    }
  }, []);

  /** Fetch emails by label (ou deux labels pour mixed) puis démarre la session. */
  const startFiltered = useCallback(async (mode: SessionMode) => {
    if (starting) return;
    // #1134 : gate UNIVERSEL langue — quel que soit le chemin d'entrée (tap
    // carte, voix idle, deep-link, auto-start), aucun mot ne part avant que
    // la langue du compte soit appliquée. 2s max puis on démarre quand même.
    if (!langSyncedRef.current) {
      await new Promise<void>((resolve) => {
        const poll = setInterval(() => {
          if (langSyncedRef.current) { clearInterval(poll); clearTimeout(cap); resolve(); }
        }, 50);
        const cap = setTimeout(() => { clearInterval(poll); resolve(); }, 2000);
      });
    }
    setStarting(mode);
    setStartError(null);
    drive.stopIdleSTT();
    await tts.stop();  // ← critique : stoppe la voix du home avant que drive démarre la sienne
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    try {
      let emails: Email[] = [];
      if (mode === "actions") {
        emails = await loadEmailsForLabel("Action");
      } else if (mode === "infos") {
        emails = await loadEmailsForLabel("FYI");
      } else {
        // mixed — action puis info, dédupliqué
        const [a, f] = await Promise.all([
          loadEmailsForLabel("Action").catch(() => [] as Email[]),
          loadEmailsForLabel("FYI").catch(() => [] as Email[]),
        ]);
        const seen = new Set<string>();
        emails = [];
        for (const e of [...a, ...f]) {
          if (!seen.has(e.id)) { seen.add(e.id); emails.push(e); }
        }
      }
      if (emails.length === 0) {
        const msg = t("noEmailsInCategory");
        setStartError(msg);
        tts.speak(msg);
        return;
      }
      drive.startSession(emails, mode);
    } catch (err: any) {
      const detail = err?.message || String(err);
      console.warn(`[home] startFiltered(${mode}) failed:`, detail);
      // Affiche l'erreur à l'écran (avec détail technique utile au debug)
      // plutôt que de juste la parler : l'utilisateur peut lire + retry.
      setStartError(detail);
      tts.speak(t("loadError"));
    } finally {
      setStarting(null);
    }
  }, [drive, tts, starting, loadEmailsForLabel, t]);

  // ── Entrée zéro-toucher (Siri Shortcut / deep link) ───────────────────────
  // `agentys://?autostart=mixed` : pas de fenêtre d'objection, pas de tap.
  // L'app parle EN PREMIER — brief conversationnel du backend (« Salut, 12
  // mails t'attendent, 3 urgents… ») puis session immédiate. Le téléphone
  // peut rester dans la poche dès la phrase Siri prononcée.
  const deepLinkHandledRef = useRef(false);
  useEffect(() => {
    if (onboardingSeen !== true) return;
    if (!langSynced) return; // #1134 : le brief backend rend dans la langue courante
    if (loading || loadError || !counts) return;
    const requested = typeof params.autostart === "string" ? params.autostart : null;
    if (!requested || deepLinkHandledRef.current) return;
    // M-P2d (c) : ne déclenche PAS si une session tourne déjà (Siri shortcut
    // ré-ouvert mid-session, ou retour-arrière avec le param encore en route).
    if (drive.state !== "idle") {
      deepLinkHandledRef.current = true;
      router.setParams({ autostart: undefined });
      return;
    }
    deepLinkHandledRef.current = true;
    // Le deep-link EST notre unique auto-start : neutralise l'auto-start direct
    // générique (évite une 2e session pendant qu'on attend le brief).
    autoStartedOnceRef.current = true;
    // M-P2d (c) : consomme le param pour qu'un remount (qui réinitialise
    // deepLinkHandledRef) ne re-déclenche pas un autostart non demandé.
    router.setParams({ autostart: undefined });

    const mode: SessionMode =
      requested === "actions" ? "actions" :
      requested === "infos" ? "infos" : "mixed";
    const total = counts.action + counts.fyi;

    (async () => {
      if (total === 0) {
        tts.speak(t("noEmails"));
        return;
      }
      try {
        const brief = await getVoiceBriefing({
          counts: { total, action: counts.action, fyi: counts.fyi },
          lang: (i18n.language || "fr").split(/[-_]/)[0],
        });
        // Si l'utilisateur a démarré quelque chose entre-temps, on abandonne.
        if (drive.state !== "idle") return;
        await new Promise<void>((resolve) => tts.speak(brief.text, resolve));
      } catch {
        // Brief indisponible — on démarre quand même, la session s'annonce.
      }
      startFiltered(mode);
    })();
  }, [loading, loadError, counts, onboardingSeen, params.autostart, langSynced]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-start direct (plus d'écran de choix ni d'annonce « on y va ») ─────
  // À l'ouverture, si des mails attendent, on démarre DIRECTEMENT la session
  // « mixed » (action + info). Aucune fenêtre d'objection : en conduite, on veut
  // que ça lise tout de suite. Une seule fois par ouverture (autoStartedOnceRef)
  // — après une session terminée, l'idle bascule sur l'écran repos au lieu de
  // relancer en boucle. Le deep-link Siri (params.autostart) garde son chemin
  // dédié (brief conversationnel) et pose le même garde.
  useEffect(() => {
    if (onboardingSeen !== true) return;
    // NB : pas de gate `langSynced` ici — startFiltered attend lui-même la
    // sync langue (plafonnée à 2s). Gater ici bloquait le boot indéfiniment
    // si la sync backend traînait, sur un écran d'attente sans issue.
    if (loading || loadError || !counts) return;
    if (drive.state !== "idle") return;
    if (autoStartedOnceRef.current) return;
    if (params.autostart) return; // laisser le deep-link Siri gérer
    if (counts.action + counts.fyi === 0) return; // rien à jouer → écran repos
    autoStartedOnceRef.current = true;
    startFiltered("mixed");
  }, [loading, loadError, counts, onboardingSeen, drive.state, params.autostart]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auth loading ──────────────────────────────────────────────────────────
  // Audit UX 2026-04-28 : BreathingTriangle en mode loading remplace
  // l'ActivityIndicator générique. Identité visuelle préservée même
  // pendant les chargements ; rythme ralenti (8s) pour signaler "patience".
  if (authLoading) {
    return (
      <View style={[styles.center, { paddingTop: insets.top }]}>
        <BreathingTriangle size={120} mode="loading" />
      </View>
    );
  }

  // ── Onboarding tour (1× au premier launch après login) ──────────────────
  // Affiché en overlay AVANT toute logique drive — l'user doit comprendre
  // l'app avant que le 1.8s auto-start ne kick. tts.stop() pour éviter que
  // les compteurs s'annoncent par-dessus.
  if (isAuthenticated && onboardingSeen === false) {
    return (
      <View style={[styles.fullscreen, { paddingTop: insets.top }]}>
        <OnboardingTour
          onDone={() => {
            tts.stop().catch(() => {}); // no-op légitime : déjà à l'arrêt
            setOnboardingSeen(true);
          }}
        />
      </View>
    );
  }

  // ── Session terminée ──────────────────────────────────────────────────────
  if (drive.state === "completed" && drive.sessionStats) {
    return (
      <View style={[styles.fullscreen, { paddingTop: insets.top }]}>
        <SessionSummary stats={drive.sessionStats} onDismiss={drive.reset} />
      </View>
    );
  }

  // ── Session active ────────────────────────────────────────────────────────
  if (drive.state !== "idle") {
    const currentEmailData = drive.emails[drive.currentIndex];
    const currentClassification = currentEmailData ? getEmailClassification(currentEmailData) : null;
    const sameClassEmails = drive.emails.filter((e) => getEmailClassification(e) === currentClassification);
    const classIndex = currentEmailData ? sameClassEmails.indexOf(currentEmailData) : -1;
    const classLabel =
      currentClassification === "Action" ? t("drive:classLabel.Action", { defaultValue: "Action" })
      : currentClassification === "FYI"    ? t("drive:classLabel.FYI", { defaultValue: "Info" })
      : currentClassification === "Noise"  ? t("drive:classLabel.Noise", { defaultValue: "Noise" })
      : t("drive:classLabel.Email", { defaultValue: "Email" });

    return (
      <View style={[styles.fullscreen, { paddingTop: insets.top }]}>
        <DrivePlayer
          state={drive.state}
          emailSubject={drive.currentEmail?.subject}
          senderName={drive.currentEmail?.sender_name}
          senderEmail={currentEmailData?.sender}
          draftContent={drive.draftContent}
          error={drive.error}
          currentIndex={drive.currentIndex}
          totalEmails={drive.emails.length}
          classificationLabel={classLabel}
          classificationIndex={classIndex >= 0 ? classIndex : 0}
          classificationTotal={sameClassEmails.length}
          transcript={drive.transcript}
          commandRecognized={drive.commandRecognized}
          generatingElapsedMs={drive.generatingElapsedMs}
          onNext={drive.next}
          onPrevious={drive.previous}
          onFinishDictation={drive.finishDictation}
          onConfirmDictation={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
            drive.approveContextual();
          }}
          onCancelSend={drive.rejectAndRelisten}
          onOpenSettings={handleSettings}
          stalled={drive.watchdogStalled}
          onRetryStalled={drive.retryFromStall}
          onBack={drive.currentIndex > 0 ? drive.previous : drive.stopWithFarewell}
          audioLevel={drive.audioLevel}
          isListening={drive.isListening}
          isTranscribing={drive.isTranscribing}
          onTogglePlayback={drive.interruptAndListen}
          isPlayback={drive.ttsState === "speaking" || drive.ttsState === "paused"}
          pendingUndoCount={drive.pendingActionCount}
          onUndo={drive.undoLastAction}
        />
      </View>
    );
  }

  // ── Boot → drive direct (retour device 2026-07) ───────────────────────────
  // Au démarrage, on ne montre PAS l'écran « Écouter mes messages » : la
  // session part toute seule dès que les compteurs arrivent. En attendant
  // (~0,5-2s), une vue de préparation minimale : logo + compteur si connu.
  // L'écran repos ne sert plus qu'après une session ou pour l'inbox zéro.
  const mixedCount = loading ? 0 : (counts ? counts.action + counts.fyi : 0);
  const bootingToDrive =
    !autoStartedOnceRef.current && !loadError && !params.autostart &&
    (loading || !counts || mixedCount > 0);

  if (bootingToDrive) {
    return (
      <View style={[styles.center, { paddingTop: insets.top }]}>
        <BreathingTriangle size={160} mode="loading" />
        <View style={styles.bootRow}>
          <ActivityIndicator size="small" color={theme.colors.cyan} />
          <Text style={styles.bootText}>
            {counts && mixedCount > 0
              ? t("bootStarting", { count: mixedCount, defaultValue: `${mixedCount} messages — démarrage…` })
              : t("preparing")}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.fullscreen}>
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 80, paddingBottom: insets.bottom + 32 },
      ]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={handleRefresh}
          tintColor={theme.colors.cyan}
          colors={[theme.colors.cyan]}
        />
      }
      showsVerticalScrollIndicator={false}
    >
      {/* ── Logo animé — tap → réglages ── */}
      <Pressable
        onPress={handleSettings}
        style={styles.logoWrap}
        accessibilityRole="button"
        accessibilityLabel={t("openSettings", { defaultValue: "Réglages" })}
        accessibilityHint={t("openSettingsHint", { defaultValue: "Ouvre les réglages" })}
      >
        <BreathingTriangle size={180} />
      </Pressable>

      <View style={styles.greetingWrap}>
        <Greeting />
      </View>

      {/* ── Contenu selon l'état : erreur / chargement / inbox zéro / relance ── */}
      {loadError ? (
        <Text style={styles.errorText}>{loadError}</Text>
      ) : loading ? (
        <ActivityIndicator size="small" color={theme.colors.cyan} />
      ) : mixedCount === 0 ? (
        <EmptyState variant="zero" />
      ) : (
        <Pressable
          style={({ pressed }) => [styles.listenBtn, pressed && styles.listenBtnPressed]}
          onPress={() => startFiltered("mixed")}
          accessibilityRole="button"
          accessibilityLabel={t("listenAll", { count: mixedCount, defaultValue: "Écouter mes messages" })}
        >
          <Ionicons name="play" size={20} color={theme.colors.bg} />
          <Text style={styles.listenBtnText}>
            {t("listenAll", { count: mixedCount, defaultValue: `Écouter mes messages (${mixedCount})` })}
          </Text>
        </Pressable>
      )}

      {/* ── Erreur de chargement session ── */}
      {startError && (
        <View style={styles.startErrorBox}>
          <Text style={styles.startErrorTitle}>{t("loadFailTitle")}</Text>
          <Text style={styles.startErrorDetail} numberOfLines={3}>{startError}</Text>
          <Pressable
            style={styles.startErrorRetry}
            onPress={() => { setStartError(null); fetchCounts(); }}
          >
            <Text style={styles.startErrorRetryText}>{t("common:retry")}</Text>
          </Pressable>
        </View>
      )}

      {/* ── Cache badge ⚡ — affichage instant depuis cache ── */}
      {showCacheBadge ? (
        <View style={styles.cacheBadge} accessibilityRole="text" accessibilityLabel="Affichage instantané depuis le cache">
          <Text style={styles.cacheBadgeText}>⚡ Instantané</Text>
        </View>
      ) : null}

      {/* ── Indicateur de préchargement ── */}
      {starting && (
        <View style={styles.startingBadge}>
          <ActivityIndicator size="small" color={theme.colors.cyan} />
          <Text style={styles.startingText}>{t("preparing")}</Text>
        </View>
      )}
    </ScrollView>

      {/* ── FAB nouveau message ── */}
      <Pressable
        style={({ pressed }) => [
          styles.fab,
          { bottom: insets.bottom + 24 },
          pressed && styles.fabPressed,
        ]}
        onPress={() => {
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {}); // no-op légitime : compteurs rafraîchis au prochain événement
          tts.stop();
          router.push("/compose");
        }}
        accessibilityLabel={t("newMessage")}
        accessibilityRole="button"
        hitSlop={8}
      >
        <Ionicons name="add" size={30} color={theme.colors.bg} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  fullscreen: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  center: {
    flex: 1,
    backgroundColor: theme.colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  scroll: {
    flex: 1,
    backgroundColor: theme.colors.bg,
  },
  content: {
    alignItems: "center",
    paddingHorizontal: 20,
  },

  /* Triangle viz */
  logoWrap: {
    marginBottom: 12,
    alignItems: "center",
    justifyContent: "center",
  },

  /* Greeting */
  greetingWrap: {
    marginBottom: 40,
  },

  /* Bouton « Écouter mes messages » (écran repos, s'il reste des mails) */
  listenBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 28,
    backgroundColor: theme.colors.cyan,
    shadowColor: theme.colors.cyan,
    shadowOpacity: 0.4,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 5 },
    elevation: 8,
  },
  listenBtnPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.97 }],
  },
  listenBtnText: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 16,
    color: theme.colors.bg,
    letterSpacing: 0.3,
  },

  /* Boot → drive (vue de préparation au démarrage) */
  bootRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: 24,
  },
  bootText: {
    fontFamily: theme.fonts.body,
    fontSize: 13,
    color: theme.colors.textSecondary,
    letterSpacing: 0.3,
  },

  /* Starting badge */
  startingBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: 20,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  startingText: {
    fontFamily: theme.fonts.body,
    fontSize: 12,
    color: theme.colors.cyan,
    opacity: 0.8,
  },

  /* Cache badge — Audit UX 2026-04-28 (Performance perçue) */
  cacheBadge: {
    marginTop: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: `${theme.colors.cyan}10`,
    alignSelf: "center",
  },
  cacheBadgeText: {
    fontFamily: theme.fonts.body,
    fontSize: 10,
    color: theme.colors.cyan,
    letterSpacing: 0.5,
    opacity: 0.7,
  },

  fab: {
    position: "absolute",
    right: 20,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: theme.colors.cyan,
    alignItems: "center",
    justifyContent: "center",
    padding: 0,
    shadowColor: theme.colors.cyan,
    shadowOpacity: 0.55,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 10,
  },
  fabPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.96 }],
  },

  /* Error */
  errorText: {
    fontFamily: theme.fonts.body,
    fontSize: 14,
    color: theme.colors.red,
    textAlign: "center",
    marginTop: 12,
  },

  /* Start-session error box */
  startErrorBox: {
    width: "100%",
    marginTop: 16,
    padding: 14,
    borderRadius: 12,
    backgroundColor: "rgba(239, 68, 68, 0.08)",
    borderWidth: 1,
    borderColor: "rgba(239, 68, 68, 0.25)",
    gap: 8,
  },
  startErrorTitle: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 13,
    color: theme.colors.red,
  },
  startErrorDetail: {
    fontFamily: theme.fonts.body,
    fontSize: 11,
    color: theme.colors.textSecondary,
    lineHeight: 15,
  },
  startErrorRetry: {
    alignSelf: "flex-start",
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 6,
    backgroundColor: "rgba(239, 68, 68, 0.18)",
    marginTop: 4,
  },
  startErrorRetryText: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 12,
    color: theme.colors.red,
  },
});
