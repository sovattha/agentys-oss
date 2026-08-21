const STORAGE_KEY = "agentys_ui_sounds_enabled";

type SoundType = "send" | "draftReady" | "archive" | "delete" | "recordStart" | "recordStop";

const audioCtxRef: { ctx: AudioContext | null } = { ctx: null };

function getAudioCtx(): AudioContext {
  if (!audioCtxRef.ctx) {
    audioCtxRef.ctx = new AudioContext();
  }
  return audioCtxRef.ctx;
}

const SOUND_CONFIGS: Record<SoundType, { freq: number; duration: number; type: OscillatorType; ramp?: number }[]> = {
  send: [
    { freq: 600, duration: 0.08, type: "sine" },
    { freq: 900, duration: 0.08, type: "sine" },
    { freq: 1200, duration: 0.12, type: "sine" },
  ],
  draftReady: [
    { freq: 523, duration: 0.1, type: "sine" },
    { freq: 659, duration: 0.1, type: "sine" },
    { freq: 784, duration: 0.15, type: "sine" },
  ],
  archive: [
    { freq: 400, duration: 0.06, type: "triangle" },
    { freq: 500, duration: 0.08, type: "triangle" },
  ],
  delete: [
    { freq: 300, duration: 0.08, type: "square", ramp: 150 },
  ],
  recordStart: [
    { freq: 440, duration: 0.06, type: "sine" },
    { freq: 660, duration: 0.08, type: "sine" },
  ],
  recordStop: [
    { freq: 660, duration: 0.06, type: "sine" },
    { freq: 440, duration: 0.1, type: "sine" },
  ],
};

export function isUISoundsEnabled(): boolean {
  return localStorage.getItem(STORAGE_KEY) === "true";
}

export function setUISoundsEnabled(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
}

export function playUISound(sound: SoundType): void {
  if (!isUISoundsEnabled()) return;

  try {
    const ctx = getAudioCtx();
    const notes = SOUND_CONFIGS[sound];
    let offset = 0;
    const volume = 0.15;

    for (const note of notes) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = note.type;
      osc.frequency.setValueAtTime(note.freq, ctx.currentTime + offset);
      if (note.ramp) {
        osc.frequency.linearRampToValueAtTime(note.ramp, ctx.currentTime + offset + note.duration);
      }
      gain.gain.setValueAtTime(volume, ctx.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + offset + note.duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + offset);
      osc.stop(ctx.currentTime + offset + note.duration + 0.05);
      offset += note.duration;
    }
  } catch {
    // Web Audio API not available
  }
}
