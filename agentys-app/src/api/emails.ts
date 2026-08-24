/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import type { EmailsResponse, EmailDetail, EmailThreadResponse, SearchResponse } from '../types/email';
import i18n from '../i18n';
import { API_URL } from '../config';
import { cacheRead, cacheWrite, cacheIsStale, cacheInvalidatePrefix, cacheWriteSync } from './cache';
import {
  buildCachedDraftEmailContext,
  clearEmailBodyCache,
  readEmailBodyCache,
  writeEmailBodyCacheSync,
  type CachedDraftEmailContext,
} from './emailBodyCache';
import { getAuthHeaders, registerActiveAccountProvider } from '../services/authToken';

const API_BASE_URL = `${API_URL}/api`;

export type EmailFilter = 'all' | 'unread';
export type EmailFolder = 'inbox' | 'sent' | 'archived' | 'spam' | 'trash';

export interface FetchEmailsOptions {
  limit?: number;
  offset?: number;
  filter?: EmailFilter;
  signal?: AbortSignal;
  folder?: EmailFolder;
  forceRefresh?: boolean;
  skipCache?: boolean;  // Skip frontend cache only (no backend force_refresh)
  skipBackendCache?: boolean;  // Skip backend in-memory cache (for WS-triggered refreshes)
  skipIndexedDb?: boolean;  // Skip writing result to IndexedDB
  label?: string;
  providerLabel?: string;
  excludeLabel?: string;
}

export interface EnqueueEmailSyncOptions {
  folder?: EmailFolder;
  limit?: number;
  unreadOnly?: boolean;
  source?: string;
  signal?: AbortSignal;
}

export interface EnqueueEmailSyncResult {
  success: boolean;
  job?: {
    id: string;
    account_id: number;
    folder: string;
    status: string;
    coalesced?: boolean;
  };
  error?: string;
}

export function createEmailFetchController(): AbortController {
  return new AbortController();
}

// ============================================================================
// CACHE HELPERS (IndexedDB via cache.ts)
// ============================================================================

const CACHE_PREFIX = 'agentys_emails_';

// Track active account to namespace cache keys and prevent cross-account leakage
let _activeAccountId = 'default';

// F11 (MEDIUM): account-level AbortController. Pre-fix, switching accounts
// while a `fetchEmails(limit=200)` for account A was still in flight could
// land its response after the switch and clobber `setEmails` with stale
// account-A data. Now every request that opts in (via getAccountFetchSignal)
// will be aborted on switch.
let _accountFetchController: AbortController | null = null;

/**
 * Returns the current account-scoped abort signal. Components and API
 * helpers can attach this to fetch options so that, on account switch,
 * stale in-flight requests are aborted before their response can mutate
 * the post-switch UI state. Survives re-creation across switches: each
 * `setActiveAccountId` aborts the previous controller and installs a fresh
 * one — never throws.
 */
export function getAccountFetchSignal(): AbortSignal {
  if (!_accountFetchController) {
    _accountFetchController = new AbortController();
  }
  return _accountFetchController.signal;
}

export function getActiveAccountId(): string {
  return _activeAccountId;
}

// Enregistre le provider côté authToken pour que getAuthHeaders() puisse
// injecter le header X-Account-Id (isolation multi-compte, double-clé JWT + header).
registerActiveAccountProvider(getActiveAccountId);

export const ACCOUNT_INVALID_EVENT = 'agentys:account-invalid';

export function setActiveAccountId(accountId: string): void {
  const newId = accountId || 'default';
  if (newId !== _activeAccountId) {
    const previousId = _activeAccountId;
    const wasDefault = _activeAccountId === 'default';
    // F11: abort all in-flight requests scoped to the previous account
    // BEFORE flipping the id. This guarantees that stale-response handlers
    // see AbortError and short-circuit instead of running setState on
    // post-switch state.
    if (_accountFetchController) {
      try { _accountFetchController.abort(); } catch { /* defensive */ }
    }
    _accountFetchController = new AbortController();
    _activeAccountId = newId;
    if (!wasDefault) {
      // Only invalidate when switching between real accounts, not on initial setup
      void cacheInvalidatePrefix(CACHE_PREFIX);
      void clearEmailBodyCache(previousId);
      void cacheInvalidatePrefix('calendar:events:');
      // Clear label-related caches (localStorage, not IndexedDB)
      try { localStorage.removeItem('agentys_favorite_labels_order'); } catch { /* ignore */ }
    }
    // Signal la transition 'default' → compte réel (OAuth initial) ou
    // compte A → compte B (switch). useLabels et EmailList écoutent cet
    // event pour refetch sans stocker eux-mêmes l'ID.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('agentys:account-changed'))
    }
  }
}

