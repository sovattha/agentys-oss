import { createSettingHook } from "./createSettingHook";

const useSetting = createSettingHook({
  settingKey: "auto_reminder_on_commitment",
  defaultValue: false,
  useLocalStorage: true,
  localStorageKey: "agentys_auto_reminder_on_commitment",
  useAuthHeaders: true,
  hookName: "useAutoReminderOnCommitment",
});

export function useAutoReminderOnCommitment(accountId?: number) {
  const { value, toggle } = useSetting(accountId);
  return { autoReminderOnCommitment: value, toggleAutoReminderOnCommitment: toggle };
}
