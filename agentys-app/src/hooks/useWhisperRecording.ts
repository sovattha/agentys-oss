/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import i18n from '../i18n'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'
import { playUISound } from '../services/uiSounds'
import {
  queryMicPermissionState,
  hasUserAcknowledgedMicSoftAsk,
  setUserAcknowledgedMicSoftAsk,
} from '../services/micPermission'

const NUM_BARS = 48
const SILENCE_THRESHOLD_DEFAULT = 0.12   // fallback when adaptive calibration didn't produce a usable noise floor
const SILENCE_THRESHOLD_MIN = 0.06       // floor for adaptive threshold — below this is too sensitive (breathing triggers)
const SILENCE_THRESHOLD_MAX = 0.20       // cap for adaptive threshold — above this we'd never auto-stop
const CALIBRATION_MS = 200               // first 200ms after mic-on used to sample ambient noise floor
const NOISE_MULTIPLIER = 2.5             // dynamicThreshold = noiseFloor × this (clamped)
const MIN_SPEECH_CONFIRM_MS = 500 // sustained ms above threshold required before triggering silence countdown
const WAVEFORM_HISTORY_LENGTH = 60  // ~1 second at 60fps
const PEAK_THRESHOLD = 0.7  // bars above this amplitude trigger particles
const PTT_SILENT_ABORT_MS = 120  // release this fast after PTT kicks in = silent cancel (no transcription, no error)
const PREWARM_IDLE_TIMEOUT_MS = 30_000  // release the pre-warmed mic stream after this many ms of inactivity
const TRANSCRIBE_TIMEOUT_MS = 60_000    // hard timeout per transcription attempt
const RETRY_BACKOFF_MS = 1_500          // delay before single retry on transient failure
const SILENT_DROP_BLOB_BYTES = 5_000    // audio under this size with no confirmed speech → silent drop (likely hallucination)

function debugLog(...args: unknown[]) {
  if (import.meta.env.DEV) console.debug(...args)
}

// Force browser-level cleanup for speech capture; raw `audio: true` lets some
// browsers disable these defaults, which hurts STT signal-to-noise ratio.
const AUDIO_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
}

/** Whisper hallucinations returned on silent audio — treat as empty transcript. */
const WHISPER_HALLUCINATIONS = [
  'amara.org',
  'sous-titres réalisés',
  'sous-titres par',
  'subtitles by',
  'transcribed by',
  'www.microsoft.com',
  'merci d\'avoir regardé',
  'thank you for watching',
]

// Module-level PTT lock — prevents two mounted hook instances (e.g. PendingDraftDetail
// + ReplyComposer) from racing the same Space keypress and starting two
// MediaRecorders. The first instance to claim Space keeps it until release.
let _activePttOwner: symbol | null = null

function isHallucination(text: string): boolean {
  const lower = text.toLowerCase()
  if (WHISPER_HALLUCINATIONS.some(h => lower.includes(h))) return true
  // Reject transcripts that are only punctuation/symbols with no real words
  if (text.replace(/[^a-zA-ZÀ-ÿ0-9]/g, '').length < 2) return true
  return false
}

/**
 * Décide si une transcription doit être REJOUÉE en auto-détection.
 *
 * Vrai uniquement quand (1) une langue SPÉCIFIQUE était épinglée (ni undefined,
 * ni 'auto', ni ''), (2) de la parole a été détectée, et (3) le transcript est
 * vide. C'est la signature « mauvais pin → Deepgram rend vide » (incident
 * 2026-06-11). Le garde-fou `hasSpoke` évite un aller-retour inutile sur un vrai
 * silence. NB : ne couvre PAS le transcript NON-vide mais mal transcrit.
 * Exporté pour test unitaire (le filet est ce qui rend sûr le défaut destinataire).
 */
export function shouldRetryAutoDetectOnEmpty(
  pinnedLang: string | undefined,
  hasSpoke: boolean,
  transcriptText: string | undefined,
): boolean {
  const pinned = pinnedLang !== undefined && pinnedLang !== 'auto' && pinnedLang !== ''
  return pinned && hasSpoke && !(transcriptText || '').trim()
}

/** Escape HTML special chars to prevent XSS when interpolating transcripts into HTML. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Adaptive silence timeout based on cumulative speech duration (~2.5 words/sec). */
function getAdaptiveSilenceTimeout(speechMs: number): number {
  if (speechMs < 4_000)  return 1.5   // short message (<~10 words)
  if (speechMs < 20_000) return 2.5   // medium message (~10-50 words)
  return 3.5                           // long message (>~50 words)
}

// Container preference order. Safari (< 18.4) cannot record webm at all — it
// records AAC in an mp4 container, so an unconditional 'audio/webm' fallback
// throws NotSupportedError there and dictation never starts.
const RECORDING_MIME_CANDIDATES = [
  'audio/webm;codecs=opus', // Chrome / Edge / Firefox
  'audio/webm',
  'audio/mp4;codecs=mp4a.40.2', // Safari ≤ 18.3
  'audio/mp4',
]

/** First recordable container, or undefined to let the browser pick its native default. */
export function pickRecordingMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return undefined
  }
  return RECORDING_MIME_CANDIDATES.find(c => MediaRecorder.isTypeSupported(c))
}

/**
 * Upload filename derived from the blob's real container. The backend's
 * OpenAI Whisper fallback infers the decoder from the extension — a Safari
 * mp4 named `.webm` would be rejected there.
 */