function getCacheKey(folder: string, offset: number, limit: number, filter: string): string {
  return `${CACHE_PREFIX}${_activeAccountId}_${folder}_${filter}_${offset}_${limit}`;
}

/** Build a cache key for an email list — usable from outside this module (e.g. init bootstrap). */
export function getEmailListCacheKey(
  accountId: string, folder: string, offset: number, limit: number, filter: string
): string {
  return `${CACHE_PREFIX}${accountId || _activeAccountId}_${folder}_${filter}_${offset}_${limit}`;
}

// ============================================================================
// EMAIL DETAIL PREFETCH CACHE (IndexedDB only, memory fallback)
// ============================================================================

export function invalidateEmailCache(): void {
  void cacheInvalidatePrefix(CACHE_PREFIX);
}
const prefetchInFlight = new Set<string>();

async function signalInvalidAccountHeader(response: Response, url: string): Promise<void> {
  if (response.status !== 404) return;

  try {
    const bodySource = typeof response.clone === 'function' ? response.clone() : response;
    const data = await bodySource.json() as { code?: string; error_code?: string };
    const code = data.code || data.error_code;
    if (code !== 'INVALID_ACCOUNT_HEADER') return;
  } catch {
    return;
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(ACCOUNT_INVALID_EVENT, {
      detail: {
        activeAccountId: _activeAccountId,
        status: response.status,
        url,
      },
    }));
  }
}

export async function getCachedEmailDetail(emailId: string): Promise<EmailDetail | null> {
  return readEmailBodyCache(_activeAccountId, emailId);
}

export async function getCachedDraftEmailContext(emailId: string): Promise<CachedDraftEmailContext | null> {
  return buildCachedDraftEmailContext(emailId, await getCachedEmailDetail(emailId));
}

export function prefetchEmailDetails(emailIds: string[], concurrency: number = 4): void {
  // Filter out in-flight IDs synchronously; cache check is async so we
  // optimistically enqueue and let fetchEmailDetail's own cache-read deduplicate.
  const queue = emailIds.filter(id => !prefetchInFlight.has(id));
  let active = 0;
  let index = 0;

  function next() {
    while (active < concurrency && index < queue.length) {
      const id = queue[index++];
      active++;
      prefetchInFlight.add(id);
      fetchEmailDetail(id)
        .catch(() => { /* fire-and-forget */ })
        .finally(() => {
          active--;
          prefetchInFlight.delete(id);
          next();
        });
    }
  }

  next();
}

export function prefetchSingleEmail(emailId: string): void {
  if (prefetchInFlight.has(emailId)) return;
  prefetchEmailDetails([emailId], 1);
}

// ============================================================================
// FETCH EMAILS (with stale-while-revalidate)
// ============================================================================

export interface FetchEmailsResult extends EmailsResponse {
  fromCache: boolean;
}

