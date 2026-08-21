// Régression (2026-06-09) : « le raccourci espace pour dicter ne fait rien »
// dans les Brouillons. Le guard PTT de useWhisperRecording n'autorise Espace
// que dans .new-message-modal / .reply-composer ; le panneau Brouillons
// (.pending-draft-detail) édite désormais dans le DraftEditor TipTap partagé
// (b69db5be — avant c'était un <textarea>, exclu par design) mais n'a jamais
// été ajouté au guard → maintenir Espace n'y démarre jamais la dictée.
// Ce test pilote le VRAI hook avec de vrais événements clavier auto-repeat.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, cleanup } from '@testing-library/react'
import { useWhisperRecording } from './useWhisperRecording'

vi.mock('../services/uiSounds', () => ({ playUISound: vi.fn() }))
vi.mock('../services/micPermission', () => ({
  queryMicPermissionState: vi.fn().mockResolvedValue('granted'),
  hasUserAcknowledgedMicSoftAsk: vi.fn().mockReturnValue(true),
  setUserAcknowledgedMicSoftAsk: vi.fn(),
}))

class FakeMediaRecorder {
  static isTypeSupported() { return true }
  state = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((e: unknown) => void) | null = null
  onstop: (() => void) | null = null
  start() { this.state = 'recording' }
  stop() { this.state = 'inactive'; this.onstop?.() }
}

function fakeStream() {
  const track = { stop: vi.fn() }
  return { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream
}

function mountSurface(className: string): HTMLElement {
  const root = document.createElement('div')
  root.className = className
  const editor = document.createElement('div')
  editor.setAttribute('contenteditable', 'true')
  editor.tabIndex = -1
  root.appendChild(editor)
  document.body.appendChild(root)
  editor.focus()
  return root
}

function holdSpace() {
  // Premier keydown (tap normal) puis auto-repeat = signal « maintenu »
  document.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', key: ' ', bubbles: true }))
  document.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space', key: ' ', repeat: true, bubbles: true }))
}

function releaseSpace() {
  document.dispatchEvent(new KeyboardEvent('keyup', { code: 'Space', key: ' ', bubbles: true }))
}

describe('useWhisperRecording — push-to-talk Espace par surface', () => {
  let getUserMedia: ReturnType<typeof vi.fn>

  beforeEach(() => {
    getUserMedia = vi.fn().mockResolvedValue(fakeStream())
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    // AudioContext absent → branche fallback « recording without waveform »
    vi.stubGlobal('AudioContext', undefined)
  })

  afterEach(() => {
    releaseSpace() // libère le lock PTT module-level entre les tests
    cleanup()
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })

  it('démarre la dictée dans .new-message-modal (maintien Espace)', async () => {
    mountSurface('new-message-modal')
    const { result } = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.new-message-modal' }))
    holdSpace()
    await waitFor(() => expect(result.current.isRecording).toBe(true))
    expect(getUserMedia).toHaveBeenCalled()
  })

  it('démarre la dictée dans .reply-composer', async () => {
    mountSurface('reply-composer')
    const { result } = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.reply-composer' }))
    holdSpace()
    await waitFor(() => expect(result.current.isRecording).toBe(true))
  })

  it('démarre la dictée dans .pending-draft-detail (panneau Brouillons)', async () => {
    // LE bug rapporté : Espace maintenu dans l'éditeur des Brouillons.
    mountSurface('pending-draft-detail')
    const { result } = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.pending-draft-detail' }))
    holdSpace()
    await waitFor(() => expect(result.current.isRecording).toBe(true))
    expect(getUserMedia).toHaveBeenCalled()
  })

  it('sans option : garde legacy compose-only (compat)', async () => {
    mountSurface('new-message-modal')
    const { result } = renderHook(() => useWhisperRecording(true, true, vi.fn()))
    holdSpace()
    await waitFor(() => expect(result.current.isRecording).toBe(true))
  })

  it("n'intercepte pas Espace hors d'un contexte compose (liste, détail email)", async () => {
    mountSurface('email-list')
    const { result } = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.new-message-modal' }))
    holdSpace()
    await new Promise(r => setTimeout(r, 50))
    expect(result.current.isRecording).toBe(false)
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it("multi-instances : c'est l'instance de la surface FOCALISÉE qui enregistre", async () => {
    // Page Brouillons avec « Nouveau message » ouvert par-dessus : l'instance
    // PendingDraftDetail (montée en premier) reçoit le keydown d'abord. Sans
    // scope par instance, elle vole le lock et la transcription part dans le
    // mauvais éditeur (le draft caché derrière le modal).
    const pddRoot = mountSurface('pending-draft-detail')
    const pdd = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.pending-draft-detail' }))
    const nmRoot = mountSurface('new-message-modal')
    const nm = renderHook(() =>
      useWhisperRecording(true, true, vi.fn(), { surfaceSelector: '.new-message-modal' }))
    // focus dans le modal Nouveau message (dernier monté)
    ;(nmRoot.querySelector('[contenteditable]') as HTMLElement).focus()

    holdSpace()
    await waitFor(() => expect(nm.result.current.isRecording).toBe(true))
    expect(pdd.result.current.isRecording).toBe(false)
    void pddRoot
  })
})
