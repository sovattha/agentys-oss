/**
 * SessionSummary — Écran de fin de session vocale.
 *
 * Audit UX 2026-04-28 (#3 audit) : transformé d'un écran de stats froid en
 * **moment de célébration** :
 *   - Big number count-up animé (0 → N envoyés sur 800ms)
 *   - Streak persisté (jours consécutifs avec ≥1 session)
 *   - 10 phrases de félicitation random (stable par mount)
 *   - Confetti via Animated (pas de dépendance externe)
 *   - Bouton Partager (Share API natif iOS) avec stats
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, Pressable, StyleSheet, Animated, Easing, Share, Dimensions } from "react-native";
import * as Haptics from "expo-haptics";
import * as SecureStore from "expo-secure-store";
import { useTranslation } from "react-i18next";
import { useTts } from "../hooks/useTts";
import { theme } from "../theme";
import { AgentysLogo } from "./AgentysLogo";
import type { SessionStats } from "../types";

const { width: WIN_W } = Dimensions.get("window");

const STREAK_COUNT_KEY = "agentys_streak_count";
const STREAK_DATE_KEY  = "agentys_streak_last_date";

interface Props {
  stats: SessionStats;
  onDismiss: () => void;
}

function formatDuration(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

function isYesterday(dateStr: string): boolean {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  return yesterday.toISOString().slice(0, 10) === dateStr;
}

/** Lit + met à jour la streak. Renvoie le compte à afficher. */
async function bumpStreak(): Promise<number> {
  const today = todayStr();
  const [countRaw, dateRaw] = await Promise.all([
    SecureStore.getItemAsync(STREAK_COUNT_KEY).catch(() => null),
    SecureStore.getItemAsync(STREAK_DATE_KEY).catch(() => null),
  ]);
  const prevCount = parseInt(countRaw || "0", 10) || 0;

  let newCount: number;
  if (dateRaw === today) {
    // Déjà compté aujourd'hui — pas de re-incrément.
    newCount = prevCount;
  } else if (dateRaw && isYesterday(dateRaw)) {
    newCount = prevCount + 1;
  } else {
    newCount = 1;
  }

  await Promise.all([
    SecureStore.setItemAsync(STREAK_COUNT_KEY, String(newCount)).catch(() => {}), // no-op légitime : streak best-effort
    SecureStore.setItemAsync(STREAK_DATE_KEY, today).catch(() => {}), // no-op légitime : streak best-effort
  ]);
  return newCount;
}

/** Confetti minimaliste : 14 particules animées du centre vers les bords. */
function Confetti({ active }: { active: boolean }) {
  const PARTICLES = 14;
  const particles = useMemo(
    () =>
      Array.from({ length: PARTICLES }).map((_, i) => {
        const angle = (i / PARTICLES) * Math.PI * 2 + Math.random() * 0.5;
        return {
          tx: Math.cos(angle) * (140 + Math.random() * 60),
          ty: Math.sin(angle) * (140 + Math.random() * 60),
          color: [theme.colors.cyan, theme.colors.green, theme.colors.amber, theme.colors.primary][i % 4],
          size: 6 + Math.random() * 4,
          rotEnd: (Math.random() - 0.5) * 720,
        };
      }),
    [],
  );
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!active) return;
    Animated.timing(progress, {
      toValue: 1,
      duration: 1400,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [active, progress]);

  if (!active) return null;
  return (
    <View style={confettiStyles.container} pointerEvents="none">
      {particles.map((p, i) => {
        const tx = progress.interpolate({ inputRange: [0, 1], outputRange: [0, p.tx] });
        const ty = progress.interpolate({ inputRange: [0, 1], outputRange: [0, p.ty] });
        const opacity = progress.interpolate({ inputRange: [0, 0.7, 1], outputRange: [1, 1, 0] });
        const rotate = progress.interpolate({ inputRange: [0, 1], outputRange: ["0deg", `${p.rotEnd}deg`] });
        return (
          <Animated.View
            key={i}
            style={[
              confettiStyles.particle,
              {
                width: p.size,
                height: p.size,
                backgroundColor: p.color,
                transform: [{ translateX: tx }, { translateY: ty }, { rotate }],
                opacity,
              },
            ]}
          />
        );
      })}
    </View>
  );
}

const confettiStyles = StyleSheet.create({
  container: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 5,
  },
  particle: {
    position: "absolute",
    borderRadius: 2,
  },
});

