import { createSettingHook } from "./createSettingHook";

const useSetting = createSettingHook({
  settingKey: "auto_empty_trash_30d",
  defaultValue: false,
  useLocalStorage: true,
  localStorageKey: "agentys_auto_empty_trash_30d",
  useAuthHeaders: true,
  hookName: "useAutoEmptyTrashSetting",
});

export function useAutoEmptyTrashSetting(accountId?: number) {
  const { value, toggle } = useSetting(accountId);
  return { autoEmptyTrash: value, toggleAutoEmptyTrash: toggle };
}
