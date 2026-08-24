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

import type { jsPDF as JsPDFType } from 'jspdf'
import DOMPurify from 'dompurify'
import { sanitizeEmailBody } from './emailContent'

export interface PdfEmailMessage {
  subject: string
  sender: string
  senderName?: string
  senderEmail?: string
  to: string[]
  cc?: string[]
  body: string
  receivedAt?: string
  attachments?: Array<{ filename: string; size: number; content_type: string }>
}

function formatDate(iso?: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('fr-FR', {
      day: '2-digit', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
}

// Audit Codex 2026-04-25 [F-XSS-05]: container is briefly attached to the live
// document while html2canvas rasterises it. Anything raw we splat into innerHTML
// (subject, sender, recipients, attachment names) executes as HTML against the
// parent origin during that window. Encode every header field; the email body
// goes through the same DOMPurify allowlist used at render time.
function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function buildContainer(subject: string, messages: PdfEmailMessage[]): HTMLDivElement {
  const container = document.createElement('div')
  container.style.cssText = 'position:fixed;left:-9999px;top:0;width:794px;background:#fff;font-family:Arial,sans-serif;font-size:12px;color:#111;line-height:1.5;'

  const title = document.createElement('div')
  title.style.cssText = 'padding:24px 32px 12px;border-bottom:2px solid #e5e7eb;'
  title.innerHTML = `<h1 style="font-size:18px;font-weight:700;margin:0 0 4px;color:#111;">${escapeHtml(subject || 'Email')}</h1>`
  container.appendChild(title)

  messages.forEach((msg, idx) => {
    const wrap = document.createElement('div')
    wrap.style.cssText = `padding:20px 32px;${idx < messages.length - 1 ? 'border-bottom:1px solid #e5e7eb;' : ''}`

    const senderLine = msg.senderName
      ? `${escapeHtml(msg.senderName)} &lt;${escapeHtml(msg.senderEmail || msg.sender)}&gt;`
      : escapeHtml(msg.sender)
    const meta = [
      `<b>De :</b> ${senderLine}`,
      msg.to?.length ? `<b>À :</b> ${msg.to.map(escapeHtml).join(', ')}` : '',
      msg.cc?.length ? `<b>CC :</b> ${msg.cc.map(escapeHtml).join(', ')}` : '',
      msg.receivedAt ? `<b>Date :</b> ${escapeHtml(formatDate(msg.receivedAt))}` : '',
    ].filter(Boolean).join('<br>')

    // sanitizeEmailBody handles the html-vs-text-vs-markdown branching and the
    // existing DOMPurify allowlist. Use the raw library directly as a defensive
    // double-pass when the body is already HTML to keep the surface tiny.
    const safeBody = msg.body
      ? DOMPurify.sanitize(sanitizeEmailBody(msg.body))
      : ''

    const attachmentBlock = msg.attachments?.length
      ? `<div style="margin-top:12px;font-size:11px;color:#6b7280;"><b>Pièces jointes :</b> ${msg.attachments
          .map((a) => `${escapeHtml(a.filename)} (${formatBytes(a.size)})`)
          .join(', ')}</div>`
      : ''

    wrap.innerHTML = `
      <div style="font-size:11px;color:#6b7280;margin-bottom:12px;line-height:1.7;">${meta}</div>
      <div style="font-size:12px;">${safeBody}</div>
      ${attachmentBlock}
    `
    container.appendChild(wrap)
  })

  return container
}

/**
 * Generates and downloads a PDF from one or more email messages.
 */
export async function exportEmailToPdf(subject: string, messages: PdfEmailMessage[]): Promise<void> {
  const container = buildContainer(subject, messages)
  document.body.appendChild(container)

  try {
    const [{ jsPDF }, html2canvas] = await Promise.all([
      import('jspdf'),
      import('html2canvas').then(m => m.default),
    ])

    const canvas = await (html2canvas as typeof import('html2canvas').default)(container, {
      scale: 2,
      useCORS: true,
      allowTaint: true,
      backgroundColor: '#ffffff',
      logging: false,
    })

    const A4_W = 595.28
    const A4_H = 841.89
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' }) as InstanceType<typeof JsPDFType>

    const imgW = A4_W
    const imgH = (canvas.height * A4_W) / canvas.width
    let remaining = imgH
    let srcY = 0

    while (remaining > 0) {
      const sliceH = Math.min(remaining, A4_H)
      const sliceCanvas = document.createElement('canvas')
      sliceCanvas.width = canvas.width
      sliceCanvas.height = Math.round((sliceH / imgH) * canvas.height)
      const ctx = sliceCanvas.getContext('2d')
      if (ctx) {
        ctx.drawImage(canvas, 0, srcY, canvas.width, sliceCanvas.height, 0, 0, canvas.width, sliceCanvas.height)
      }
      if (srcY > 0) pdf.addPage()
      pdf.addImage(sliceCanvas.toDataURL('image/jpeg', 0.92), 'JPEG', 0, 0, imgW, sliceH)
      srcY += sliceCanvas.height
      remaining -= sliceH
    }

    const filename = (subject || 'email')
      .replace(/[^a-z0-9\s-]/gi, '')
      .trim()
      .replace(/\s+/g, '-')
      .toLowerCase()
      .slice(0, 60) || 'email'

    const inTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
    if (inTauri) {
      try {
        const { save } = await import('@tauri-apps/plugin-dialog')
        const selectedPath = await save({
          filters: [{ name: 'PDF', extensions: ['pdf'] }],
        })
        if (selectedPath) {
          const { writeFile } = await import('@tauri-apps/plugin-fs')
          const pdfBytes = pdf.output('arraybuffer')
          await writeFile(selectedPath, new Uint8Array(pdfBytes))
          return
        }
        return // Annulé
      } catch (err) {
        console.warn('[exportPdf] Tauri save failed, falling back to browser:', err)
      }
    }

    // Browser fallback
    pdf.save(`${filename}.pdf`)
  } finally {
    document.body.removeChild(container)
  }
}
