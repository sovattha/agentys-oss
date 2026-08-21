/**
 * driveCommands — détection de commandes vocales du Drive Mode (FR + EN).
 *
 * Fonctions PURES extraites de useDriveMode (#1124, étape 1) : vocabulaire,
 * normalisation Whisper (ponctuation/casse), détection tail-command en
 * barge-in, fin de dictée, et disposition d'envoi explicite.
 *
 * NB : distinct de voice-commands.ts qui parse les intentions du composer
 * (send/cancel/correct/add_cc) — vocabulaires et écrans différents.
 */

// ---------------------------------------------------------------------------
// Commandes vocales reconnues (FR + EN)
// ---------------------------------------------------------------------------
export const COMMANDS = {
  // « répandre » : confusion Deepgram fréquente de « répondre » ([ʁepɔ̃dʁ] ≈
  // [ʁepɑ̃dʁ] avec bruit de route) — retour device 2026-07, user coincé.
  // « réponds »/« répondez » : impératifs naturels au volant.
  REPLY:       ["répondre", "répandre", "réponds", "répondez", "réponse", "reply"],
  REPLY_ALL:   ["répondre à tous", "répondre a tous", "reply all", "reply to all"],
  FORWARD:     ["transférer", "transferer", "forward"],
  NEXT:        ["suivant", "passer", "next", "skip", "passe"],
  PREVIOUS:    ["précédent", "precedent", "previous", "retour", "back"],
  ARCHIVE:     ["archiver", "archive", "archives"],
  DELETE:      ["supprimer", "supprime", "supp", "delete", "deletes",
                "effacer", "efface", "corbeille", "trash", "remove"],
  // « envoyé »/« envoyez »/« envoi » : homophones FR de « envoyer » — Deepgram
  // choisit la graphie au hasard, on accepte toute la famille (match exact).
  APPROVE:     ["approuver", "envoyer", "envoie", "envoyé", "envoyez", "envoi",
                "ok", "okay",
                "parfait", "valider", "valide", "send", "approve"],
  REJECT:      ["refaire", "recommencer", "non", "no", "redo", "retry"],
  MODIFY:      ["modifier", "changer", "change", "modify", "edit"],
  REPEAT:      ["répéter", "répète", "repeat", "réécouter", "again"],
  PAUSE:       ["pause", "attendre", "wait"],
  RESUME:      ["reprends", "reprendre", "continue", "continuer", "resume"],
  STOP:        ["stop", "arrêter", "arrête", "fin", "terminé", "termine"],
  // F7 — Annule la réponse en cours, retour à choosing (≠ STOP qui ferme la
  // session entière). Phrases volontairement spécifiques pour éviter les
  // faux positifs si l'user dicte "j'annule mon vol" ou similaire.
  CANCEL_REPLY: [
    "abandon", "abandonne",
    "laisse tomber", "laisse tombe",
    "tant pis",
    "annule la réponse", "annule la reponse",
    "annule l'email", "annule lemail", "annule le mail",
    "annule le message",
    "cancel reply", "cancel that", "nevermind",
  ],
};

// Phrases indiquant que l'utilisateur a fini de dicter
export const END_DICTATION_PHRASES = [
  "c'est tout", "cest tout", "voilà", "voila", "terminé", "termine",
  "c'est bon", "cest bon", "c'est good", "fin de message",
];

/**
 * Détecte une commande vocale parmi le vocabulaire `COMMANDS`.
 *
 * Normalisation requise pour Fireworks Whisper : contrairement à Siri
 * on-device qui rendait des transcriptions brutes ("archiver"), Whisper
 * ajoute systématiquement la ponctuation et la capitalisation
 * ("Archiver."). Sans normalisation, "archiver." !== "archiver" et la
 * commande tombe en silence sur `null`. On strip la ponctuation finale
 * + on collapse les espaces internes pour le match.
 */
