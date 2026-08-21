import { openDB, type IDBPDatabase } from 'idb';
import type { EmailDetail } from '../types/email';

const DB_NAME = 'agentys_email_body_cache';
const DB_VERSION = 2;
const STORE_NAME = 'email_bodies';
const KEY_STORE_NAME = 'email_body_cache_keys';
const ACCOUNT_INDEX = 'accountId';
const CACHE_KEY_ID = 'email_body_cache_v1';

export const EMAIL_BODY_CACHE_TTL_MS = 10 * 60 * 1000;
export const EMAIL_BODY_CACHE_MAX_ENTRIES_PER_ACCOUNT = 100;

interface EmailBodyCacheEntryBase {
  key: string;
  accountId: string;
  emailId: string;
  timestamp: number;
  lastAccessed: number;
}

interface LegacyEmailBodyCacheEntry extends EmailBodyCacheEntryBase {
  detail: EmailDetail;
}

interface EncryptedEmailBodyCacheEntry extends EmailBodyCacheEntryBase {
  schemaVersion: 2;
  encryptedDetail: string;
  iv: string;
}

type EmailBodyCacheEntry = LegacyEmailBodyCacheEntry | EncryptedEmailBodyCacheEntry;

export interface EncryptedEmailBodyCachePayload {
  encryptedDetail: string;
  iv: string;
}

export interface CachedDraftEmailContext {
  id: string;
  sender: string;
  sender_name?: string | null;
  subject: string;
  received_at?: string | null;
  body: string;
  body_html?: string | null;
  body_text?: string | null;
  conversation_id?: string | null;
  to?: string[];
  cc?: string[];
  source: 'local_email_body_cache';
}

let dbPromise: Promise<IDBPDatabase | null> | null = null;
const memoryEntries = new Map<string, LegacyEmailBodyCacheEntry>();

function now(): number {
  return Date.now();
}

function normalizeAccountId(accountId: string): string {
  return accountId || 'default';
}

function getCacheKey(accountId: string, emailId: string): string {
  return `${normalizeAccountId(accountId)}:${emailId}`;
}

function hasVisibleBody(detail: EmailDetail | null | undefined): boolean {
  return Boolean(detail?.body || detail?.body_html || detail?.body_text);
}

function isExpired(entry: EmailBodyCacheEntry): boolean {
  return now() - entry.timestamp > EMAIL_BODY_CACHE_TTL_MS;
}

function isEncryptedEntry(entry: EmailBodyCacheEntry): entry is EncryptedEmailBodyCacheEntry {
  return typeof (entry as EncryptedEmailBodyCacheEntry).encryptedDetail === 'string'
    && typeof (entry as EncryptedEmailBodyCacheEntry).iv === 'string';
}

function getCryptoApi(): Crypto | null {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.subtle || typeof cryptoApi.getRandomValues !== 'function') return null;
  return cryptoApi;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}

async function encryptEmailDetail(
  detail: EmailDetail,
  key: CryptoKey,
  cryptoApi: Crypto,
): Promise<EncryptedEmailBodyCachePayload> {
  const iv = cryptoApi.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(JSON.stringify(detail));
  const encrypted = await cryptoApi.subtle.encrypt(
    { name: 'AES-GCM', iv: toArrayBuffer(iv) },
    key,
    toArrayBuffer(encoded),
  );
  return {
    encryptedDetail: bytesToBase64(new Uint8Array(encrypted)),
    iv: bytesToBase64(iv),
  };
}

async function decryptEmailDetail(
  payload: EncryptedEmailBodyCachePayload,
  key: CryptoKey,
  cryptoApi: Crypto,
): Promise<EmailDetail | null> {
  try {
    const iv = base64ToBytes(payload.iv);
    const encrypted = base64ToBytes(payload.encryptedDetail);
    const decrypted = await cryptoApi.subtle.decrypt(
      { name: 'AES-GCM', iv: toArrayBuffer(iv) },
      key,
      toArrayBuffer(encrypted),
    );
    return JSON.parse(new TextDecoder().decode(decrypted)) as EmailDetail;
  } catch {
    return null;
  }
}

