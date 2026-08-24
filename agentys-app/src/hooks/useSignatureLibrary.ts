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
import { fetchAccounts, listSignatures, type SignatureEntry } from '../api/accounts';

/**
 * Charge (paresseusement) la bibliothèque de signatures du compte pour les
 * chips de bascule de l'éditeur de signature inline des composeurs.
 *
 * `enabled` : fetch à CHAQUE ouverture de l'éditeur — pas de cache : une
 * bibliothèque modifiée dans Settings entre deux ouvertures doit se refléter
 * dans les chips (noms à jour, entrées supprimées absentes). Les chips sont
 * une affordance optionnelle, tout échec est silencieux (l'éditeur texte
 * reste pleinement fonctionnel sans elles).
 *
 * Sélection de compte alignée sur useAccountSignature : match par email
 * (compte d'envoi de la réponse) d'abord, sinon le compte courant.
 */
export function useSignatureLibrary(enabled: boolean, accountEmail?: string | null): SignatureEntry[] {
  const [entries, setEntries] = useState<SignatureEntry[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const { accounts, current_account_id } = await fetchAccounts();
        const wanted = (accountEmail || '').trim().toLowerCase();
        const account =
          (wanted && accounts.find(a => (a.email || '').toLowerCase() === wanted)) ||
          (current_account_id && accounts.find(a => a.id === current_account_id)) ||
          accounts[0];
        if (!account) return;
        const { signatures } = await listSignatures(account.id);
        if (!cancelled) setEntries(signatures);
      } catch {
        // silencieux — les chips sont facultatives
      }
    })();
    return () => { cancelled = true; };
  }, [enabled, accountEmail]);

  return entries;
}
