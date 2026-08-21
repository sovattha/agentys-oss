/**
 * Injection de fautes STT — le drive complet piloté par des scénarios
 * scriptés (Phase 2 fondations §2.1). Ces tests reproduisent EN JEST les
 * bugs qui coûtaient un build device par hypothèse :
 *   (a) course « transcript en vol » autour du tap fin-de-dictée (2026-07-11)
 *   (b) homophone « Envoyé. » en confirmation (2026-07-12)
 *   (c) résilience à la boucle de transcripts vides (2026-07-13/16)
 */
import { renderHook, act, waitFor } from '@testing-library/react-native';
import { AppState } from 'react-native';
import { Audio } from 'expo-av';
import { useDriveMode } from '../../src/hooks/useDriveMode';
import {
  scriptStt,
  remainingTurns,
  drainStt,
} from '../support/fakeSttPipeline';

// ── Le cœur du harnais : STT scriptée ──
jest.mock('../../src/hooks/useVoiceDictation', () => {
  const actual = jest.requireActual('../../src/hooks/useVoiceDictation');
  const { makeFakeDictation } = require('../support/fakeSttPipeline');
  return { ...actual, useVoiceDictation: () => makeFakeDictation() };
});

jest.mock('../../src/services/api', () => ({
  getEmailSpeakable: jest.fn(),
  getPendingDraftByEmail: jest.fn().mockResolvedValue(null),
  createVoiceDraft: jest.fn(),
  approveDraft: jest.fn().mockResolvedValue({ success: true }),
  generateProcessDraftFast: jest.fn(),
  archiveEmail: jest.fn().mockResolvedValue({ success: true }),
  deleteEmail: jest.fn().mockResolvedValue({ success: true }),
  transcribeAudio: jest.fn((uri: string) => require('../support/fakeSttPipeline').fakeTranscribe(uri)),
  voiceAgent: jest.fn().mockResolvedValue({ source: 'llm', confidence: 0, actions: [] }),
  postVoiceMetrics: jest.fn().mockResolvedValue(undefined),
}));

jest.mock('../../src/services/tts', () => ({
  speak: jest.fn().mockResolvedValue({ audioUrl: 'https://srv/a.mp3', cached: true, chars: 5 }),
  audioAuthHeaders: jest.fn().mockResolvedValue({}),
}));

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn().mockImplementation((key: string) =>
    Promise.resolve(key === 'voice_id' ? 'voice-test' : null),
  ),
  setItemAsync: jest.fn().mockResolvedValue(undefined),
  deleteItemAsync: jest.fn().mockResolvedValue(undefined),
}));

import { getEmailSpeakable, generateProcessDraftFast } from '../../src/services/api';

const mockGetEmailSpeakable = getEmailSpeakable as jest.Mock;
const mockGenerateFast = generateProcessDraftFast as jest.Mock;

const EMAILS = [
  { id: 'm1', sender: 'a@t.co', subject: 'Sujet 1', received_at: '2026-01-01T10:00:00Z' },
  { id: 'm2', sender: 'b@t.co', subject: 'Sujet 2', received_at: '2026-01-01T09:00:00Z' },
];

// Démontage strict : sans lui, les promesses listen/transcribe en vol
// résolvent après le teardown jest → crash « Animated undefined » du worker.
let activeUnmount: (() => void) | null = null;
afterEach(async () => {
  drainStt();
  if (activeUnmount) { activeUnmount(); activeUnmount = null; }
  await new Promise((r) => setTimeout(r, 80)); // laisse retomber les async en vol
  // 2e drain APRÈS le settle : une chaîne TTS achevée post-unmount (ex.
  // l'annonce « J'envoie. » de la fenêtre d'annulation) peut ré-armer une
  // écoute — sans ce drain elle consommerait les tours scriptés du test
  // suivant et décalerait tout l'alignement.
  drainStt();
  const { voiceMetrics } = require('../../src/lib/voiceMetrics');
  voiceMetrics.endSession();
});

function renderDrive() {
  const rendered = renderHook(() => useDriveMode());
  activeUnmount = rendered.unmount;
  return rendered;
}

