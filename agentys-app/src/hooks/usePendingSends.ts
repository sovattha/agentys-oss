/**
 * Pending Sends Store — tracks emails in the 15s undo-send window.
 *
 * Persists payloads to localStorage so a window-close / refresh / OS sleep during
 * the undo window does not silently lose the email (audit 2026-04-25, Send-HIGH).
 *
 * On module load, expired snapshots fire immediately; live snapshots get a fresh
 * timer scheduled for their remaining time.
 *
 * Used by SwipeableEmailItem to show "Annuler l'envoi" in context menu.
 */

import i18n from '../i18n';
import { apiClient } from '../services/api';
import { updateCachedEmailDetail } from '../api/emails';
import { saveComposeDraft } from '../services/draftStorage';

const PERSIST_KEY = 'agentys:pending-sends-v1';
const PERSIST_TTL_MS = 5 * 60 * 1000; // drop stale snapshots after 5 minutes

export interface SendAttachment {
  filename: string;
  data: string; // base64 (without the data: prefix)
  content_type: string;
}

export interface SendPayload {
  to: string;
  subject: string;
  body: string;
  cc?: string;
  bcc?: string;
  attachments?: SendAttachment[];
  aiAssisted?: boolean;
  skipSignature?: boolean;
  signatureHtml?: string;
  /** Account that initiated this send. Captured at registration time so an
   *  account switch during the undo window doesn't send from the wrong account. */
  accountId?: string;
}

interface PersistedSnapshot {
  emailId: string;
  payload: SendPayload;
  scheduledAt: number; // ms timestamp when send should fire
  createdAt: number;
  firedAt?: number; // ms timestamp a boot last fired this snapshot (in-flight guard)
}

export interface PendingSend {
  payload: SendPayload;
  timerId: ReturnType<typeof setTimeout>;
  sentAt: Date;
  /** Seconds remaining (updated every second by an interval) */
  remaining: number;
  /** Interval that ticks `remaining` down */
  tickId: ReturnType<typeof setInterval>;
}

const pendingSends = new Map<string, PendingSend>();
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((fn) => fn());
}

// ─── Persistence helpers ───────────────────────────────────────────────────

function safeStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function loadAllPersisted(): PersistedSnapshot[] {
  const storage = safeStorage();
  if (!storage) return [];
  try {
    const raw = storage.getItem(PERSIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as PersistedSnapshot[];
  } catch {
    return [];
  }
}

function writeAllPersisted(snapshots: PersistedSnapshot[]) {
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.setItem(PERSIST_KEY, JSON.stringify(snapshots));
  } catch {
    // Quota exceeded or storage unavailable — degrade gracefully
  }
}

function persistAdd(snapshot: PersistedSnapshot) {
  const all = loadAllPersisted().filter(s => s.emailId !== snapshot.emailId);
  all.push(snapshot);
  writeAllPersisted(all);
}

function persistRemove(emailId: string) {
  const all = loadAllPersisted().filter(s => s.emailId !== emailId);
  writeAllPersisted(all);
}