export const COMMAND_ORDER = [
  // CANCEL_REPLY en premier pour matcher les phrases longues ("annule la
  // réponse") avant les keywords courts ("annule" qui n'existe pas seul).
  "CANCEL_REPLY",
  "REPLY_ALL", "FORWARD", "REPLY", "ARCHIVE", "DELETE",
  "NEXT", "PREVIOUS", "APPROVE", "REJECT", "MODIFY",
  "REPEAT", "PAUSE", "RESUME", "STOP",
] as const;

/**
 * Commandes dont l'exécution est ANNONCÉE À VOIX HAUTE (clé `cmdAck.*`).
 *
 * Au volant l'utilisateur ne regarde pas l'écran : le badge « ✓ SUIVANT » ne
 * lui apprend rien, et l'earcon seul ne dit pas CE QUI a été fait (retour
 * utilisateur 2026-08-05). Ces commandes-là ne produisaient qu'un haptique +
 * un earcon.
 *
 * Volontairement restreint aux commandes qui n'ont PAS déjà de réponse parlée
 * explicite : APPROVE (« J'envoie. »), PAUSE/STOP/REPEAT/REJECT/MODIFY et
 * CANCEL_REPLY s'annoncent déjà eux-mêmes — les doubler serait bavard.
 *
 * REPLY/REPLY_ALL/FORWARD sont inclus malgré leur prompt parlé : celui-ci
 * (« J'écoute. ») ne dit PAS lequel des trois modes a été retenu, or ce sont
 * les trois commandes les plus confondues à l'oreille par le STT.
 */
export const SPOKEN_ACK_COMMANDS = [
  "NEXT", "PREVIOUS", "ARCHIVE", "DELETE",
  "REPLY", "REPLY_ALL", "FORWARD",
] as const;

export function isSpokenAckCommand(cmd: string): boolean {
  return (SPOKEN_ACK_COMMANDS as readonly string[]).includes(cmd);
}

/** Accusé parlé en attente : libellé + instant du parse (garde d'obsolescence). */
export interface SpokenAck {
  label: string;
  at: number;
}

/** Au-delà, l'accusé est périmé : la commande n'a produit aucun énoncé pour le
 *  porter, on ne le colle pas à un énoncé sans rapport bien plus tard. */
export const SPOKEN_ACK_MAX_AGE_MS = 5000;

/**
 * Colle l'accusé DEVANT l'énoncé : « Supprimé. De Marc, objet réunion. »
 *
 * Préfixe et non énoncé séparé : `useTts.speak` décharge le son courant avant
 * d'en jouer un nouveau, donc un « Supprimé. » isolé serait tranché net par la
 * lecture de l'email qui démarre ~100 ms après (`archiveAndNext` →
 * `safeTimeout(next, 100)`). En préfixe : aucune course, aucune latence
 * ajoutée, et la phrase se lit naturellement.
 */
export function applySpokenAck(text: string, ack: SpokenAck | null, nowMs: number): string {
  if (!ack?.label) return text;
  if (nowMs - ack.at > SPOKEN_ACK_MAX_AGE_MS) return text;
  return `${ack.label}. ${text}`;
}

export function normalizeForCommand(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[.!?,;:…]+$/g, "")  // ponctuation finale (Whisper)
    .replace(/\s+/g, " ")           // collapse espaces multiples
    .trim();
}

export function detectCommand(text: string): keyof typeof COMMANDS | "free_text" | null {
  const lower = normalizeForCommand(text);
  for (const cmd of COMMAND_ORDER) {
    if (COMMANDS[cmd].some((kw) => lower === kw || lower.startsWith(kw + " "))) {
      return cmd;
    }
  }
  if (lower.split(" ").length > 2) return "free_text";
  return null;
}

