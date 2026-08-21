/**
 * Table de transitions du drive — test EXHAUSTIF (Phase 2 fondations §2.2).
 *
 * Chaque couple (état, événement) est vérifié : soit une transition définie
 * vers l'état attendu, soit un rejet (accepted=false, état inchangé). Une
 * transition ajoutée sans son cas attendu ici casse le test — la table et sa
 * spec ne peuvent pas diverger.
 */
import {
  DRIVE_TRANSITIONS,
  driveTransition,
  INITIAL_DRIVE_CORE,
  type DriveEvent,
  type DriveCore,
} from '../../src/hooks/driveReducer';
import type { DriveState } from '../../src/types';

const ALL_STATES: DriveState[] = [
  'idle', 'loading', 'speaking', 'choosing', 'listening',
  'confirming_dictation', 'processing', 'generating', 'asking_preview',
  'asking_send', 'reviewing', 'undo_window', 'paused', 'completed', 'error',
];

// Un représentant par type d'événement (payloads par défaut).
const EVENT_SAMPLES: DriveEvent[] = [
  { type: 'SESSION_START' },
  { type: 'EMAIL_LOAD' },
  { type: 'EMAIL_LOADED' },
  { type: 'TTS_DONE' },
  { type: 'SPEAK' },
  { type: 'REPLY_CHOSEN' },
  { type: 'DICTATION_FINISHED' },
  { type: 'DICTATION_CANCELLED' },
  { type: 'GENERATE' },
  { type: 'DRAFT_READY', autoSend: false },
  { type: 'DRAFT_FAILED' },
  { type: 'SEND_SCHEDULED' },
  { type: 'SEND_CANCELLED' },
  { type: 'REVIEW' },
  { type: 'PAUSE' },
  { type: 'RESUME' },
  { type: 'SESSION_END' },
  { type: 'RESET' },
  { type: 'FLOW_ERROR' },
  { type: 'RECOVER', to: 'choosing' },
];

function coreIn(state: DriveState): DriveCore {
  return { ...INITIAL_DRIVE_CORE, state };
}

describe('driveTransition — produit cartésien exhaustif', () => {
  it.each(ALL_STATES.flatMap((s) => EVENT_SAMPLES.map((e) => [s, e] as const)))(
    '%s × %j',
    (state, event) => {
      const target = DRIVE_TRANSITIONS[state]?.[event.type];
      const outcome = driveTransition(coreIn(state), event);
      if (target === undefined) {
        // Rejet : état STRICTEMENT inchangé, jamais d'exécution par défaut.
        expect(outcome.accepted).toBe(false);
        expect(outcome.core.state).toBe(state);
      } else {
        expect(outcome.accepted).toBe(true);
        const expected = typeof target === 'function' ? target(coreIn(state), event) : target;
        expect(outcome.core.state).toBe(expected);
      }
    },
  );

  it('les cibles dynamiques honorent leurs payloads', () => {
    expect(driveTransition(coreIn('generating'), { type: 'DRAFT_READY', autoSend: true }).core.state)
      .toBe('undo_window');
    // Surface 3 : sans autoSend, le brouillon est LU (auto-read F5) avant la
    // question d'envoi — speaking, puis TTS_DONE{next:'asking_send'}.
    expect(driveTransition(coreIn('generating'), { type: 'DRAFT_READY', autoSend: false }).core.state)
      .toBe('speaking');
    expect(driveTransition(coreIn('speaking'), { type: 'TTS_DONE', next: 'asking_send' }).core.state)
      .toBe('asking_send');
    expect(driveTransition(coreIn('speaking'), { type: 'TTS_DONE' }).core.state)
      .toBe('choosing');
    expect(driveTransition(coreIn('listening'), { type: 'RECOVER', to: 'reviewing' }).core.state)
      .toBe('reviewing');
  });

  it('invariants de sûreté du flux', () => {
    // On ne peut JAMAIS armer un envoi depuis la dictée brute (le contenu
    // doit passer par confirmation ou génération) — la classe de bug
    // « envoi accidentel sur un mot mal transcrit ».
    expect(driveTransition(coreIn('listening'), { type: 'SEND_SCHEDULED' }).accepted).toBe(false);
    // idle n'accepte que l'ouverture de session (SESSION_START, ou
    // EMAIL_LOAD car startSession délègue l'ouverture à readEmailAtIndex —
    // surface 2, 2026-07-28) et le RESET idempotent. Tout autre événement
    // en idle est un bug (ex. un transcript fantôme post-session).
    const IDLE_ACCEPTED = new Set(['SESSION_START', 'EMAIL_LOAD', 'RESET']);
    for (const ev of EVENT_SAMPLES) {
      const out = driveTransition(coreIn('idle'), ev);
      expect(out.accepted).toBe(IDLE_ACCEPTED.has(ev.type));
    }
    // undo_window ne peut pas rebasculer en dictée (le timer d'envoi court).
    expect(driveTransition(coreIn('undo_window'), { type: 'REPLY_CHOSEN' }).accepted).toBe(false);
  });

  it('feedback (badge « ✓ commande ») : présent si accepté + label, JAMAIS sur rejet (P2.5)', () => {
    // Transition acceptée avec label → feedback porté par le TransitionResult.
    const ok = driveTransition(coreIn('choosing'), { type: 'REPLY_CHOSEN' }, 'Répondre');
    expect(ok.accepted).toBe(true);
    expect(ok.feedback).toEqual({ flash: 'Répondre' });
    // Événement REJETÉ → pas de flash, même avec un label fourni — la classe
    // de bug « le badge flashe mais rien ne se passe ».
    const ko = driveTransition(coreIn('idle'), { type: 'DICTATION_FINISHED' }, 'Terminer');
    expect(ko.accepted).toBe(false);
    expect(ko.feedback).toBeUndefined();
    // Accepté sans label → pas de feedback (transitions internes silencieuses).
    const silent = driveTransition(coreIn('choosing'), { type: 'REPLY_CHOSEN' });
    expect(silent.accepted).toBe(true);
    expect(silent.feedback).toBeUndefined();
  });
});
