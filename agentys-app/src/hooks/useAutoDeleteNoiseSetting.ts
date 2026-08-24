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

import { createSettingHook } from "./createSettingHook";

const useSetting = createSettingHook({
  settingKey: "auto_delete_noise_30d",
  defaultValue: false,
  useLocalStorage: true,
  localStorageKey: "agentys_auto_delete_noise_30d",
  useAuthHeaders: true,
  hookName: "useAutoDeleteNoiseSetting",
});

export function useAutoDeleteNoiseSetting(accountId?: number) {
  const { value, toggle } = useSetting(accountId);
  return { autoDeleteNoise: value, toggleAutoDeleteNoise: toggle };
}