/**
 * Détecte une commande émise par l'utilisateur en marge d'un TTS contaminant
 * la transcription.
 *
 * Cas d'usage : pendant la lecture TTS d'un email, l'utilisateur dit
 * "supprimer". Le mic enregistre TTS + voix utilisateur en simultané.
 * Whisper rend "Hello Alice. The contract is ready for review. Supprimer."
 * `detectCommand` voit > 2 mots et renvoie `free_text` → commande ignorée.
 *
 * Stratégie : split sur la ponctuation de fin de phrase (`. ! ?`), prendre
 * la DERNIÈRE phrase, et vérifier match EXACT contre une commande.
 *
 * Pourquoi match exact (et pas `startsWith`) ? Pour éviter les faux positifs
 * sur les emails qui mentionnent des mots-clés. Exemple :
 *   - TTS lit "please delete the old file" → last sentence (sans ponctuation
 *     finale) = "please delete the old file" → pas d'égalité avec "delete"
 *     → pas de match, ouf.
 *   - User dit "Delete." en barge-in → last sentence = "delete" → match.
 *   - User dit "Supprime." → "supprime" → match.
 *
 * Si Whisper ne ponctue pas l'utterance utilisateur, on fallback sur les
 * 1-2 derniers mots avec match exact (pour le cas "...email body delete").
 */
export function detectTailCommand(text: string): keyof typeof COMMANDS | null {
  const norm = normalizeForCommand(text);
  if (!norm) return null;

  // 1) Last sentence (après split sur . ! ?)
  const sentences = text
    .split(/[.!?]+/)
    .map((s) => normalizeForCommand(s))
    .filter(Boolean);
  if (sentences.length > 0) {
    const last = sentences[sentences.length - 1];
    for (const cmd of COMMAND_ORDER) {
      if (COMMANDS[cmd].some((kw) => last === kw)) {
        return cmd;
      }
    }
  }

  // 2) Fallback : 1 ou 2 derniers mots (cas où Whisper n'a pas ponctué).
  // Limité à 2 mots pour réduire les faux positifs (ex. "supprime pas" → 2 mots,
  // pas de match avec "supprime" seul, donc safe).
  const words = norm.split(/\s+/);
  for (let n = Math.min(2, words.length); n >= 1; n--) {
    const tail = words.slice(-n).join(" ");
    for (const cmd of COMMAND_ORDER) {
      if (COMMANDS[cmd].some((kw) => tail === kw)) {
        return cmd;
      }
    }
  }
  return null;
}

