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

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_URL } from '../../config';
import { downloadAttachment, isPreviewableAttachment } from '../../utils/downloadAttachment';
import { ReceivedAttachmentCard } from '../compose/AttachmentCard';
import { AttachmentPreviewModal } from './AttachmentPreviewModal';

export interface ReceivedAttachmentMeta {
  id: string;
  filename: string;
  size: number;
  content_type?: string;
}

/** Filter out noise attachments embedded by email services (favicons, tracking pixels) */
function isNoiseAttachment(att: ReceivedAttachmentMeta): boolean {
  const name = (att.filename || '').toLowerCase();
  if (name === 'favicon.ico') return true;
  // Tiny images (< 3KB) with generic icon/logo names — embedded service branding
  if (att.size > 0 && att.size < 3072) {
    if (/^(icon|logo|spacer|pixel|tracking|transparent|blank)\b/i.test(name)) return true;
    // 1x1 tracking pixels
    if (/\.(gif|png)$/i.test(name) && att.size < 200) return true;
  }
  return false;
}

/**
 * Rangée de pièces jointes reçues, alignée sur les cartes du compose
 * (AttachmentCard) : clic sur la carte = aperçu intégré pour pdf/image/texte
 * (téléchargement direct sinon), chip overlay = téléchargement.
 * Utilisée par EmailDetailModal (email + fil) et PendingDraftDetail.
 */
export function ReceivedAttachments({ attachments, emailId }: { attachments: ReceivedAttachmentMeta[]; emailId: string }) {
  const { t: tCommon } = useTranslation('common');
  const [preview, setPreview] = useState<ReceivedAttachmentMeta | null>(null);
  const realAttachments = (attachments || []).filter(att => att.filename && !isNoiseAttachment(att));
  if (realAttachments.length === 0) return null;

  const downloadUrlFor = (att: ReceivedAttachmentMeta) =>
    `${API_URL}/api/emails/${encodeURIComponent(emailId)}/attachments/${encodeURIComponent(att.id)}/download`;

  const handleDownload = (att: ReceivedAttachmentMeta) => {
    // Audit Toast Site 1 (2026-05-12): previously log-only — the user
    // clicked download, the file never arrived, and they had no idea.
    downloadAttachment(downloadUrlFor(att), att.filename)
      .catch(err => {
        console.error('Attachment download error:', err);
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tCommon('toasts.download_failed', { filename: att.filename }),
            type: 'error',
            duration: 6000,
          },
        }));
      });
  };

  const handleDownloadAll = () => {
    const zipName = `${tCommon('attachments_zip_name', 'pieces-jointes')}.zip`;
    const zipUrl = `${API_URL}/api/emails/${encodeURIComponent(emailId)}/attachments/download-all`;
    downloadAttachment(zipUrl, zipName)
      .then(({ failedAttachments }) => {
        // Audit 2026-06-10 F-02 : un zip partiel répond 200 — sans ce toast,
        // l'utilisateur croit tout avoir sauvegardé et peut archiver/supprimer
        // l'email source alors que des fichiers manquent à l'archive.
        if (failedAttachments.length > 0) {
          // 3 noms max dans le toast (8s) — au-delà c'est illisible (review F4).
          const shown = failedAttachments.slice(0, 3).join(', ');
          const more = failedAttachments.length > 3 ? '…' : '';
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: tCommon('toasts.download_all_partial', {
                count: failedAttachments.length,
                files: `${shown}${more}`,
              }),
              type: 'warning',
              duration: 8000,
            },
          }));
        }
      })
      .catch(err => {
        console.error('Attachment download-all error:', err);
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tCommon('toasts.download_failed', { filename: zipName }),
            type: 'error',
            duration: 6000,
          },
        }));
      });
  };

  return (
    <div className="email-attachments-section">
      <div className="email-attachments-row">
        {realAttachments.map((att) => (
          <ReceivedAttachmentCard
            key={att.id}
            name={att.filename}
            size={att.size}
            previewable={isPreviewableAttachment(att.content_type || '', att.filename)}
            onOpen={() => setPreview(att)}
            onDownload={() => handleDownload(att)}
            openLabel={tCommon('open', 'Ouvrir')}
            downloadLabel={tCommon('download', 'Télécharger')}
          />
        ))}
      </div>
      {realAttachments.length >= 3 && (
        <button type="button" className="att-download-all" onClick={handleDownloadAll}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 2v6M3.5 5.5L6 8l2.5-2.5" />
            <path d="M2 10h8" />
          </svg>
          {tCommon('download_all', 'Tout télécharger')}
        </button>
      )}
      {preview && (
        <AttachmentPreviewModal
          url={downloadUrlFor(preview)}
          filename={preview.filename}
          onClose={() => setPreview(null)}
          onDownload={() => handleDownload(preview)}
        />
      )}
    </div>
  );
}
