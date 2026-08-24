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
 * useWatchdog — détecteur de gel du tour de parole (Phase 1 fondations §1.6).
 *
 * Pourquoi : chaque panne du pipeline vocal (VAD sourd, transcripts vides,
 * recorder mort) s'est présentée à l'utilisateur comme « l'app est coincée »
 * — un écran qui n'avoue jamais qu'il n'avance plus. Ce watchdog surveille
 * les signaux de progrès et, après `timeoutMs` sans aucun changement dans un
 * état actif, déclare le gel : l'appelant affiche un bandeau de récupération
 * (« Je n'entends rien — touchez pour réessayer »).
 *
 * `signals` : tableau de valeurs dont TOUT changement réarme le timer
 * (état drive, transcript, isListening, état TTS…). `active=false` désarme
 * tout (états où l'attente est légitime : idle, lecture TTS, génération).
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { logEvent } from "../lib/eventLog";

export const WATCHDOG_TIMEOUT_MS = 12_000;

export interface UseWatchdogResult {
  /** true ⇔ aucun progrès depuis timeoutMs dans un état actif. */
  stalled: boolean;
  /** À appeler quand l'utilisateur relance (tap du bandeau) — efface le gel. */
  acknowledge: () => void;
}

export function useWatchdog(
  active: boolean,
  signals: readonly unknown[],
  timeoutMs: number = WATCHDOG_TIMEOUT_MS,
  onStall?: () => void,
): UseWatchdogResult {
  const [stalled, setStalled] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onStallRef = useRef(onStall);
  onStallRef.current = onStall;

  useEffect(() => {
    // Tout changement de signal = progrès → le gel éventuel est terminé.
    setStalled(false);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!active) return;

    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setStalled(true);
      logEvent("watchdog", { timeoutMs });
      try {
        onStallRef.current?.();
      } catch {
        // no-op légitime : le callback de gel ne doit pas casser le watchdog
      }
    }, timeoutMs);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, timeoutMs, ...signals]);

  const acknowledge = useCallback(() => setStalled(false), []);

  return { stalled, acknowledge };
}
