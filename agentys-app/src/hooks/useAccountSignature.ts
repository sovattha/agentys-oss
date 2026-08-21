import { useState, useEffect } from 'react';
import { fetchAccounts } from '../api/accounts';
import { ACCOUNT_CHANGED, appEvents } from '../lib/appEvents';
import { getStoredToken } from '../services/authToken';

interface SignatureData {
  html: string | null;
  text: string | null;
}

// Module-level cache to avoid re-fetching on every mount. It is invalidated on
// account/login transitions because signatures are mailbox identity data.
let cachedSignature: SignatureData = { html: null, text: null };
let cacheLoaded = false;
let fetchPromise: Promise<SignatureData> | null = null;
let fetchFailed = false;
let invalidationListenersInstalled = false;
const scopedCache = new Map<string, SignatureData>();
const scopedLoaded = new Set<string>();
const scopedFetches = new Map<string, Promise<SignatureData>>();
const scopedFailures = new Set<string>();
const scopedListeners = new Map<string, Set<(data: SignatureData) => void>>();

function htmlToPlainText(html: string): string {
  let text = html;
  // Block-level closing tags → newline
  text = text.replace(/<\/(div|p|li|tr|h[1-6])>/gi, '\n');
  // <br> → newline
  text = text.replace(/<br\s*\/?>/gi, '\n');
  // Strip remaining HTML tags
  text = text.replace(/<[^>]+>/g, '');
  // Decode HTML entities (use a textarea for full coverage)
  const ta = document.createElement('textarea');
  ta.innerHTML = text;
  text = ta.value;
  // Collapse any multiple blank lines to a single newline, trim each line
  text = text.split('\n').map(l => l.trim()).join('\n').replace(/\n{2,}/g, '\n');
  return text.trim();
}

function normalizeAccountEmail(accountEmail?: string | null): string {
  return (accountEmail || '').trim().toLowerCase();
}

function selectAccount(
  accounts: Awaited<ReturnType<typeof fetchAccounts>>['accounts'],
  currentAccountId: string | null,
  accountEmail?: string | null
) {
  const requestedEmail = normalizeAccountEmail(accountEmail);
  if (requestedEmail) {
    const match = accounts.find(a => (a.email || '').toLowerCase() === requestedEmail);
    if (match) return match;
  }
  return (
    currentAccountId
      ? accounts.find(a => a.id === currentAccountId) || accounts.find(a => a.is_current)
      : accounts.find(a => a.is_current)
  ) || accounts[0];
}

function signatureFromAccount(account: ReturnType<typeof selectAccount>): SignatureData {
  const html = account?.signature_html || account?.signature || null;
  const text = html ? htmlToPlainText(html) : (account?.signature || null);
  return { html, text };
}

function notifyListeners(data: SignatureData): void {
  listeners.forEach(fn => fn(data));
}

function notifyScopedListeners(accountEmail: string, data: SignatureData): void {
  scopedListeners.get(accountEmail)?.forEach(fn => fn(data));
}

function addScopedListener(accountEmail: string, fn: (data: SignatureData) => void): void {
  const existing = scopedListeners.get(accountEmail) || new Set<(data: SignatureData) => void>();
  existing.add(fn);
  scopedListeners.set(accountEmail, existing);
}

function removeScopedListener(accountEmail: string, fn: (data: SignatureData) => void): void {
  const existing = scopedListeners.get(accountEmail);
  if (!existing) return;
  existing.delete(fn);
  if (existing.size === 0) scopedListeners.delete(accountEmail);
}

function doFetch(): Promise<SignatureData> {
  if (!getStoredToken()) {
    fetchPromise = null;
    fetchFailed = false;
    cacheLoaded = false;
    cachedSignature = { html: null, text: null };
    notifyListeners(cachedSignature);
    return Promise.resolve(cachedSignature);
  }

  if (!fetchPromise || fetchFailed) {
    fetchFailed = false;
    fetchPromise = fetchAccounts()
      .then(({ accounts, current_account_id }) => {
        cachedSignature = signatureFromAccount(selectAccount(accounts, current_account_id));
        cacheLoaded = true;
        fetchPromise = null;
        // Notify all mounted hooks
        notifyListeners(cachedSignature);
        return cachedSignature;
      })
      .catch(() => {
        fetchFailed = true;
        fetchPromise = null;
        return { html: null, text: null } as SignatureData;
      });
  }
  return fetchPromise;
}

