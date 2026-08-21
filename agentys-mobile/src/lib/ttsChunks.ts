/**
 * ttsChunks — découpage d'un texte long en chunks TTS aux frontières de
 * phrases, pour le pipeline « streaming » d'ElevenLabs.
 *
 * Le but : la latence ElevenLabs croît avec la longueur du texte. Un brouillon
 * de 600 caractères = ~1,5-3 s avant le PREMIER son. En synthétisant un
 * premier chunk court (la première phrase) pendant que le reste se synthétise
 * en parallèle, l'audio démarre en ~400-700 ms — la voix « répond » au lieu
 * de « charger ».
 *
 * Contraintes :
 *  - frontières de phrases uniquement (une coupure mi-phrase s'entend) ;
 *  - premier chunk volontairement court (FIRST_TARGET), suivants plus longs
 *    (MAX_CHARS) pour limiter le nombre de requêtes ;
 *  - le cache serveur est par-hash(texte) : prefetch et speak DOIVENT passer
 *    par ce même découpage pour partager les entrées de cache.
 *
 * Pas de lookbehind regex (support Hermes inégal) — scan par match global.
 */

export interface ChunkOptions {
  /** En-dessous de cette taille totale, pas de découpage. */
  singleMax?: number;
  /** Taille visée du premier chunk (audio le plus tôt possible). */
  firstTarget?: number;
  /** Taille max des chunks suivants. */
  maxChars?: number;
}

const DEFAULTS: Required<ChunkOptions> = {
  singleMax: 200,
  firstTarget: 140,
  maxChars: 300,
};

/** Découpe une phrase trop longue (sans ponctuation forte) sur virgules puis
 *  espaces, sans jamais dépasser maxChars par morceau. */
function splitLongSentence(sentence: string, maxChars: number): string[] {
  if (sentence.length <= maxChars) return [sentence];
  const out: string[] = [];
  let rest = sentence.trim();
  while (rest.length > maxChars) {
    const window = rest.slice(0, maxChars);
    // Coupure préférée : dernière virgule/point-virgule, sinon dernier espace.
    let cut = Math.max(window.lastIndexOf(", "), window.lastIndexOf("; "));
    if (cut >= maxChars * 0.4) {
      cut += 1; // garde la virgule dans le morceau de gauche
    } else {
      cut = window.lastIndexOf(" ");
      if (cut < maxChars * 0.4) cut = maxChars; // pas d'espace exploitable
    }
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out;
}

/** Extrait les phrases (ponctuation forte conservée). */
function toSentences(text: string): string[] {
  const matches = text.match(/[^.!?…]+[.!?…]+["»)\]]*\s*|[^.!?…]+$/g);
  if (!matches) return [text];
  return matches.map((s) => s.trim()).filter((s) => s.length > 0);
}

/**
 * Découpe `text` en chunks TTS. Retourne toujours ≥ 1 chunk ; la
 * concaténation des chunks (avec espaces) reconstitue le texte normalisé.
 */
export function splitIntoTtsChunks(text: string, opts: ChunkOptions = {}): string[] {
  const { singleMax, firstTarget, maxChars } = { ...DEFAULTS, ...opts };
  const normalized = (text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  if (normalized.length <= singleMax) return [normalized];

  const sentences = toSentences(normalized).flatMap((s) =>
    splitLongSentence(s, maxChars),
  );

  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    const target = chunks.length === 0 ? firstTarget : maxChars;
    if (current && current.length + 1 + sentence.length > target) {
      chunks.push(current);
      current = sentence;
    } else {
      current = current ? `${current} ${sentence}` : sentence;
    }
    // Le premier chunk part dès qu'il atteint sa cible : chaque caractère de
    // plus retarde le premier son.
    if (chunks.length === 0 && current.length >= firstTarget) {
      chunks.push(current);
      current = "";
    }
  }
  if (current) chunks.push(current);
  return chunks;
}
