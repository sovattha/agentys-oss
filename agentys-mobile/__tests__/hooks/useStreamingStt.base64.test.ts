/**
 * base64ToBytes — décodeur sans dépendance (atob non garanti sur Hermes).
 * Les frames mic natives transitent en base64 ; un décodage faux = audio
 * corrompu envoyé à Deepgram = transcripts silencieusement faux.
 */
import { base64ToBytes } from '../../src/hooks/useStreamingStt';

function toBase64(bytes: number[]): string {
  // Node Buffer dispo dans l'env jest
  return Buffer.from(bytes).toString('base64');
}

describe('base64ToBytes', () => {
  it('décode une séquence simple', () => {
    const bytes = [72, 101, 108, 108, 111]; // "Hello"
    expect(Array.from(base64ToBytes(toBase64(bytes)))).toEqual(bytes);
  });

  it('gère les paddings = et ==', () => {
    expect(Array.from(base64ToBytes(toBase64([1])))).toEqual([1]);          // ==
    expect(Array.from(base64ToBytes(toBase64([1, 2])))).toEqual([1, 2]);    // =
    expect(Array.from(base64ToBytes(toBase64([1, 2, 3])))).toEqual([1, 2, 3]); // sans padding
  });

  it('round-trip sur une frame PCM16 réaliste (valeurs 0-255)', () => {
    const frame = Array.from({ length: 3200 }, (_, i) => (i * 37) % 256);
    const decoded = base64ToBytes(toBase64(frame));
    expect(decoded.byteLength).toBe(3200);
    expect(Array.from(decoded)).toEqual(frame);
  });

  it('tolère les sauts de ligne dans le base64', () => {
    const b64 = toBase64([10, 20, 30, 40, 50, 60]);
    const withNewlines = b64.slice(0, 4) + '\n' + b64.slice(4);
    expect(Array.from(base64ToBytes(withNewlines))).toEqual([10, 20, 30, 40, 50, 60]);
  });

  it('chaîne vide → 0 octets', () => {
    expect(base64ToBytes('').byteLength).toBe(0);
  });
});
