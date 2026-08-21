import { useEffect, useCallback, useRef } from 'react';
import { isTauri } from '../services/tokenStorage';

const TRAY_ID = 'main-tray';

// Dynamic Tauri imports
async function getTauriTray() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/tray');
  } catch {
    return null;
  }
}

async function getTauriWindow() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/window');
  } catch {
    return null;
  }
}

export interface UseTrayBadgeOptions {
  enabled?: boolean;
}

export interface UseTrayBadgeResult {
  updateBadge: (count: number) => Promise<void>;
  clearBadge: () => Promise<void>;
}

export function useTrayBadge(
  unreadCount: number,
  options: UseTrayBadgeOptions = {}
): UseTrayBadgeResult {
  const { enabled = true } = options;
  const lastCount = useRef<number>(-1);

  const updateBadge = useCallback(async (count: number) => {
    if (!enabled || !isTauri()) return;

    try {
      const trayModule = await getTauriTray();
      if (!trayModule) return;

      // Update tray tooltip with count
      const tray = await trayModule.TrayIcon.getById(TRAY_ID);
      if (tray) {
        const tooltip =
          count > 0
            ? `Agentys - ${count} email${count > 1 ? 's' : ''} non lu${count > 1 ? 's' : ''}`
            : 'Agentys - Assistant IA Email';
        await tray.setTooltip(tooltip);

        // On macOS, also set the title (appears next to the icon in menu bar)
        // On Windows/Linux, title is not shown but tooltip is
        if (count > 0) {
          await tray.setTitle(count > 99 ? '99+' : String(count));
        } else {
          await tray.setTitle(null);
        }
      }

      // Also set the window badge count for macOS dock icon
      try {
        const windowModule = await getTauriWindow();
        if (windowModule) {
          const window = windowModule.getCurrentWindow();
          await window.setBadgeCount(count > 0 ? count : undefined);
        }
      } catch {
        // setBadgeCount may not be available on all platforms
      }
    } catch (error) {
      console.warn('Failed to update tray badge:', error);
    }
  }, [enabled]);

  const clearBadge = useCallback(async () => {
    await updateBadge(0);
  }, [updateBadge]);

  // Update badge when unread count changes
  useEffect(() => {
    if (!enabled || !isTauri()) return;
    if (unreadCount === lastCount.current) return;

    lastCount.current = unreadCount;
    updateBadge(unreadCount);
  }, [unreadCount, enabled, updateBadge]);

  return {
    updateBadge,
    clearBadge,
  };
}