export function isEndOfDictation(text: string): boolean {
  // Même normalisation que detectCommand — Whisper rend "Voilà." pas "voilà".
  const lower = text
    .toLowerCase()
    .trim()
    .replace(/[.!?,;:…]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return END_DICTATION_PHRASES.some((p) => lower === p || lower.endsWith(p));
}

/**
 * L'utterance ENTIÈRE est-elle un ordre d'envoi ? (« Envoyer. », « Envoyé. »,
 * « J'envoie », « Send it »…)
 *
 * Retour device 2026-07 : en français, envoyer / envoyé / envoyez / envoi(e)
 * sont des HOMOPHONES [ɑ̃vwaje] — Deepgram choisit la graphie au hasard du
 * modèle de langage (souvent le participe « Envoyé. » pour un mot isolé).
 * Un matcher qui ne couvre que l'infinitif rate donc l'ordre une fois sur
 * deux. On accepte toute la famille, MAIS uniquement si l'utterance entière
 * est le verbe (± clitique le/la/ça/moi) — « dis-lui d'envoyer le contrat »
 * ne matche pas (c'est du contenu de dictée).
 */
const SEND_UTTERANCE_RE =
  /^(?:j[' ])?(?:envoie[sz]?|envoyer|envoyez|envoyée?s?|envoi|send(?:[-\s]it)?)(?:[-\s](?:le|la|les|ça|ca|moi))?[\s.!?…]*$/i;

export function isSendUtterance(text: string): boolean {
  return SEND_UTTERANCE_RE.test((text || "").trim());
}

// Famille « annuler » en énoncé ENTIER — mêmes principes que
// SEND_UTTERANCE_RE : homophones du STT (annule / annuler / annulez /
// annulé(e)(s)), clitiques usuels, et JAMAIS de match sur un contenu qui
// mentionne le verbe au milieu (« annule mon vol de demain »). Device
// 2026-08-04 : « Annulé. » en relecture partait en texte libre →
// regénération du brouillon avec "Annulé" comme instruction.
const CANCEL_UTTERANCE_RE =
  /^(?:(?:j[' ])?annul(?:e[sz]?|er|ez|ée?s?)(?:[-\s](?:tout|ça|ca))?|cancel(?:[-\s]it)?|laisse tomber|abandonne)[\s.!?…]*$/i;

export function isCancelUtterance(text: string): boolean {
  return CANCEL_UTTERANCE_RE.test((text || "").trim());
}

// Verbe d'envoi EXPLICITE en fin de dictée → l'utilisateur a tout dit en un
// souffle ("réponds que je serai là à 15h, et envoie"). On détecte ce suffixe
// pour router vers un envoi immédiat (fenêtre d'annulation) au lieu de
// reposer la question parlée "J'envoie ?". Volontairement STRICT (suffixe
// uniquement, ancré `$`) pour ne JAMAIS se déclencher sur un corps qui
// mentionne "envoie" en son milieu ("dis-lui d'envoyer le contrat").
// Le verbe d'envoi DOIT être introduit soit par un connecteur explicite
// (et / puis / and / then), soit par une ponctuation de fin de phrase
// (", envoie" / ". send it"). Sans ce garde, "dis-lui d'envoyer le contrat"
// (verbe au milieu, "d'envoyer") déclencherait un faux envoi.
// Même famille d'homophones [ɑ̃vwaje] que SEND_UTTERANCE_RE (envoyez /
// envoyé(e)(s) / envoi) — retour device 2026-07-28 : « Ok merci, envoyez. »
// n'était pas reconnu, la dictée bufferisait l'ordre d'envoi comme contenu.
const SEND_TAIL_RE =
  /(?:[\s,.;:!?–—-]+(?:et|puis|then|and)\s+|[,.;:!?–—-]+\s*)(?:tu\s+)?(?:l[' ]?)?(?:envoie[sz]?(?:[-\s]?(?:le|la|les|moi|leur|ça|ca))*|envoyer|envoyez|envoyée?s?|envoi|expédie(?:[-\s]?(?:le|la|les))*|send(?:[-\s]?it)?)[\s.!?…]*$/i;

/**
 * Sépare un corps de dictée d'un éventuel verbe d'envoi explicite en fin.
 * Retourne `{ body, send }`. `send=true` UNIQUEMENT si le verbe est un
 * suffixe ET qu'il reste un corps non trivial devant (≥ 3 chars) — sinon
 * "envoie" seul reste une commande gérée ailleurs (detectCommand/APPROVE).
 * Pure + exportée pour les tests.
 */
export function extractSendDisposition(text: string): { body: string; send: boolean } {
  const raw = (text || "").trim();
  if (!raw) return { body: raw, send: false };
  const m = raw.match(SEND_TAIL_RE);
  if (m && m.index !== undefined && m.index > 0) {
    const body = raw.slice(0, m.index).replace(/[\s,.;:!?–—-]+$/, "").trim();
    if (body.length >= 3) return { body, send: true };
  }
  return { body: raw, send: false };
}

// Step 3 — fenêtre d'annulation après un envoi implicite ("…et envoie"). On
// agit (envoi différé) puis on laisse ~4s pour dire "annule" plutôt que de
// poser "J'envoie ?". Une parole quelconque pendant la fenêtre annule.
// 5 s (au lieu de 4) : la fenêtre s'ouvre désormais sur l'annonce parlée
// « J'envoie. » (~0,7 s) — le temps de réaction utilisateur est préservé.
export const UNDO_WINDOW_MS = 5000;

// Mots d'annulation de la dernière action différée. Volontairement stricts
// (préfixe exact) : ne matchent que pendant qu'une action est en attente,
// donc ≤ 8 s après un archive/delete/send.
export const UNDO_RE = /^(annule|annuler|undo|cancel)([\s!.,]|$)/i;

// Act-then-undo généralisé : archive/delete jouent leur earcon et avancent
// IMMÉDIATEMENT ; l'appel API part après ce délai, annulable à la voix
// (« annule ») ou au chip. Même philosophie que undo_window pour l'envoi.
export const UNDO_ACTION_MS = 5000;
// L'envoi (irréversible côté destinataire) garde une fenêtre plus longue.
export const SEND_UNDO_MS = 8000;
