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
 * Plancher ambiant glissant du VAD (device 2026-08-03).
 *
 * MIN des `windowN` derniers frames de metering. Un plancher calibré une
 * fois pour toutes sur un instant calme (fenêtre de grâce) EXPIRE si
 * l'ambiant réel est plus haut (pièce vivante, voiture) — sinon le seuil
 * reste SOUS l'ambiant, tout frame compte comme « voix » et la fin-de-parole
 * par silence ne se déclenche jamais. Le min glissant remonte tout seul
 * quand les frames calmes sortent de la fenêtre, et retombe instantanément
 * sur un frame plus calme. Insensible aux transitoires forts (earcon, tap) :
 * un MIN ne retient que le plus calme.
 */
export interface FloorTracker {
  /** Ajoute un frame (dB) et renvoie le plancher courant. */
  push(db: number): number;
  /** Plancher courant, null avant tout frame. */
  floor(): number | null;
}

export function createFloorTracker(windowN: number): FloorTracker {
  const ring: number[] = [];
  return {
    push(db: number): number {
      ring.push(db);
      if (ring.length > windowN) ring.shift();
      return Math.min(...ring);
    },
    floor(): number | null {
      return ring.length === 0 ? null : Math.min(...ring);
    },
  };
}
