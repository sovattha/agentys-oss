/**
 * voice-commands — parseur d'intentions vocales pour l'écran compose.
 *
 * Pragmatique : leading-word match + guard contre la négation.
 *   "oui envoie"          → send
 *   "non laisse tomber"   → cancel
 *   "corrige le message"  → correct { target: "body" }
 *   "ajoute Marie"        → add_cc("Marie")
 *   "merci bonne soirée"  → none
 */

export type VoiceIntent =
  | { kind: "send" }
  | { kind: "cancel" }
  | { kind: "correct"; target?: "body" | "recipients" }
  | { kind: "add_cc"; payload: string }
  | { kind: "none" };

const PUNCT_END = /[.!?…,;:]+$/;

const SEND_WORDS =
  /^(oui|yes|ok(ay)?|envoie[zr]?|envoie-le|envoies?|valide[z]?|confirme[z]?|parfait|go|vas-y|let'?s\s+go|send(\s+it)?|c'est\s+(bon|parfait)|allez)\b/;

const CANCEL_WORDS =
  /^(non|no|annule[zr]?|arrête|arrete|laisse\s+tomber|abandonne|oublie|oublie\s+ça|oublie\s+ca|cancel|stop)\b/;

const NEGATION_ANY = /\b(ne\s+pas|ne\s+l'envoie|pas\s+(encore|maintenant)|surtout\s+pas|jamais|nope)\b/;

const CORRECT_BODY =
  /\b(corrig|refais|recommenc|redis|redict|nouveau|refait)\w*\b.*\b(message|texte|contenu|mail|email|corps)\b|\b(message|texte|contenu|mail|email|corps)\b.*\b(corrig|refais|recommenc|redis|redict|nouveau|refait)\w*\b/;

const CORRECT_RECIPIENTS =
  /\b(corrig|refais|recommenc|change|changé|chang|reprend)\w*\b.*\b(destinataire|nom|personne|contact|cc|copie|à\s+qui)\b|\b(destinataire|nom|personne|contact|cc|copie|à\s+qui)\b.*\b(corrig|refais|recommenc|change|chang|reprend)\w*\b/;

const CORRECT_BARE =
  /^(corrige|refais|recommence|redis|attends|redicte|reprend|reprends|change)\s*$/;

const ADD_CC =
  /^(?:ajoute|rajoute|met[stz]?(?:\s+aussi)?|inclus|mettez?)\s+(?:aussi\s+)?(.+?)(?:\s+(?:en\s+)?(?:cc|copie))?$/;

export function parseVoiceCommand(raw: string): VoiceIntent {
  const t = (raw || "").toLowerCase().trim().replace(PUNCT_END, "").trim();
  if (!t) return { kind: "none" };

  const isNegated = NEGATION_ANY.test(t);

  if (SEND_WORDS.test(t) && !isNegated) return { kind: "send" };
  if (CANCEL_WORDS.test(t) || isNegated) return { kind: "cancel" };

  if (CORRECT_BODY.test(t)) return { kind: "correct", target: "body" };
  if (CORRECT_RECIPIENTS.test(t)) return { kind: "correct", target: "recipients" };
  if (CORRECT_BARE.test(t)) return { kind: "correct" };

  const addMatch = t.match(ADD_CC);
  if (addMatch && addMatch[1]) {
    const payload = addMatch[1].trim();
    if (payload.length > 0 && payload.length < 80) {
      return { kind: "add_cc", payload };
    }
  }

  return { kind: "none" };
}

/** Pour corriger un target après un "non" : parse "message" vs "destinataires". */
export function parseCorrectionTarget(raw: string): "body" | "recipients" | null {
  const t = (raw || "").toLowerCase();
  if (!t) return null;
  if (/\b(destinataire|nom|personne|contact|cc|copie|qui)\b/.test(t)) return "recipients";
  if (/\b(message|texte|contenu|mail|email|corps|body)\b/.test(t)) return "body";
  return null;
}

/** Détecte une phrase chaînée « destinataires + corps » en un seul utterance.
 *  Exemples qui matchent :
 *    "à Paul dis-lui que je serai en retard"
 *    "à Marie et Paul : je serai en retard"
 *    "pour Léa, message je rentre ce soir"
 *    "envoie à Paul — à demain"
 *  Retourne null si aucun séparateur détecté → fallback au flow 2-étapes.
 */
export function trySplitRecipientsAndBody(
  raw: string,
): { recipients: string; body: string } | null {
  const t = (raw || "").trim();
  if (t.length < 10) return null;

  // Séparateurs ordonnés du plus spécifique au plus générique.
  // Captures case-insensitive. match.index doit être > 2 pour éviter
  // de séparer avant même d'avoir entendu un nom.
  const SEPARATORS: RegExp[] = [
    /\bdis[-\s]?(?:lui|leur)\s+(?:que\s+|de\s+)?/i,
    /\bpour\s+(?:lui|leur)\s+dire\s+(?:que\s+)?/i,
    /,\s+(?:dis|message)\b[\s:]+/i,
    /\bmessage\s*:\s+/i,
    /\s—\s+/,          // em-dash
    /\s–\s+/,          // en-dash
    /\s:\s+/,          // colon avec espaces
  ];

  for (const sep of SEPARATORS) {
    const match = t.match(sep);
    if (match && match.index !== undefined && match.index > 2) {
      const recipients = t.slice(0, match.index).trim();
      const body = t.slice(match.index + match[0].length).trim();
      if (recipients.length >= 2 && body.length >= 3) {
        return { recipients, body };
      }
    }
  }
  return null;
}
