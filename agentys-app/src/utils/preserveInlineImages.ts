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

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function isEditorImageSrc(src: string): boolean {
  return /^data:image\//i.test(src) || /^blob:/i.test(src)
}

export function extractEditorImages(html: string): string[] {
  if (!html || typeof DOMParser === 'undefined') return []

  const doc = new DOMParser().parseFromString(html, 'text/html')
  const images: string[] = []

  for (const img of Array.from(doc.querySelectorAll('img'))) {
    const src = img.getAttribute('src') || ''
    if (!isEditorImageSrc(src)) continue

    const alt = img.getAttribute('alt') || ''
    const width = img.getAttribute('width')
    const widthAttr = width && /^\d{1,4}$/.test(width)
      ? ` width="${escapeAttr(width)}"`
      : ''

    images.push(`<p><img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}"${widthAttr}></p>`)
  }

  return images
}

export function preserveInlineImages(originalHtml: string, nextHtml: string): string {
  const images = extractEditorImages(originalHtml)
  if (images.length === 0) return nextHtml

  const missing = images.filter((imageHtml) => {
    const src = imageHtml.match(/\bsrc="([^"]+)"/)?.[1]
    return src ? !nextHtml.includes(src) : true
  })

  if (missing.length === 0) return nextHtml
  return `${nextHtml}${missing.join('')}`
}
