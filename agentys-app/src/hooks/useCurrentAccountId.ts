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

import { useEffect, useState } from "react";
import {
  ensureCurrentAccountId,
  getCurrentAccountId,
  isCurrentAccountLoaded,
  subscribeCurrentAccountId,
} from "../lib/currentAccountId";

/**
 * Wrapper React autour du module `lib/currentAccountId`.
 * Retourne `null` tant que le compte actif n'a pas été résolu.
 */
export function useCurrentAccountId(): string | null {
  const [id, setId] = useState<string | null>(getCurrentAccountId());

  useEffect(() => {
    if (isCurrentAccountLoaded()) {
      setId(getCurrentAccountId());
    }
    const unsub = subscribeCurrentAccountId(setId);
    ensureCurrentAccountId();
    return unsub;
  }, []);

  return id;
}