function splitRecipients(value?: string): string[] {
  return (value || '')
    .split(/[,;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function stripHtmlForPreview(value: string): string {
  return value
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function clientSendIdForBackend(emailId: string): string {
  return emailId.startsWith('sent:') ? emailId.slice('sent:'.length) : emailId;
}

// ─── Send execution ────────────────────────────────────────────────────────

async function executeSend(emailId: string, payload: SendPayload): Promise<void> {
  let keepSnapshot = false;
  try {
    await apiClient.sendNewEmail(
      payload.to,
      payload.subject,
      payload.body,
      payload.cc,
      payload.bcc,
      payload.attachments,
      payload.aiAssisted ?? false,
      payload.skipSignature,
      payload.signatureHtml,
      payload.accountId,
      clientSendIdForBackend(emailId),
    );
    const bodyText = stripHtmlForPreview(payload.body);
    updateCachedEmailDetail(emailId, {
      id: emailId,
      sender: '',
      sender_name: '',
      subject: payload.subject || '(Sans objet)',
      received_at: new Date().toISOString(),
      has_attachments: Boolean(payload.attachments?.length),
      body_preview: bodyText.slice(0, 200),
      has_pending_draft: false,
      labels: [],
      to: splitRecipients(payload.to),
      cc: splitRecipients(payload.cc),
      attachments: (payload.attachments || []).map((attachment) => ({
        id: attachment.filename,
        filename: attachment.filename,
        size: Math.ceil((attachment.data.length * 3) / 4),
        content_type: attachment.content_type,
      })),
      body: payload.body,
      body_html: payload.body,
      body_text: bodyText,
      is_read: true,
    });
  } catch (err) {
    console.error('[PendingSend] Send failed:', err);
    let message = err instanceof Error ? err.message : i18n.t('compose:err_unknown');
    // Friendly 429 with retry_after countdown (audit Send-MEDIUM
    // "rate-limit silently triggered"). ApiError surfaces .retryAfter.
    const apiErr = err as { status?: number; retryAfter?: number };
    if (apiErr?.status === 429) {
      // Audit Codex 2026-04-25 [Stability MED-10]: previously the finally
      // unconditionally cleared the persisted snapshot, so a 429 lost the
      // payload before the user could retry. Keep the snapshot live and let
      // hydrateFromStorage re-fire after the retry-after window. We push the
      // scheduled time forward so the timer doesn't immediately re-trigger.
      const retryAfter = apiErr.retryAfter && apiErr.retryAfter > 0 ? apiErr.retryAfter : 30;
      message = i18n.t('compose:err_rate_limited', { seconds: retryAfter });
      const now = Date.now();
      persistAdd({
        emailId,
        payload,
        scheduledAt: now + retryAfter * 1000,
        createdAt: now,
      });
      keepSnapshot = true;
    }
    // Audit e2e 2026-06-10 U-02: a terminal send failure used to destroy the
    // content — the modal deletes its saved draft before registering the send,
    // and the finally below clears the persisted snapshot. Restore the payload
    // as a compose draft so the user can reopen/retry from Brouillons. The 429
    // path is excluded: its snapshot stays live and auto-refires, so a restored
    // draft would turn into a stale duplicate once the retry lands.
    let draftRestored = false;
    if (apiErr?.status !== 429) {
      try {
        saveComposeDraft({
          id: `restored-${emailId}`,
          to: payload.to,
          cc: payload.cc || '',
          bcc: payload.bcc || '',
          subject: payload.subject,
          body: payload.body,
        });
        draftRestored = true;
      } catch (restoreErr) {
        console.error('[PendingSend] draft restore failed:', restoreErr);
      }
    }
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('agentys:send-failed', {
        detail: {
          error: message,
          to: payload.to,
          subject: payload.subject || '(sans objet)',
          emailId,
          retryAfter: apiErr?.retryAfter,
          draftRestored,
        },
      }));
    }
  } finally {
    if (!keepSnapshot) persistRemove(emailId);
  }
}

function scheduleSend(emailId: string, payload: SendPayload, delaySec: number, sentAt: Date) {
  // Clear any existing pending send for this ID (keeps the timer count bounded).
  cancelPendingSend(emailId);

  const timerId = setTimeout(() => {
    const entry = pendingSends.get(emailId);
    if (entry) clearInterval(entry.tickId);
    pendingSends.delete(emailId);
    notify();
    void executeSend(emailId, payload);
  }, Math.max(0, delaySec * 1000));

  let remaining = delaySec;
  const tickId = setInterval(() => {
    remaining -= 1;
    const entry = pendingSends.get(emailId);
    if (entry) {
      entry.remaining = remaining;
      notify();
    }
    if (remaining <= 0) clearInterval(tickId);
  }, 1000);

  pendingSends.set(emailId, {
    payload,
    timerId,
    sentAt,
    remaining: delaySec,
    tickId,
  });

  notify();
}

// ─── Public API ────────────────────────────────────────────────────────────

/**
 * Register an email send that will execute after `delaySec` seconds.
 * The payload is persisted to localStorage and rehydrated on next boot
 * if the window closes during the undo window.
 *
 * Returns a cleanup function (cancels the send).
 */
export function registerPendingSend(
  emailId: string,
  payload: SendPayload,
  delaySec: number,
): () => void {
  const now = Date.now();
  const scheduledAt = now + delaySec * 1000;

  persistAdd({
    emailId,
    payload,
    scheduledAt,
    createdAt: now,
  });

  scheduleSend(emailId, payload, delaySec, new Date(now));

  return () => cancelPendingSend(emailId);
}

/**
 * Cancel a pending send — clears the timer and removes the persisted snapshot.
 * The email is NOT sent. Returns true if there was a pending send to cancel.
 */
export function cancelPendingSend(emailId: string): boolean {
  persistRemove(emailId);
  const entry = pendingSends.get(emailId);
  if (!entry) return false;
  clearTimeout(entry.timerId);
  clearInterval(entry.tickId);
  pendingSends.delete(emailId);
  notify();
  return true;
}

/** Check if an email is in the pending-send window. */
export function isPendingSend(emailId: string): boolean {
  return pendingSends.has(emailId);
}

/** Get remaining seconds for a pending send (0 if not pending). */
export function getPendingSendRemaining(emailId: string): number {
  return pendingSends.get(emailId)?.remaining ?? 0;
}

/** Subscribe to changes. Returns unsubscribe function. */
export function subscribePendingSends(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// ─── Boot rehydration ──────────────────────────────────────────────────────

/**
 * Walk localStorage on module load. Snapshots whose scheduled time has already
 * passed fire immediately (best-effort recovery from a previous window close).
 * Snapshots still in the future get a fresh timer for the remaining delay.
 *
 * Snapshots older than PERSIST_TTL_MS are dropped (safety net against forever-stuck entries).
 */
function hydrateFromStorage() {
  const snapshots = loadAllPersisted();
  if (!snapshots.length) return;
  const now = Date.now();
  const survivors: PersistedSnapshot[] = [];

  for (const snap of snapshots) {
    if (typeof snap?.scheduledAt !== 'number' || typeof snap?.createdAt !== 'number') continue;
    if (now - snap.createdAt > PERSIST_TTL_MS) continue; // too stale, drop

    if (now >= snap.scheduledAt) {
      // Already due. Guard against a DOUBLE send across a second reload: a
      // previous boot may have fired this snapshot and the POST could still be
      // in flight (executeSend only persistRemove()s in its finally, AFTER the
      // network call resolves). If we fired it within the in-flight window, do
      // NOT re-fire this boot — but keep it, so a later boot past the window
      // still re-fires for eventual delivery if that first attempt never
      // completed. (chaos audit 2026-06-02 — /emails/send-new has no idempotency key)
      const IN_FLIGHT_GUARD_MS = 90_000;
      if (typeof snap.firedAt === 'number' && now - snap.firedAt < IN_FLIGHT_GUARD_MS) {
        survivors.push(snap);
        // Audit 2026-06-02 K: don't depend on a SECOND reload to re-fire after
        // the guard window. Arm an in-session timer; when the window closes, if
        // the snapshot is still persisted (the first attempt's POST never
        // completed — its finally never ran persistRemove), re-fire for eventual
        // delivery. A completed or caught-error attempt already removed the
        // snapshot, so this no-ops in the common case. Re-stamping firedAt keeps
        // the cross-boot guard intact if this re-fire is itself torn down.
        const refireId = snap.emailId;
        const recheckDelay = Math.max(1000, snap.firedAt + IN_FLIGHT_GUARD_MS - now + 1000);
        setTimeout(() => {
          const still = loadAllPersisted().find(s => s.emailId === refireId);
          if (!still) return; // first attempt completed → nothing to re-fire
          persistAdd({ ...still, firedAt: Date.now() });
          void executeSend(still.emailId, still.payload);
        }, recheckDelay);
        continue;
      }
      // Stamp firedAt so a subsequent boot can see this is already in flight.
      survivors.push({ ...snap, firedAt: now });
      void executeSend(snap.emailId, snap.payload);
    } else {
      const remainingSec = Math.max(1, Math.ceil((snap.scheduledAt - now) / 1000));
      survivors.push(snap);
      scheduleSend(snap.emailId, snap.payload, remainingSec, new Date(snap.createdAt));
    }
  }

  writeAllPersisted(survivors);
}

// Best-effort beforeunload flush — synchronously persist anything still queued
// (it's already persisted via persistAdd, but snapshot the latest remaining
// time so a fast-cycle rehydrate doesn't double-fire).
function installBeforeUnloadFlush() {
  if (typeof window === 'undefined') return;
  window.addEventListener('beforeunload', () => {
    // No-op: persistence is already maintained synchronously on register/cancel.
    // The hook is here as a placeholder for future "fire-now" semantics if we
    // ever decide to send immediately on close instead of rehydrating later.
  });
}

if (typeof window !== 'undefined') {
  // Defer slightly to avoid hydrating before apiClient is ready in dev HMR.
  setTimeout(() => {
    try { hydrateFromStorage(); } catch (e) { console.warn('[PendingSend] hydrate failed:', e); }
  }, 0);
  installBeforeUnloadFlush();
}

// ─── React hook ────────────────────────────────────────────────────────────

import { useSyncExternalStore } from 'react';

// Audit Codex 2026-04-25 [CRIT-Stability-2]: previously this module called
// `listeners.add(() => { snapshotVersion++; })` at top level — every HMR
// re-evaluation appended a closure that was never removed. Drive the version
// counter through the same subscribe channel that React uses; useSyncExternalStore
// already wires/unwires the listener on mount/unmount.
let snapshotVersion = 0;

function subscribeAndBumpVersion(cb: () => void): () => void {
  const wrapped = () => {
    snapshotVersion++;
    cb();
  };
  return subscribePendingSends(wrapped);
}

export function usePendingSends(emailId?: string) {
  useSyncExternalStore(
    subscribeAndBumpVersion,
    // Per-row callers pass their emailId: the snapshot is THEN that email's
    // pending-remaining (a primitive), so useSyncExternalStore's Object.is
    // bail-out skips re-rendering rows whose value didn't change on the 1s tick
    // — only the single counting-down row re-renders (audit 2026-06-02 O:
    // previously every visible row re-rendered each second during the undo
    // window, since all subscribers shared one global version counter).
    // List-level callers (no emailId) keep the global version counter.
    emailId != null ? () => getPendingSendRemaining(emailId) : () => snapshotVersion,
  );

  return {
    isPendingSend,
    getPendingSendRemaining,
    cancelPendingSend,
  };
}