export async function fetchEmails(
  limitOrOptions: number | FetchEmailsOptions = 50,
  filter: EmailFilter = 'all'
): Promise<FetchEmailsResult> {
  const options: FetchEmailsOptions = typeof limitOrOptions === 'number'
    ? { limit: limitOrOptions, filter }
    : limitOrOptions;

  const { limit = 50, offset = 0, filter: emailFilter = 'all', signal, folder = 'inbox', forceRefresh = false, skipCache = false, skipBackendCache = false, skipIndexedDb = false, label, providerLabel, excludeLabel } = options;
  const cacheKey = getCacheKey(folder, offset, limit, emailFilter) + (label ? `_label_${label}` : '') + (providerLabel ? `_plabel_${providerLabel}` : '') + (excludeLabel ? `_excl_${excludeLabel}` : '');

  if (!forceRefresh && !skipCache && !label && !providerLabel) {
    // 1. Try IndexedDB cache first (skip cache when label/folder filtering — server handles it)
    const cached = await cacheRead<EmailsResponse>(cacheKey);

    if (cached && !cacheIsStale(cached) && (cached.data.emails?.length > 0 || folder !== 'inbox')) {
      // Fresh cache — return instantly, no network call needed
      // Never serve an empty inbox from cache (emails may exist but cache is stale after archive/delete)
      return { ...cached.data, fromCache: true };
    }

    // 2. If stale cache exists, return it immediately AND revalidate in background
    if (cached && (cached.data.emails?.length > 0 || folder !== 'inbox')) {
      // Background revalidation: don't bypass backend cache (skip_cache) — let the
      // backend serve from SQLite/memory quickly. Its stale-while-revalidate will
      // trigger a provider sync in background if needed.
      let bgUrl = `${API_BASE_URL}/emails?limit=${limit}&offset=${offset}&filter=${emailFilter}&folder=${folder}`;
      if (label)         bgUrl += `&label=${encodeURIComponent(label)}`;
      if (providerLabel) bgUrl += `&provider_label=${encodeURIComponent(providerLabel)}`;
      if (excludeLabel)  bgUrl += `&exclude_label=${encodeURIComponent(excludeLabel)}`;
      const bgFetch = fetch(bgUrl, { signal, headers: { ...getAuthHeaders() } })
        .then(async r => {
          if (!r.ok) {
            await signalInvalidAccountHeader(r, bgUrl);
            return null;
          }
          return r.json();
        })
        .then(data => { if (data) cacheWriteSync(cacheKey, data); })
        .catch(() => {});

      void bgFetch;

      return { ...cached.data, fromCache: true };
    }
  }

  if (forceRefresh) {
    try {
      await enqueueEmailSyncJob({
        folder,
        limit,
        unreadOnly: emailFilter === 'unread',
        source: 'manual',
        signal,
      });
    } catch (err) {
      console.warn('[emails] sync job enqueue failed, falling back to DB read:', err);
    }
  }

  // 3. No cache or forceRefresh — fetch from backend DB only
  let url = `${API_BASE_URL}/emails?limit=${limit}&offset=${offset}&filter=${emailFilter}&folder=${folder}`;
  if (label) {
    url += `&label=${encodeURIComponent(label)}`;
  }
  if (providerLabel) {
    url += `&provider_label=${encodeURIComponent(providerLabel)}`;
  }
  if (excludeLabel) {
    url += `&exclude_label=${encodeURIComponent(excludeLabel)}`;
  }
  if (skipBackendCache) {
    url += '&skip_cache=true';
  }
  const authHeaders = getAuthHeaders();
  const response = await fetch(url, { 
    signal,
    headers: { ...authHeaders }
  });
  if (!response.ok) {
    await signalInvalidAccountHeader(response, url);
    throw new Error(`Failed to fetch emails: ${response.status}`);
  }
  const data: EmailsResponse = await response.json();
  if (!skipIndexedDb && data.source !== 'syncing' && !data.sync_in_progress && !data.sync_failed) {
    await cacheWrite(cacheKey, data);
  }
  return { ...data, fromCache: false };
}

export async function enqueueEmailSyncJob(
  options: EnqueueEmailSyncOptions = {}
): Promise<EnqueueEmailSyncResult> {
  const {
    folder = 'inbox',
    limit = 50,
    unreadOnly = false,
    source = 'manual',
    signal,
  } = options;
  const response = await fetch(`${API_BASE_URL}/sync/jobs`, {
    method: 'POST',
    signal,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      folder,
      limit,
      unread_only: unreadOnly,
      source,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to enqueue sync job: ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// STANDARD API FUNCTIONS
// ============================================================================

export async function fetchEmailDetail(emailId: string, options?: { skipCache?: boolean }): Promise<EmailDetail> {
  if (!options?.skipCache) {
    // Check prefetch cache first (IndexedDB)
    const cached = await getCachedEmailDetail(emailId);
    if (cached) {
      const expectsAttachments = cached.has_attachments === true;
      const hasRealAttachments = Array.isArray(cached.attachments)
        && cached.attachments.length > 0
        && !!(cached.attachments as Array<{filename?: string}>)[0]?.filename;
      // Don't serve stale cache when attachments are expected but metadata is missing
      if (!expectsAttachments || hasRealAttachments) {
        return cached;
      }
    }
  }

  const response = await fetch(`${API_BASE_URL}/emails/${encodeURIComponent(emailId)}`, { headers: { ...getAuthHeaders() } });
  if (!response.ok) {
    throw new Error(`Failed to fetch email detail: ${response.status}`);
  }
  const detail: EmailDetail = await response.json();
  // Cache the result for future access (IndexedDB) — only if body is present
  // Don't cache incomplete results where attachments are expected but missing
  const attComplete = !detail.has_attachments || (Array.isArray(detail.attachments) && detail.attachments.length > 0);
  if ((detail.body || detail.body_html) && attComplete) {
    writeEmailBodyCacheSync(_activeAccountId, emailId, detail);
  }
  return detail;
}

export function updateCachedEmailDetail(emailId: string, detail: EmailDetail): void {
  if (detail.body || detail.body_html) {
    writeEmailBodyCacheSync(_activeAccountId, emailId, detail);
  }
}

export async function fetchEmailThread(emailId: string): Promise<EmailThreadResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/${emailId}/thread`, { headers: { ...getAuthHeaders() } });
  if (!response.ok) {
    throw new Error(`Failed to fetch email thread: ${response.status}`);
  }
  return response.json();
}

export interface SearchEmailsOptions {
  query: string;
  limit?: number;
  signal?: AbortSignal;
  accountId?: string;
}

export async function searchEmails(
  queryOrOptions: string | SearchEmailsOptions,
  limitArg: number = 50
): Promise<SearchResponse> {
  // Support both (query, limit) and ({ query, limit, signal }) signatures
  const options: SearchEmailsOptions = typeof queryOrOptions === 'string'
    ? { query: queryOrOptions, limit: limitArg }
    : queryOrOptions;

  const { query, limit = 50, signal, accountId } = options;

  const params = new URLSearchParams();
  if (query) {
    params.set('q', query);
  }
  params.set('limit', String(limit));
  if (accountId) {
    params.set('account_id', accountId);
  }

  const response = await fetch(`${API_BASE_URL}/emails/search?${params.toString()}`, { signal, headers: { ...getAuthHeaders() } });
  if (!response.ok) {
    throw new Error(`Search failed: ${response.status}`);
  }
  return response.json();
}

export interface MarkReadResponse {
  success: boolean;
  email_id: string;
  is_read: boolean;
}

export interface BulkMarkReadResponse {
  success: boolean;
  updated_count: number;
  email_ids: string[];
  is_read: boolean;
}

export async function markEmailRead(emailId: string): Promise<MarkReadResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/${emailId}/read`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ is_read: true }),
  });
  if (!response.ok) {
    throw new Error(`Failed to mark email as read: ${response.status}`);
  }
  return response.json();
}

