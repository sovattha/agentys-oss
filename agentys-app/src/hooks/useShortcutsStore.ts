import { useState, useEffect, useCallback } from 'react';
import i18n from '../i18n';
import { isTauri } from '../services/tokenStorage';
import type { ShortcutConfig } from '../types/shortcuts';
import { DEFAULT_SHORTCUTS } from '../types/shortcuts';

const STORAGE_KEY = 'agentys_custom_shortcuts';

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

interface ShortcutsStoreState {
  shortcuts: ShortcutConfig[];
  isLoading: boolean;
  error: string | null;
}

interface UseShortcutsStoreReturn extends ShortcutsStoreState {
  updateShortcuts: (shortcuts: ShortcutConfig[]) => Promise<void>;
  resetToDefaults: () => Promise<void>;
  reloadShortcuts: () => Promise<void>;
}

function mergeWithDefaults(stored: Record<string, string>): ShortcutConfig[] {
  return DEFAULT_SHORTCUTS.map(defaultShortcut => ({
    ...defaultShortcut,
    currentBinding: stored[defaultShortcut.id] || defaultShortcut.defaultBinding,
  }));
}

function shortcutsToStorageFormat(shortcuts: ShortcutConfig[]): Record<string, string> {
  return shortcuts.reduce((acc, s) => {
    if (s.currentBinding !== s.defaultBinding) {
      acc[s.id] = s.currentBinding;
    }
    return acc;
  }, {} as Record<string, string>);
}

export function useShortcutsStore(): UseShortcutsStoreReturn {
  const [state, setState] = useState<ShortcutsStoreState>({
    shortcuts: DEFAULT_SHORTCUTS,
    isLoading: true,
    error: null,
  });

  // Load shortcuts from storage on mount
  const loadShortcuts = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      // Try to load from Tauri store first
      const core = await getTauriCore();
      if (core) {
        const storedData = await core.invoke<string | null>('get_shortcuts_config').catch(() => null);

        if (storedData) {
          const parsed = JSON.parse(storedData) as Record<string, string>;
          const merged = mergeWithDefaults(parsed);
          setState({ shortcuts: merged, isLoading: false, error: null });
          return;
        }
      }

      // Fallback to localStorage for development
      const localData = localStorage.getItem(STORAGE_KEY);
      if (localData) {
        const parsed = JSON.parse(localData) as Record<string, string>;
        const merged = mergeWithDefaults(parsed);
        setState({ shortcuts: merged, isLoading: false, error: null });
        return;
      }

      // Use defaults
      setState({ shortcuts: DEFAULT_SHORTCUTS, isLoading: false, error: null });
    } catch (err) {
      console.error('Failed to load shortcuts:', err);
      setState({
        shortcuts: DEFAULT_SHORTCUTS,
        isLoading: false,
        error: 'Erreur lors du chargement des raccourcis',
      });
    }
  }, []);

  // Save shortcuts to storage
  const saveShortcuts = useCallback(async (shortcuts: ShortcutConfig[]) => {
    const storageData = shortcutsToStorageFormat(shortcuts);
    const jsonData = JSON.stringify(storageData);

    try {
      const core = await getTauriCore();
      const event = await getTauriEvent();

      if (core) {
        // Save to Tauri store
        await core.invoke('set_shortcuts_config', { config: jsonData }).catch(err => {
          console.error('[useShortcutsStore] Tauri invoke failed, falling back to localStorage:', err);
          localStorage.setItem(STORAGE_KEY, jsonData);
        });
      } else {
        // Web fallback
        localStorage.setItem(STORAGE_KEY, jsonData);
      }

      // Emit event for backend to re-register shortcuts
      if (event) {
        await event.emit('shortcuts-changed', { shortcuts }).catch(() => { /* fire-and-forget */ });
      }
    } catch (err) {
      console.error('Failed to save shortcuts:', err);
      throw err;
    }
  }, []);

  const updateShortcuts = useCallback(async (newShortcuts: ShortcutConfig[]) => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      await saveShortcuts(newShortcuts);
      setState({ shortcuts: newShortcuts, isLoading: false, error: null });
    } catch (err) {
      console.error('Failed to update shortcuts:', err);
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: 'Erreur lors de la sauvegarde des raccourcis',
      }));
    }
  }, [saveShortcuts]);

  const resetToDefaults = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const core = await getTauriCore();
      const event = await getTauriEvent();

      if (core) {
        // Clear storage
        await core.invoke('set_shortcuts_config', { config: '{}' }).catch(err => {
          console.error('[useShortcutsStore] Tauri reset failed, falling back to localStorage:', err);
          localStorage.removeItem(STORAGE_KEY);
        });
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }

      // Emit event for backend to re-register shortcuts
      if (event) {
        await event.emit('shortcuts-changed', { shortcuts: DEFAULT_SHORTCUTS }).catch(() => { /* fire-and-forget */ });
      }

      setState({ shortcuts: DEFAULT_SHORTCUTS, isLoading: false, error: null });
    } catch (err) {
      console.error('Failed to reset shortcuts:', err);
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: i18n.t('errors:shortcuts_reset_failed'),
      }));
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadShortcuts();
  }, [loadShortcuts]);

  // Listen for external changes (e.g., from another window)
  useEffect(() => {
    let unlisten: (() => void) | undefined;

    const setupListener = async () => {
      const event = await getTauriEvent();
      if (!event) return;

      unlisten = await event.listen('shortcuts-updated', () => {
        loadShortcuts();
      });
    };

    setupListener();

    return () => {
      unlisten?.();
    };
  }, [loadShortcuts]);

  return {
    ...state,
    updateShortcuts,
    resetToDefaults,
    reloadShortcuts: loadShortcuts,
  };
}
