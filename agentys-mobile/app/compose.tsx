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
 * Compose — Nouveau message 100% vocal avec barge-in.
 *
 * Chaque phase « greeting_X » exécute TTS + mic EN PARALLÈLE via
 * speakAndListen. L'utilisateur peut interrompre l'AI à tout moment —
 * dès qu'une voix soutenue est détectée (seuil élevé pendant le TTS pour
 * filtrer l'écho du haut-parleur), le TTS s'arrête et la capture continue.
 *
 * State machine (4 phases + sending) :
 *   greeting_recipients
 *     → speakAndListen("À qui ?")
 *     → transcribe + (regex || LLM Haiku) pour chaîner recipients + body
 *     → si chaîné         → greeting_confirmation (skip body)
 *     → sinon             → greeting_body
 *     → si cancel vocal   → router.back()
 *   greeting_body
 *     → speakAndListen("Dicte ton message.")
 *     → transcribe → setBody → greeting_confirmation
 *   greeting_confirmation
 *     → speakAndListen(recap)   [recap adaptatif : court / plein / retry]
 *     → parseVoiceCommand :
 *       - send   → doSend() → router.back()
 *       - cancel → greeting_correction
 *       - correct(body|recipients) → retour au greeting correspondant
 *       - add_cc(X) → résout X → ajoute en CC → greeting_confirmation
 *       - none   → retry avec re-prompt court
 *   greeting_correction
 *     → speakAndListen("Message ou destinataires ?")
 *     → parseCorrectionTarget → greeting_body (défaut) ou greeting_recipients
 *   sending
 *     → sendNewEmailSafe (queue offline si pas de réseau)
 *     → router.back()
 *
 * Safety nets : pills `annuler` / `envoyer` toujours cliquables en secours.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Alert,
  ActivityIndicator,
  Animated,
  Dimensions,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { useTranslation } from "react-i18next";
import i18n from "../src/i18n";
import { useTts } from "../src/hooks/useTts";
import { useVoiceDictation } from "../src/hooks/useVoiceDictation";
import { useEarcons } from "../src/hooks/useEarcons";
import {
  autocompleteContacts,
  parseComposeUtterance,
  polishComposeBody,
  transcribeAudio,
  type ContactHit,
} from "../src/services/api";
import { sendNewEmailSafe } from "../src/lib/sendQueue";
import { VoiceVisualizer, type SpeakerMode } from "../src/components/VoiceVisualizer";
import { SpeakerChip } from "../src/components/SpeakerChip";
import { sampleGradient } from "../src/components/ribbons-engine";
import {
  parseVoiceCommand,
  parseCorrectionTarget,
  trySplitRecipientsAndBody,
} from "../src/lib/voice-commands";
import { theme } from "../src/theme";

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get("window");

// ── Types ───────────────────────────────────────────────────────────────────

interface Recipient {
  email: string;
  name?: string;
}

// Phases fusionnées (speak + listen en parallèle via speakAndListen)
// — plus d'étape « listening_X » séparée : le barge-in est systématique.
type Phase =
  | "greeting_recipients"
  | "greeting_body"
  | "greeting_confirmation"
  | "greeting_correction"
  | "sending"
  | "done";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// ── Helpers ─────────────────────────────────────────────────────────────────

function nameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? email;
  return local
    .split(/[._\-+]/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function initial(r: Recipient): string {
  const src = r.name || nameFromEmail(r.email);
  return (src.trim().charAt(0) || "?").toUpperCase();
}

function gradientPos(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) & 0xffffff;
  return (h % 1000) / 1000;
}

function parseRecipientCandidates(transcript: string): string[] {
  let cleaned = transcript.trim().toLowerCase();
  if (!cleaned) return [];
  cleaned = cleaned.replace(/[.!?…]+$/g, "");

  const openers = [
    /^(envoie|envoyer|écris|écrire|mail(?:er|e)?|message(?:r)?|parle|dis|contact(?:e|er))\s+/,
    /^(un\s+)?(email|mail|message|courriel|sms|mot)\s+/,
    /^(à|au|aux|pour|avec)\s+/,
  ];
  for (let i = 0; i < 4; i++) {
    const before = cleaned;
    for (const p of openers) cleaned = cleaned.replace(p, "");
    if (cleaned === before) break;
  }

  const parts = cleaned.split(/\s+et\s+|\s+puis\s+|\s+and\s+|\s*,\s*|\s*&\s*|\s+plus\s+/);
  return parts
    .map((p) => p.trim())
    .filter((p) => p.length > 0 && p.length < 80);
}

