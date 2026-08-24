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
 * frenchNumbers — convertit les entiers d'un texte en toutes lettres françaises
 * avant synthèse TTS.
 *
 * #1134 : ElevenLabs prononce parfois les chiffres avec une détection de langue
 * séparée (« 66 » → « sixty-six ») même quand `language_code=fr-FR`, surtout en
 * début de phrase courte (le briefing « 66 emails. C'est parti. »). En écrivant
 * le nombre en lettres, il n'y a plus de chiffre à « normaliser » → prononciation
 * française garantie.
 *
 * Couvre 0–999 (largement suffisant pour des compteurs d'emails) ; au-delà, le
 * nombre est laissé en chiffres (cas non pertinent pour la voix).
 */

const SMALL = [
  "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
  "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
  "dix-sept", "dix-huit", "dix-neuf",
];

const TENS = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante"];

function under100(n: number): string {
  if (n < 20) return SMALL[n];
  if (n < 70) {
    const t = Math.floor(n / 10);
    const u = n % 10;
    if (u === 0) return TENS[t];
    if (u === 1) return `${TENS[t]}-et-un`;
    return `${TENS[t]}-${SMALL[u]}`;
  }
  if (n < 80) {
    // 70–79 : soixante-dix … soixante-dix-neuf (71 = soixante-et-onze)
    if (n === 71) return "soixante-et-onze";
    return `soixante-${SMALL[n - 60]}`;
  }
  // 80–99 : quatre-vingts, quatre-vingt-un … quatre-vingt-dix-neuf
  const u = n - 80;
  if (u === 0) return "quatre-vingts";
  return `quatre-vingt-${SMALL[u]}`;
}

function under1000(n: number): string {
  if (n < 100) return under100(n);
  const h = Math.floor(n / 100);
  const r = n % 100;
  const hundreds = h === 1 ? "cent" : `${SMALL[h]} cent`;
  if (r === 0) return h === 1 ? "cent" : `${SMALL[h]} cents`;
  return `${hundreds} ${under100(r)}`;
}

/** Un entier 0–999 en toutes lettres françaises. Hors plage : la chaîne du nombre. */
export function toFrenchWords(n: number): string {
  if (!Number.isInteger(n) || n < 0 || n > 999) return String(n);
  return under1000(n);
}

/** Remplace chaque entier isolé (0–999) d'un texte par sa forme en lettres. */
export function spellFrenchNumbers(text: string): string {
  return text.replace(/\d+/g, (match) => {
    const n = parseInt(match, 10);
    return n >= 0 && n <= 999 ? toFrenchWords(n) : match;
  });
}
