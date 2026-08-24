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

﻿/**
 * DrivePlayer — "Nested Breathe" V3
 * Layout épuré : état → animation → expéditeur → sujet → compteur → actions.
 * Polyrhythmic triangles concentriques au centre.
 */

import { useEffect, useRef, useMemo } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Animated,
  PanResponder,
  ActivityIndicator,
  useWindowDimensions,
} from "react-native";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";
import { theme } from "../theme";
import type { SpeakerMode } from "./VoiceVisualizer";
import { BreathingTriangle } from "./BreathingTriangle";
import { SpeakerChip } from "./SpeakerChip";
import type { DriveState } from "../types";

interface Props {
  state: DriveState;
  emailSubject?: string;
  senderName?: string;
  senderEmail?: string;
  draftContent?: string | null;
  error?: string | null;
  currentIndex?: number;
  totalEmails?: number;
  classificationLabel?: string;
  classificationIndex?: number;
  classificationTotal?: number;
  transcript?: string;
  commandRecognized?: string | null;
  /** Temps écoulé en ms pendant generating (affiché en suffix dans StatusPill). */
  generatingElapsedMs?: number;
  onNext:     () => void;
  onPrevious?: () => void;
  /** Flèche retour — revient à l'email précédent (ou quitte la session si premier). */
  onBack?:     () => void;
  /** Niveau audio 0..1 (Animated) pour la viz réactive — TTS + STT. */
  audioLevel?: Animated.Value;
  /** STT actif : bascule la visualisation en mode « user » (bursty). */
  isListening?: boolean;
  /** Tap n'importe où sur la visualisation pour interrompre la lecture TTS et
   *  ouvrir le mic — équivalent manuel du barge-in vocal. */
  onTogglePlayback?: () => void;
  /** True quand le TTS joue (speaking) ou est en pause — active le tap-to-interrupt. */
  isPlayback?: boolean;
  /** True pendant la ~1s de transcription backend (VAD terminé, transcript pas encore là). */
  isTranscribing?: boolean;
  /** Nombre d'actions différées annulables (act-then-undo) — > 0 affiche le
   *  chip « Annuler », l'escape hatch latency-proof (tap, pas de STT). */
  pendingUndoCount?: number;
  /** Tap du chip undo : annule la dernière action différée. */
  onUndo?: () => void;
  /** Long-press sur le logo → ouvre les réglages (pattern établi de l'app). */
  onOpenSettings?: () => void;
  /** Tap « c'est fini » pendant la dictée : clôt la prise de parole et passe
   *  en confirmation (où « envoyer » fonctionne). */
  onFinishDictation?: () => void;
  /** Tap plein-écran en confirming_dictation : « c'est fini → rédige »
   *  (trace live 2026-07-28 : aucune cible de tap dans cet état — le tap
   *  était mort, ni earcon ni action, ressenti « ça n'écoute pas »). */
  onConfirmDictation?: () => void;
  /** Tap plein-écran en undo_window : annule l'envoi différé et GARDE le
   *  brouillon (P2.5 — le tap unifié n'a plus de zone morte). */
  onCancelSend?: () => void;
  /** Watchdog (§1.6) : true ⇔ aucun progrès depuis 12 s — bandeau visible. */
  stalled?: boolean;
  /** Tap du bandeau de gel : relance l'écoute. */
  onRetryStalled?: () => void;
}

/**
 * Indicateur de statut explicite — l'utilisateur DOIT toujours savoir ce qui
 * se passe. Sans ça : "le système est-il bloqué ? est-ce qu'il m'écoute ?
 * est-ce qu'il pense ?". Phase 1 du fix UX.
 *
 * Affichage par état :
 *   speaking     → 🔊 + label    (redondant avec audio mais utile en silencieux)
 *   listening    → 🎤 + label + pulse rouge
 *   loading      → ActivityIndicator + label
 *   generating   → ActivityIndicator + label (pendant pipeline backend)
 *   processing   → ActivityIndicator + label
 *   asking_*     → ❓ + label
 *   confirming_dictation → ❓ + label
 *   reviewing    → ✏️ + label
 *   choosing     → 👉 + label
 *   paused       → ⏸ + label
 *   completed    → ✅ + label
 *   error        → ⚠ + label
 *   idle         → masqué
 */