async function resolveRecipients(
  candidates: string[],
  alreadySeen: Set<string>,
): Promise<{ found: Recipient[]; notFound: string[] }> {
  const found: Recipient[] = [];
  const notFound: string[] = [];
  for (const cand of candidates) {
    try {
      const hits: ContactHit[] = await autocompleteContacts(cand, 3);
      if (!hits || hits.length === 0) {
        notFound.push(cand);
        continue;
      }
      const words = cand.split(/\s+/).filter(Boolean);
      const scored = hits
        .map((h) => {
          const hay = `${(h.name || "").toLowerCase()} ${h.email.toLowerCase()}`;
          const matches = words.filter((w) => hay.includes(w)).length;
          return { h, matches };
        })
        .sort((a, b) => b.matches - a.matches);
      const top = scored[0].h;
      if (!alreadySeen.has(top.email)) {
        found.push({
          email: top.email,
          name: top.name?.trim() || nameFromEmail(top.email),
        });
        alreadySeen.add(top.email);
      }
    } catch {
      notFound.push(cand);
    }
  }
  return { found, notFound };
}

/** Top contacts par fréquence d'interaction (q vide côté backend) — prénoms
 *  affichables pour les suggestions (demande device 2026-08-04). */
async function fetchSuggestionNames(limit = 3): Promise<string[]> {
  try {
    const hits: ContactHit[] = await autocompleteContacts("", limit);
    return (hits || [])
      .slice(0, limit)
      .map((h) => h.name?.trim() || nameFromEmail(h.email));
  } catch {
    return []; // best-effort : pas de suggestions ≠ flux bloqué
  }
}

function deriveSubject(body: string): string {
  const firstLine = body.split(/\n/)[0].trim();
  if (!firstLine) return i18n.t("compose:subjectDefault");
  if (firstLine.length <= 60) return firstLine;
  const cut = firstLine.slice(0, 60);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > 30 ? cut.slice(0, lastSpace) : cut) + "…";
}