export async function markEmailUnread(emailId: string): Promise<MarkReadResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/${emailId}/read`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ is_read: false }),
  });
  if (!response.ok) {
    throw new Error(`Failed to mark email as unread: ${response.status}`);
  }
  return response.json();
}

export async function markEmailsBulk(emailIds: string[], isRead: boolean): Promise<BulkMarkReadResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/bulk-read`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ email_ids: emailIds, is_read: isRead }),
  });
  if (!response.ok) {
    throw new Error(`Failed to bulk update emails: ${response.status}`);
  }
  return response.json();
}

export interface GenerateDraftRequest {
  instructions?: string;
  reply_type?: 'reply' | 'reply_all';
  cached_email?: CachedDraftEmailContext;
}

export interface GenerateDraftResponse {
  success: boolean;
  draft_id: string;
  email_id: string;
  classification: string;
  priority: string;
  status: string;
  draft_preview: string;
  instructions: string;
  reply_type: string;
}

export async function generateDraft(
  emailId: string,
  options: GenerateDraftRequest = {}
): Promise<GenerateDraftResponse> {
  // Draft generation can take time (LLM calls, conversation history, etc.)
  // Use a 3-minute timeout instead of default browser timeout
  const DRAFT_TIMEOUT_MS = 180000; // 3 minutes

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DRAFT_TIMEOUT_MS);

  try {
    const cachedEmail = options.cached_email || await getCachedDraftEmailContext(emailId);
    const response = await fetch(`${API_BASE_URL}/emails/${emailId}/process`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        instructions: options.instructions || '',
        reply_type: options.reply_type || 'reply',
        force: true,
        ...(cachedEmail ? { cached_email: cachedEmail } : {}),
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      if (response.status === 429 && errorData.retry_after) {
        throw new Error(i18n.t('errors:rate_limited_retry_in', { seconds: errorData.retry_after }));
      }
      if (response.status === 404) {
        throw new Error('EMAIL_NOT_FOUND');
      }
      throw new Error(errorData.error || `Failed to generate draft: ${response.status}`);
    }

    return response.json();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('Request timeout - Draft generation took too long. Please try again.', { cause: error });
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

// Subscriptions Feature
export interface Subscription {
  domain: string;
  service_name: string;
  sender: string;
  last_seen: string | null;
  unsubscribe_url: string;
  email_count: number;
}

export interface SubscriptionsResponse {
  subscriptions: Subscription[];
  total: number;
}

export async function fetchSubscriptions(): Promise<SubscriptionsResponse> {
  const response = await fetch(`${API_BASE_URL}/subscriptions`, { headers: { ...getAuthHeaders() } });
  if (!response.ok) {
    throw new Error(`Failed to fetch subscriptions: ${response.status}`);
  }
  return response.json();
}

// Newsletters Feature
export interface Newsletter {
  domain: string;
  service_name: string;
  sender: string;
  last_seen: string | null;
  unsubscribe_url: string;
  unsubscribe_mailto: string;
  can_auto_unsubscribe: boolean;
  email_count: number;
  last_subject: string;
  current_label?: string;
}

export interface NewslettersResponse {
  newsletters: Newsletter[];
  total: number;
}

export interface UnsubscribeResponse {
  success: boolean;
  status_code?: number;
  message: string;
}

export async function fetchNewsletters(): Promise<NewslettersResponse> {
  const response = await fetch(`${API_BASE_URL}/newsletters`, { headers: { ...getAuthHeaders() } });
  if (!response.ok) {
    throw new Error(`Failed to fetch newsletters: ${response.status}`);
  }
  return response.json();
}

export async function unsubscribeNewsletter(unsubscribeUrl: string): Promise<UnsubscribeResponse> {
  const response = await fetch(`${API_BASE_URL}/newsletters/unsubscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ unsubscribe_url: unsubscribeUrl }),
  });
  if (!response.ok) {
    throw new Error(`Failed to unsubscribe: ${response.status}`);
  }
  return response.json();
}

export async function unsubscribeBySender(sender: string): Promise<UnsubscribeResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/unsubscribe-sender`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ sender }),
  });
  if (!response.ok) {
    throw new Error(`Failed to unsubscribe: ${response.status}`);
  }
  return response.json();
}

