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

import { useRef, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import type { DraftEditorHandle } from '../components/DraftEditor';

const MAX_IMAGE_SIZE = 5 * 1024 * 1024; // 5 MB
const MAX_IMAGE_WIDTH = 800;
const JPEG_QUALITY = 0.80;

/**
 * Shared hook for inline image insertion in compose editors.
 * Handles: file validation (MIME + size), canvas compression, error reporting.
 */
export function useInlineImage(editorRef: React.RefObject<DraftEditorHandle | null>) {
  const { t } = useTranslation('compose');
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [imageError, setImageError] = useState<string | null>(null);

  const clearImageError = useCallback(() => setImageError(null), []);

  const compressAndInsert = useCallback((dataUrl: string, fileName: string) => {
    const img = new Image();
    img.onload = () => {
      try {
        const ratio = Math.min(MAX_IMAGE_WIDTH / img.width, 1);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * ratio);
        canvas.height = Math.round(img.height * ratio);
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          editorRef.current?.insertImage(dataUrl, fileName);
          return;
        }
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const compressed = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
        editorRef.current?.insertImage(compressed, fileName);
      } catch {
        editorRef.current?.insertImage(dataUrl, fileName);
      }
    };
    img.onerror = () => {
      setImageError(t('image_read_error'));
    };
    img.src = dataUrl;
  }, [editorRef, t]);

  const handleImageInsert = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImageError(null);

    if (!file.type.startsWith('image/')) {
      setImageError(t('image_invalid_type'));
      return;
    }

    if (file.size > MAX_IMAGE_SIZE) {
      setImageError(t('image_too_large'));
      return;
    }

    const reader = new FileReader();
    reader.onerror = () => {
      setImageError(t('image_read_error'));
    };
    reader.onload = () => {
      compressAndInsert(reader.result as string, file.name);
    };
    reader.readAsDataURL(file);
  }, [t, compressAndInsert]);

  return { imageInputRef, handleImageInsert, imageError, clearImageError };
}
