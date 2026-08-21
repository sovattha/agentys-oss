/**
 * errors — politique « loud failure » (Phase 1 fondations, tech spec §1.1).
 * Aucune erreur ne meurt en silence : reportError route chaque erreur vers
 * le ring buffer + os_log + (selon le domaine) une représentation utilisateur.
 */
import { reportError, registerErrorEarcon, unregisterErrorEarcon } from '../../src/lib/errors';
import { getRecentEvents, clearEvents } from '../../src/lib/eventLog';
import { toast } from '../../src/lib/toast';
import * as AgentysAudio from '../../modules/agentys-audio';

jest.mock('../../src/lib/toast', () => ({
  toast: { warning: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

describe('reportError', () => {
  beforeEach(() => {
    clearEvents();
    jest.clearAllMocks();
    unregisterErrorEarcon();
  });

  it("pousse un événement 'error' structuré dans le ring buffer", () => {
    reportError(new Error('boom'), { domain: 'api', op: 'transcribe', state: 'choosing' });
    const events = getRecentEvents(5);
    expect(events).toHaveLength(1);
    expect(events[0].kind).toBe('error');
    expect(events[0].data).toMatchObject({
      domain: 'api',
      op: 'transcribe',
      state: 'choosing',
      message: 'boom',
    });
  });

  it('trace vers os_log (debugLog) pour la visibilité Release', () => {
    const spy = jest.spyOn(AgentysAudio, 'debugLog').mockImplementation(() => {});
    reportError(new Error('boom'), { domain: 'stt', op: 'listen' });
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('stt/listen'));
    spy.mockRestore();
  });

  it('domaine api/stt → toast warning par défaut', () => {
    reportError(new Error('HTTP 500'), { domain: 'api', op: 'sendEmail' });
    expect(toast.warning).toHaveBeenCalled();
  });

  it('userFacing "silent" → aucune UI (mais loggé quand même)', () => {
    reportError(new Error('x'), { domain: 'api', op: 'prefetch' }, { userFacing: 'silent' });
    expect(toast.warning).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(getRecentEvents(5)).toHaveLength(1);
  });

  it("domaine audio/state → earcon alert via le callback enregistré", () => {
    const play = jest.fn();
    registerErrorEarcon(play);
    reportError(new Error('recorder collision'), { domain: 'audio', op: 'createAsync' });
    expect(play).toHaveBeenCalledWith('alert');
  });

  it('accepte les non-Error (string, undefined) sans throw', () => {
    expect(() => reportError('raw string', { domain: 'unknown', op: 'x' })).not.toThrow();
    expect(() => reportError(undefined, { domain: 'unknown', op: 'y' })).not.toThrow();
    expect(getRecentEvents(5)).toHaveLength(2);
  });

  it('ne throw JAMAIS même si un sink casse (earcon qui lève)', () => {
    registerErrorEarcon(() => { throw new Error('sink broken'); });
    expect(() =>
      reportError(new Error('x'), { domain: 'audio', op: 'z' }),
    ).not.toThrow();
    // L'événement est quand même loggé.
    expect(getRecentEvents(5)).toHaveLength(1);
  });
});
