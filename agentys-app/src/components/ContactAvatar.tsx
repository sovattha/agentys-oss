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

import { useContactAvatar } from '../hooks/useContactAvatar'

interface ContactAvatarProps {
  email: string | null | undefined
  fallbackInitial: string
  fallbackBg: string
  className?: string
  ariaLabel?: string
}

/**
 * Renders a contact's profile photo (Gmail/Outlook directory) when
 * available, otherwise a coloured initial-letter fallback identical to
 * the legacy avatar.
 *
 * The component always renders the same wrapper element so the existing
 * `.thread-card-avatar` CSS sizing/border-radius applies in both states.
 * The photo, when present, fills the wrapper via `object-fit: cover`.
 */
export function ContactAvatar({
  email,
  fallbackInitial,
  fallbackBg,
  className = 'thread-card-avatar',
  ariaLabel,
}: ContactAvatarProps) {
  const photoUrl = useContactAvatar(email || null)
  const resolvedAriaLabel = ariaLabel ?? email ?? ''

  return (
    <div
      className={className}
      style={
        photoUrl
          ? { padding: 0, overflow: 'hidden' }
          : { backgroundColor: fallbackBg, color: '#fff' }
      }
      aria-label={resolvedAriaLabel || undefined}
      aria-hidden={resolvedAriaLabel ? undefined : true}
    >
      {photoUrl ? (
        <img
          src={photoUrl}
          alt=""
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : (
        fallbackInitial
      )}
    </div>
  )
}
