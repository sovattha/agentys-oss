/**
 * Sélecteur de voix ElevenLabs — tabs Premade / Clonées, preview, radio select.
 */

import { useState, useMemo } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";
import { theme } from "../theme";
import type { TtsVoice } from "../types";
import type { VoiceSettings } from "../hooks/useVoiceSettings";

type Tab = "premade" | "cloned";

interface Props {
  voice: VoiceSettings;
  onOpenClone: () => void;
}

export function VoicePicker({ voice, onOpenClone }: Props) {
  const [tab, setTab] = useState<Tab>("premade");
  const { t } = useTranslation(["voice", "common"]);

  const { premade, cloned } = useMemo(() => {
    const p: TtsVoice[] = [];
    const c: TtsVoice[] = [];
    for (const v of voice.availableVoices) {
      if (v.category === "cloned") c.push(v);
      else p.push(v);
    }
    return { premade: p, cloned: c };
  }, [voice.availableVoices]);

  const current = tab === "cloned" ? cloned : premade;

  const handleDelete = (v: TtsVoice) => {
    Alert.alert(
      t("voice:deleteTitle"),
      t("voice:deleteMessage", { name: v.name }),
      [
        { text: t("common:cancel"), style: "cancel" },
        {
          text: t("common:delete"),
          style: "destructive",
          onPress: async () => {
            try {
              await voice.deleteVoice(v.voice_id);
            } catch (err: any) {
              Alert.alert(t("common:failed"), err?.message || t("voice:deleteFailed"));
            }
          },
        },
      ],
    );
  };

  return (
    <View>
      {/* Tabs */}
      <View style={styles.tabsRow}>
        <Pressable
          style={[styles.tab, tab === "premade" && styles.tabActive]}
          onPress={async () => {
            await Haptics.selectionAsync();
            setTab("premade");
          }}
          accessibilityRole="tab"
          accessibilityLabel={t("voice:tabPremade", { count: premade.length })}
          accessibilityState={{ selected: tab === "premade" }}
        >
          <Text style={[styles.tabText, tab === "premade" && styles.tabTextActive]}>
            {t("voice:tabPremade", { count: premade.length })}
          </Text>
        </Pressable>
        <Pressable
          style={[styles.tab, tab === "cloned" && styles.tabActive]}
          onPress={async () => {
            await Haptics.selectionAsync();
            setTab("cloned");
          }}
          accessibilityRole="tab"
          accessibilityLabel={t("voice:tabCloned", { count: cloned.length })}
          accessibilityState={{ selected: tab === "cloned" }}
        >
          <Text style={[styles.tabText, tab === "cloned" && styles.tabTextActive]}>
            {t("voice:tabCloned", { count: cloned.length })}
          </Text>
        </Pressable>
      </View>

      {/* Loading / error */}
      {voice.voicesLoading && (
        <View style={styles.center}>
          <ActivityIndicator color={theme.colors.cyan} />
          <Text style={styles.meta}>{t("voice:loadingVoices")}</Text>
        </View>
      )}

      {voice.voicesError && !voice.voicesLoading && (
        <View style={styles.center}>
          <Text style={styles.error}>{voice.voicesError}</Text>
          <Pressable
            style={styles.retryBtn}
            onPress={() => voice.refreshVoices()}
            accessibilityRole="button"
            accessibilityLabel={t("common:retry")}
          >
            <Text style={styles.retryBtnText}>{t("common:retry")}</Text>
          </Pressable>
        </View>
      )}

      {/* Empty state cloned */}
      {tab === "cloned" && !voice.voicesLoading && cloned.length === 0 && (
        <View style={styles.emptyState}>
          <Ionicons name="mic-outline" size={32} color={theme.colors.textMuted} />
          <Text style={styles.emptyTitle}>{t("voice:noClonedVoices")}</Text>
          <Text style={styles.emptyDesc}>
            {t("voice:cloneDescription")}
          </Text>
          <Pressable
            style={styles.cloneCta}
            onPress={onOpenClone}
            accessibilityRole="button"
            accessibilityLabel={t("voice:cloneCta")}
          >
            <Ionicons name="add-circle-outline" size={16} color={theme.colors.bg} />
            <Text style={styles.cloneCtaText}>{t("voice:cloneCta")}</Text>
          </Pressable>
        </View>
      )}

      {/* List */}
      {!voice.voicesLoading &&
        current.map((v) => {
          const selected = voice.selectedVoice === v.voice_id;
          return (
            <Pressable
              key={v.voice_id}
              style={[styles.item, selected && styles.itemSelected]}
              onPress={() => voice.setVoice(v.voice_id)}
              accessibilityRole="radio"
              accessibilityLabel={v.name}
              accessibilityState={{ selected }}
            >
              <View style={styles.radio}>
                {selected && <View style={styles.radioDot} />}
              </View>
              <View style={styles.itemInfo}>
                <Text
                  style={[styles.itemName, selected && styles.itemNameSelected]}
                  numberOfLines={1}
                >
                  {v.name}
                </Text>
                {(v.language || v.labels?.accent) && (
                  <Text style={styles.itemMeta} numberOfLines={1}>
                    {v.language || v.labels?.accent}
                  </Text>
                )}
              </View>
              <Pressable
                style={styles.iconBtn}
                onPress={(e) => {
                  e.stopPropagation?.();
                  voice.previewVoice(v.voice_id);
                }}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel={t("voice:previewVoiceA11y", { name: v.name })}
              >
                <Ionicons
                  name="play-circle-outline"
                  size={22}
                  color={theme.colors.textSecondary}
                />
              </Pressable>
              {v.category === "cloned" && (
                <Pressable
                  style={styles.iconBtn}
                  onPress={(e) => {
                    e.stopPropagation?.();
                    handleDelete(v);
                  }}
                  hitSlop={8}
                  accessibilityRole="button"
                  accessibilityLabel={t("voice:deleteVoiceA11y", { name: v.name })}
                >
                  <Ionicons name="trash-outline" size={18} color={theme.colors.red} />
                </Pressable>
              )}
            </Pressable>
          );
        })}

      {/* Clone CTA at bottom of cloned list */}
      {tab === "cloned" && cloned.length > 0 && (
        <Pressable
          style={[styles.cloneCta, { marginTop: 8 }]}
          onPress={onOpenClone}
          accessibilityRole="button"
          accessibilityLabel={t("voice:cloneAnother")}
        >
          <Ionicons name="add-circle-outline" size={16} color={theme.colors.bg} />
          <Text style={styles.cloneCtaText}>{t("voice:cloneAnother")}</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  tabsRow: {
    flexDirection: "row",
    gap: 2,
    backgroundColor: theme.colors.surfaceHigh,
    borderRadius: 10,
    padding: 3,
    borderWidth: 1,
    borderColor: theme.colors.border,
    marginBottom: 10,
  },
  tab: {
    flex: 1,
    paddingVertical: 8,
    alignItems: "center",
    borderRadius: 7,
  },
  tabActive: {
    backgroundColor: `${theme.colors.cyan}22`,
  },
  tabText: {
    fontSize: 12,
    fontFamily: theme.fonts.bodyMedium,
    color: theme.colors.textMuted,
  },
  tabTextActive: {
    color: theme.colors.cyan,
    fontFamily: theme.fonts.bodyBold,
  },
  center: {
    alignItems: "center",
    gap: 8,
    padding: 20,
  },
  meta: {
    fontSize: 12,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
  },
  error: {
    fontSize: 13,
    fontFamily: theme.fonts.body,
    color: theme.colors.red,
    textAlign: "center",
  },
  retryBtn: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  retryBtnText: {
    fontSize: 12,
    fontFamily: theme.fonts.bodyMedium,
    color: theme.colors.textPrimary,
  },
  emptyState: {
    alignItems: "center",
    gap: 8,
    paddingVertical: 24,
    paddingHorizontal: 20,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  emptyTitle: {
    fontSize: 14,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
  },
  emptyDesc: {
    fontSize: 12,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    textAlign: "center",
  },
  cloneCta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: theme.colors.cyan,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: theme.radius.md,
    alignSelf: "center",
    marginTop: 4,
  },
  cloneCtaText: {
    fontSize: 13,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.bg,
  },
  item: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.surface,
    borderWidth: 1,
    borderColor: theme.colors.border,
    marginBottom: 6,
  },
  itemSelected: {
    borderColor: theme.colors.cyan,
    backgroundColor: `${theme.colors.cyan}12`,
  },
  radio: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: theme.colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  radioDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: theme.colors.cyan,
  },
  itemInfo: {
    flex: 1,
  },
  itemName: {
    fontSize: 14,
    fontFamily: theme.fonts.body,
    color: theme.colors.textPrimary,
  },
  itemNameSelected: {
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.cyan,
  },
  itemMeta: {
    fontSize: 11,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    marginTop: 1,
  },
  iconBtn: {
    padding: 4,
  },
});
