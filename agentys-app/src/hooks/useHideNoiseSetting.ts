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