beforeEach(() => {
  jest.clearAllMocks();
  // La garde #1122 (pas de micro hors foreground) court-circuite tout en
  // jest où AppState.currentState est undefined — on simule le premier plan.
  (AppState as any).currentState = 'active';
  mockGetEmailSpeakable.mockImplementation(async (id: string) => ({
    id, // le backend to_dict expose id = email_id — generateDraft lit .id
    email_id: id,
    speakable_text: `contenu de ${id}`,
    sender_name: 'Test',
    subject: 'Sujet',
  }));
  mockGenerateFast.mockResolvedValue({ draft_id: 'draft-1', content: 'Brouillon généré.' });
  // TTS : playback qui se termine immédiatement (pattern useDriveMode.test).
  (Audio.Sound.createAsync as jest.Mock).mockImplementation(
    async (_s: any, _st: any, onStatus?: (s: any) => void) => {
      const sound = {
        stopAsync: jest.fn().mockResolvedValue(undefined),
        unloadAsync: jest.fn().mockResolvedValue(undefined),
        pauseAsync: jest.fn().mockResolvedValue(undefined),
        playAsync: jest.fn().mockResolvedValue(undefined),
        getStatusAsync: jest.fn().mockResolvedValue({
          isLoaded: true, isPlaying: false, positionMillis: 1000, durationMillis: 1000,
        }),
        setOnPlaybackStatusUpdate: jest.fn(),
      };
      setTimeout(() => onStatus?.({ isLoaded: true, didJustFinish: true }), 5);
      return { sound, status: { isLoaded: true } };
    },
  );
});

async function startSessionAndReachChoosing(result: { current: ReturnType<typeof useDriveMode> }) {
  await act(async () => {
    await result.current.startSession(EMAILS as any, 'mixed');
  });
  await waitFor(() => expect(result.current.state).toBe('choosing'), { timeout: 4000 });
}