function StatusPill({
  state,
  isListening,
  stateColor,
  generatingElapsedMs,
  t,
}: {
  state: DriveState;
  isListening: boolean;
  stateColor: string;
  generatingElapsedMs: number;
  t: (key: string, opts?: any) => string;
}) {
  const pulseOpacity = useRef(new Animated.Value(0.4)).current;
  const isProcessing =
    state === "loading" || state === "generating" || state === "processing";
  const isMicActive = isListening || state === "listening" || state === "confirming_dictation";

  // Pulse continu pour les états live (mic ou TTS).
  useEffect(() => {
    if (isMicActive || state === "speaking") {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseOpacity, {
            toValue: 1,
            duration: 600,
            useNativeDriver: true,
          }),
          Animated.timing(pulseOpacity, {
            toValue: 0.4,
            duration: 600,
            useNativeDriver: true,
          }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    } else {
      pulseOpacity.setValue(1);
    }
  }, [isMicActive, state, pulseOpacity]);

  if (state === "idle") return null;

  const emoji =
    state === "undo_window" ? "📤" : // envoi différé (tap pour annuler)
    isMicActive       ? "🎤" :
    state === "speaking" ? "🔊" :
    state === "asking_preview" || state === "asking_send" ? "❓" :
    state === "reviewing" ? "✏️" :
    state === "choosing" ? "👉" :
    state === "paused" ? "⏸" :
    state === "completed" ? "✅" :
    state === "error" ? "⚠️" :
    isProcessing ? "" : // spinner remplace l'emoji
    "";

  // Suffix "(Xs)" pendant la génération pour rassurer l'user que ça avance.
  const elapsedSuffix =
    isProcessing && generatingElapsedMs > 0
      ? ` (${Math.round(generatingElapsedMs / 1000)}s)`
      : "";
  const label = t(`state.${state}`) + elapsedSuffix;
  // undo_window garde sa couleur d'état (amber "en attente") même si le mic
  // est ouvert — c'est un envoi en attente, pas une dictée.
  const color = state === "undo_window" ? stateColor : (isMicActive ? "#3DE3C7" : stateColor);

  return (
    <Animated.View
      style={[
        statusPillStyles.pill,
        {
          opacity: isMicActive || state === "speaking" ? pulseOpacity : 1,
          borderColor: color,
        },
      ]}
      // Audit a11y 2026-04-28 : VoiceOver lit le state pill au changement
      // (le content change → accessibilityLiveRegion="polite" annonce sans
      // interrompre la session vocale en cours).
      accessibilityRole="text"
      accessibilityLiveRegion="polite"
      accessibilityLabel={t(`state.${state}`)}
    >
      {isProcessing ? (
        <ActivityIndicator size="small" color={color} style={statusPillStyles.spinner} />
      ) : emoji ? (
        <Text style={statusPillStyles.emoji}>{emoji}</Text>
      ) : null}
      <Text style={[statusPillStyles.label, { color }]}>{label}</Text>
    </Animated.View>
  );
}

/**
 * Hint « touchez pour interrompre » — pastille pulsée, bien plus visible que
 * l'ancien texte discret (opacity 0.55). En conduite l'utilisateur doit savoir
 * d'un coup d'œil qu'un simple toucher coupe la lecture. pointerEvents="none"
 * pour ne pas voler le tap à l'overlay d'interruption placé dessous.
 */
