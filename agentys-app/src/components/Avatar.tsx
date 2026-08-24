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

import { useState, useEffect } from 'react';
import './Avatar.css';

interface AvatarProps {
  name: string | null;
  email: string;
  size?: 'sm' | 'md' | 'lg';
  /** Explicit photo URL override — e.g. Google profile photo fetched upstream. */
  photoUrl?: string;
  /** Tooltip shown on hover. Defaults to "name <email>" or email. */
  title?: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function generateColorFromString(str: string): string {
  const colors = [
    '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
    '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  ];
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  return colors[Math.abs(hash) % colors.length];
}

// Shared so message-thread avatars (ContactAvatar in EmailDetailModal) derive
// the SAME 2-letter initials as the account chip — keeps "You" reading "CR"
// instead of a lone "C". eslint-disable mirrors generateColorFromString above.
//
// Règle unique app-wide (2026-06-09, « je veux toujours 2 lettres comme AS ») :
//  - nom présent : ≥2 mots → 1re lettre du premier + du dernier mot ; le split
//    inclut ._- car les labels de chips sont souvent une local-part capitalisée
//    (« Alexandre.simon » → AS, pas AL) ;
//  - sinon email : local-part splittée sur ._- → 2 premières lettres de
//    segments, sinon 2 premiers chars ;
//  - jamais 1 lettre sauf si la source ne contient qu'un seul caractère.
// eslint-disable-next-line react-refresh/only-export-components
export function getInitials(name: string | null, email: string): string {
  const trimmedName = (name ?? '').trim();
  // Un « nom » qui est en réalité une adresse email (ex: EmailDetailModal passe
  // l'email du compte pour les messages « You ») suit la règle email.
  const effectiveEmail = trimmedName.includes('@') ? trimmedName : email;
  const effectiveName = trimmedName.includes('@') ? '' : trimmedName;

  const nameParts = effectiveName.split(/[\s._-]+/).filter(Boolean);
  if (nameParts.length >= 2) return (nameParts[0][0] + nameParts[nameParts.length - 1][0]).toUpperCase();
  if (nameParts.length === 1 && (nameParts[0].length >= 2 || !effectiveEmail)) {
    return nameParts[0].slice(0, 2).toUpperCase();
  }

  const local = (effectiveEmail || '').split('@')[0];
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (local) return local.slice(0, 2).toUpperCase();
  return (nameParts[0] ?? '?').slice(0, 2).toUpperCase();
}

// Module-level cache: email → base Gravatar URL (reused across all Avatar instances)
const gravatarCache = new Map<string, string>();

async function resolveGravatarUrl(email: string, sizePx: number): Promise<string> {
  const key = email.trim().toLowerCase();
  let base = gravatarCache.get(key);
  if (!base) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key));
    const hex = Array.from(new Uint8Array(buf))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');
    base = `https://www.gravatar.com/avatar/${hex}`;
    gravatarCache.set(key, base);
  }
  // Audit 2026-05-18: `d=404` pollutes the browser console with red errors on
  // every redraw for accounts without a Gravatar (the common case). Switch to
  // `d=blank` so the response is 200 OK with a 1×1 transparent PNG; the
  // onLoad handler below detects the 1×1 dimensions and falls back to
  // initials with no console noise.
  return `${base}?d=blank&s=${sizePx}`;
}

const SIZE_PX: Record<string, number> = { sm: 28, md: 36, lg: 44 };

export function Avatar({ name, email, size = 'md', photoUrl: externalPhoto, title }: AvatarProps) {
  const initials = getInitials(name, email);
  const bgColor = generateColorFromString(email);
  const tooltip = title ?? (name ? `${name} <${email}>` : email);

  const [resolvedPhoto, setResolvedPhoto] = useState<string | null>(externalPhoto ?? null);
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setImgFailed(false);
    if (externalPhoto) {
      setResolvedPhoto(externalPhoto);
      return;
    }
    resolveGravatarUrl(email, SIZE_PX[size] ?? 36).then(setResolvedPhoto);
  }, [email, size, externalPhoto]);

  const showPhoto = resolvedPhoto !== null && !imgFailed;

  return (
    <div
      className={`avatar avatar-${size}`}
      style={showPhoto ? undefined : { backgroundColor: bgColor }}
      aria-label={`Avatar for ${name || email}`}
      title={tooltip}
    >
      {showPhoto ? (
        <img
          src={resolvedPhoto!}
          alt={name || email}
          onError={() => setImgFailed(true)}
          onLoad={(e) => {
            // Gravatar's `d=blank` returns a 1×1 transparent PNG when the
            // account has no avatar; treat that as "no photo" and render
            // initials. Real avatars are always ≥ 16×16.
            const img = e.currentTarget;
            if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
              setImgFailed(true);
            }
          }}
        />
      ) : (
        initials
      )}
    </div>
  );
}
