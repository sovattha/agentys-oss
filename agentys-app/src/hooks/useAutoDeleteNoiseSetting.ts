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