async function getEmailBodyCacheKey(db: IDBPDatabase, cryptoApi: Crypto): Promise<CryptoKey | null> {
  try {
    const existing = await db.get(KEY_STORE_NAME, CACHE_KEY_ID) as CryptoKey | undefined;
    if (existing) return existing;

    const key = await cryptoApi.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt', 'decrypt'],
    );
    await db.put(KEY_STORE_NAME, key, CACHE_KEY_ID);
    return key;
  } catch {
    return null;
  }
}

function pruneMemoryAccount(normalizedAccountId: string): void {
  const entries = [...memoryEntries.values()]
    .filter((entry) => entry.accountId === normalizedAccountId)
    .sort((a, b) => b.lastAccessed - a.lastAccessed);
  for (const entry of entries.slice(EMAIL_BODY_CACHE_MAX_ENTRIES_PER_ACCOUNT)) {
    memoryEntries.delete(entry.key);
  }
}

async function getDB(): Promise<IDBPDatabase | null> {
  if (typeof indexedDB === 'undefined') return null;
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db, _oldVersion, _newVersion, transaction) {
        const store = db.objectStoreNames.contains(STORE_NAME)
          ? transaction.objectStore(STORE_NAME)
          : db.createObjectStore(STORE_NAME, { keyPath: 'key' });
        if (!store.indexNames.contains(ACCOUNT_INDEX)) {
          store.createIndex(ACCOUNT_INDEX, ACCOUNT_INDEX, { unique: false });
        }
        if (!db.objectStoreNames.contains(KEY_STORE_NAME)) {
          db.createObjectStore(KEY_STORE_NAME);
        }
      },
    }).catch(() => null);
  }
  return dbPromise;
}

async function pruneAccount(accountId: string): Promise<void> {
  const normalizedAccountId = normalizeAccountId(accountId);
  const db = await getDB();
  if (!db) {
    pruneMemoryAccount(normalizedAccountId);
    return;
  }

  const tx = db.transaction(STORE_NAME, 'readwrite');
  const store = tx.objectStore(STORE_NAME);
  const entries = await store.index(ACCOUNT_INDEX).getAll(normalizedAccountId) as EmailBodyCacheEntry[];
  entries.sort((a, b) => b.lastAccessed - a.lastAccessed);
  await Promise.all(
    entries
      .slice(EMAIL_BODY_CACHE_MAX_ENTRIES_PER_ACCOUNT)
      .map((entry) => store.delete(entry.key))
  );
  await tx.done;
}

export async function readEmailBodyCache(accountId: string, emailId: string): Promise<EmailDetail | null> {
  const key = getCacheKey(accountId, emailId);
  const db = await getDB();

  if (!db) {
    const entry = memoryEntries.get(key);
    if (!entry) return null;
    if (isExpired(entry)) {
      memoryEntries.delete(key);
      return null;
    }

    entry.lastAccessed = now();
    memoryEntries.set(key, entry);
    return entry.detail;
  }

  const entry = await db.get(STORE_NAME, key) as EmailBodyCacheEntry | undefined;
  if (!entry) return null;
  if (isExpired(entry)) {
    await db.delete(STORE_NAME, key);
    return null;
  }

  if (!isEncryptedEntry(entry)) {
    const legacyDetail = entry.detail;
    await db.delete(STORE_NAME, key);
    await writeEmailBodyCache(accountId, emailId, legacyDetail);
    return legacyDetail;
  }

  const cryptoApi = getCryptoApi();
  const encryptionKey = cryptoApi ? await getEmailBodyCacheKey(db, cryptoApi) : null;
  if (!cryptoApi || !encryptionKey) {
    await db.delete(STORE_NAME, key);
    return null;
  }

  const detail = await decryptEmailDetail(entry, encryptionKey, cryptoApi);
  if (!detail) {
    await db.delete(STORE_NAME, key);
    return null;
  }

  entry.lastAccessed = now();
  await db.put(STORE_NAME, entry);
  return detail;
}

