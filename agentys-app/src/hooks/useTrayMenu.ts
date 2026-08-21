import { useEffect, useCallback, useRef } from 'react';
import { isTauri } from '../services/tokenStorage';
import i18n from '../i18n';
import type { Email } from '../services/api';

type UnlistenFn = () => void;

export interface UseTrayMenuOptions {
  enabled?: boolean;
  onSync?: () => Promise<void>;
  onNavigate?: (path: string) => void;
  onOpenEmail?: (emailId: string) => void;
}

export interface UseTrayMenuResult {
  updateUnreadCount: (count: number) => Promise<void>;
  updateRecentEmails: (emails: Email[]) => Promise<void>;
}

// Dynamic Tauri imports
async function getTauriCore() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/core');
  } catch {
    return null;
  }
}

async function getTauriEvent() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/event');
  } catch {
    return null;
  }
}

async function getTauriTray() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/tray');
  } catch {
    return null;
  }
}

async function getTauriMenu() {
  if (!isTauri()) return null;
  try {
    return await import('@tauri-apps/api/menu');
  } catch {
    return null;
  }
}

const TRAY_ID = 'main-tray';

export function useTrayMenu(
  unreadCount: number,
  recentEmails: Email[],
  options: UseTrayMenuOptions = {}
): UseTrayMenuResult {
  const { enabled = true, onSync, onNavigate, onOpenEmail } = options;
  const lastUnreadCount = useRef<number>(-1);
  const lastEmailsRef = useRef<string>('');
  const unlistenRef = useRef<UnlistenFn[]>([]);

  const updateUnreadCount = useCallback(
    async (count: number) => {
      if (!enabled || !isTauri()) return;

      try {
        const core = await getTauriCore();
        const trayModule = await getTauriTray();
        const menuModule = await getTauriMenu();

        if (!core || !trayModule || !menuModule) return;

        // Update tray tooltip and title via Tauri command
        await core.invoke('update_tray_unread_count', { count });

        // Also update the status menu item text
        const tray = await trayModule.TrayIcon.getById(TRAY_ID);
        if (tray) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const menu = await (tray as any).menu?.();
          if (menu) {
            const items = await menu.items();
            for (const item of items) {
              if (item.id === 'status') {
                // CP-04: was hardcoded French for all locales.
                const statusText = i18n.t('common:tray_unread', { count });
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                await (item as any).setText(statusText);
                break;
              }
            }
          }
        }
      } catch (error) {
        console.warn('Failed to update tray unread count:', error);
      }
    },
    [enabled]
  );

  const updateRecentEmails = useCallback(
    async (emails: Email[]) => {
      if (!enabled || !isTauri()) return;

      try {
        const trayModule = await getTauriTray();
        const menuModule = await getTauriMenu();

        if (!trayModule || !menuModule) return;

        const tray = await trayModule.TrayIcon.getById(TRAY_ID);
        if (!tray) return;

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const menu = await (tray as any).menu?.();
        if (!menu) return;

        // Find the recent-emails submenu
        const items = await menu.items();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let recentSubmenu: any = null;

        for (const item of items) {
          if (item.id === 'recent-emails') {
            recentSubmenu = item;
            break;
          }
        }

        if (!recentSubmenu) return;

        // Get the 3 most recent emails
        const recentThree = emails.slice(0, 3);

        if (recentThree.length === 0) {
          // Keep the placeholder
          return;
        }

        // Build new submenu items
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const newItems: any[] = [];
        for (let i = 0; i < recentThree.length; i++) {
          const email = recentThree[i];
          const senderName = email.sender_name || email.sender;
          const truncatedSubject =
            email.subject.length > 40 ? email.subject.substring(0, 37) + '...' : email.subject;
          const text = `${senderName}: ${truncatedSubject}`;

          const menuItem = await menuModule.MenuItem.new({
            id: `recent-email-${email.id}`,
            text,
            action: () => {
              // This action is handled by the Rust side via event
            },
          });
          newItems.push(menuItem);
        }

        // Rebuild submenu - for Tauri v2, we need to rebuild the entire tray menu
        // This is a limitation of the current API.
      } catch (error) {
        console.warn('Failed to update recent emails submenu:', error);
      }
    },
    [enabled]
  );

  // Listen for tray menu events
  useEffect(() => {
    if (!enabled || !isTauri()) return;

    const setupListeners = async () => {
      const eventModule = await getTauriEvent();
      if (!eventModule) return;

      // Listen for sync trigger from tray menu
      const unlistenSync = await eventModule.listen('trigger-sync', async () => {
        if (onSync) {
          await onSync();
        }
      });
      unlistenRef.current.push(unlistenSync);

      // Listen for navigation events
      const unlistenNavigate = await eventModule.listen<string>('navigate', (event) => {
        if (onNavigate) {
          onNavigate(event.payload);
        }
      });
      unlistenRef.current.push(unlistenNavigate);

      // Listen for open recent email events
      const unlistenOpenEmail = await eventModule.listen<string>('open-recent-email', (event) => {
        if (onOpenEmail) {
          // Extract email ID from "recent-email-{id}" format
          const emailId = event.payload.replace('recent-email-', '');
          onOpenEmail(emailId);
        }
      });
      unlistenRef.current.push(unlistenOpenEmail);
    };

    setupListeners();

    return () => {
      unlistenRef.current.forEach((unlisten) => unlisten());
      unlistenRef.current = [];
    };
  }, [enabled, onSync, onNavigate, onOpenEmail]);

  // Update unread count when it changes
  useEffect(() => {
    if (!enabled || !isTauri()) return;
    if (unreadCount === lastUnreadCount.current) return;

    lastUnreadCount.current = unreadCount;
    updateUnreadCount(unreadCount);
  }, [unreadCount, enabled, updateUnreadCount]);

  // Update recent emails when they change
  useEffect(() => {
    if (!enabled || !recentEmails || !isTauri()) return;

    const emailsKey = recentEmails
      .slice(0, 3)
      .map((e) => e.id)
      .join(',');
    if (emailsKey === lastEmailsRef.current) return;

    lastEmailsRef.current = emailsKey;
    updateRecentEmails(recentEmails);
  }, [recentEmails, enabled, updateRecentEmails]);

  return {
    updateUnreadCount,
    updateRecentEmails,
  };
}
