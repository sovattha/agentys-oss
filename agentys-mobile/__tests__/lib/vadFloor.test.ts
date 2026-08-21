/**
 * Plancher ambiant glissant du VAD (device 2026-08-03).
 *
 * Bug d'origine : le seuil était calibré UNE fois sur le MIN des 600 ms de
 * grâce puis figé. Un instant calme (-34 dB) dans un ambiant réel à -26 dB
 * → seuil -27,3 sous l'ambiant → « voix » permanente → la fin-de-parole par
 * silence ne se déclenchait jamais (l'app ne rendait pas la main).
 */
import { createFloorTracker } from '../../src/lib/vadFloor';

describe('createFloorTracker', () => {
  it('le plancher est le MIN de la fenêtre glissante', () => {
    const t = createFloorTracker(4);
    expect(t.push(-30)).toBe(-30);
    expect(t.push(-40)).toBe(-40);
    expect(t.push(-25)).toBe(-40);
  });

  it("un instant calme EXPIRE quand il sort de la fenêtre (l'ambiant réel reprend)", () => {
    const t = createFloorTracker(3);
    t.push(-34); // le blip calme de la grâce
    t.push(-26);
    t.push(-26);
    // Le -34 sort de la fenêtre : le plancher remonte à l'ambiant réel.
    expect(t.push(-26)).toBe(-26);
  });

  it('retombe instantanément sur un frame plus calme', () => {
    const t = createFloorTracker(3);
    t.push(-25);
    t.push(-26);
    expect(t.push(-45)).toBe(-45);
  });

  it('floor() est null avant tout frame, puis reflète la fenêtre', () => {
    const t = createFloorTracker(2);
    expect(t.floor()).toBeNull();
    t.push(-30);
    expect(t.floor()).toBe(-30);
  });
});