export async function writeEmailBodyCache(
  accountId: string,
  emailId: string,
  detail: EmailDetail,
): Promise<void> {
  if (!hasVisibleBody(detail)) return;
  const normalizedAccountId = normalizeAccountId(accountId);
  const timestamp = now();
  const key = getCacheKey(normalizedAccountId, emailId);
  const db = await getDB();

  if (db) {
    const cryptoApi = getCryptoApi();
    const encryptionKey = cryptoApi ? await getEmailBodyCacheKey(db, cryptoApi) : null;
    if (cryptoApi && encryptionKey) {
      const encrypted = await encryptEmailDetail(detail, encryptionKey, cryptoApi);
      const entry: EncryptedEmailBodyCacheEntry = {
        key,
        accountId: normalizedAccountId,
        emailId,
        timestamp,
        lastAccessed: timestamp,
        schemaVersion: 2,
        encryptedDetail: encrypted.encryptedDetail,
        iv: encrypted.iv,
      };
      await db.put(STORE_NAME, entry);
      await pruneAccount(normalizedAccountId);
      return;
    }
  }

  memoryEntries.set(key, {
    key,
    accountId: normalizedAccountId,
    emailId,
    detail,
    timestamp,
    lastAccessed: timestamp,
  });
  pruneMemoryAccount(normalizedAccountId);
}

export function writeEmailBodyCacheSync(
  accountId: string,
  emailId: string,
  detail: EmailDetail,
): void {
  void writeEmailBodyCache(accountId, emailId, detail);
}

export async function clearEmailBodyCache(accountId?: string): Promise<void> {
  const normalizedAccountId = accountId ? normalizeAccountId(accountId) : null;
  const db = await getDB();

  if (db) {
    if (!normalizedAccountId) {
      await db.clear(STORE_NAME);
    } else {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const entries = await store.index(ACCOUNT_INDEX).getAll(normalizedAccountId) as EmailBodyCacheEntry[];
      await Promise.all(entries.map((entry) => store.delete(entry.key)));
      await tx.done;
    }
  }

  for (const [entryKey, entry] of memoryEntries.entries()) {
    if (!normalizedAccountId || entry.accountId === normalizedAccountId) {
      memoryEntries.delete(entryKey);
    }
  }
}

export function buildCachedDraftEmailContext(
  emailId: string,
  detail: EmailDetail | null,
): CachedDraftEmailContext | null {
  if (!detail || !hasVisibleBody(detail) || !detail.sender || !detail.subject) {
    return null;
  }

  const body = detail.body || detail.body_text || '';
  const bodyText = detail.body_text || detail.body || '';
  if (!body && !detail.body_html) return null;

  return {
    id: detail.id || emailId,
    sender: detail.sender,
    sender_name: detail.sender_name ?? null,
    subject: detail.subject,
    received_at: detail.received_at,
    body,
    body_html: detail.body_html ?? null,
    body_text: bodyText,
    conversation_id: detail.conversation_id ?? null,
    to: detail.to || [],
    cc: detail.cc || [],
    source: 'local_email_body_cache',
  };
}

export async function _encryptEmailDetailForTests(
  detail: EmailDetail,
  key: CryptoKey,
): Promise<EncryptedEmailBodyCachePayload> {
  const cryptoApi = getCryptoApi();
  if (!cryptoApi) throw new Error('WebCrypto unavailable');
  return encryptEmailDetail(detail, key, cryptoApi);
}

export async function _decryptEmailDetailForTests(
  payload: EncryptedEmailBodyCachePayload,
  key: CryptoKey,
): Promise<EmailDetail | null> {
  const cryptoApi = getCryptoApi();
  if (!cryptoApi) throw new Error('WebCrypto unavailable');
  return decryptEmailDetail(payload, key, cryptoApi);
}

export async function _resetEmailBodyCacheForTests(): Promise<void> {
  memoryEntries.clear();
  dbPromise = null;
}
