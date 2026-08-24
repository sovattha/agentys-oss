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

import { useCallback, useState, useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import './ConfirmationDialog.css';

interface ConfirmationDialogProps {
  isOpen: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  /** ReactNode to allow multi-line messages (count + "queued in background" hint). */
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

// Délai de sécurité (ms) avant que le bouton destructif devienne cliquable.
// Empêche les confirmations accidentelles juste après l'ouverture de la modal.
const DESTRUCTIVE_DELAY_MS = 1500;

export default function ConfirmationDialog({
  isOpen,
  onConfirm,
  onCancel,
  title,
  message,
  confirmLabel,
  cancelLabel,
  destructive = false,
}: ConfirmationDialogProps) {
  const { t } = useTranslation('common');
  const resolvedConfirmLabel = confirmLabel ?? t('confirm');
  const resolvedCancelLabel = cancelLabel ?? t('cancel');

  // Pour les actions destructives : le bouton de confirmation est désactivé
  // pendant DESTRUCTIVE_DELAY_MS ms après l'ouverture pour éviter les clics accidentels.
  const [confirmEnabled, setConfirmEnabled] = useState(!destructive);

  useEffect(() => {
    if (!isOpen) {
      // Réinitialiser l'état disabled à la fermeture
      setConfirmEnabled(!destructive);
      return;
    }
    if (!destructive) {
      setConfirmEnabled(true);
      return;
    }
    // Action destructive : désactiver pendant le délai de sécurité
    setConfirmEnabled(false);
    const timer = setTimeout(() => setConfirmEnabled(true), DESTRUCTIVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [isOpen, destructive]);

  const handleConfirm = useCallback(() => {
    if (!confirmEnabled) return;
    onConfirm();
    onCancel(); // fermer après confirmation
  }, [onConfirm, onCancel, confirmEnabled]);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent
        className={`confirmation-dialog${destructive ? ' destructive' : ''}`}
        showCloseButton={false}
        data-testid="confirmation-dialog"
      >
        <DialogHeader>
          <DialogTitle className="confirmation-dialog-title">
            {title}
          </DialogTitle>
          <DialogDescription className="confirmation-dialog-message">
            {message}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="confirmation-dialog-actions">
          {/* autoFocus sur Annuler pour les actions destructives — empêche Enter/Space de valider accidentellement */}
          <Button
            variant="outline"
            onClick={onCancel}
            autoFocus={destructive}
            data-testid="cancel-btn"
          >
            {resolvedCancelLabel}
          </Button>
          <Button
            variant={destructive ? 'destructive' : 'default'}
            onClick={handleConfirm}
            disabled={!confirmEnabled}
            autoFocus={!destructive}
            data-testid="confirm-btn"
            aria-disabled={!confirmEnabled}
          >
            {resolvedConfirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
