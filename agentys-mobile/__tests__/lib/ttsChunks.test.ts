/**
 * splitIntoTtsChunks — le découpage conditionne le time-to-first-audio ET les
 * hits du cache TTS serveur (hash par chunk). Contrats verrouillés ici :
 * texte court intact, premier chunk court, frontières de phrases, contenu
 * intégralement préservé.
 */
import { splitIntoTtsChunks } from '../../src/lib/ttsChunks';

describe('splitIntoTtsChunks', () => {
  it('texte vide → []', () => {
    expect(splitIntoTtsChunks('')).toEqual([]);
    expect(splitIntoTtsChunks('   ')).toEqual([]);
  });

  it('texte court → un seul chunk inchangé', () => {
    const text = 'Bonjour, je serai là à 15h.';
    expect(splitIntoTtsChunks(text)).toEqual([text]);
  });

  it('normalise les espaces multiples', () => {
    expect(splitIntoTtsChunks('Salut   toi.\n\nÇa va ?')).toEqual(['Salut toi. Ça va ?']);
  });

  it('texte long → premier chunk court (≤ ~220 chars), audio rapide', () => {
    const sentence = 'Voici une phrase de longueur tout à fait raisonnable pour un email. ';
    const text = sentence.repeat(10).trim();
    const chunks = splitIntoTtsChunks(text);
    expect(chunks.length).toBeGreaterThan(1);
    // Le 1er chunk doit être nettement plus court que le texte total —
    // c'est lui qui conditionne le délai avant le premier son.
    expect(chunks[0].length).toBeLessThanOrEqual(220);
  });

  it('coupe aux frontières de phrases (chaque chunk finit par une ponctuation forte)', () => {
    const text =
      'Première phrase assez longue pour remplir le premier segment du découpage. ' +
      'Deuxième phrase qui continue le propos avec des détails supplémentaires. ' +
      'Troisième phrase encore, pour dépasser le seuil de découpage du texte. ' +
      'Et une quatrième phrase pour faire bonne mesure dans ce test.';
    const chunks = splitIntoTtsChunks(text);
    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks.slice(0, -1)) {
      expect(chunk).toMatch(/[.!?…]["»)\]]*$/);
    }
  });

  it('préserve tout le contenu (concat = texte normalisé)', () => {
    const text =
      'Bonjour Marie. Merci pour ton retour sur le dossier de candidature. ' +
      'Je te confirme que la réunion de jeudi est maintenue à 15h en salle B. ' +
      "N'hésite pas à inviter Paul si tu penses que c'est pertinent. " +
      'Je préparerai le support de présentation et les documents annexes. À jeudi !';
    const chunks = splitIntoTtsChunks(text);
    expect(chunks.join(' ')).toBe(text);
  });

  it('phrase interminable sans ponctuation → hard-split borné', () => {
    const text = ('mot '.repeat(200)).trim(); // 800 chars sans ponctuation
    const chunks = splitIntoTtsChunks(text);
    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) {
      expect(chunk.length).toBeLessThanOrEqual(300);
    }
    expect(chunks.join(' ')).toBe(text);
  });

  it('respecte les options custom', () => {
    const text = 'Une phrase. Une autre phrase. Encore une. Et une dernière.';
    const chunks = splitIntoTtsChunks(text, { singleMax: 10, firstTarget: 12, maxChars: 40 });
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks[0].length).toBeLessThanOrEqual(40);
  });
});