export function transcribeFilename(blobType: string): string {
  const t = (blobType || '').toLowerCase()
  if (t.includes('mp4') || t.includes('aac')) return 'recording.mp4'
  if (t.includes('ogg')) return 'recording.ogg'
  return 'recording.webm'
}

/**
 * Hook for Whisper voice dictation — shared by NewMessageModal and ReplyComposer.
 *
 * Shows a mic button when body is empty. Records audio via MediaRecorder,
 * sends to POST /api/transcribe, and injects the transcript via onTranscript.
 *
 * Exposes real-time audio levels (via AnalyserNode) for waveform visualization.
 * Auto-stops after SILENCE_TIMEOUT_SEC of continuous silence.
 *
 * Returns:
 * - isRecording, isTranscribing, showMicButton, handleMicClick
 * - audioLevels: current frame frequency levels (0-1 per bar)
 * - formattedTime: M:SS format of elapsed recording time
 * - silenceDetected: true when silence is detected after speech
 * - silenceCountdown: seconds remaining before auto-stop (0 when not in silence)
 * - waveformHistory: scrolling buffer of past ~60 level snapshots
 * - peakBars: array of bar indices currently above PEAK_THRESHOLD
 */
export interface UseWhisperRecordingOptions {
  /** ISO 639-1 code (fr, en, es, ...). Overrides navigator.language. Empty/undefined → fallback to navigator.language. */
  language?: string
  /** Extra vocabulary words/phrases to bias Whisper toward product and project terms. */
  promptVocabulary?: string[]
  /** Feature gate: false disables button state, prewarm and push-to-talk activation. */
  enabled?: boolean
  /**
   * CSS selector of THIS instance's compose surface. The Space push-to-talk
   * only activates when focus is inside it. Without a per-instance scope,
   * the first-mounted instance (e.g. PendingDraftDetail under an open
   * NewMessageModal) claims the module-level PTT lock for a keypress aimed
   * at another surface and records into the wrong editor (bug 2026-06-09).
   * Defaults to the legacy compose contexts for callers not yet migrated.
   */
  surfaceSelector?: string
}

const DEFAULT_SURFACE_SELECTOR = '.new-message-modal, .reply-composer'