function formatRecapRecipients(to: Recipient, cc: Recipient[]): string {
  const names = [to, ...cc].map((r) => r.name || nameFromEmail(r.email));
  const and = i18n.t("common:and");
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]}${and}${names[1]}`;
  return names.slice(0, -1).join(", ") + and + names[names.length - 1];
}

// ── Screen ──────────────────────────────────────────────────────────────────

export default function ComposeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const tts = useTts();
  const dictation = useVoiceDictation();
  const earcons = useEarcons();
  const { t } = useTranslation(["compose", "common"]);

  const [phase, setPhase] = useState<Phase>("greeting_recipients");
  /** Ré-entrée dans la MÊME phase (retry no_voice) : setPhase(même valeur)
   *  ne re-rend pas → l'effet [phase] ne se relançait pas → micro jamais
   *  ré-armé (device 2026-08-03). Le nonce force un tour supplémentaire. */
  const [phaseNonce, setPhaseNonce] = useState(0);
  const [to, setTo] = useState<Recipient | null>(null);
  const [cc, setCc] = useState<Recipient[]>([]);
  const [body, setBody] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false); // transcription / resolution

  // Compteurs de retry par étape (évite les boucles infinies si VAD rate)
  const retryRef = useRef({ recipients: 0, body: 0, confirmation: 0 });

  // Niveau audio réactif pour les ribbons
  const audioLevel = useRef(new Animated.Value(0)).current;
  const onLevel = useCallback(
    (v: number) => {
      audioLevel.setValue(v);
    },
    [audioLevel],
  );

  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const speakAndWait = useCallback(
    (text: string): Promise<void> =>
      new Promise((resolve) => {
        tts.speak(text, resolve);
      }),
    [tts],
  );

  /** Parle PUIS écoute — séquentiel, sans AEC (#1134 règle 4, aligné drive).
   *  L'ancien barge-in TTS+mic exigeait la session voiceChat (AEC hardware),
   *  qui écrase le gain du micro : device 2026-08-03, « Alexandre » capté à
   *  -25 dB sous le seuil anti-écho de -28 → no_voice systématique. Les
   *  prompts compose sont courts (« À qui ? ») — le barge-in n'apportait
   *  rien. TTS d'abord, puis écoute batch avec le seuil ADAPTATIF du hook. */
  const speakAndListen = useCallback(
    async (
      text: string,
      listenOpts: Parameters<typeof dictation.listen>[0] = {},
    ) => {
      // Le filet est annulé dès que la course est tranchée : un `setTimeout`
      // laissé courir survit 10 s au démontage de l'écran (worker Jest tenu en
      // vie après teardown, et en prod un handle inutile par prompt parlé).
      let guardId: ReturnType<typeof setTimeout> | undefined;
      await Promise.race([
        new Promise<void>((resolve) => { tts.speak(text, resolve); }),
        // Filet anti-blocage : un TTS qui ne rend jamais son onDone ne doit
        // pas geler le flux (le mic s'ouvre quand même).
        new Promise<void>((r) => { guardId = setTimeout(r, 10_000); }),
      ]).finally(() => clearTimeout(guardId));
      // Signal de tour (device 2026-08-03) : sans earcon après la question,
      // impossible de savoir quand le micro s'ouvre — même convention que le
      // drive (« à toi »).
      earcons.play("turn");
      // Device 2026-08-04 : l'earcon était JOUÉ (trace loaded:true) mais
      // INAUDIBLE — l'ouverture du micro 3 ms plus tard rebascule la session
      // audio en mode enregistrement et coupe le son à peine parti. (Le drive
      // n'a pas ce problème : sa session voiceChat reste active entre les
      // écoutes.) 250 ms lui laissent le temps de sonner.
      await new Promise<void>((r) => setTimeout(r, 250));
      return dictation.listen({
        useVoiceChat: false,
        // Calibration du plancher ambiant (device 2026-08-03) : sans grace,
        // le seuil reste au -42 fixe — dans un environnement à -26 dB, le VAD
        // voit de la « voix » en continu et la fin-de-parole par silence ne
        // se déclenche JAMAIS (l'app ne rend pas la main). Même valeur que
        // le drive.
        graceMs: 600,
        ...listenOpts,
        onLevel,
      });
    },
    [tts, dictation, earcons, onLevel],
  );

  // Earcon d'ouverture (device 2026-08-03) : accuse réception du lancement
  // du compose AVANT la première question TTS (~1 s de latence réseau) —
  // sans lui, « au tout début » l'écran est muet. play() attend le
  // préchargement des clips à froid (useEarcons).
  useEffect(() => {
    earcons.play("tick");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup au démontage
  useEffect(() => {
    return () => {
      tts.stop().catch(() => {}); // no-op légitime : déjà à l'arrêt
      dictation.cancel().catch(() => {}); // no-op légitime : capture déjà terminée
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── State machine ─────────────────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    const current = phase;

    const isStill = (p: Phase) => active && phaseRef.current === p;

    (async () => {
      try {
        // ═══════════════════════════════════════════════════════════════
        // greeting_recipients — TTS + mic en parallèle (barge-in activé)
        // ═══════════════════════════════════════════════════════════════
        if (current === "greeting_recipients") {
          setHint(null);
          // Suggestions de contacts fréquents (demande device 2026-08-04) —
          // hint VISUEL pendant que la question est posée, fire-and-forget.
          fetchSuggestionNames().then((names) => {
            if (names.length > 0 && isStill("greeting_recipients")) {
              setHint(t("suggestContacts", { names: names.join(", ") }));
            }
          }).catch(() => {}); // no-op légitime : suggestions best-effort
          const res = await speakAndListen(
            to ? t("askNewRecipients") : t("askRecipients"),
          );
          if (!isStill("greeting_recipients")) return;

          if (res.kind === "cancelled") return;
          if (res.kind === "no_voice") {
            await handleNoVoice("recipients");
            return;
          }
          if (res.kind === "error") {
            setHint(t("micUnavailableHint"));
            return;
          }

          setIsBusy(true);
          try {
            const { text } = await transcribeAudio(res.uri);
            const clean = (text || "").trim();
            if (!clean) {
              await handleNoVoice("recipients");
              return;
            }
            const cmd = parseVoiceCommand(clean);
            if (cmd.kind === "cancel") {
              await speakAndWait(t("cancelling"));
              router.back();
              return;
            }

            // Chaînage : regex rapide d'abord, LLM Haiku en fallback
            let chained = trySplitRecipientsAndBody(clean);
            let recipientText = chained ? chained.recipients : clean;
            let candidates = parseRecipientCandidates(recipientText);

            if (!chained && candidates.length === 0) {
              try {
                const llm = await parseComposeUtterance(clean);
                if (llm.recipients.length > 0) {
                  candidates = llm.recipients.map((r) => r.toLowerCase());
                  if (llm.body) {
                    chained = { recipients: llm.recipients.join(", "), body: llm.body };
                  }
                }
              } catch {
                // silent fallback
              }
            }

            if (candidates.length === 0) {
              retryRef.current.recipients++;
              await speakAndWait(t("noRecipients"));
              if (retryRef.current.recipients >= 2) {
                setHint(t("blockedHint"));
              }
              // Dead-end setPhase(valeur courante) → nonce (cf. phaseNonce).
              if (isStill("greeting_recipients")) setPhaseNonce((n) => n + 1);
              return;
            }

            const seen = new Set<string>();
            if (to) seen.add(to.email);
            cc.forEach((r) => seen.add(r.email));

            const { found, notFound } = await resolveRecipients(candidates, seen);
            if (found.length === 0) {
              // Demande device 2026-08-04 : sur introuvable, PROPOSER des
              // contacts connus (top fréquence) — parlé + hint visuel.
              const suggestions = await fetchSuggestionNames();
              if (suggestions.length > 0) {
                setHint(t("suggestContacts", { names: suggestions.join(", ") }));
                await speakAndWait(t("noContactsForWithSuggestions", {
                  names: notFound.join(", ") || "…",
                  suggestions: suggestions.join(", "),
                }));
              } else {
                await speakAndWait(
                  notFound.length > 0
                    ? t("noContactsFor", { names: notFound.join(", ") })
                    : t("noContactsFound"),
                );
              }
              retryRef.current.recipients++;
              if (retryRef.current.recipients >= 2) {
                setHint(t("blockedHint"));
              }
              // Dead-end setPhase(valeur courante) → nonce (cf. phaseNonce).
              if (isStill("greeting_recipients")) setPhaseNonce((n) => n + 1);
              return;
            }

            retryRef.current.recipients = 0;
            const [primary, ...rest] = found;
            setTo(primary);
            setCc(rest);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});

            setHint(notFound.length > 0 ? t("notRecognized", { names: notFound.join(", ") }) : null);

            if (chained) {
              // Mise au propre du corps dicté (ponctuation, tournures) —
              // best-effort, renvoie le brut en cas d'erreur.
              setBody(await polishComposeBody(chained.body));
              retryRef.current.body = 0;
              if (isStill("greeting_recipients")) setPhase("greeting_confirmation");
            } else {
              if (isStill("greeting_recipients")) setPhase("greeting_body");
            }
          } finally {
            setIsBusy(false);
          }
        }

        // ═══════════════════════════════════════════════════════════════
        // greeting_body — dictée du corps du message
        // ═══════════════════════════════════════════════════════════════
        else if (current === "greeting_body") {
          setHint(null);
          const res = await speakAndListen(t("askBody"), {
            silenceMs: 2200,       // plus de pause tolérée pendant un body
            maxDurationMs: 60_000, // body peut être long
          });
          if (!isStill("greeting_body")) return;

          if (res.kind === "cancelled") return;
          if (res.kind === "no_voice") {
            await handleNoVoice("body");
            return;
          }
          if (res.kind === "error") {
            setHint(t("micUnavailable"));
            return;
          }

          setIsBusy(true);
          try {
            const { text } = await transcribeAudio(res.uri);
            const clean = (text || "").trim();
            if (!clean) {
              await handleNoVoice("body");
              return;
            }
            const cmd = parseVoiceCommand(clean);
            if (cmd.kind === "cancel") {
              await speakAndWait(t("cancelling"));
              router.back();
              return;
            }
            retryRef.current.body = 0;
            // Mise au propre du corps dicté (device 2026-08-03 : « coucou
            // comment ça va » partait verbatim) — best-effort.
            setBody(await polishComposeBody(clean));
            setHint(null);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
            if (isStill("greeting_body")) setPhase("greeting_confirmation");
          } finally {
            setIsBusy(false);
          }
        }

        // ═══════════════════════════════════════════════════════════════
        // greeting_confirmation — recap + attente oui/non/correct
        // ═══════════════════════════════════════════════════════════════
        else if (current === "greeting_confirmation") {
          if (!to || !body) {
            setPhase(to ? "greeting_body" : "greeting_recipients");
            return;
          }
          setHint(null);
          // Recap adaptatif : abrégé en retry, court si body ≤ 40 et 1 dest,
          // complet sinon. Barge-in permet d'interrompre dès le début.
          const isRetry = retryRef.current.confirmation > 0;
          const isShort = cc.length === 0 && body.length <= 40;
          const primaryName = to.name || nameFromEmail(to.email);
          const recap = isRetry
            ? t("recapRetry")
            : isShort
              // Ponctuation finale strippée : le gabarit ajoute déjà « . » —
              // sinon « …Agentys.. J'envoie ? » (double point, vu trace).
              ? t("recapShort", { name: primaryName, body: body.replace(/[.!…]+$/, "") })
              : t("recapFull", { recipients: formatRecapRecipients(to, cc), body: body.replace(/[.!…]+$/, "") });

          const res = await speakAndListen(recap, {
            silenceMs: 1400,
            maxDurationMs: 10_000,
            noVoiceTimeoutMs: 7_000,
          });
          if (!isStill("greeting_confirmation")) return;

          if (res.kind === "cancelled") return;
          if (res.kind === "no_voice") {
            retryRef.current.confirmation++;
            if (retryRef.current.confirmation >= 2) {
              setHint(t("recapYesNoHint"));
            }
            // Même dead-end que handleNoVoice : setPhase(valeur courante) ne
            // relance pas l'effet — bump du nonce pour ré-armer le micro.
            if (isStill("greeting_confirmation")) setPhaseNonce((n) => n + 1);
            return;
          }
          if (res.kind === "error") {
            setHint(t("micUnavailable"));
            return;
          }

          setIsBusy(true);
          try {
            const { text } = await transcribeAudio(res.uri);
            const clean = (text || "").trim();
            const cmd = parseVoiceCommand(clean);

            if (cmd.kind === "send") {
              retryRef.current.confirmation = 0;
              if (isStill("greeting_confirmation")) await doSend();
              return;
            }
            if (cmd.kind === "cancel") {
              retryRef.current.confirmation = 0;
              if (isStill("greeting_confirmation")) setPhase("greeting_correction");
              return;
            }
            if (cmd.kind === "correct") {
              if (cmd.target === "recipients") {
                setTo(null);
                setCc([]);
                if (isStill("greeting_confirmation")) setPhase("greeting_recipients");
              } else {
                if (isStill("greeting_confirmation")) setPhase("greeting_body");
              }
              return;
            }
            if (cmd.kind === "add_cc") {
              const { found } = await resolveRecipients(
                [cmd.payload],
                new Set([to?.email ?? "", ...cc.map((r) => r.email)]),
              );
              if (found.length > 0) {
                setCc((prev) => [...prev, ...found]);
                Haptics.selectionAsync().catch(() => {});
                if (isStill("greeting_confirmation")) setPhase("greeting_confirmation");
              } else {
                await speakAndWait(t("contactNotFoundFor", { name: cmd.payload }));
                if (isStill("greeting_confirmation")) setPhase("greeting_confirmation");
              }
              return;
            }

            // cmd.kind === "none" → on boucle en re-demandant
            retryRef.current.confirmation++;
            if (retryRef.current.confirmation >= 2) {
              setHint(t("recapEchoHint", { clean }));
            }
            if (isStill("greeting_confirmation")) setPhase("greeting_confirmation");
          } finally {
            setIsBusy(false);
          }
        }

        // ═══════════════════════════════════════════════════════════════
        // greeting_correction — « on change quoi ? »
        // ═══════════════════════════════════════════════════════════════
        else if (current === "greeting_correction") {
          const res = await speakAndListen(
            t("askCorrection"),
            { silenceMs: 1400, maxDurationMs: 8_000, noVoiceTimeoutMs: 6_000 },
          );
          if (!isStill("greeting_correction")) return;

          if (res.kind === "cancelled") return;
          if (res.kind === "no_voice" || res.kind === "error") {
            // Défaut : reprendre le body (le plus probable)
            if (isStill("greeting_correction")) setPhase("greeting_body");
            return;
          }

          setIsBusy(true);
          try {
            const { text } = await transcribeAudio(res.uri);
            const clean = (text || "").trim();
            const target = parseCorrectionTarget(clean);
            if (target === "recipients") {
              setTo(null);
              setCc([]);
              if (isStill("greeting_correction")) setPhase("greeting_recipients");
            } else {
              if (isStill("greeting_correction")) setPhase("greeting_body");
            }
          } finally {
            setIsBusy(false);
          }
        }
      } catch (err: any) {
        console.warn(`[compose] phase ${current} error:`, err?.message || err);
        // F07 (MEDIUM): if the user navigated away (router.back) between the
        // inner await and this catch, the component is unmounted. Skip ALL
        // side effects — including setIsBusy(false) — to avoid the React
        // setState-after-unmount warning. The new mount (if any) starts with
        // a fresh state machine anyway.
        if (!active) return;
        // Défensif : l'inner finally gère déjà, mais si l'erreur survient avant,
        // l'UI resterait bloquée en "thinking" silencieusement.
        setIsBusy(false);
        // Composer vocal = pas d'écran lu → on PARLE l'erreur, sinon l'user attend
        // indéfiniment. Hint visible en plus pour les sourds ou sorties TTS mutées.
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
        setHint(t("transcribeError"));
        await speakAndWait(t("transcribeError"));
      }
    })();

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, phaseNonce]);

  // ── Handlers auxiliaires ──────────────────────────────────────────────────
  const handleNoVoice = async (kind: "recipients" | "body") => {
    retryRef.current[kind]++;
    // Après 2 essais ratés, on affiche un escape hint mais on CONTINUE
    if (retryRef.current[kind] >= 2) {
      setHint(t("noVoiceHint"));
    }
    await speakAndWait(t("noVoice"));
    const greetingPhase: Phase =
      kind === "recipients" ? "greeting_recipients" : "greeting_body";
    if (phaseRef.current === greetingPhase) {
      // Déjà dans la phase cible : bump du nonce (setPhase même valeur = no-op
      // React, l'effet ne se relancerait pas — voir déclaration de phaseNonce).
      setPhaseNonce((n) => n + 1);
    }
  };

  const doSend = async () => {
    if (!to || !body) return;
    setPhase("sending");
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    try {
      const res = await sendNewEmailSafe({
        to: to.email,
        subject: deriveSubject(body),
        body,
        cc: cc.length > 0 ? cc.map((r) => r.email).join(", ") : undefined,
      });
      if (!res.success) throw new Error(res.error || t("sendFailedGeneric"));
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      // Différence UX : envoyé direct vs mis en file d'attente offline
      if (res.queued) {
        await speakAndWait(t("queuedOffline"));
      } else {
        await speakAndWait(t("sent"));
      }
      router.back();
    } catch (err: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      Alert.alert(t("sendFailedTitle"), err?.message || t("sendFailedDetail"));
      setPhase("greeting_confirmation");
    }
  };

  // ── Safety net : boutons annuler / envoyer ────────────────────────────────
  const canSend =
    !!to && EMAIL_RE.test(to.email) && body.trim().length > 0 && phase !== "sending";

  const handleBack = async () => {
    await tts.stop();
    await dictation.cancel();
    if (body.trim() || to) {
      Alert.alert(t("abandonTitle"), t("abandonDetail"), [
        { text: t("common:continue"), style: "cancel" },
        { text: t("abandonButton"), style: "destructive", onPress: () => router.back() },
      ]);
      return;
    }
    router.back();
  };

  const handleForceSend = async () => {
    if (!canSend) return;
    await tts.stop();
    await dictation.cancel();
    await doSend();
  };

  // ── Dérivations UI ────────────────────────────────────────────────────────
  const isListening = dictation.state === "listening" || dictation.state === "capturing";
  const isSpeakingTts = tts.state === "speaking";
  const isCapturing = dictation.state === "capturing";

  const vizMode: SpeakerMode = isListening ? "user" : "ai";

  const chipMode: SpeakerMode =
    isSpeakingTts ? "ai"
    : isListening ? "user"
    : "idle";

  const chipLabels = useMemo(() => {
    if (phase === "sending") return { sublabel: t("chip.sending"), glyph: "…" };
    if (isBusy) return { sublabel: t("chip.thinking"), glyph: "…" };
    if (isSpeakingTts) return { sublabel: t("chip.speaking"), glyph: "✦" };
    switch (phase) {
      case "greeting_recipients":
        return {
          sublabel: isCapturing ? t("chip.listening") : t("chip.sayNames"),
          glyph: isCapturing ? "●" : "…",
        };
      case "greeting_body":
        return {
          sublabel: isCapturing ? t("chip.listening") : t("chip.sayMessage"),
          glyph: isCapturing ? "●" : "…",
        };
      case "greeting_confirmation":
        return {
          sublabel: t("chip.yesOrNo"),
          glyph: isCapturing ? "●" : "?",
        };
      case "greeting_correction":
        return {
          sublabel: t("chip.messageOrNames"),
          glyph: isCapturing ? "●" : "?",
        };
      default:
        return { sublabel: t("chip.ready"), glyph: "✓" };
    }
  }, [phase, isBusy, isSpeakingTts, isCapturing, t]);

  return (
    <View style={styles.root}>
      {/* Ribbons full-bleed, pilotés par le mic pendant listening_* */}
      <VoiceVisualizer
        mode={vizMode}
        width={SCREEN_W}
        height={SCREEN_H}
        centerY={SCREEN_H * 0.78}
        intensity={isListening ? 1.15 : isBusy ? 0.9 : 0.65}
        speed={isListening ? 1.1 : isBusy ? 1 : 0.85}
        audioLevel={isListening ? audioLevel : undefined}
      />

      <View pointerEvents="none" style={styles.topScrim} />

      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + 12 }]}>
        <Pressable
          onPress={handleBack}
          hitSlop={12}
          style={styles.backBtn}
          disabled={phase === "sending"}
          accessibilityRole="button"
          accessibilityLabel={t("common:back")}
          accessibilityState={{ disabled: phase === "sending" }}
        >
          <Ionicons
            name="chevron-back"
            size={26}
            color={phase === "sending" ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.82)"}
          />
        </Pressable>
      </View>

      {/* Cluster destinataires */}
      <View style={styles.recipientCluster} pointerEvents="box-none">
        <PrimaryRecipientPill recipient={to} dimmed={phase === "sending"} />
        {cc.length > 0 && (
          <View style={styles.ccRow} pointerEvents="box-none">
            {cc.map((r, i) => (
              <View key={r.email} style={styles.ccItem}>
                <CcChip recipient={r} />
                {i < cc.length - 1 && <Text style={styles.ccSep}>·</Text>}
              </View>
            ))}
          </View>
        )}
      </View>

      {/* Titre */}
      <View style={styles.titleBlock} pointerEvents="none">
        <Text style={styles.title}>{t("title")}</Text>
      </View>

      {/* SpeakerChip — pur indicateur (no onPress) */}
      <View style={styles.speakerWrap} pointerEvents="box-none">
        <SpeakerChip
          mode={chipMode}
          aiName={t("speaker.ai")}
          userName={t("speaker.user")}
          idleLabel={t("speaker.idle")}
          userGlyph={chipLabels.glyph}
          idleGlyph={chipLabels.glyph}
          activeSublabel={chipLabels.sublabel}
          idleSublabel={chipLabels.sublabel}
          discStyle={chipMode === "user" ? "outlined" : "filled"}
          accentOverride={chipMode === "user" ? "#3DE3C7" : undefined}
        />

        {isBusy && (
          <View style={styles.spinnerRow}>
            <ActivityIndicator size="small" color="#3DE3C7" />
            <Text style={styles.hintMuted}>{t("chip.transcribing")}</Text>
          </View>
        )}

        {hint && !isBusy && (
          <Text style={styles.hintWarn} numberOfLines={3}>
            {hint}
          </Text>
        )}

        {(phase === "greeting_confirmation" || phase === "greeting_correction") &&
          !!body && (
            <Text style={styles.draftPreview} numberOfLines={3}>
              « {body} »
            </Text>
          )}
      </View>

      {/* Boutons filet de sécurité */}
      <View
        style={[styles.bottomBar, { paddingBottom: insets.bottom + 28 }]}
        pointerEvents="box-none"
      >
        <Pressable
          onPress={handleBack}
          style={({ pressed }) => [styles.pillBtn, pressed && styles.pillBtnPressed]}
          disabled={phase === "sending"}
          accessibilityRole="button"
          accessibilityLabel={t("cancelPill")}
          accessibilityState={{ disabled: phase === "sending" }}
        >
          <Text style={styles.pillLabel}>{t("cancelPill")}</Text>
        </Pressable>

        <Pressable
          onPress={handleForceSend}
          disabled={!canSend}
          accessibilityRole="button"
          accessibilityLabel={t("common:send")}
          accessibilityState={{ disabled: !canSend, busy: phase === "sending" }}
          style={({ pressed }) => [
            styles.pillBtn,
            !canSend && styles.pillBtnDisabled,
            pressed && canSend && styles.pillBtnPressed,
          ]}
        >
          {phase === "sending" ? (
            <ActivityIndicator size="small" color={PILL_GOLD} />
          ) : (
            <Text style={[styles.pillLabel, !canSend && styles.pillLabelDisabled]}>
              {t("common:send")}
            </Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

// ── Chips ───────────────────────────────────────────────────────────────────

function PrimaryRecipientPill({
  recipient,
  dimmed,
}: {
  recipient: Recipient | null;
  dimmed?: boolean;
}) {
  const { t } = useTranslation("compose");
  const isEmpty = !recipient;
  const pos = useMemo(
    () => (recipient ? gradientPos(recipient.email) : 0.25),
    [recipient],
  );
  const colorA = sampleGradient(Math.max(0, pos - 0.12));
  const colorB = sampleGradient(Math.min(1, pos + 0.18));
  const label = recipient ? recipient.name || nameFromEmail(recipient.email) : t("placeholderTo");

  return (
    <View
      style={[pillStyles.pill, isEmpty && pillStyles.pillEmpty, dimmed && { opacity: 0.5 }]}
    >
      <View style={[pillStyles.avatar, { backgroundColor: colorA }]}>
        <View style={[pillStyles.avatarGradB, { backgroundColor: colorB }]} />
        <Text style={pillStyles.avatarGlyph}>
          {isEmpty ? "?" : initial(recipient!)}
        </Text>
      </View>
      <Text style={pillStyles.name} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

function CcChip({ recipient }: { recipient: Recipient }) {
  const pos = gradientPos(recipient.email);
  const bg = sampleGradient(pos);
  const label = recipient.name || nameFromEmail(recipient.email);
  return (
    <View style={ccStyles.wrap}>
      <View style={[ccStyles.mini, { backgroundColor: bg }]}>
        <Text style={ccStyles.miniGlyph}>{initial(recipient)}</Text>
      </View>
      <Text style={ccStyles.name}>{label}</Text>
    </View>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────

const PILL_GOLD = "rgb(240, 220, 140)";
const PILL_BORDER = "rgba(240, 220, 140, 0.85)";

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#0a0a0c",
    overflow: "hidden",
  },
  topScrim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 220,
    backgroundColor: "rgba(10,10,12,0.55)",
    zIndex: 1,
  },
  header: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    zIndex: 3,
  },
  backBtn: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  recipientCluster: {
    position: "absolute",
    top: "12%",
    left: 0,
    right: 0,
    alignItems: "center",
    gap: 8,
    zIndex: 3,
  },
  ccRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    justifyContent: "center",
    maxWidth: SCREEN_W - 48,
  },
  ccItem: {
    flexDirection: "row",
    alignItems: "center",
  },
  ccSep: {
    color: "rgba(255,255,255,0.35)",
    fontFamily: theme.fonts.body,
    fontSize: 11,
    marginHorizontal: 6,
  },
  titleBlock: {
    position: "absolute",
    top: "23%",
    left: 0,
    right: 0,
    alignItems: "center",
    zIndex: 2,
  },
  title: {
    color: "#ffffff",
    fontSize: 32,
    fontFamily: theme.fonts.bodyBold,
    fontWeight: "700",
    letterSpacing: -0.3,
  },
  speakerWrap: {
    position: "absolute",
    top: "38%",
    left: 0,
    right: 0,
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 24,
    zIndex: 3,
  },
  spinnerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  hintMuted: {
    color: "rgba(255,255,255,0.55)",
    fontFamily: theme.fonts.body,
    fontSize: 12,
    textAlign: "center",
  },
  hintWarn: {
    color: "rgba(251,191,36,0.9)",
    fontFamily: theme.fonts.body,
    fontSize: 12,
    textAlign: "center",
    lineHeight: 17,
    maxWidth: SCREEN_W - 64,
  },
  draftPreview: {
    marginTop: 4,
    maxWidth: SCREEN_W - 72,
    color: "rgba(255,255,255,0.82)",
    fontFamily: theme.fonts.body,
    fontSize: 13,
    fontStyle: "italic",
    textAlign: "center",
    lineHeight: 19,
  },
  bottomBar: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "center",
    gap: 12,
    zIndex: 3,
  },
  pillBtn: {
    minWidth: 120,
    paddingVertical: 11,
    paddingHorizontal: 22,
    borderRadius: 999,
    borderWidth: 1.5,
    borderColor: PILL_BORDER,
    backgroundColor: "rgba(0,0,0,0.3)",
    alignItems: "center",
    justifyContent: "center",
  },
  pillBtnPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.97 }],
  },
  pillBtnDisabled: {
    borderColor: "rgba(240,220,140,0.3)",
    opacity: 0.5,
  },
  pillLabel: {
    color: PILL_GOLD,
    fontFamily: theme.fonts.bodyMedium,
    fontSize: 14.5,
    fontWeight: "500",
  },
  pillLabelDisabled: {
    color: "rgba(240,220,140,0.4)",
  },
});

const pillStyles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingLeft: 6,
    paddingRight: 14,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.06)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.14)",
  },
  pillEmpty: {
    borderStyle: "dashed",
    borderColor: "rgba(255,255,255,0.28)",
  },
  avatar: {
    width: 30,
    height: 30,
    borderRadius: 15,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarGradB: {
    position: "absolute",
    right: -6,
    bottom: -6,
    width: 24,
    height: 24,
    borderRadius: 12,
    opacity: 0.85,
  },
  avatarGlyph: {
    color: "#ffffff",
    fontFamily: theme.fonts.bodyBold,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.2,
    zIndex: 1,
  },
  name: {
    color: "#ffffff",
    fontFamily: theme.fonts.bodySemi,
    fontSize: 14,
    fontWeight: "600",
    maxWidth: 200,
  },
});

const ccStyles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  mini: {
    width: 16,
    height: 16,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  miniGlyph: {
    color: "#0a0a0c",
    fontFamily: theme.fonts.bodyBold,
    fontSize: 9,
    fontWeight: "700",
  },
  name: {
    color: "rgba(255,255,255,0.65)",
    fontFamily: theme.fonts.body,
    fontSize: 12,
  },
});
