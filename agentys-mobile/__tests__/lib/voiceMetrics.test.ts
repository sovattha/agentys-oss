/**
 * VoiceMetricsCollector — la mesure voice-to-voice ne doit JAMAIS coûter
 * quoi que ce soit à l'UX : pas de double comptage, pas de retry réseau,
 * flush batché.
 */
import { VoiceMetricsCollector } from '../../src/lib/voiceMetrics';

describe('VoiceMetricsCollector', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-06-10T10:00:00Z'));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('mesure turn_latency_ms entre fin de parole et début TTS', async () => {
    const collector = new VoiceMetricsCollector();
    const sent: any[] = [];
    collector.configure(async (events) => { sent.push(...events); });

    collector.markUserSpeechEnd();
    jest.advanceTimersByTime(1450);
    collector.markAiSpeakStart('choosing');

    await collector.flush();
    expect(sent).toEqual([
      { kind: 'turn_latency_ms', value_ms: 1450, state: 'choosing' },
    ]);
  });

  it('mesure stt_latency_ms indépendamment', async () => {
    const collector = new VoiceMetricsCollector();
    const sent: any[] = [];
    collector.configure(async (events) => { sent.push(...events); });

    collector.markUserSpeechEnd();
    jest.advanceTimersByTime(800);
    collector.markTranscriptReady('listening');
    jest.advanceTimersByTime(700);
    collector.markAiSpeakStart('generating');

    await collector.flush();
    expect(sent).toEqual([
      { kind: 'stt_latency_ms', value_ms: 800, state: 'listening' },
      { kind: 'turn_latency_ms', value_ms: 1500, state: 'generating' },
    ]);
  });

  it('pas de double comptage : un seul turn par prise de parole', async () => {
    const collector = new VoiceMetricsCollector();
    const sent: any[] = [];
    collector.configure(async (events) => { sent.push(...events); });

    collector.markUserSpeechEnd();
    collector.markAiSpeakStart('a');
    collector.markAiSpeakStart('b'); // TTS chunk 2, 3… ne recomptent pas
    collector.markAiSpeakStart('c');

    await collector.flush();
    expect(sent.filter((e) => e.kind === 'turn_latency_ms')).toHaveLength(1);
  });

  it('markAiSpeakStart sans speech end préalable → ignoré (TTS spontanée)', async () => {
    const collector = new VoiceMetricsCollector();
    const sent: any[] = [];
    collector.configure(async (events) => { sent.push(...events); });
    collector.markAiSpeakStart('speaking'); // ex: annonce d'ouverture
    await collector.flush();
    expect(sent).toHaveLength(0);
  });

  it('compteurs accumulés et flush batché', async () => {
    const collector = new VoiceMetricsCollector();
    const batches: any[][] = [];
    collector.configure(async (events) => { batches.push(events); });

    collector.counter('barge_ins', 'speaking');
    collector.counter('undo_cancels', 'choosing');
    await collector.flush();

    expect(batches).toHaveLength(1);
    expect(batches[0]).toEqual([
      { kind: 'barge_ins', count: 1, state: 'speaking' },
      { kind: 'undo_cancels', count: 1, state: 'choosing' },
    ]);
    expect(collector.pendingCount()).toBe(0);
  });

  it('échec réseau → événements jetés, pas de retry, pas de throw', async () => {
    const collector = new VoiceMetricsCollector();
    const sender = jest.fn().mockRejectedValue(new Error('offline'));
    collector.configure(sender);
    collector.counter('false_restarts');
    await expect(collector.flush()).resolves.toBeUndefined();
    expect(sender).toHaveBeenCalledTimes(1);
    // Pas re-tenté au flush suivant
    await collector.flush();
    expect(sender).toHaveBeenCalledTimes(1);
  });

  it('flush sans sender configuré → no-op silencieux', async () => {
    const collector = new VoiceMetricsCollector();
    collector.counter('barge_ins');
    await expect(collector.flush()).resolves.toBeUndefined();
  });

  it('endSession flush et stoppe le timer périodique', async () => {
    const collector = new VoiceMetricsCollector();
    const sender = jest.fn().mockResolvedValue(undefined);
    collector.configure(sender);
    collector.startSession();
    collector.counter('barge_ins');
    collector.endSession();
    await Promise.resolve();
    expect(sender).toHaveBeenCalledTimes(1);
    // Le timer 60s ne tourne plus
    collector.counter('barge_ins');
    jest.advanceTimersByTime(120_000);
    expect(sender).toHaveBeenCalledTimes(1);
  });
});
