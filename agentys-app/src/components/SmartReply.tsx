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

/* eslint-disable react-refresh/only-export-components */
import React, { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import './SmartReply.css';

interface SmartReplyProps {
  emailId: string;
  emailClassification?: string;
  emailSubject?: string;
  emailBody?: string;
  onReplyWithText: (text: string) => void;
  onCustomPrompt: (prompt: string) => void;
}

export type EmailIntent =
  | 'meeting'
  | 'availability'
  | 'urgent'
  | 'document'
  | 'confirmation'
  | 'question'
  | 'social'
  | 'issue'
  | 'followup'
  | 'introduction'
  | 'thanks'
  | 'action';

/**
 * Detect email intent from subject + body to generate relevant suggestions.
 * Returns null for emails that don't warrant quick replies.
 */
export function detectIntent(subject: string, body: string): EmailIntent | null {
  const text = `${subject} ${body}`.toLowerCase();
  const bodyLower = body.toLowerCase();

  // Thank you / acknowledgment — rarely needs a reply
  if (/\b(merci beaucoup|merci pour|remerci|thanks? for|thank you for|félicitation)\b/.test(text) && body.length < 300) {
    return 'thanks';
  }

  // Meeting / calendar invite
  if (/\b(réunion|meeting|rendez-vous|rdv|invitation|invit[eé]|calendar|agenda|call|appel|visio|conf[ée]rence)\b/.test(text)) {
    return 'meeting';
  }

  // Availability request
  if (/\b(disponible|dispo|créneau|slot|free|available|quand est-ce que|quel jour|quelle heure)\b/.test(text)) {
    return 'availability';
  }

  // Problem / issue report
  if (/\b(problème|bug|erreur|issue|panne|ne fonctionne|ne marche|broken|doesn't work|bloqué|bloqu[ée])\b/.test(text)) {
    return 'issue';
  }

  // Deadline / urgent request
  if (/\b(urgent|deadline|échéance|asap|dès que possible|au plus vite|fin de journée|avant demain|priorit[ée])\b/.test(text)) {
    return 'urgent';
  }

  // Document / file request
  if (/\b(document|fichier|pièce jointe|attachment|envoie-moi|partager le|lien vers|pdf|facture|devis|contrat)\b/.test(text)) {
    return 'document';
  }

  // Confirmation / validation request
  if (/\b(confirmer?|valider?|validation|approuver?|accord|ok pour|d'accord|donner ton go|feu vert)\b/.test(text)) {
    return 'confirmation';
  }

  // Follow-up / status update request
  if (/\b(où en est|avancement|status|update|point sur|suivi|nouvelles|retour sur|relance)\b/.test(text)) {
    return 'followup';
  }

  // Introduction / first contact
  if (/\b(enchanté|bonjour.*je suis|je me présente|nice to meet|allow me to introduce)\b/.test(text)) {
    return 'introduction';
  }

  // Social greeting / casual check-in (short body + greeting patterns)
  // Must be before generic 'question' — "comment ça va?" is social, not a real question
  if (body.length < 200 && /\b(comment (ça|ca) va|how are you|how('s| is) it going|quoi de neuf|ça roule|ça va|what's up|how have you been|la forme)\b/i.test(text)) {
    return 'social';
  }

  // Generic question (broad — checked last)
  if (/\?/.test(bodyLower)) {
    return 'question';
  }

  // Email seems like it needs action but no specific pattern matched
  return 'action';
}

const INTENT_SUGGESTIONS: Record<EmailIntent, string[]> = {
  meeting: [
    'Perfect, noted. I will be there.',
    'Unfortunately I am not available at that time. Would it be possible to reschedule?',
  ],
  availability: [
    'I am available, feel free to suggest a time slot.',
    'I am not available this week. Next week would work better for me.',
  ],
  urgent: [
    'Noted, I will take care of it as a priority.',
    'Received. I will keep you posted as soon as it is done.',
  ],
  document: [
    'I will get that ready and send it to you today.',
    'Noted, I will look into it on my end and get back to you with the document.',
  ],
  confirmation: [
    'Confirmed on my end, we can move forward.',
    'I need to check one point before confirming, I will get back to you shortly.',
  ],
  question: [
    'Good question, let me check and I will get back to you on that.',
    'I will look into that and keep you posted.',
  ],
  issue: [
    'Thanks for the report, I will look into it.',
    'I am aware, we are working on it. I will keep you informed.',
  ],
  followup: [
    'Thanks for following up. I will take stock and get back to you with a status.',
    'It is in progress, I will keep you posted as soon as I have an update.',
  ],
  introduction: [
    'Great to meet you. Looking forward to connecting.',
  ],
  social: [
    'Doing well, thanks! How about you?',
    'Hey! All good, thanks. And on your end?',
  ],
  thanks: [],  // No reply needed
  action: [
    'Received, I will take care of it.',
    'Noted, I will get back to you.',
  ],
};

/**
 * SmartReply — Contextual quick-reply chips.
 *
 * Only shown for emails that genuinely need a response.
 * Hidden for: Noise, FYI, thank-you emails.
 * Suggestions adapt to email intent (meeting, question, document, etc.).
 */
export const SmartReply = React.memo(function SmartReply({
  emailClassification,
  emailSubject,
  emailBody,
  onReplyWithText,
  onCustomPrompt,
}: SmartReplyProps) {
  const { t } = useTranslation('common');
  const [prompt, setPrompt] = useState('');

  const { shouldShow, suggestions } = useMemo(() => {
    // Never show for Noise or FYI
    if (emailClassification === 'Noise' || emailClassification === 'FYI') {
      return { shouldShow: false, suggestions: [] };
    }

    const intent = detectIntent(emailSubject || '', emailBody || '');

    // No intent detected or thank-you email
    if (!intent || intent === 'thanks') {
      return { shouldShow: false, suggestions: [] };
    }

    const chips = INTENT_SUGGESTIONS[intent];
    if (!chips || chips.length === 0) {
      return { shouldShow: false, suggestions: [] };
    }

    return { shouldShow: true, suggestions: chips };
  }, [emailClassification, emailSubject, emailBody]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (prompt.trim()) {
      onCustomPrompt(prompt.trim());
      setPrompt('');
    }
  }, [prompt, onCustomPrompt]);

  if (!shouldShow) {
    return null;
  }

  return (
    <div className="smart-reply">
      <div className="smart-reply-chips">
        {suggestions.map((text) => (
          <button
            key={text}
            className="smart-reply-chip"
            onClick={() => onReplyWithText(text)}
          >
            {text}
          </button>
        ))}
      </div>
      <form className="smart-reply-input-form" onSubmit={handleSubmit}>
        <span className="smart-reply-sparkle">&#10022;</span>
        <input
          className="smart-reply-input"
          type="text"
          placeholder={t('ask_agentys')}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <button
          className="smart-reply-send"
          type="submit"
          disabled={!prompt.trim()}
          aria-label={t('send')}
        >
          <span className="smart-reply-arrow" aria-hidden="true">&#8593;</span>
        </button>
      </form>
    </div>
  );
});
