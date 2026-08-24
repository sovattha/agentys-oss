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

import { describe, expect, it } from 'vitest'
import {
  isPreviewableAttachment,
  parseFailedAttachmentsHeader,
  safeDisplayBlobType,
  toSafeDisplayBlob,
} from '../downloadAttachment'

// Audit 2026-06-10 F-01 : une pièce jointe text/html ne doit JAMAIS être
// prévisualisable ni conserver son type serveur (attaquant-contrôlé) — sinon
// elle se rend comme HTML vivant dans l'iframe de préview (phishing in-app).
describe('isPreviewableAttachment', () => {
  it('refuse text/html (F-01 — vecteur de phishing)', () => {
    expect(isPreviewableAttachment('text/html', 'invoice.html')).toBe(false)
    expect(isPreviewableAttachment('text/html; charset=utf-8', 'invoice.html')).toBe(false)
  })

  it('refuse les autres text/* actifs (xml, javascript)', () => {
    expect(isPreviewableAttachment('text/xml', 'feed.xml')).toBe(false)
    expect(isPreviewableAttachment('text/javascript', 'script.js')).toBe(false)
  })

  it('accepte les text/* inertes (plain, csv)', () => {
    expect(isPreviewableAttachment('text/plain', 'notes.txt')).toBe(true)
    expect(isPreviewableAttachment('text/csv', 'data.csv')).toBe(true)
  })

  it('accepte pdf et images', () => {
    expect(isPreviewableAttachment('application/pdf', 'doc.pdf')).toBe(true)
    expect(isPreviewableAttachment('image/png', 'photo.png')).toBe(true)
  })

  it("retombe sur l'extension quand le type manque", () => {
    expect(isPreviewableAttachment('', 'doc.pdf')).toBe(true)
    expect(isPreviewableAttachment('', 'notes.txt')).toBe(true)
    expect(isPreviewableAttachment('', 'invoice.html')).toBe(false)
  })
})

describe('safeDisplayBlobType / toSafeDisplayBlob', () => {
  it("dérive toujours le type de l'extension, jamais du serveur", () => {
    expect(safeDisplayBlobType('notes.txt')).toBe('text/plain')
    expect(safeDisplayBlobType('data.csv')).toBe('text/plain')
    expect(safeDisplayBlobType('doc.pdf')).toBe('application/pdf')
    expect(safeDisplayBlobType('photo.jpg')).toBe('image/jpeg')
    // .html n'a pas de type d'affichage sûr → inerte
    expect(safeDisplayBlobType('invoice.html')).toBe('application/octet-stream')
  })

  it('force le type sûr même quand le blob serveur prétend text/html (F-01)', () => {
    const malicious = new Blob(['<h1>phish</h1>'], { type: 'text/html' })
    expect(toSafeDisplayBlob(malicious, 'notes.txt').type).toBe('text/plain')
    expect(toSafeDisplayBlob(malicious, 'invoice.html').type).toBe('application/octet-stream')
  })

  it("honore un type serveur de l'allowlist quand l'extension est inconnue (review F1)", () => {
    // README sans extension, formats image exotiques : affichés avant le fix,
    // ils doivent le rester — via l'allowlist serveur, jamais en confiance aveugle.
    expect(safeDisplayBlobType('README', 'text/plain')).toBe('text/plain')
    expect(safeDisplayBlobType('photo.jfif', 'image/jpeg')).toBe('image/jpeg')
    expect(safeDisplayBlobType('notes.markdown', 'text/markdown')).toBe('text/plain')
    expect(safeDisplayBlobType('facture', 'application/pdf')).toBe('application/pdf')
    // text/html n'est JAMAIS honoré, même sans extension.
    expect(safeDisplayBlobType('invoice', 'text/html')).toBe('application/octet-stream')
    expect(safeDisplayBlobType('invoice', 'text/html; charset=utf-8')).toBe('application/octet-stream')
  })

  it('conserve le blob tel quel quand le type correspond déjà', () => {
    const pdf = new Blob(['%PDF-1.4'], { type: 'application/pdf' })
    expect(toSafeDisplayBlob(pdf, 'doc.pdf')).toBe(pdf)
  })
})

// Audit 2026-06-10 F-02 : le backend signale les fichiers absents du zip
// via X-Failed-Attachments (URL-encodé, séparé par des virgules).
describe('parseFailedAttachmentsHeader', () => {
  it('retourne [] sans header', () => {
    expect(parseFailedAttachmentsHeader(null)).toEqual([])
    expect(parseFailedAttachmentsHeader('')).toEqual([])
  })

  it('décode les noms URL-encodés', () => {
    expect(parseFailedAttachmentsHeader('rapport%20final.pdf,annexe.pdf')).toEqual([
      'rapport final.pdf',
      'annexe.pdf',
    ])
  })

  it('survit à un encodage invalide sans jeter', () => {
    expect(parseFailedAttachmentsHeader('rapport%ZZ.pdf')).toEqual(['rapport%ZZ.pdf'])
  })
})
