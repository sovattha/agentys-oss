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

/**
 * ToastHost — affiche les messages publiés via `toast.error/warning/info/success`.
 *
 * Doit être monté UNE fois à la racine de l'app (`app/_layout.tsx`). Position
 * fixe en haut de l'écran avec safe area, animation slide-in/out, dismiss
 * automatique après `duration` (3.5s par défaut) ou tap pour dismisser.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { AccessibilityInfo, Animated, StyleSheet, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";
import { toast, type ToastMessage } from "../lib/toast";

const KIND_COLORS: Record<ToastMessage["kind"], { bg: string; border: string; text: string }> = {
  error:   { bg: "rgba(220, 38, 38, 0.95)", border: "#fca5a5", text: "#ffffff" },
  warning: { bg: "rgba(251, 146, 60, 0.95)", border: "#fdba74", text: "#1a1a1a" },
  info:    { bg: "rgba(59, 130, 246, 0.95)", border: "#93c5fd", text: "#ffffff" },
  success: { bg: "rgba(34, 197, 94, 0.95)", border: "#86efac", text: "#ffffff" },
};

const KIND_EMOJI: Record<ToastMessage["kind"], string> = {
  error:   "⚠️",
  warning: "⚠",
  info:    "ℹ",
  success: "✓",
};

interface InternalToast extends ToastMessage {
  fade: Animated.Value;
}

export function ToastHost() {
  const insets = useSafeAreaInsets();
  const { t: tr } = useTranslation("common");
  const [toasts, setToasts] = useState<InternalToast[]>([]);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => {
      const target = prev.find((t) => t.id === id);
      if (target) {
        Animated.timing(target.fade, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }).start(() => {
          setToasts((curr) => curr.filter((t) => t.id !== id));
        });
        return prev;
      }
      return prev;
    });
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  useEffect(() => {
    const unsubscribe = toast.subscribe((msg) => {
      const fade = new Animated.Value(0);
      const internal: InternalToast = { ...msg, fade };
      setToasts((prev) => [...prev, internal]);
      // #1127 : annonce le toast aux lecteurs d'écran (VoiceOver iOS ;
      // TalkBack couvert par accessibilityLiveRegion sur la vue).
      AccessibilityInfo.announceForAccessibility(msg.text);
      Animated.timing(fade, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }).start();
      const duration = msg.duration ?? 3500;
      if (duration > 0) {
        const timer = setTimeout(() => dismiss(msg.id), duration);
        timersRef.current.set(msg.id, timer);
      }
    });
    const timers = timersRef.current;
    return () => {
      unsubscribe();
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, [dismiss]);

  if (toasts.length === 0) return null;

  return (
    <View pointerEvents="box-none" style={[styles.container, { top: insets.top + 8 }]}>
      {toasts.map((t) => {
        const colors = KIND_COLORS[t.kind];
        return (
          <Animated.View
            key={t.id}
            style={[
              styles.toast,
              {
                backgroundColor: colors.bg,
                borderColor: colors.border,
                opacity: t.fade,
                transform: [
                  {
                    translateY: t.fade.interpolate({
                      inputRange: [0, 1],
                      outputRange: [-12, 0],
                    }),
                  },
                ],
              },
            ]}
          >
            <Pressable
              onPress={() => dismiss(t.id)}
              style={styles.row}
              hitSlop={6}
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
              accessibilityLabel={t.text}
              accessibilityHint={tr("toastDismissHint")}
            >
              <Text style={styles.emoji}>{KIND_EMOJI[t.kind]}</Text>
              <Text style={[styles.text, { color: colors.text }]} numberOfLines={3}>
                {t.text}
              </Text>
            </Pressable>
          </Animated.View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    left: 12,
    right: 12,
    zIndex: 1000,
    gap: 8,
  },
  toast: {
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 11,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 6,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  emoji: {
    fontSize: 16,
  },
  text: {
    flex: 1,
    fontSize: 14,
    lineHeight: 19,
  },
});
