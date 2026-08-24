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
  settingKey: "hide_noise_from_inbox",
  defaultValue: true,
  useLocalStorage: true,
  localStorageKey: "agentys_hide_noise_from_inbox",
  useAuthHeaders: true,
  hookName: "useHideNoiseSetting",
});

export function useHideNoiseSetting(accountId?: number) {
  const { value, toggle } = useSetting(accountId);
  return { hideNoise: value, toggleHideNoise: toggle };
}