describe('drive sous injection de fautes STT', () => {
  it('(b) homophone : « Envoyé. » en confirmation déclenche la génération + envoi différé', async () => {
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      // Tampon : les ré-écoutes intermédiaires (annulées/relancées autour du
      // tap) consomment des tours — un no_voice absorbe sans effet de bord.
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Envoyé.' }, // ← l'homophone qui partait en contenu
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    // « Répondre. » → dictée
    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    // Le chunk de dictée arrive dans le buffer, puis tap « c'est fini ».
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });
    await waitFor(() => expect(result.current.state).toBe('confirming_dictation'), { timeout: 4000 });

    // « Envoyé. » → rédige + envoi différé (undo_window), PAS du contenu.
    try {
      await waitFor(() => expect(result.current.state).toBe('undo_window'), { timeout: 5000 });
    } catch (e) {
      // Diagnostic via l'observabilité Phase 1 : le ring buffer dit tout.
      const { dumpEvents } = require('../../src/lib/eventLog');
      const { consumedTurns } = require('../support/fakeSttPipeline');
      // eslint-disable-next-line no-console
      console.log('RING BUFFER:\n' + dumpEvents());
      // eslint-disable-next-line no-console
      console.log('CONSOMMÉS:', JSON.stringify(consumedTurns));
      // eslint-disable-next-line no-console
      console.log('generateFast appels:', JSON.stringify(mockGenerateFast.mock.calls));
      // eslint-disable-next-line no-console
      console.log('état final:', result.current.state, '| draft:', result.current.draftContent);
      throw e;
    }
    expect(mockGenerateFast).toHaveBeenCalledWith(
      'm1', 'je confirme pour demain', 'reply', expect.anything(),
    );
  }, 15000);

  it("(a) course transcript-en-vol : le « Envoyé. » post-rebond n'est PAS avalé comme contenu", async () => {
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'premier morceau' },
      // Deuxième chunk : transcription LENTE — encore en vol au moment du tap.
      { kind: 'ok', transcript: 'second morceau', transcribeMs: 250 },
      // Après le rebond confirming→listening causé par le chunk en vol :
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Envoyé.' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);
    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('premier morceau'), { timeout: 4000 });

    // Tap pendant que « second morceau » est en cours de transcription.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60)); // le listen du chunk 2 a résolu, transcribe en vol
      result.current.finishDictation();
    });

    // Issue attendue (post-fix) : quelle que soit la course, « Envoyé. »
    // finit par déclencher la génération avec le contenu dicté, jamais
    // être ajouté au brouillon.
    await waitFor(() => expect(result.current.state).toBe('undo_window'), { timeout: 6000 });
    const dictated = mockGenerateFast.mock.calls[0][1] as string;
    expect(dictated).toContain('premier morceau');
    expect(dictated).not.toContain('Envoyé');
  }, 20000);

  it('(d) suffixe d\'envoi : « Ok merci, envoyez. » en confirmation rédige + envoie, pas du contenu', async () => {
    // Retour device 2026-07-28 : contenu + ordre d'envoi dans la MÊME
    // utterance (homophone « envoyez ») était bufferisé comme dictée →
    // l'utilisateur tournait en rond sans jamais atteindre la génération.
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Ok merci, envoyez.' }, // ← suffixe homophone
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });
    await waitFor(() => expect(result.current.state).toBe('confirming_dictation'), { timeout: 4000 });

    await waitFor(() => expect(result.current.state).toBe('undo_window'), { timeout: 5000 });
    // Le corps dicté inclut « Ok merci » (contenu) mais JAMAIS le verbe d'envoi.
    const dictated = mockGenerateFast.mock.calls[0][1] as string;
    expect(dictated).toContain('je confirme pour demain');
    expect(dictated).toContain('Ok merci');
    expect(dictated).not.toMatch(/envoyez/i);
  }, 15000);

  it("(e) undo_window : voix entendue mais transcript vide → ANNULE l'envoi (jamais l'inverse)", async () => {
    // Retour device 2026-07-28 : « annule » prononcé pendant la fenêtre,
    // capture ok (voicedMs=960) mais Whisper rend "" → parole ignorée →
    // l'email part. Politique conservatrice : voix non comprise = annulation.
    const { approveDraft } = require('../../src/services/api');
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Envoyé.' },
      { kind: 'ok', transcript: '' }, // ← « annule » avalé par le STT batch
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });
    // NE PAS attendre `undo_window` : état transitoire — le transcript vide
    // l'annule parfois avant l'échantillonnage de waitFor (course harnais).
    // On attend directement l'issue stable : retour sur le brouillon.
    await waitFor(() => expect(result.current.state).toBe('reviewing'), { timeout: 8000 });
    expect(mockGenerateFast).toHaveBeenCalled();
    expect(approveDraft).not.toHaveBeenCalled();
  }, 20000);

  it('(f) consignes parlées : « J\'écoute. » à l\'entrée en dictée', async () => {
    // Design audio 2026-07-30 : earcon = signal de tour, parole = signal de
    // vocabulaire. L'entrée en dictée est un point de décision (on passe de
    // commandes à du contenu libre) → consigne parlée courte.
    // Observation via le ring buffer (logEvent "tts" est SYNCHRONE dans
    // speak) — le mock backend TTS échoue avant l'appel réseau, seul le ring
    // buffer voit tous les textes demandés.
    const { clearEvents, getRecentEvents } = require('../../src/lib/eventLog');
    clearEvents();
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => {
      const texts = getRecentEvents(500)
        .filter((e: { kind: string }) => e.kind === 'tts')
        .map((e: { data: { text?: unknown } }) => String(e.data.text ?? ''));
      expect(texts.some((t: string) => t.includes("J'écoute"))).toBe(true);
    }, { timeout: 4000 });
  }, 15000);

  it('(g) consignes parlées : « J\'envoie ? » après la lecture du brouillon', async () => {
    // Constat n°4 de la vérification cinématique : asking_send n'était
    // signalé que par le earcon — si l'utilisateur le rate, il ne sait pas
    // que le micro l'attend. La question est désormais parlée d'office.
    const { clearEvents, getRecentEvents } = require('../../src/lib/eventLog');
    clearEvents();
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Oui.' }, // « rédige » sans envoi auto
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });

    await waitFor(() => expect(result.current.state).toBe('asking_send'), { timeout: 6000 });
    const texts = getRecentEvents(500)
      .filter((e: { kind: string }) => e.kind === 'tts')
      .map((e: { data: { text?: unknown } }) => String(e.data.text ?? ''));
    expect(texts.some((t: string) => t.includes("J'envoie ?"))).toBe(true);
  }, 20000);

  it('(h) consignes parlées : « J\'envoie. » affirmatif à l\'ouverture de la fenêtre d\'annulation', async () => {
    const { clearEvents, getRecentEvents } = require('../../src/lib/eventLog');
    clearEvents();
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Envoyé.' }, // envoi auto → undo_window
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });

    await waitFor(() => expect(result.current.state).toBe('undo_window'), { timeout: 6000 });
    await waitFor(() => {
      const texts = getRecentEvents(500)
        .filter((e: { kind: string }) => e.kind === 'tts')
        .map((e: { data: { text?: unknown } }) => String(e.data.text ?? ''));
      // « J'envoie. » exact (l'affirmatif), pas la question « J'envoie ? ».
      expect(texts.some((t: string) => t.trim() === "J'envoie.")).toBe(true);
    }, { timeout: 4000 });
  }, 20000);

  it("(i) loud failure : 2 transcripts vides consécutifs → l'app AVOUE qu'elle ne comprend pas", async () => {
    // Device 2026-08-04 : 4 transcriptions vides d'affilée en choosing (voix
    // bien captée, texte vide) → ré-écoute MUETTE en boucle, l'utilisateur
    // parlait dans le vide et a abandonné (RESET). Après 2 vides consécutifs,
    // consigne parlée avant de rouvrir le micro.
    const { clearEvents, getRecentEvents } = require('../../src/lib/eventLog');
    clearEvents();
    scriptStt([
      { kind: 'ok', transcript: '' },
      { kind: 'ok', transcript: '' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => {
      const texts = getRecentEvents(500)
        .filter((e: { kind: string }) => e.kind === 'tts')
        .map((e: { data: { text?: unknown } }) => String(e.data.text ?? ''));
      expect(texts.some((t: string) => t.includes('comprends pas'))).toBe(true);
    }, { timeout: 6000 });
  }, 15000);

  it("(j) « Annulé. » en relecture ANNULE la réponse (pas une regénération, pas un silence)", async () => {
    // Device 2026-08-04 : en reviewing, « Annulé. » partait en texte libre →
    // regénération du brouillon avec "Annulé" comme instruction ; le second
    // « Annulé » mourait en silence (cmd non géré, pas de filet). L'utilisateur
    // était coincé sur le même email.
    scriptStt([
      { kind: 'ok', transcript: 'Répondre.' },
      { kind: 'ok', transcript: 'je confirme pour demain' },
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'ok', transcript: 'Oui.' },     // rédige (pas d'envoi auto)
      { kind: 'ok', transcript: 'Non.' },     // asking_send → reviewing
      { kind: 'ok', transcript: 'Annulé.' },  // ← doit ANNULER la réponse
      { kind: 'no_voice', listenMs: 30 },
      { kind: 'no_voice', listenMs: 30 },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    await waitFor(() => expect(result.current.state).toBe('listening'), { timeout: 4000 });
    await waitFor(() => expect(result.current.transcript).toBe('je confirme pour demain'), { timeout: 4000 });
    await act(async () => { result.current.finishDictation(); });

    // NE PAS attendre asking_send/reviewing : transitoires — « Non. » puis
    // « Annulé. » les consomment parfois avant l'échantillonnage de waitFor
    // (même leçon que le test (e)). On attend l'issue STABLE : retour menu.
    await waitFor(() => expect(result.current.state).toBe('choosing'), { timeout: 8000 });
    expect(result.current.draftContent).toBeNull();
    // Une SEULE génération (l'originale) — « Annulé » n'a pas regénéré.
    expect(mockGenerateFast).toHaveBeenCalledTimes(1);
  }, 20000);

  it('(c) résilience : une rafale de transcripts vides ne bloque pas la session', async () => {
    scriptStt([
      { kind: 'ok', transcript: '' },
      { kind: 'ok', transcript: '' },
      { kind: 'ok', transcript: '' },
      { kind: 'ok', transcript: 'Suivant.' },
    ]);
    const { result } = renderDrive();
    await startSessionAndReachChoosing(result);

    // Les vides déclenchent le retry auto ; « Suivant. » doit finir par passer.
    await waitFor(() => expect(result.current.currentIndex).toBe(1), { timeout: 8000 });
    expect(remainingTurns()).toBe(0);
  }, 20000);
});
