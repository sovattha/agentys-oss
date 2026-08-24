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

/**
 * Bus d'événements applicatifs légers.
 *
 * Usage : découpler les API clients des hooks React sans dépendance circulaire.
 * Par exemple : `activateAccount()` dispatch `ACCOUNT_CHANGED`, et `useCurrentAccountId`
 * écoute pour invalider son cache module-level.
 */

export const appEvents = new EventTarget();

export const ACCOUNT_CHANGED = "agentys:account-changed";
