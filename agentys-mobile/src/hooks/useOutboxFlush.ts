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
 * useOutboxFlush — vide la file d'attente au lancement + sur foreground.
 *
 * À appeler une fois dans un layout racine. Pas de throttle complexe : un flush
 * ne tente qu'à chaque transition active, pas en boucle. Les résultats (X sent,
 * Y failed) peuvent être notifiés via un callback.
 *
 * Vide aussi le journal act-then-undo (pendingActions) : si l'app est morte
 * pendant une fenêtre d'annulation Drive Mode, les archive/delete/send que
 * l'utilisateur croit faits sont exécutés au boot suivant.
 */

import { useEffect, useRef } from "react";
import { reportError } from "../lib/errors";
import { AppState, type AppStateStatus } from "react-native";
import { flushQueue, getQueueSize, type QueuedMessage } from "../lib/sendQueue";
import { flushJournal } from "../lib/pendingActions";
import { approveDraft, archiveEmail, deleteEmail } from "../services/api";

export interface UseOutboxFlushOptions {
  /** Appelé après chaque flush qui envoie ≥ 1 message. */
  onFlushed?: (summary: { sent: number; failed: number; total: number }) => void;
  /** Détail par message envoyé, pour toast personnalisé. */
  onMessageSent?: (m: QueuedMessage) => void;
}

export function useOutboxFlush(opts: UseOutboxFlushOptions = {}): void {
  const inFlightRef = useRef(false);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const tryFlush = async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const size = await getQueueSize();
      if (size === 0) return;
      const summary = await flushQueue({
        onSuccess: (m) => optsRef.current.onMessageSent?.(m),
      });
      if (summary.sent > 0) {
        optsRef.current.onFlushed?.(summary);
      }
    } finally {
      inFlightRef.current = false;
    }
  };

  useEffect(() => {
    // Journal act-then-undo : AU BOOT UNIQUEMENT (process frais, aucun timer
    // vivant). Le rejouer sur chaque foreground exécuterait des actions dont
    // le timer in-process tourne encore → double exécution (double approve).
    flushJournal({
      archive: async (emailId) => { await archiveEmail(emailId); },
      delete: async (emailId) => { await deleteEmail(emailId); },
      send: async (draftId) => { await approveDraft(draftId); },
    }).catch((e) => reportError(e, { domain: "api", op: "outbox.replayOrphans" }, { userFacing: "silent" }));

    // Au mount (app boot ou login) — best-effort flush
    tryFlush().catch((e) => reportError(e, { domain: "api", op: "outbox.flushOnMount" }, { userFacing: "silent" }));

    const sub = AppState.addEventListener("change", (state: AppStateStatus) => {
      if (state === "active") {
        tryFlush().catch((e) => reportError(e, { domain: "api", op: "outbox.flushOnForeground" }, { userFacing: "silent" }));
      }
    });
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
