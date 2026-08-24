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

// Parité compose (2026-06-09) : le body des Drafts est édité dans le
// DraftEditor TipTap partagé avec Reply/Nouveau message. `draft_body` peut
// donc contenir du HTML (draft édité dans l'éditeur riche) OU du texte brut
// (draft IA fraîchement généré, anciens drafts). Ces helpers normalisent les
// deux formes pour les chemins LLM, envoi et détection d'état vide.

export const looksLikeHtmlBody = (s: string): boolean => /<[a-z][\s\S]*>/i.test(s);

/** Texte brut pour les chemins LLM (refine/notes) — même strip que ReplyComposer. */
export const htmlBodyToPlainText = (s: string): string =>
  looksLikeHtmlBody(s) ? s.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim() : s.trim();

/** Vide au sens utilisateur — TipTap normalise un éditeur vidé en `<p></p>`. */
export const isBodyBlank = (s: string): boolean =>
  !s
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;|&#160;/gi, '')
    .replace(/\u00a0/g, '')
    .replace(/\s+/g, '')
    .trim();

/** Corps prêt pour un envoi HTML : les paragraphes (séparés par \n\n) deviennent des <p>,
 *  les sauts simples (\n) dans un paragraphe deviennent des <br>. */
export const toHtmlEmailBody = (s: string): string => {
  if (looksLikeHtmlBody(s)) return s;
  return s
    .split(/\n{2,}/)
    .map(block => block.trim())
    .filter(block => block.length > 0)
    .map(block => `<p>${block.replace(/\n/g, '<br>')}</p>`)
    .join('');
};

const escapeSigHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Signature texte (compte/contact) → bloc HTML pour les envois côté client. */
export const signatureToHtml = (sig: string): string =>
  `<p>${sig.split('\n').map(escapeSigHtml).join('<br>')}</p>`;