export function SessionSummary({ stats, onDismiss }: Props) {
  const duration = Date.now() - stats.started;
  const tts = useTts();
  const { t } = useTranslation("session");

  // Pick celebration variant stable par mount
  const celebrationKey = useMemo(() => {
    const idx = Math.floor(Math.random() * 10) + 1;
    return `celebration${idx}`;
  }, []);

  // Count-up animation : 0 → stats.approved sur 800ms
  const [displayCount, setDisplayCount] = useState(0);
  useEffect(() => {
    const target = stats.approved;
    if (target === 0) { setDisplayCount(0); return; }
    const startTs = Date.now();
    const duration = 800;
    let raf: ReturnType<typeof requestAnimationFrame>;
    const tick = () => {
      const elapsed = Date.now() - startTs;
      const t01 = Math.min(1, elapsed / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t01, 3);
      setDisplayCount(Math.round(target * eased));
      if (t01 < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [stats.approved]);

  // Streak (mounted once)
  const [streak, setStreak] = useState<number | null>(null);
  useEffect(() => {
    bumpStreak().then(setStreak).catch(() => {}); // no-op légitime : streak best-effort
  }, []);

  // Celebration haptic + TTS
  useEffect(() => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    setTimeout(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {}), 200);
    const parts: string[] = [];
    if (stats.totalEmails > 0) parts.push(t("statEmails", { count: stats.totalEmails }));
    if (stats.approved > 0) parts.push(t("statReplies", { count: stats.approved }));
    if (stats.skipped > 0) parts.push(t("statSkipped", { count: stats.skipped }));
    tts.speak(t("announce", { stats: parts.join(", ") }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleShare = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {}); // no-op légitime : streak best-effort
    try {
      await Share.share({
        message: t("shareMessage", {
          processed: stats.totalEmails,
          duration: formatDuration(duration),
        }),
      });
    } catch {
      /* user cancelled or unavailable */
    }
  };

  return (
    <View style={styles.container}>
      <Confetti active={stats.approved > 0} />

      <AgentysLogo size={120} bgColor={theme.colors.bg} />

      <Text style={styles.title}>{t("title")}</Text>

      {/* Phrase de célébration variable */}
      <Text style={styles.celebration}>{t(celebrationKey)}</Text>

      {/* Stat principal — count-up animé */}
      <Text style={styles.bigNumber}>{displayCount}</Text>
      <Text style={styles.bigLabel}>{t("sent", { count: stats.approved })}</Text>

      {/* Streak — affichée uniquement si > 1 (1 jour seul = pas une streak intéressante) */}
      {streak !== null && streak > 1 ? (
        <Text style={styles.streak}>{t("streak", { count: streak })}</Text>
      ) : null}

      {/* Stats secondaires */}
      <View style={styles.statsRow}>
        <View style={styles.statItem}>
          <Text style={styles.statValue}>{stats.totalEmails}</Text>
          <Text style={styles.statLabel}>{t("processed")}</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={styles.statValue}>{stats.skipped}</Text>
          <Text style={styles.statLabel}>{t("skipped")}</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statItem}>
          <Text style={styles.statValue}>{formatDuration(duration)}</Text>
          <Text style={styles.statLabel}>{t("duration")}</Text>
        </View>
      </View>

      <View style={styles.spacer} />

      <View style={styles.actionsRow}>
        {stats.approved > 0 ? (
          <Pressable
            style={({ pressed }) => [styles.shareBtn, pressed && styles.doneBtnPressed]}
            onPress={handleShare}
            accessibilityRole="button"
            accessibilityLabel={t("share")}
          >
            <Text style={styles.shareBtnText}>{t("share")}</Text>
          </Pressable>
        ) : null}
        <Pressable
          style={({ pressed }) => [styles.doneBtn, pressed && styles.doneBtnPressed]}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
            tts.stop();
            onDismiss();
          }}
          accessibilityRole="button"
          accessibilityLabel={t("done")}
        >
          <Text style={styles.doneBtnText}>{t("done")}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bg,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    paddingBottom: 44,
  },
  title: {
    fontFamily: theme.fonts.body,
    fontSize: 11,
    color: theme.colors.textMuted,
    letterSpacing: 2,
    textTransform: "uppercase",
    marginTop: 24,
    marginBottom: 32,
  },
  celebration: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 18,
    color: theme.colors.textPrimary,
    textAlign: "center",
    letterSpacing: -0.2,
    marginBottom: 24,
    paddingHorizontal: 32,
    lineHeight: 24,
  },
  bigNumber: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 64,
    color: theme.colors.green,
    lineHeight: 72,
  },
  bigLabel: {
    fontFamily: theme.fonts.body,
    fontSize: 14,
    color: theme.colors.green,
    letterSpacing: 1,
    marginBottom: 16,
  },
  streak: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 13,
    color: theme.colors.amber,
    letterSpacing: 0.5,
    marginBottom: 24,
  },
  actionsRow: {
    flexDirection: "row",
    gap: 12,
    alignItems: "center",
  },
  shareBtn: {
    paddingVertical: 14,
    paddingHorizontal: 28,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: theme.colors.cyan,
  },
  shareBtnText: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 14,
    color: theme.colors.cyan,
    letterSpacing: 1,
  },
  statsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 20,
  },
  statItem: {
    alignItems: "center",
  },
  statValue: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 18,
    color: theme.colors.textPrimary,
  },
  statLabel: {
    fontFamily: theme.fonts.body,
    fontSize: 10,
    color: theme.colors.textMuted,
    letterSpacing: 1,
    marginTop: 2,
  },
  statDivider: {
    width: 1,
    height: 24,
    backgroundColor: theme.colors.border,
  },
  spacer: {
    flex: 1,
    maxHeight: 60,
  },
  doneBtn: {
    paddingVertical: 14,
    paddingHorizontal: 48,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: theme.colors.primary,
  },
  doneBtnPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  doneBtnText: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 14,
    color: theme.colors.primary,
    letterSpacing: 1,
  },
});