function TapToInterruptHint({ label }: { label: string }) {
  const pulse = useRef(new Animated.Value(0.55)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 800, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.55, duration: 800, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  return (
    <Animated.View style={[tapHintStyles.pill, { opacity: pulse }]} pointerEvents="none">
      <Text style={tapHintStyles.icon}>☝</Text>
      <Text style={tapHintStyles.label}>{label}</Text>
    </Animated.View>
  );
}

/** Sous cette hauteur de fenêtre (pt), l'écran est trop court pour porter la
 *  typo « volant » ET un triangle de 190 : iPhone SE / mini / 8. */
const SHORT_SCREEN_HEIGHT = 750;

const STATE_COLORS: Record<DriveState, string> = {
  idle:                  theme.colors.textMuted,
  loading:               theme.colors.textMuted,
  speaking:              theme.colors.amber,
  choosing:              theme.colors.primary,
  listening:             theme.colors.primaryLight,
  confirming_dictation:  theme.colors.primaryLight,
  processing:            theme.colors.primary,
  generating:            theme.colors.primaryLight,
  asking_preview:        theme.colors.amber,
  asking_send:           theme.colors.green,
  reviewing:             theme.colors.green,
  undo_window:           theme.colors.amber,
  paused:                theme.colors.textMuted,
  completed:             theme.colors.green,
  error:                 theme.colors.red,
};

export function DrivePlayer({
  state,
  emailSubject,
  senderName,
  senderEmail,
  draftContent,
  error,
  currentIndex = 0,
  totalEmails = 0,
  classificationLabel = "Email",
  classificationIndex = 0,
  classificationTotal = 0,
  transcript,
  commandRecognized,
  generatingElapsedMs = 0,
  onNext,
  onPrevious,
  onBack,
  audioLevel,
  isListening = false,
  onTogglePlayback,
  isPlayback = false,
  isTranscribing = false,
  pendingUndoCount = 0,
  onUndo,
  onOpenSettings,
  onFinishDictation,
  onConfirmDictation,
  onCancelSend,
  stalled = false,
  onRetryStalled,
}: Props) {
  const { t } = useTranslation("drive");
  const stateColor = STATE_COLORS[state];
  const cmdFlashOpacity = useRef(new Animated.Value(0)).current;

  // Le contenu ne défile pas (pas de scroll en conduite) : sur un écran court,
  // la typo grossie pour le volant déborderait et serait rognée en silence.
  // Le triangle est l'élément le plus compressible — il cède la place.
  const { height: windowHeight } = useWindowDimensions();
  const logoSize = windowHeight < SHORT_SCREEN_HEIGHT ? 140 : 190;

  // #1134 (anti-flicker) : le chip doit refléter le TOUR DE PAROLE (core.state),
  // pas le clignotement de `isListening` entre deux cycles VAD. En "choosing"/
  // "listening"/etc., l'écoute se réarme toutes les ~5 s (trou de ~0,5 s où
  // isListening repasse false) — sans ce garde, le chip retombait alors en
  // "ai" = « Agentys parle » → oscillation « Agentys ↔ À toi » sans earcon.
  // On classe donc par état : dormant → idle, tour de l'user → user, IA → ai.
  const speakerMode: SpeakerMode =
    state === "idle" || state === "paused" || state === "completed" || state === "error"
      ? "idle"
      : isListening ||
          state === "choosing" || state === "listening" || state === "reviewing" ||
          state === "asking_preview" || state === "asking_send" ||
          state === "confirming_dictation" || state === "undo_window"
        ? "user"
        : "ai";

  useEffect(() => {
    if (commandRecognized) {
      // Retour device 2026-07 : pop rapide, TENUE 700ms (le flash 150/600
      // d'origine était illisible en conduite), puis fade. L'accusé de
      // réception doit être évident : « compris, je joue "suivant" ».
      Animated.sequence([
        Animated.timing(cmdFlashOpacity, { toValue: 1, duration: 120, useNativeDriver: true }),
        Animated.delay(700),
        Animated.timing(cmdFlashOpacity, { toValue: 0, duration: 350, useNativeDriver: true }),
      ]).start();
    }
  }, [commandRecognized]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Swipe horizontal : gauche = précédent, droite = suivant ───────────────
  // Seuil horizontal 60px, vertical max 40px (évite les conflits avec le scroll).
  const swipeHandledRef = useRef(false);
  const panResponder = useMemo(() =>
    PanResponder.create({
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (_, g) => {
        return Math.abs(g.dx) > 12 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5;
      },
      onPanResponderGrant: () => { swipeHandledRef.current = false; },
      onPanResponderMove: (_, g) => {
        if (swipeHandledRef.current) return;
        if (Math.abs(g.dx) > 60 && Math.abs(g.dy) < 40) {
          swipeHandledRef.current = true;
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          if (g.dx < 0) {
            // swipe gauche → suivant
            onNext();
          } else if (onPrevious) {
            // swipe droite → précédent
            onPrevious();
          }
        }
      },
      onPanResponderRelease: () => { swipeHandledRef.current = false; },
      onPanResponderTerminate: () => { swipeHandledRef.current = false; },
    }),
    [onNext, onPrevious]
  );

  return (
    <View style={styles.container} {...panResponder.panHandlers}>

      {/* ── Tap unifié plein écran (P2.5) : UNE cible permanente, l'action
          dérive de l'état machine — plus aucune zone morte (retour device
          2026-07-29 « c'est chaotique, je dois appuyer plusieurs fois »).
          Placé EN ARRIÈRE des chips/boutons (ordre du DOM), qui restent
          prioritaires. Les états sans action tap répondent par un haptique
          discret « bien reçu, rien à faire ici ». ── */}
      {state !== "idle" ? (() => {
        const tap =
          isPlayback && onTogglePlayback ? {
            label: t("a11y.togglePlayback", { defaultValue: "Interrompre la lecture et parler" }),
            action: () => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              onTogglePlayback();
            },
          } :
          state === "listening" && onFinishDictation ? {
            label: t("a11y.finishDictation", { defaultValue: "Terminer la dictée" }),
            action: onFinishDictation,
          } :
          state === "confirming_dictation" && onConfirmDictation ? {
            label: t("a11y.confirmDictation", { defaultValue: "Rédiger la réponse" }),
            action: onConfirmDictation,
          } :
          state === "undo_window" && onCancelSend ? {
            label: t("a11y.cancelSend", { defaultValue: "Annuler l'envoi" }),
            action: () => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
              onCancelSend();
            },
          } : {
            label: t("a11y.driveScreen", { defaultValue: "Écran session vocale" }),
            action: () => { Haptics.selectionAsync().catch(() => {}); }, // no-op légitime : accusé seul
          };
        return (
          <Pressable
            accessibilityLabel={tap.label}
            accessibilityRole="button"
            onPress={tap.action}
            style={StyleSheet.absoluteFill}
          />
        );
      })() : null}

      {/* ── Command recognition flash overlay — badge « ✓ commande » ── */}
      {commandRecognized ? (
        <Animated.View style={[styles.cmdFlash, { opacity: cmdFlashOpacity }]} pointerEvents="none">
          <Animated.View
            style={[
              styles.cmdBadge,
              {
                transform: [{
                  scale: cmdFlashOpacity.interpolate({
                    inputRange: [0, 1],
                    outputRange: [0.85, 1],
                  }),
                }],
              },
            ]}
          >
            <Text style={styles.cmdCheck}>✓</Text>
            <Text style={styles.cmdFlashText}>{commandRecognized}</Text>
          </Animated.View>
        </Animated.View>
      ) : null}

      {/* ── Flèche retour (top-left) ── */}
      {/*
        F12 (LOW): the long-press-on-logo settings shortcut was removed in
        the recent UI cleanup. VoiceOver users now reach settings via:
        back-button → home → long-press triangle. The accessibilityHint
        below documents the path so blind drivers know how to find it.
      */}
      {onBack ? (
        <Pressable
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
            onBack();
          }}
          hitSlop={16}
          style={styles.backBtn}
          accessibilityRole="button"
          accessibilityLabel={t("backToPrevEmail")}
          accessibilityHint={t("backToPrevEmailHint")}
        >
          <View style={styles.backArrow} />
        </Pressable>
      ) : null}

      {/* ── Classification counter: "Action 3/5" or "Info 2/8" ── */}
      {classificationTotal > 0 ? (
        <Text style={styles.counter}>
          {classificationLabel} {classificationIndex + 1}/{classificationTotal}
        </Text>
      ) : null}

      {/* ── Spacer supérieur → pousse sender+chip vers le centre ── */}
      <View style={styles.spacerTop} />

      {/* ── Logo animé (remplace les vagues) ──
          - couleur = état courant (accentColor), enveloppe réactive à la voix
            (externalLevel = audioLevel) : le triangle bouge quand ça parle/écoute.
          - long-press → réglages (pattern établi de l'app, cf. F12).
          - tap pendant la lecture → interrompt (comme le reste de l'écran). */}
      <Pressable
        onLongPress={onOpenSettings}
        delayLongPress={500}
        onPress={
          isPlayback && onTogglePlayback
            ? () => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
                onTogglePlayback();
              }
            : undefined
        }
        style={styles.logoWrap}
        accessibilityRole="button"
        accessibilityLabel={t("a11y.logo", { defaultValue: "Logo Agentys" })}
        accessibilityHint={t("a11y.logoHint", { defaultValue: "Appui long pour ouvrir les réglages" })}
      >
        <BreathingTriangle size={logoSize} externalLevel={audioLevel} accentColor={stateColor} />
      </Pressable>

      {/* ── Expéditeur + email ── */}
      {senderName ? (
        <Text style={styles.sender} numberOfLines={1}>{senderName}</Text>
      ) : null}
      {senderEmail ? (
        <Text style={styles.senderEmail} numberOfLines={1}>{senderEmail}</Text>
      ) : null}

      {/* ── Sujet ── */}
      {emailSubject ? (
        <Text style={styles.subject} numberOfLines={2}>{emailSubject}</Text>
      ) : null}

      {/* ── Speaker chip — qui parle maintenant ── */}
      {speakerMode !== "idle" ? (
        <View style={styles.chipWrap}>
          <SpeakerChip
            mode={speakerMode}
            userName={t("speaker.you")}
            aiName={t("speaker.ai")}
            activeSublabel={t("speaker.speaking")}
            idleSublabel={t("speaker.tapToTalk")}
            idleLabel={t("speaker.idle")}
          />
        </View>
      ) : null}

      {/* ── Status pill — état explicite avec emoji + animation ── */}
      <StatusPill
        state={state}
        isListening={isListening}
        stateColor={stateColor}
        generatingElapsedMs={generatingElapsedMs}
        t={t}
      />

      {/* ── Bandeau watchdog — le gel s'AVOUE au lieu d'un écran muet ── */}
      {stalled && onRetryStalled ? (
        <Pressable
          style={styles.stallBanner}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
            onRetryStalled();
          }}
          accessibilityRole="button"
          accessibilityLabel={t("stallBanner", { defaultValue: "Je n'entends rien — touchez pour réessayer" })}
        >
          <Text style={styles.stallBannerText}>
            {t("stallBanner", { defaultValue: "Je n'entends rien — touchez pour réessayer" })}
          </Text>
        </Pressable>
      ) : null}

      {/* ── Hint tap-to-interrupt / fin-de-dictée — pastille pulsée ── */}
      {isPlayback && onTogglePlayback ? (
        <TapToInterruptHint label={t("tapHint", { defaultValue: "Touchez l'écran pour interrompre" })} />
      ) : state === "listening" && onFinishDictation ? (
        <TapToInterruptHint label={t("tapFinishHint", { defaultValue: "Touchez quand c'est fini" })} />
      ) : state === "confirming_dictation" && onConfirmDictation ? (
        <TapToInterruptHint label={t("tapConfirmHint", { defaultValue: "Touchez pour rédiger" })} />
      ) : state === "undo_window" && onCancelSend ? (
        <TapToInterruptHint label={t("tapCancelSendHint", { defaultValue: "Touchez pour annuler l'envoi" })} />
      ) : null}

      {/* ── Chip « Annuler » — act-then-undo, escape hatch latency-proof ── */}
      {pendingUndoCount > 0 && onUndo ? (
        <Pressable
          style={styles.undoChip}
          onPress={() => {
            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
            onUndo();
          }}
          accessibilityRole="button"
          accessibilityLabel={t("undoChip", { defaultValue: "Annuler" })}
        >
          <Text style={styles.undoChipText}>↩  {t("undoChip", { defaultValue: "Annuler" })}</Text>
        </Pressable>
      ) : null}

      {/* ── Transcription — s'affiche aussi pendant l'écoute et la transcription (Fix UX #2/#3) ── */}
      {(transcript || isListening || isTranscribing) ? (
        <View style={styles.transcriptBubble}>
          <Text style={[styles.transcriptText, !transcript && styles.transcriptPlaceholder]}>
            {transcript
              ? `« ${transcript} »`
              : isTranscribing
                ? t("state.transcribing", { defaultValue: "Transcription…" })
                : t("state.listeningHint", { defaultValue: "J'écoute…" })}
          </Text>
        </View>
      ) : null}

      {/* ── Erreur ── */}
      {error ? (
        <Text style={styles.error}>{error}</Text>
      ) : null}

      {/* ── Spacer bas — les mots d'action ont été retirés (2026-07) : tout
          passe par la voix + gestes (guide dans les réglages). ── */}
      <View style={styles.spacer} />

    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.bg,
    paddingHorizontal: 32,
    paddingTop: 16,
    paddingBottom: 44,
    alignItems: "center",
  },

  /* Command flash overlay — badge sombre haute lisibilité (retour device) */
  cmdFlash: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "rgba(0,0,0,0.35)",
    zIndex: 10,
  },
  cmdBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 30,
    paddingVertical: 18,
    borderRadius: 28,
    borderWidth: 2,
    borderColor: theme.colors.cyan,
    backgroundColor: "rgba(8, 18, 24, 0.94)",
    shadowColor: theme.colors.cyan,
    shadowOpacity: 0.5,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 0 },
    elevation: 12,
  },
  cmdCheck: {
    fontSize: 28,
    lineHeight: 32,
    color: "#3DE3C7",
    fontFamily: theme.fonts.bodyBold,
  },
  cmdFlashText: {
    fontFamily: theme.fonts.bodyBold,
    fontSize: 28,
    color: "#FFFFFF",
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },

  /* Back button */
  backBtn: {
    position: "absolute",
    top: 12,
    left: 12,
    width: 40,
    height: 40,
    padding: 0,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 20,
  },
  backArrow: {
    width: 12,
    height: 12,
    borderLeftWidth: 2,
    borderBottomWidth: 2,
    borderColor: theme.colors.textDimmed,
    transform: [{ rotate: "45deg" }],
  },

  /* Expéditeur — lisible en une glance (~0,5 s) depuis un support voiture */
  sender: {
    fontSize: 30,
    fontFamily: theme.fonts.bodyBold,
    color: theme.colors.textPrimary,
    textAlign: "center",
    marginBottom: 2,
  },
  /* L'adresse est l'info la moins utile au volant : elle reste secondaire,
     mais assez grande pour ne pas être une tache grise illisible. */
  senderEmail: {
    fontSize: 15,
    fontFamily: theme.fonts.body,
    color: theme.colors.textMuted,
    textAlign: "center",
    marginBottom: 6,
  },

  /* Sujet — LA donnée qui dit de quoi parle le mail : plus jamais en 13px */
  subject: {
    fontSize: 22,
    fontFamily: theme.fonts.body,
    color: theme.colors.textSecondary,
    textAlign: "center",
    lineHeight: 30,
    paddingHorizontal: 8,
    marginBottom: 4,
  },

  /* Compteur */
  counter: {
    fontFamily: theme.fonts.body,
    fontSize: 15,
    color: theme.colors.textDim,
    letterSpacing: 2,
    marginTop: 4,
  },

  /* Spacer supérieur — pousse le bloc sender/chip vers le centre vertical */
  spacerTop: {
    flex: 0.6,
  },

  /* Speaker chip */
  chipWrap: {
    marginTop: 18,
    alignItems: "center",
  },

  /* Logo animé (remplace les vagues) */
  logoWrap: {
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 6,
  },

  /* Transcription */
  transcriptBubble: {
    marginTop: 20,
    paddingHorizontal: 20,
    paddingVertical: 12,
    backgroundColor: `${theme.colors.cyan}0F`,
    borderWidth: 1,
    borderColor: `${theme.colors.cyan}1A`,
    borderRadius: theme.radius.lg,
    maxWidth: 340,
  },
  transcriptText: {
    fontSize: 20,
    fontFamily: theme.fonts.body,
    fontStyle: "italic",
    color: theme.colors.primaryLight,
    textAlign: "center",
    lineHeight: 28,
  },
  transcriptPlaceholder: {
    opacity: 0.5,
    fontStyle: "normal",
  },
  undoChip: {
    marginTop: 14,
    paddingHorizontal: 22,
    paddingVertical: 11,
    backgroundColor: `${theme.colors.amber}22`,
    borderWidth: 1,
    borderColor: `${theme.colors.amber}55`,
    borderRadius: theme.radius.lg,
  },
  undoChipText: {
    fontSize: 20,
    fontFamily: theme.fonts.body,
    fontWeight: "600",
    color: theme.colors.amber,
    textAlign: "center",
  },

  /* Erreur */
  error: {
    fontSize: 17,
    fontFamily: theme.fonts.body,
    color: theme.colors.red,
    textAlign: "center",
    marginTop: 8,
  },

  /* Spacer */
  spacer: {
    flex: 1,
  },

  /* Status pill — affiché entre SpeakerChip et transcript */

  /* Bandeau watchdog (§1.6) */
  stallBanner: {
    marginTop: 14,
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: theme.radius.lg,
    borderWidth: 1.5,
    borderColor: `${theme.colors.amber}66`,
    backgroundColor: `${theme.colors.amber}1A`,
  },
  stallBannerText: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 19,
    color: theme.colors.amber,
    textAlign: "center",
  },
});

const tapHintStyles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 12,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderRadius: 22,
    borderWidth: 1.5,
    borderColor: `${theme.colors.cyan}66`,
    backgroundColor: `${theme.colors.cyan}14`,
    alignSelf: "center",
  },
  icon: {
    fontSize: 21,
    lineHeight: 26,
  },
  label: {
    fontFamily: theme.fonts.bodySemi,
    fontSize: 17,
    color: theme.colors.cyan,
    letterSpacing: 0.5,
  },
});

const statusPillStyles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    borderWidth: 1.5,
    backgroundColor: "rgba(0,0,0,0.4)",
    marginTop: 12,
    alignSelf: "center",
  },
  emoji: {
    fontSize: 20,
    lineHeight: 25,
  },
  spinner: {
    transform: [{ scale: 0.8 }],
  },
  label: {
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 18,
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
});
