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

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { getAuthHeaders } from '../../services/authToken';
import { PREVIEW_IMAGE_RE, toSafeDisplayBlob } from '../../utils/downloadAttachment';
import { CloseIcon } from '../icons/ActionIcons';
import './AttachmentPreviewModal.css';

interface AttachmentPreviewModalProps {
  url: string;
  filename: string;
  onClose: () => void;
  onDownload: () => void;
}

/**
 * Aperçu intégré d'une pièce jointe reçue (pdf / image / texte) — « ouvrir
 * sans télécharger ». Rend son root avec data-escape-owner pour que les
 * hosts (EmailDetailModal, etc.) ne se ferment pas sur le même Escape —
 * contrat utils/escapeOwner.ts.
 */
export function AttachmentPreviewModal({ url, filename, onClose, onDownload }: AttachmentPreviewModalProps) {
  const { t: tCommon } = useTranslation('common');
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  // Type d'affichage effectif du blob re-typé — pilote la décision sandbox
  // (un pdf sans extension mais au type serveur sûr ne doit pas être sandboxé,
  // sinon le viewer Chromium rend un panneau vide — review F1).
  const [displayType, setDisplayType] = useState('');
  const [error, setError] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(url, { headers: getAuthHeaders() });
        if (!res.ok) throw new Error(`preview fetch ${res.status}`);
        const raw = await res.blob();
        if (cancelled) return;
        // Audit 2026-06-10 F-01 : re-typage SYSTÉMATIQUE (extension d'abord,
        // type serveur seulement s'il est dans l'allowlist d'affichage).
        // L'ancien garde « si != octet-stream on garde le type serveur »
        // laissait passer text/html (type issu du MIME de l'email, donc
        // attaquant-contrôlé) directement dans l'iframe.
        const typed = toSafeDisplayBlob(raw, filename);
        objectUrl = URL.createObjectURL(typed);
        setDisplayType(typed.type);
        setBlobUrl(objectUrl);
      } catch (err) {
        console.error('Attachment preview error:', err);
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, filename]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const isImage = PREVIEW_IMAGE_RE.test(filename) || displayType.startsWith('image/');
  const isPdf = displayType === 'application/pdf';

  return createPortal(
    <div className="att-preview-overlay" data-escape-owner="" onClick={onClose} role="dialog" aria-modal="true" aria-label={filename}>
      <div className="att-preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="att-preview-header">
          <span className="att-preview-name" title={filename}>{filename}</span>
          <div className="att-preview-actions">
            <button type="button" className="att-preview-download" onClick={onDownload}>
              {tCommon('download', 'Télécharger')}
            </button>
            <button type="button" className="att-preview-close" onClick={onClose} aria-label={tCommon('close', 'Fermer')}>
              <CloseIcon size={16} />
            </button>
          </div>
        </div>
        <div className="att-preview-body">
          {error ? (
            <p className="att-preview-error">
              {tCommon('toasts.download_failed', { filename, defaultValue: 'Échec du téléchargement de {{filename}}' })}
            </p>
          ) : !blobUrl ? (
            <div className="att-preview-loading" aria-hidden="true" />
          ) : isImage ? (
            <img className="att-preview-image" src={blobUrl} alt={filename} />
          ) : (
            // Audit 2026-06-10 F-01 : sandbox vide = aucun script, aucune
            // navigation top, aucun formulaire. Exception pdf : le viewer
            // Chromium ne se charge pas sandboxé, et le blob est déjà re-typé
            // application/pdf (inerte) par toSafeDisplayBlob.
            <iframe
              className="att-preview-frame"
              src={blobUrl}
              title={filename}
              sandbox={isPdf ? undefined : ''}
            />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
