import { createSettingHook } from "./createSettingHook";

const useSetting = createSettingHook({
  settingKey: "auto_empty_spam_30d",
  defaultValue: false,
  useLocalStorage: true,
  localStorageKey: "agentys_auto_empty_spam_30d",
  useAuthHeaders: true,
  hookName: "useAutoEmptySpamSetting",
});

export function useAutoEmptySpamSetting(accountId?: number) {
  const { value, toggle } = useSetting(accountId);
  return { autoEmptySpam: value, toggleAutoEmptySpam: toggle };
}