export async function bulkDeleteNewsletters(olderThanDays: number = 0): Promise<{ deleted_count: number; message: string }> {
  const response = await fetch(`${API_BASE_URL}/newsletters/bulk-delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ older_than_days: olderThanDays }),
  });
  if (!response.ok) {
    throw new Error(`Failed to delete newsletters: ${response.status}`);
  }
  return response.json();
}

export async function labelNewsletter(sender: string, label: 'FYI' | 'Noise' | null): Promise<{ ok: boolean; affected: number }> {
  const response = await fetch(`${API_BASE_URL}/newsletters/label-sender`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ sender, label }),
  });
  if (!response.ok) throw new Error(`Failed to label newsletter: ${response.status}`);
  return response.json();
}

export async function deleteNewsletterBySender(sender: string): Promise<{ deleted_count: number; message: string }> {
  const response = await fetch(`${API_BASE_URL}/newsletters/bulk-delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ sender }),
  });
  if (!response.ok) {
    throw new Error(`Failed to delete newsletter emails: ${response.status}`);
  }
  return response.json();
}

export interface UnsubscribeAndPurgeResponse {
  success: boolean;
  unsubscribe_method: 'rfc8058_post' | 'http_post' | 'http_get' | 'mailto' | 'blocked_only' | 'none';
  status_code: number | null;
  blocked: boolean;
  deleted_count: number;
  message: string;
}

export async function unsubscribeAndPurge(
  sender: string,
  unsubscribeUrl: string,
  unsubscribeMailto: string,
): Promise<UnsubscribeAndPurgeResponse> {
  const response = await fetch(`${API_BASE_URL}/newsletters/unsubscribe-and-purge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      sender,
      unsubscribe_url: unsubscribeUrl || undefined,
      unsubscribe_mailto: unsubscribeMailto || undefined,
    }),
  });
  if (!response.ok) {
    throw new Error(`Failed to unsubscribe-and-purge: ${response.status}`);
  }
  return response.json();
}

// Clean Inbox Feature
export interface CleanInboxOptions {
  olderThanDays: number;
  keepUnread: boolean;
  unsubscribeNewsletters: boolean;
}

export interface CleanInboxSyncResponse {
  mode?: 'sync';
  success: true;
  archived_count: number;
  unsubscribed_count?: number;
  message: string;
}

export interface CleanInboxAsyncResponse {
  mode: 'async';
  accepted: true;
  job_id: string;
  target_total: number;
}

export type CleanInboxResponse = CleanInboxSyncResponse | CleanInboxAsyncResponse;

export async function cleanInbox(options: CleanInboxOptions): Promise<CleanInboxResponse> {
  const response = await fetch(`${API_BASE_URL}/emails/clean-inbox`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({
      older_than_days: options.olderThanDays,
      keep_unread: options.keepUnread,
      unsubscribe_newsletters: options.unsubscribeNewsletters,
    }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `Failed to clean inbox: ${response.status}`);
  }
  return response.json();
}

export async function triggerFullSync(): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_URL}/api/sync/full`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || `Full sync failed: ${response.status}`);
  }
  return response.json();
}
