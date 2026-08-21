import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import i18n from '../i18n';
import { fetchPinnedEmailIds, pinEmail, unpinEmail } from '../services/api';
import { silentFailWithToast } from '../utils/silentFail';

const STORAGE_KEY = 'agentys_pinned';

function readPinnedIds(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

export interface PinnedHook {
  pinnedIds: Set<string>;
  togglePin: (emailId: string) => void;
  addPin: (emailId: string) => void;
}

export function usePinned(): PinnedHook {
  const [ids, setIds] = useState<string[]>(() => readPinnedIds());
  const skipExternalSync = useRef(false);

  // On mount: adopt the backend-persisted pin set as authoritative. It is
  // written by the daemon auto-trigger and the follow-up wake sweep, and
  // CLEARED when a follow-up is auto-unpinned server-side (its relance was
  // sent / the draft rejected). Two-way, mirroring useSnooze's reminder sync:
  // backend additions appear AND ids the backend no longer reports are
  // dropped — so a handled follow-up stops showing as pinned on next mount.
  // (A manual pin whose POST is still in flight at mount is rare and
  // self-heals on the next mount once it commits.)
  useEffect(() => {
    fetchPinnedEmailIds().then((response) => {
      const pinned_ids = Array.isArray(response?.pinned_ids) ? response.pinned_ids : null;
      if (!pinned_ids) return;
      setIds(prev =>
        (prev.length === pinned_ids.length && prev.every(id => pinned_ids.includes(id)))
          ? prev
          : pinned_ids
      );
    }).catch(() => {/* best-effort: leave local state intact */});
  }, []);

  // Sync from other tabs / windows
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && !skipExternalSync.current) {
        setIds(readPinnedIds());
      }
    };
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
  }, []);

  // Sync to localStorage after every state change (pure side effect, outside updater)
  useEffect(() => {
    skipExternalSync.current = true;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
      window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }));
    } catch {
      // ignore
    }
    skipExternalSync.current = false;
  }, [ids]);

  // Audit F-05 (2026-05-12): when the optimistic pin/unpin fails, roll back
  // the local state and surface a warning toast. Previously the UI stayed in
  // its optimistic state forever — next refresh silently dropped the pin.
  const togglePin = useCallback((emailId: string) => {
    setIds(prev => {
      const isPinning = !prev.includes(emailId);
      const next = isPinning
        ? [...prev, emailId]
        : prev.filter(id => id !== emailId);
      const op = isPinning ? pinEmail(emailId) : unpinEmail(emailId);
      op.catch(err => {
        silentFailWithToast(isPinning ? 'pin-email' : 'unpin-email', {
          message: isPinning
            ? i18n.t('common:toasts.pin_save_failed')
            : i18n.t('common:toasts.unpin_save_failed'),
        })(err);
        setIds(curr => isPinning
          ? curr.filter(id => id !== emailId)
          : (curr.includes(emailId) ? curr : [...curr, emailId])
        );
      });
      return next;
    });
  }, []);

  const addPin = useCallback((emailId: string) => {
    setIds(prev => {
      if (prev.includes(emailId)) return prev;
      pinEmail(emailId).catch(err => {
        silentFailWithToast('pin-email', {
          message: i18n.t('common:toasts.pin_save_failed'),
        })(err);
        setIds(curr => curr.filter(id => id !== emailId));
      });
      return [...prev, emailId];
    });
  }, []);

  // Memoize the Set so its identity is stable while `ids` is unchanged.
  // Returning `new Set(ids)` on every render produced a fresh reference each
  // time, invalidating EmailList's `flatRows`/`rowProps` useMemos (pinnedIds is
  // a dep) and re-rendering the whole virtualized inbox on every interaction.
  const pinnedIds = useMemo(() => new Set(ids), [ids]);

  return { pinnedIds, togglePin, addPin };
}