function doFetchForAccount(accountEmail: string): Promise<SignatureData> {
  if (!getStoredToken()) {
    const empty = { html: null, text: null };
    scopedFetches.delete(accountEmail);
    scopedFailures.delete(accountEmail);
    scopedLoaded.delete(accountEmail);
    scopedCache.set(accountEmail, empty);
    notifyScopedListeners(accountEmail, empty);
    return Promise.resolve(empty);
  }

  const failed = scopedFailures.has(accountEmail);
  const existing = scopedFetches.get(accountEmail);
  if (existing && !failed) return existing;

  scopedFailures.delete(accountEmail);
  const promise = fetchAccounts()
    .then(({ accounts, current_account_id }) => {
      const signature = signatureFromAccount(
        selectAccount(accounts, current_account_id, accountEmail)
      );
      scopedCache.set(accountEmail, signature);
      scopedLoaded.add(accountEmail);
      scopedFetches.delete(accountEmail);
      notifyScopedListeners(accountEmail, signature);
      return signature;
    })
    .catch(() => {
      scopedFailures.add(accountEmail);
      scopedFetches.delete(accountEmail);
      return { html: null, text: null } as SignatureData;
    });
  scopedFetches.set(accountEmail, promise);
  return promise;
}

function invalidateAndRefetch(): void {
  const scopedEmails = Array.from(scopedListeners.keys());
  cachedSignature = { html: null, text: null };
  cacheLoaded = false;
  fetchPromise = null;
  fetchFailed = false;
  scopedCache.clear();
  scopedLoaded.clear();
  scopedFetches.clear();
  scopedFailures.clear();
  notifyListeners(cachedSignature);
  scopedEmails.forEach(email => notifyScopedListeners(email, cachedSignature));
  void doFetch();
  scopedEmails.forEach(email => {
    void doFetchForAccount(email);
  });
}

function installInvalidationListeners(): void {
  if (invalidationListenersInstalled || typeof window === 'undefined') return;
  invalidationListenersInstalled = true;
  const onAccountChange = () => invalidateAndRefetch();
  appEvents.addEventListener(ACCOUNT_CHANGED, onAccountChange);
  window.addEventListener('auth:login_success', onAccountChange);
}

// Listener pattern so all mounted hooks get notified when fetch completes
const listeners = new Set<(data: SignatureData) => void>();

/**
 * Returns the active account's signature HTML and plain text (cached, single fetch).
 * Retries on failure. All mounted instances update when fetch completes.
 */
export function useAccountSignature(accountEmail?: string | null): SignatureData {
  const requestedEmail = normalizeAccountEmail(accountEmail);
  const initial = requestedEmail && scopedLoaded.has(requestedEmail)
    ? scopedCache.get(requestedEmail) || cachedSignature
    : cachedSignature;
  const [sig, setSig] = useState<SignatureData>(initial);

  useEffect(() => {
    // If already cached, use it immediately
    if (requestedEmail && scopedLoaded.has(requestedEmail)) {
      setSig(scopedCache.get(requestedEmail) || { html: null, text: null });
    } else if (!requestedEmail && cacheLoaded) {
      setSig(cachedSignature);
    }

    // Register listener for when fetch completes
    const onResult = (data: SignatureData) => setSig(data);
    if (requestedEmail) {
      addScopedListener(requestedEmail, onResult);
    } else {
      listeners.add(onResult);
    }

    // Trigger fetch (deduped)
    installInvalidationListeners();
    if (requestedEmail) {
      void doFetchForAccount(requestedEmail);
    } else {
      doFetch();
    }

    return () => {
      if (requestedEmail) {
        removeScopedListener(requestedEmail, onResult);
      } else {
        listeners.delete(onResult);
      }
    };
  }, [requestedEmail]);

  return sig;
}

/** Imperatively prefetch so the cache is warm before any component mounts */
export function prefetchAccountSignature(): void {
  doFetch();
}

/**
 * Push a new signature directly into the cache and notify all mounted hooks.
 * Call this after saving or syncing the signature so the preview updates immediately.
 *
 * `accountEmail` (optionnel) : met aussi à jour le cache SCOPÉ de ce compte et
 * notifie ses listeners — sans ça, un ReplyComposer monté (qui lit
 * useAccountSignature(ownEmail) via scopedCache) garderait l'ancienne
 * signature dans son footer alors que l'envoi utilise la nouvelle.
 */
export function setAccountSignatureCache(html: string | null, text: string | null, accountEmail?: string | null): void {
  cachedSignature = { html, text };
  cacheLoaded = true;
  fetchPromise = null;
  fetchFailed = false;
  listeners.forEach(fn => fn(cachedSignature));

  const scopedKey = normalizeAccountEmail(accountEmail);
  if (scopedKey) {
    scopedCache.set(scopedKey, cachedSignature);
    scopedLoaded.add(scopedKey);
    scopedFetches.delete(scopedKey);
    scopedFailures.delete(scopedKey);
    notifyScopedListeners(scopedKey, cachedSignature);
  }
}
