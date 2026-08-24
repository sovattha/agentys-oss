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

import { useEffect, useState } from 'react'
import { CloseIcon } from '../icons/ActionIcons'
import './AttachmentCard.css'

const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'avif', 'heic'])

// Type colours — Tailwind 600-tier across the board. Calmer than 500 (the
// shouty default), still legible against white badge text. Keeps file types
// distinguishable at a glance without competing with the filename for
// attention. See audit-2026-05-14 visual pass.
const TYPE_COLORS: Record<string, string> = {
  pdf: '#dc2626',
  doc: '#2563eb', docx: '#2563eb', rtf: '#2563eb',
  xls: '#059669', xlsx: '#059669', csv: '#059669', numbers: '#059669',
  ppt: '#ea580c', pptx: '#ea580c', key: '#ea580c',
  txt: '#475569', md: '#475569', log: '#475569',
  zip: '#9333ea', rar: '#9333ea', '7z': '#9333ea', tar: '#9333ea', gz: '#9333ea',
  mp3: '#db2777', wav: '#db2777', m4a: '#db2777', flac: '#db2777',
  mp4: '#0284c7', mov: '#0284c7', avi: '#0284c7', mkv: '#0284c7', webm: '#0284c7',
  json: '#ca8a04', xml: '#ca8a04', yml: '#ca8a04', yaml: '#ca8a04',
}

function getExt(name: string): string {
  const i = name.lastIndexOf('.')
  return i === -1 ? '' : name.slice(i + 1).toLowerCase()
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface AttachmentCardProps {
  file: File
  name: string
  size: number
  onRemove: () => void
  removeLabel: string
}

export function AttachmentCard({ file, name, size, onRemove, removeLabel }: AttachmentCardProps) {
  const ext = getExt(name)
  const isImage = IMAGE_EXT.has(ext)
  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  const [thumbFailed, setThumbFailed] = useState(false)

  useEffect(() => {
    if (!isImage) return
    setThumbFailed(false)
    const url = URL.createObjectURL(file)
    setThumbUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file, isImage])

  const showThumb = isImage && thumbUrl && !thumbFailed
  const badgeColor = TYPE_COLORS[ext] ?? '#4f46e5'
  const badgeLabel = ext ? ext.toUpperCase().slice(0, 4) : 'FILE'

  return (
    <div className="att-card" data-ext={ext}>
      <button
        type="button"
        className="att-card-remove icon-btn--delete"
        onClick={onRemove}
        aria-label={`${removeLabel} ${name}`}
      >
        <CloseIcon size={12} />
      </button>
      <div className="att-card-preview">
        {showThumb ? (
          <img
            src={thumbUrl!}
            alt=""
            className="att-card-thumb"
            onError={() => setThumbFailed(true)}
          />
        ) : (
          <span className="att-card-badge" style={{ backgroundColor: badgeColor }}>
            {badgeLabel}
          </span>
        )}
      </div>
      <div className="att-card-meta">
        <div className="att-card-name" title={name}>{name}</div>
        <div className="att-card-size">{formatSize(size)}</div>
      </div>
    </div>
  )
}

interface ReceivedAttachmentCardProps {
  name: string
  size: number
  /** Type affichable dans l'aperçu intégré (pdf/image/texte). */
  previewable: boolean
  onOpen: () => void
  onDownload: () => void
  openLabel: string
  downloadLabel: string
}

/**
 * Variante « reçue » de la carte : même langage visuel que le compose
 * (badge type coloré, nom, taille), mais le clic ouvre l'aperçu intégré
 * (ou télécharge si le type n'est pas affichable) et le chip overlay en
 * haut à droite télécharge toujours.
 */
export function ReceivedAttachmentCard({ name, size, previewable, onOpen, onDownload, openLabel, downloadLabel }: ReceivedAttachmentCardProps) {
  const ext = getExt(name)
  const badgeColor = TYPE_COLORS[ext] ?? '#4f46e5'
  const badgeLabel = ext ? ext.toUpperCase().slice(0, 4) : 'FILE'
  return (
    <div className="att-card att-card--received" data-ext={ext}>
      <button
        type="button"
        className="att-card-open"
        onClick={previewable ? onOpen : onDownload}
        title={name}
        aria-label={`${previewable ? openLabel : downloadLabel} ${name}`}
      >
        <div className="att-card-preview">
          <span className="att-card-badge" style={{ backgroundColor: badgeColor }}>
            {badgeLabel}
          </span>
        </div>
        <div className="att-card-meta">
          <div className="att-card-name">{name}</div>
          <div className="att-card-size">{size > 0 ? formatSize(size) : ' '}</div>
        </div>
      </button>
      <button
        type="button"
        className="att-card-remove att-card-dl"
        onClick={onDownload}
        aria-label={`${downloadLabel} ${name}`}
        title={downloadLabel}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 2v6M3.5 5.5L6 8l2.5-2.5" />
          <path d="M2 10h8" />
        </svg>
      </button>
    </div>
  )
}
