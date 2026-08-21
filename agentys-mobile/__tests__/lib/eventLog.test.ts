/**
 * eventLog — ring buffer structuré (Phase 1 fondations, tech spec
 * mobile-foundations-refactor §1.2). La mémoire des 500 derniers événements
 * (transitions, erreurs, STT, audio) exportable depuis l'écran Diagnostic :
 * chaque futur bug device se diagnostique en lisant ce dump.
 */
import { logEvent, dumpEvents, clearEvents, getRecentEvents, EVENT_LOG_CAPACITY } from '../../src/lib/eventLog';

describe('eventLog', () => {
  beforeEach(() => clearEvents());

  it('enregistre un événement avec timestamp, kind et data', () => {
    logEvent('stt', { transcript: 'suivant', state: 'choosing' });
    const events = getRecentEvents(10);
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe('stt');
    expect(events[0].data).toEqual({ transcript: 'suivant', state: 'choosing' });
    expect(typeof events[0].ts).toBe('number');
  });

  it('tourne en anneau : ne garde que les EVENT_LOG_CAPACITY plus récents', () => {
    for (let i = 0; i < EVENT_LOG_CAPACITY + 50; i++) {
      logEvent('audio', { i });
    }
    const events = getRecentEvents(EVENT_LOG_CAPACITY + 100);
    expect(events).toHaveLength(EVENT_LOG_CAPACITY);
    // Les plus anciens (i < 50) ont été évincés.
    expect(events[0].data).toEqual({ i: 50 });
    expect(events[events.length - 1].data).toEqual({ i: EVENT_LOG_CAPACITY + 49 });
  });

  it('dumpEvents produit du JSON-lines chronologique parsable', () => {
    logEvent('transition', { from: 'speaking', to: 'choosing' });
    logEvent('error', { domain: 'api', op: 'transcribe' });
    const dump = dumpEvents();
    const lines = dump.trim().split('\n');
    expect(lines).toHaveLength(2);
    const parsed = lines.map((l) => JSON.parse(l));
    expect(parsed[0].kind).toBe('transition');
    expect(parsed[1].kind).toBe('error');
    expect(parsed[0].ts).toBeLessThanOrEqual(parsed[1].ts);
  });

  it('clearEvents vide le buffer', () => {
    logEvent('api', { op: 'x' });
    clearEvents();
    expect(getRecentEvents(10)).toHaveLength(0);
    expect(dumpEvents()).toBe('');
  });

  it("ne throw jamais sur des data non sérialisables (best-effort)", () => {
    const circular: any = {};
    circular.self = circular;
    expect(() => logEvent('error', circular)).not.toThrow();
    expect(() => dumpEvents()).not.toThrow();
  });
});