export function useWhisperRecording(
  bodyIsEmpty: boolean,
  aiPromptEmpty: boolean,
  onTranscript: (html: string) => void,
  options?: UseWhisperRecordingOptions,
) {
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [transcriptionError, setTranscriptionError] = useState<string | null>(null)
  const [audioLevels, setAudioLevels] = useState<number[]>(() => new Array(NUM_BARS).fill(0))
  const [elapsed, setElapsed] = useState(0)
  const [silenceDetected, setSilenceDetected] = useState(false)
  const [silenceCountdown, setSilenceCountdown] = useState(0)
  const [waveformHistory, setWaveformHistory] = useState<number[][]>([])
  const [peakBars, setPeakBars] = useState<number[]>([])
  const dictationEnabled = options?.enabled !== false

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animFrameRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const silenceSinceRef = useRef<number | null>(null)
  const hasSpokeRef = useRef(false)
  const speechDurationRef = useRef(0)
  const speechConsecutiveMsRef = useRef(0) // ms continuously above threshold
  const lastFrameTimeRef = useRef(0)
  const waveformHistoryRef = useRef<number[][]>([])
  const mountedRef = useRef(true)
  const uploadAbortRef = useRef<AbortController | null>(null)

  const showMicButton = dictationEnabled && bodyIsEmpty && aiPromptEmpty
  const smoothedRef = useRef<number[]>(new Array(NUM_BARS).fill(0))

  // Push-to-talk refs (stable across renders for document event listeners)
  const pushToTalkRef = useRef(false)
  const isRecordingRef = useRef(false)
  const isTranscribingRef = useRef(false)
  const showMicButtonRef = useRef(showMicButton)
  const dictationEnabledRef = useRef(dictationEnabled)
  const handleMicClickRef = useRef<() => void>(() => {})
  const startRecordingRef = useRef<(s?: Promise<MediaStream>) => void>(() => {})
  const prewarmStreamRef = useRef<Promise<MediaStream> | null>(null)
  const prewarmReleaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Track when a recording was started via the fast-path so we can silently abort on a quick release
  const recordingStartedAtRef = useRef(0)
  const silentAbortRef = useRef(false)

  // Adaptive VAD calibration — sample the noise floor during the first CALIBRATION_MS,
  // then derive a dynamic silence threshold. Falls back to SILENCE_THRESHOLD_DEFAULT if
  // calibration was inconclusive (e.g. user spoke immediately).
  const calibrationStartRef = useRef(0)
  const noiseFloorMaxRef = useRef(0)
  const noiseFloorSumRef = useRef(0)
  const noiseFloorCountRef = useRef(0)
  const dynamicThresholdRef = useRef(SILENCE_THRESHOLD_DEFAULT)

  // Stable ref for the user's preferred language (avoids re-creating startRecording on every render)
  const languageRef = useRef<string | undefined>(options?.language)
  useEffect(() => { languageRef.current = options?.language }, [options?.language])
  const promptVocabularyRef = useRef<string[] | undefined>(options?.promptVocabulary)
  useEffect(() => { promptVocabularyRef.current = options?.promptVocabulary }, [options?.promptVocabulary])

  // Format elapsed seconds as M:SS
  const formattedTime = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`

  // Animate waveform from AnalyserNode frequency data
  const updateLevels = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return
    const data = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteFrequencyData(data)

    // Delta time for speech duration accumulation
    const now2 = Date.now()
    const dt = lastFrameTimeRef.current ? now2 - lastFrameTimeRef.current : 0
    lastFrameTimeRef.current = now2

    const step = Math.floor(data.length / NUM_BARS)
    const prev = smoothedRef.current
    const now = Date.now() / 1000
    const levels: number[] = []

    // Compute average energy across ALL frequency bins for silence detection
    // (per-bar peak is too noisy with only 2-3 bins per bar)
    let totalEnergy = 0
    for (let i = 0; i < data.length; i++) totalEnergy += data[i]
    const avgEnergy = totalEnergy / data.length / 255

    // Adaptive VAD calibration — first CALIBRATION_MS sample ambient noise.
    // We track both max and mean: max guards against transient bumps, mean
    // smooths legitimate ambient hum. Final floor = max(mean, max × 0.6).
    if (calibrationStartRef.current > 0) {
      const sinceStart = now2 - calibrationStartRef.current
      if (sinceStart <= CALIBRATION_MS) {
        if (avgEnergy < 0.30) { // ignore frames where user spoke during calibration
          noiseFloorMaxRef.current = Math.max(noiseFloorMaxRef.current, avgEnergy)
          noiseFloorSumRef.current += avgEnergy
          noiseFloorCountRef.current += 1
        }
      } else if (sinceStart < CALIBRATION_MS + 50) { // run finalization once, ~one frame after
        const count = noiseFloorCountRef.current
        if (count >= 3) {
          const mean = noiseFloorSumRef.current / count
          const noiseFloor = Math.max(mean, noiseFloorMaxRef.current * 0.6)
          const dynamic = Math.min(
            SILENCE_THRESHOLD_MAX,
            Math.max(SILENCE_THRESHOLD_MIN, noiseFloor * NOISE_MULTIPLIER),
          )
          dynamicThresholdRef.current = dynamic
          debugLog(`[Whisper] VAD calibrated: noiseFloor=${noiseFloor.toFixed(3)} → threshold=${dynamic.toFixed(3)}`)
        } else {
          // User spoke immediately — keep default threshold (still safe)
          dynamicThresholdRef.current = SILENCE_THRESHOLD_DEFAULT
        }
        calibrationStartRef.current = 0 // mark calibration complete
      }
    }
    const silenceThreshold = dynamicThresholdRef.current

    for (let i = 0; i < NUM_BARS; i++) {
      let sum = 0
      for (let j = 0; j < step; j++) sum += data[i * step + j]
      const raw = Math.min(1, (sum / step) / 200)
      // Exponential smoothing — fast attack (0.35), slow release (0.88)
      const alpha = raw > prev[i] ? 0.35 : 0.88
      const smoothed = prev[i] * alpha + raw * (1 - alpha)
      // Idle breathing — subtle sine ripple when quiet
      const idle = 0.015 + Math.sin(now * 1.8 + i * 0.35) * 0.012
      levels.push(Math.max(idle, smoothed))
    }
    smoothedRef.current = levels
    setAudioLevels(levels)

    // Update waveform history (scrolling buffer)
    waveformHistoryRef.current.push([...levels])
    if (waveformHistoryRef.current.length > WAVEFORM_HISTORY_LENGTH) {
      waveformHistoryRef.current.shift()
    }
    setWaveformHistory([...waveformHistoryRef.current])

    // Detect peak bars
    const peaks = levels
      .map((level, idx) => level > PEAK_THRESHOLD ? idx : -1)
      .filter(idx => idx !== -1)
    setPeakBars(peaks)

    // Auto-stop on prolonged silence (uses average energy across all bins,
    // not smoothed visual levels which include idle breathing animation).
    // Timeout adapts to speech length: short messages stop faster.
    // Skip auto-stop during push-to-talk — user controls stop by releasing Space.
    if (pushToTalkRef.current) {
      // Still track speech for duration stats, but never auto-stop
      if (avgEnergy > silenceThreshold) {
        speechConsecutiveMsRef.current += dt
        speechDurationRef.current += dt
        if (speechConsecutiveMsRef.current >= MIN_SPEECH_CONFIRM_MS) {
          hasSpokeRef.current = true
        }
      } else {
        speechConsecutiveMsRef.current = 0
      }
      silenceSinceRef.current = null
      setSilenceDetected(false)
      setSilenceCountdown(0)
    } else if (avgEnergy > silenceThreshold) {
      speechConsecutiveMsRef.current += dt
      speechDurationRef.current += dt
      // Only mark "has spoke" after sustained speech to avoid false triggers from mic noise
      if (speechConsecutiveMsRef.current >= MIN_SPEECH_CONFIRM_MS) {
        hasSpokeRef.current = true
      }
      silenceSinceRef.current = null
      setSilenceDetected(false)
      setSilenceCountdown(0)
    } else if (hasSpokeRef.current) {
      speechConsecutiveMsRef.current = 0
      if (!silenceSinceRef.current) {
        silenceSinceRef.current = Date.now()
      }
      const timeSilent = Date.now() - silenceSinceRef.current
      const timeout = getAdaptiveSilenceTimeout(speechDurationRef.current)
      const secsRemaining = Math.ceil(timeout - timeSilent / 1000)
      setSilenceDetected(true)
      setSilenceCountdown(Math.max(0, secsRemaining))

      if (timeSilent > timeout * 1000) {
        mediaRecorderRef.current?.stop()
        return
      }
    }

    animFrameRef.current = requestAnimationFrame(updateLevels)
  }, [])

  const acquiringMicRef = useRef(false)

  // Single transcription HTTP attempt — exposed so transcribeBlob can retry.
  const attemptTranscribe = useCallback(async (blob: Blob, durationSeconds = 0, forceAuto = false): Promise<Response> => {
    const formData = new FormData()
    formData.append('audio', blob, transcribeFilename(blob.type))
    if (durationSeconds > 0) {
      formData.append('duration_seconds', String(durationSeconds))
    }
    // Language semantics from caller :
    //   - 'auto' or '' → omit on the wire → backend uses detect_language=true.
    //   - 'fr'/'en'/... → forwarded as lang param.
    //   - undefined (no language option) → fall through to localStorage UI lang.
    //
    // We deliberately do NOT use navigator.language as a fallback : a user with
    // Windows in English (navigator='en-US') may speak French. Forcing lang=en
    // makes Deepgram mangle French speech into garbled English ("you just got
    // some of these" for "tu as juste eu quelques-uns de ceux-ci").
    let userLang = ''
    // forceAuto : court-circuite la langue épinglée pour rejouer la même audio
    // en détection automatique (fallback « transcript vide », cf. transcribeBlob).
    const explicit = forceAuto ? 'auto' : languageRef.current
    if (explicit !== undefined) {
      userLang = (explicit === 'auto') ? '' : explicit
    } else if (typeof localStorage !== 'undefined') {
      const stored = localStorage.getItem('agentys_language')
      if (stored && ['fr', 'en', 'es'].includes(stored)) userLang = stored
    }
    const langCode = userLang.split('-')[0]?.toLowerCase()
    if (langCode) formData.append('lang', langCode)
    const basePrompt = 'Agentys. Bonjour. Hi.'
    const extras = (promptVocabularyRef.current || [])
      .map(s => s.trim())
      .filter(Boolean)
      .join(', ')
    formData.append('prompt', (extras ? `${basePrompt} ${extras}.` : basePrompt).slice(0, 224))

    const controller = new AbortController()
    uploadAbortRef.current = controller
    const timeoutId = setTimeout(() => {
      try { controller.abort('timeout') } catch { controller.abort() }
    }, TRANSCRIBE_TIMEOUT_MS)
    try {
      return await fetch(`${API_URL}/api/transcribe`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
        body: formData,
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timeoutId)
    }
  }, [])

  // Transcribe with one transparent retry on transient errors (network, timeout, 5xx).
  // The audio Blob lives in RAM until the function returns, so re-sending it costs nothing.
  // User-initiated cancels (Esc / unmount) are not retried — we surface the AbortError.
  const transcribeBlob = useCallback(async (blob: Blob, durationSeconds = 0): Promise<{ text?: string }> => {
    const isTimeoutAbort = (err: unknown): boolean => {
      const e = err as Error & { cause?: unknown }
      if (e?.name !== 'AbortError') return false
      return e?.cause === 'timeout'
        || /timeout/i.test(String(e?.message || ''))
        || uploadAbortRef.current?.signal?.reason === 'timeout'
    }
    const isUserAbort = (err: unknown): boolean =>
      (err as Error)?.name === 'AbortError' && !isTimeoutAbort(err)

    let response: Response
    try {
      response = await attemptTranscribe(blob, durationSeconds)
    } catch (err) {
      if (!mountedRef.current || isUserAbort(err)) throw err
      console.warn(`[Whisper] First attempt failed (${(err as Error)?.message || 'network'}), retrying in ${RETRY_BACKOFF_MS}ms...`)
      await new Promise(r => setTimeout(r, RETRY_BACKOFF_MS))
      if (!mountedRef.current) throw new Error('unmounted', { cause: err })
      response = await attemptTranscribe(blob, durationSeconds)
    }

    // Retry once on 5xx (transient backend issue).
    if (!response.ok && response.status >= 500 && response.status < 600 && mountedRef.current) {
      console.warn(`[Whisper] HTTP ${response.status}, retrying in ${RETRY_BACKOFF_MS}ms...`)
      await new Promise(r => setTimeout(r, RETRY_BACKOFF_MS))
      if (!mountedRef.current) throw new Error('unmounted')
      response = await attemptTranscribe(blob, durationSeconds)
    }

    if (!response.ok) {
      const errBody = await response.text().catch(() => '')
      console.error(`[Whisper] HTTP ${response.status}: ${errBody}`)
      let kind: string | undefined
      let bodyError: string | undefined
      try {
        const parsed = JSON.parse(errBody) as { error?: string; kind?: string }
        kind = parsed.kind
        bodyError = parsed.error
      } catch { /* non-JSON body — fall through */ }
      const err = new Error(`http_${response.status}`) as Error & {
        status?: number; kind?: string; bodyError?: string
      }
      err.status = response.status
      err.kind = kind
      err.bodyError = bodyError
      throw err
    }

    const result = (await response.json()) as { text?: string }
    // Fallback langue épinglée → auto-détection. Quand une langue SPÉCIFIQUE a
    // été demandée (défaut destinataire OU choix du picker) et que Deepgram
    // renvoie un transcript vide ALORS QUE de la parole a été détectée, la cause
    // la plus probable est un décalage de langue (l'utilisateur a parlé une
    // autre langue que la langue épinglée — incident 2026-06-11 : pinné En,
    // parlé Fr 23 s → vide, dictée perdue). On rejoue UNE fois la même audio en
    // détection automatique pour ne pas perdre la dictée. Garde-fou : seulement
    // si parole détectée (hasSpokeRef), pour éviter un aller-retour inutile sur
    // un vrai silence (où le re-essai serait vide lui aussi).
    // PORTÉE : ce filet rattrape le transcript VIDE (symptôme dominant de
    // l'incident), PAS le transcript NON-vide mais MAL transcrit (cf. ~l.353 :
    // un pin erroné peut produire du charabia plausible « en ») — ce cas-là
    // reste injecté tel quel, à l'utilisateur de corriger la langue (badge).
    if (
      shouldRetryAutoDetectOnEmpty(languageRef.current, hasSpokeRef.current, result?.text) &&
      mountedRef.current
    ) {
      debugLog('[Whisper] Pinned-language transcript empty — retrying with auto-detect')
      try {
        const autoResp = await attemptTranscribe(blob, durationSeconds, true)
        if (autoResp.ok) return (await autoResp.json()) as { text?: string }
      } catch { /* on conserve le résultat vide d'origine */ }
    }
    return result
  }, [attemptTranscribe])

  const startRecording = useCallback(async (prewarmedStream?: Promise<MediaStream>) => {
    if (acquiringMicRef.current) return // Guard against double-click race condition
    acquiringMicRef.current = true
    setTranscriptionError(null)
    try {
      const stream = prewarmedStream
        ? await prewarmedStream
        : await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS)

      // Set up AnalyserNode for real-time waveform visualization.
      // Wrapped in try-catch: non-critical — recording works without it.
      let audioCtx: AudioContext | null = null
      try {
        audioCtx = new AudioContext()
        const source = audioCtx.createMediaStreamSource(stream)
        const analyser = audioCtx.createAnalyser()
        analyser.fftSize = 256
        analyser.smoothingTimeConstant = 0.7
        source.connect(analyser)
        analyserRef.current = analyser
      } catch (e) {
        console.warn('[Whisper] AudioContext setup failed, recording without waveform:', e)
        audioCtx = null
        analyserRef.current = null
      }

      const mimeType = pickRecordingMimeType()
      // 32kbps Opus is indistinguishable from higher bitrates for speech and halves
      // upload size vs 64kbps — measurable win on 4G / public wifi, no quality loss.
      const recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 32_000,
      })
      mediaRecorderRef.current = recorder
      audioChunksRef.current = []

      // Reset recording state
      setElapsed(0)
      setSilenceDetected(false)
      setSilenceCountdown(0)
      hasSpokeRef.current = false
      silenceSinceRef.current = null
      speechDurationRef.current = 0
      speechConsecutiveMsRef.current = 0
      lastFrameTimeRef.current = 0
      waveformHistoryRef.current = []
      smoothedRef.current = new Array(NUM_BARS).fill(0)
      // Reset adaptive VAD calibration for this session
      calibrationStartRef.current = Date.now()
      noiseFloorMaxRef.current = 0
      noiseFloorSumRef.current = 0
      noiseFloorCountRef.current = 0
      dynamicThresholdRef.current = SILENCE_THRESHOLD_DEFAULT

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        // Stop visualizer + timer
        cancelAnimationFrame(animFrameRef.current)
        if (timerRef.current) clearInterval(timerRef.current)
        analyserRef.current = null

        if (audioCtx) audioCtx.close().catch(() => {})
        stream.getTracks().forEach(t => t.stop())

        setIsRecording(false)
        setAudioLevels(new Array(NUM_BARS).fill(0))
        setSilenceDetected(false)
        setSilenceCountdown(0)
        setWaveformHistory([])
        setPeakBars([])

        // Play recording stop sound
        playUISound('recordStop')

        // Silent abort — Option 1 fast-start followed by a too-short release (user mis-tapped space in empty field).
        // Skip error display + transcription; we treat it as a no-op.
        if (silentAbortRef.current) {
          silentAbortRef.current = false
          return
        }

        const durationSeconds = recordingStartedAtRef.current > 0
          ? Math.max(1, Math.round((Date.now() - recordingStartedAtRef.current) / 1000))
          : 0
        const audioBlob = new Blob(audioChunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })

        // Heuristic hallucination guard — tiny audio with no confirmed speech is
        // almost certainly silence. Whisper still produces text for these (the
        // famous "amara.org" / "merci d'avoir regardé" outputs); drop silently
        // instead of bothering the user with an error toast.
        if (audioBlob.size < SILENT_DROP_BLOB_BYTES && !hasSpokeRef.current) {
          debugLog(`[Whisper] Silent drop: ${audioBlob.size}B audio, no speech confirmed`)
          return
        }

        if (audioBlob.size < 1000) {
          setTranscriptionError(i18n.t('errors:mic_no_audio'))
          return
        }

        setTranscriptionError(null)
        setIsTranscribing(true)
        try {
          debugLog(`[Whisper] Sending ${(audioBlob.size / 1024).toFixed(1)}KB ${audioBlob.type}`)
          const data = await transcribeBlob(audioBlob, durationSeconds)
          if (!mountedRef.current) return
          const transcript: string = data?.text ?? ''
          debugLog(`[Whisper] Transcript: "${transcript}"`)
          if (transcript.trim() && !isHallucination(transcript)) {
            onTranscript(`<p>${escapeHtml(transcript)}</p>`)
          } else {
            // Nothing usable: empty transcript or hallucinated filler — drop
            // silently. NB historique : un hint « Aucune parole détectée »
            // avait été ajouté ici (rapport 2026-06-09, silence total lu comme
            // « micro cassé ») puis RETIRÉ à la demande explicite de
            // l'utilisateur (2026-06-11) : pas d'avertissement quand il n'y a
            // pas de parole. Ne pas le réintroduire.
            debugLog('[Whisper] No usable speech — silent drop (user pref 2026-06-11)')
          }
        } catch (err) {
          // AbortError peut venir de 3 sources :
          //  1. Cleanup d'unmount → on laisse silencieux
          //  2. Notre setTimeout 60s qui a abort() avec reason='timeout'
          //  3. Cancel manuel utilisateur (Esc / ré-enregistrement immédiat)
          if ((err as Error)?.name === 'AbortError') {
            const isTimeout = (err as { cause?: unknown })?.cause === 'timeout'
              || /timeout/i.test(String((err as Error)?.message || ''))
              || (uploadAbortRef.current?.signal?.reason === 'timeout')
            if (isTimeout && mountedRef.current) {
              console.warn('[Whisper] Transcription timeout (after retry)')
              setTranscriptionError(i18n.t('errors:transcription_too_slow'))
            }
            return
          }
          if (!mountedRef.current) return
          if ((err as Error)?.message === 'unmounted') return
          const status = (err as { status?: number })?.status
          const kind = (err as { kind?: string })?.kind
          if (status) {
            // Backend signals "audio unusable" (Deepgram + Whisper both rejected
            // the bytes — usually a too-short/malformed MediaRecorder blob, i.e.
            // the user said nothing). Drop silently like empty transcripts above
            // instead of showing an error toast.
            if (kind === 'bad_audio' || status === 422) {
              debugLog('[Whisper] Backend rejected audio as unusable — silent drop')
            } else {
              setTranscriptionError(i18n.t('errors:transcription_failed_status', { status }))
            }
            return
          }
          console.error('[Whisper] Transcription error:', err)
          setTranscriptionError(i18n.t('errors:transcription_network'))
        } finally {
          uploadAbortRef.current = null
          if (mountedRef.current) setIsTranscribing(false)
        }
      }

      setIsRecording(true)

      // Play recording start sound
      playUISound('recordStart')

      // Start timer for elapsed time
      timerRef.current = setInterval(() => {
        setElapsed(prev => prev + 1)
      }, 1000)

      // Start recording
      recordingStartedAtRef.current = Date.now()
      recorder.start()

      // Start waveform animation
      animFrameRef.current = requestAnimationFrame(updateLevels)
    } catch (err) {
      // F-04 (audit 2026-06-11) : micro occupé par une autre app
      // (NotReadableError) ou absent (NotFoundError) → l'UI restait inerte.
      // Le cas « permission refusée » est déjà couvert en amont par le
      // soft-ask + mic_blocked dans handleMicClick — ne pas le doubler ici.
      console.error('Microphone access error:', err)
      if (mountedRef.current) {
        setTranscriptionError(i18n.t('errors:mic_unavailable'))
      }
    } finally {
      acquiringMicRef.current = false
    }
  }, [onTranscript, updateLevels, transcribeBlob])

  // Pre-warm helpers — keep a getUserMedia promise hot so the click path and the PTT path
  // can both consume it without paying mic-acquisition latency at activation time.
  const releasePrewarmNow = useCallback(() => {
    const pending = prewarmStreamRef.current
    prewarmStreamRef.current = null
    if (pending) {
      pending.then(s => s.getTracks().forEach(t => t.stop())).catch(() => {})
    }
    if (prewarmReleaseTimerRef.current) {
      clearTimeout(prewarmReleaseTimerRef.current)
      prewarmReleaseTimerRef.current = null
    }
  }, [])

  const schedulePrewarmRelease = useCallback(() => {
    if (prewarmReleaseTimerRef.current) clearTimeout(prewarmReleaseTimerRef.current)
    prewarmReleaseTimerRef.current = setTimeout(() => {
      releasePrewarmNow()
    }, PREWARM_IDLE_TIMEOUT_MS)
  }, [releasePrewarmNow])

  // Kick off getUserMedia now if permission is already granted — otherwise stay dormant
  // so we never trigger an unexpected permission prompt on focus.
  const ensurePrewarm = useCallback(async () => {
    if (!dictationEnabledRef.current) return
    if (prewarmStreamRef.current) {
      schedulePrewarmRelease()
      return
    }
    try {
      const permApi = (navigator as Navigator & { permissions?: Permissions }).permissions
      if (permApi?.query) {
        const perm = await permApi.query({ name: 'microphone' as PermissionName })
        if (perm.state !== 'granted') return
      } else {
        return // Permissions API not supported — skip prewarm to avoid surprise prompts
      }
    } catch {
      return
    }
    prewarmStreamRef.current = navigator.mediaDevices
      .getUserMedia(AUDIO_CONSTRAINTS)
      .catch(err => {
        console.warn('[Whisper] Focus prewarm failed:', err)
        prewarmStreamRef.current = null
        throw err
      })
    schedulePrewarmRelease()
  }, [schedulePrewarmRelease])

  const consumePrewarm = useCallback((): Promise<MediaStream> | undefined => {
    const pending = prewarmStreamRef.current
    prewarmStreamRef.current = null
    if (prewarmReleaseTimerRef.current) {
      clearTimeout(prewarmReleaseTimerRef.current)
      prewarmReleaseTimerRef.current = null
    }
    return pending ?? undefined
  }, [])

  // Dead-man's switch : si isTranscribing reste vrai pendant >90s sans
  // résolution (fetch timeout aurait dû fire à 60s, donc 90s = ceinture+
  // bretelles), on force le reset + abort + message d'erreur. Évite tout
  // état "Transcribing..." perpétuel quel que soit le bug racine.
  useEffect(() => {
    if (!isTranscribing) return
    const guard = setTimeout(() => {
      console.warn('[Whisper] Dead-man\'s switch fired — forcing isTranscribing=false after 90s')
      try { uploadAbortRef.current?.abort() } catch { /* noop */ }
      uploadAbortRef.current = null
      if (mountedRef.current) {
        setTranscriptionError(i18n.t('errors:transcription_stuck'))
        setIsTranscribing(false)
      }
    }, 90_000)
    return () => clearTimeout(guard)
  }, [isTranscribing])

  // Reset forcé exposé au parent : appelé par NewMessageModal quand la modale
  // se ferme, pour garantir que l'état isTranscribing ne reste pas "true"
  // si le composant n'est pas démonté (cas display:none ou modale persistante).
  const forceResetTranscription = useCallback(() => {
    try { uploadAbortRef.current?.abort() } catch { /* noop */ }
    uploadAbortRef.current = null
    if (mountedRef.current) {
      setIsTranscribing(false)
      setTranscriptionError(null)
    }
  }, [])

  // Soft-ask state — gates the browser's native permission prompt behind our own
  // explanatory dialog the first time the user tries to dictate. Once acknowledged
  // (or once Chrome has stored 'granted'), this never triggers again.
  const [softAskOpen, setSoftAskOpen] = useState(false)

  const beginRecording = useCallback(async () => {
    if (!dictationEnabledRef.current) return
    const prewarmed = consumePrewarm()
    await startRecording(prewarmed)
  }, [startRecording, consumePrewarm])

  const handleMicClick = useCallback(async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop()
      return
    }
    if (!dictationEnabledRef.current) return
    const state = await queryMicPermissionState()
    if (state === 'denied') {
      // User previously clicked "Ne jamais autoriser" — getUserMedia would just
      // reject silently. Surface a recovery hint instead.
      setTranscriptionError(i18n.t('errors:mic_blocked'))
      return
    }
    if (state === 'prompt' && !hasUserAcknowledgedMicSoftAsk()) {
      setSoftAskOpen(true)
      return
    }
    await beginRecording()
  }, [isRecording, beginRecording])

  const confirmSoftAsk = useCallback(async () => {
    setUserAcknowledgedMicSoftAsk()
    setSoftAskOpen(false)
    await beginRecording()
  }, [beginRecording])

  const dismissSoftAsk = useCallback(() => {
    setSoftAskOpen(false)
  }, [])

  // Keep refs in sync for stable push-to-talk listeners
  useEffect(() => { isRecordingRef.current = isRecording }, [isRecording])
  useEffect(() => { isTranscribingRef.current = isTranscribing }, [isTranscribing])
  useEffect(() => { showMicButtonRef.current = showMicButton }, [showMicButton])
  useEffect(() => { dictationEnabledRef.current = dictationEnabled }, [dictationEnabled])
  useEffect(() => { handleMicClickRef.current = handleMicClick }, [handleMicClick])
  useEffect(() => { startRecordingRef.current = startRecording }, [startRecording])
  const surfaceSelectorRef = useRef(options?.surfaceSelector ?? DEFAULT_SURFACE_SELECTOR)
  useEffect(() => {
    surfaceSelectorRef.current = options?.surfaceSelector ?? DEFAULT_SURFACE_SELECTOR
  }, [options?.surfaceSelector])

  // Push-to-talk: hold Space to record, release to stop.
  // Activation uses the OS keyboard auto-repeat (~500ms): we never preventDefault
  // the first keydown, so a normal tap inserts a space with zero latency. When the
  // OS starts emitting auto-repeats, we know the user is holding — at that point we
  // activate PTT and strip the spaces inserted while we were waiting.
  useEffect(() => {
    const ownerId = Symbol('whisper-hook-instance')

    const stripTrailingSpaces = (max: number) => {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0) return
      for (let i = 0; i < max; i++) {
        const range = sel.getRangeAt(0)
        if (!range.collapsed) break
        const node = range.startContainer
        const offset = range.startOffset
        if (node.nodeType !== Node.TEXT_NODE || offset === 0) break
        const ch = (node.textContent || '').charAt(offset - 1)
        if (ch !== ' ' && ch !== '\u00a0') break
        document.execCommand('delete', false)
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      if (_activePttOwner && _activePttOwner !== ownerId) return
      const el = document.activeElement as HTMLElement | null
      // Never intercept in regular text inputs (To, Subject, CC, BCC)
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      // Only activate PTT when focus is inside THIS instance's surface —
      // a global class list would let the first-mounted instance claim the
      // lock for a keypress aimed at another surface (wrong-editor insert).
      if (!el?.closest(surfaceSelectorRef.current)) return
      if (!dictationEnabledRef.current) return
      if (isRecordingRef.current || isTranscribingRef.current) return

      if (e.repeat) {
        // Auto-repeat is the "hold detected" signal. Activate PTT on the first
        // repeat, then suppress further auto-repeats so no extra spaces leak in.
        e.preventDefault()
        e.stopPropagation()
        if (!pushToTalkRef.current) {
          _activePttOwner = ownerId
          pushToTalkRef.current = true
          recordingStartedAtRef.current = Date.now()
          silentAbortRef.current = false
          stripTrailingSpaces(20)
          const prewarmed = consumePrewarm()
          startRecordingRef.current(prewarmed)
        }
        return
      }
      // First keydown: do nothing — let the editor insert the space normally.
    }

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      if (!pushToTalkRef.current) return // Plain tap: space already inserted, nothing to do.
      if (_activePttOwner && _activePttOwner !== ownerId) return

      e.preventDefault()
      e.stopPropagation()
      pushToTalkRef.current = false
      if (_activePttOwner === ownerId) _activePttOwner = null
      const holdDuration = Date.now() - recordingStartedAtRef.current
      if (holdDuration < PTT_SILENT_ABORT_MS && !hasSpokeRef.current) {
        silentAbortRef.current = true
      }
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop()
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    document.addEventListener('keyup', handleKeyUp, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      document.removeEventListener('keyup', handleKeyUp, true)
      if (_activePttOwner === ownerId) _activePttOwner = null
    }
  }, [consumePrewarm])

  // Esc cancels recording or in-flight transcription. Only intercepts when the user
  // is actively dictating — otherwise Esc keeps its normal role (close modal).
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.code !== 'Escape' && e.key !== 'Escape') return
      if (!isRecordingRef.current && !isTranscribingRef.current) return

      if (isRecordingRef.current) {
        // Stop the recorder and silently drop the audio (no transcription request).
        e.preventDefault()
        e.stopPropagation()
        silentAbortRef.current = true
        // Release PTT lock if we owned it
        pushToTalkRef.current = false
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
        return
      }

      if (isTranscribingRef.current) {
        // Abort the in-flight HTTP request. The catch in onstop sees AbortError
        // without a 'timeout' cause → treats it as user cancel and stays silent.
        e.preventDefault()
        e.stopPropagation()
        try { uploadAbortRef.current?.abort() } catch { /* noop */ }
        if (mountedRef.current) {
          setIsTranscribing(false)
          setTranscriptionError(null)
        }
      }
    }

    document.addEventListener('keydown', handleEsc, true)
    return () => document.removeEventListener('keydown', handleEsc, true)
  }, [])

  // Option 2 — pre-warm getUserMedia on any focus inside the compose context so click/PTT
  // activation is near-instant. Scope is the modal/composer; we no longer require the
  // focused element to be contenteditable (focusing the To/Subject field is a strong
  // signal that dictation may follow). Still gated on permissions.query === 'granted'
  // inside ensurePrewarm so we never trigger a surprise permission prompt.
  useEffect(() => {
    const handleFocusIn = (e: FocusEvent) => {
      const el = e.target as HTMLElement | null
      if (!el) return
      if (!el.closest('.new-message-modal, .reply-composer')) return
      if (!showMicButtonRef.current) return
      ensurePrewarm()
    }
    document.addEventListener('focusin', handleFocusIn)
    return () => {
      document.removeEventListener('focusin', handleFocusIn)
    }
  }, [ensurePrewarm])

  // Release the pre-warmed mic as soon as dictation context disappears (body got content).
  // Keeps the browser mic indicator off when the user starts typing instead of dictating.
  useEffect(() => {
    if (!showMicButton) releasePrewarmNow()
  }, [showMicButton, releasePrewarmNow])

  // Cleanup on unmount only — we manage start/stop lifecycle in handleMicClick
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      uploadAbortRef.current?.abort()
      uploadAbortRef.current = null
      try {
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
      } catch { /* recorder already stopped */ }
      if (timerRef.current) clearInterval(timerRef.current)
      if (prewarmReleaseTimerRef.current) clearTimeout(prewarmReleaseTimerRef.current)
      const pending = prewarmStreamRef.current
      prewarmStreamRef.current = null
      if (pending) {
        pending.then(stream => stream.getTracks().forEach(t => t.stop())).catch(() => {})
      }
      cancelAnimationFrame(animFrameRef.current)
    }
  }, [])

  return {
    isRecording,
    isTranscribing,
    transcriptionError,
    showMicButton,
    handleMicClick,
    audioLevels,
    formattedTime,
    silenceDetected,
    silenceCountdown,
    waveformHistory,
    peakBars,
    forceResetTranscription,
    /** Trigger getUserMedia prewarm now (e.g. on mic-button hover). Safe to call repeatedly. */
    prewarmMic: ensurePrewarm,
    /** True when the pre-permission soft-ask should be rendered. */
    softAskOpen,
    /** User clicked "Continue" — mark acknowledged and start recording (which triggers the browser prompt). */
    confirmSoftAsk,
    /** User clicked "Cancel" or closed the dialog. */
    dismissSoftAsk,
  }
}
