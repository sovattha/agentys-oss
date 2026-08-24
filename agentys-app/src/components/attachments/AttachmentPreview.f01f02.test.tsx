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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AttachmentPreviewModal } from './AttachmentPreviewModal'
import { ReceivedAttachments } from './ReceivedAttachments'
import { downloadAttachment } from '../../utils/downloadAttachment'

// i18n : retourne la clé verbatim pour asserter sur des identifiants stables.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('../../services/authToken', () => ({
  getAuthHeaders: () => ({ Authorization: 'Bearer test-token' }),
}))

vi.mock('../../utils/downloadAttachment', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils/downloadAttachment')>()
  return { ...actual, downloadAttachment: vi.fn() }
})

const downloadAttachmentMock = vi.mocked(downloadAttachment)

/**
 * Audit 2026-06-10 F-01 : la préview rendait une pièce jointe text/html comme
 * HTML vivant dans un iframe same-origin non sandboxé (phishing in-app).
 * Ces tests épinglent les deux contre-mesures : re-typage systématique du
 * blob + attribut sandbox sur tout iframe non-pdf.
 */
describe('AttachmentPreviewModal — re-typage et sandbox (F-01)', () => {
  const createdBlobs: Blob[] = []

  beforeEach(() => {
    createdBlobs.length = 0
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        createdBlobs.push(blob)
        return 'blob:preview'
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function stubFetchBlob(content: string, type: string) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob([content], { type })),
    }))
  }

  // Le span du header porte le même title que l'iframe — cibler la classe.
  async function findPreviewFrame(): Promise<HTMLIFrameElement> {
    return waitFor(() => {
      const frame = document.querySelector<HTMLIFrameElement>('iframe.att-preview-frame')
      expect(frame).toBeTruthy()
      return frame!
    })
  }

  it('re-type un blob text/html vers text/plain et sandboxe l’iframe', async () => {
    stubFetchBlob('<h1>phish</h1>', 'text/html')
    render(
      <AttachmentPreviewModal url="/api/x" filename="notes.txt" onClose={vi.fn()} onDownload={vi.fn()} />,
    )
    const frame = await findPreviewFrame()
    // Contenu actif neutralisé : sandbox vide = aucun script, aucune nav top.
    expect(frame.getAttribute('sandbox')).toBe('')
    // Le type serveur (attaquant-contrôlé) n'atteint jamais l'iframe.
    expect(createdBlobs[0]?.type).toBe('text/plain')
  })

  it('ne sandboxe pas le pdf (viewer Chromium) mais force son type', async () => {
    stubFetchBlob('%PDF-1.4', 'text/html')
    render(
      <AttachmentPreviewModal url="/api/x" filename="doc.pdf" onClose={vi.fn()} onDownload={vi.fn()} />,
    )
    const frame = await findPreviewFrame()
    expect(frame.getAttribute('sandbox')).toBeNull()
    expect(createdBlobs[0]?.type).toBe('application/pdf')
  })

  it('honore un type serveur sûr quand l’extension est inconnue (review F1)', async () => {
    stubFetchBlob('hello', 'text/plain')
    render(
      <AttachmentPreviewModal url="/api/x" filename="README" onClose={vi.fn()} onDownload={vi.fn()} />,
    )
    const frame = await findPreviewFrame()
    expect(createdBlobs[0]?.type).toBe('text/plain')
    expect(frame.getAttribute('sandbox')).toBe('')
  })
})

/**
 * Audit 2026-06-10 F-02 : un zip partiel répond 200 — sans toast warning,
 * l'utilisateur croit tout avoir sauvegardé (perte de complétude invisible).
 */
describe('ReceivedAttachments — toast sur zip partiel (F-02)', () => {
  const toastEvents: CustomEvent[] = []
  const onToast = (evt: Event) => toastEvents.push(evt as CustomEvent)
  const attachments = [
    { id: 'a1', filename: 'contrat.pdf', size: 50_000 },
    { id: 'a2', filename: 'rapport.pdf', size: 50_000 },
    { id: 'a3', filename: 'annexe.pdf', size: 50_000 },
  ]

  beforeEach(() => {
    toastEvents.length = 0
    downloadAttachmentMock.mockReset()
    window.addEventListener('agentys:toast', onToast)
    return () => window.removeEventListener('agentys:toast', onToast)
  })

  it('warning avec le compte et les noms quand des fichiers manquent', async () => {
    downloadAttachmentMock.mockResolvedValue({ failedAttachments: ['rapport.pdf'] })
    render(<ReceivedAttachments attachments={attachments} emailId="msg-1" />)
    fireEvent.click(screen.getByText('download_all'))
    await waitFor(() => expect(toastEvents.length).toBe(1))
    expect(toastEvents[0].detail.type).toBe('warning')
    expect(toastEvents[0].detail.message).toBe('toasts.download_all_partial')
  })

  it('aucun toast quand le zip est complet', async () => {
    downloadAttachmentMock.mockResolvedValue({ failedAttachments: [] })
    render(<ReceivedAttachments attachments={attachments} emailId="msg-1" />)
    fireEvent.click(screen.getByText('download_all'))
    await waitFor(() => expect(downloadAttachmentMock).toHaveBeenCalledTimes(1))
    await new Promise((r) => setTimeout(r, 0))
    expect(toastEvents.length).toBe(0)
  })
})
