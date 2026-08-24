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

/**
 * IndexedDB-backed cache with SWR semantics.
 *
 * Replaces localStorage for email caching — no 5 MB limit,
 * better performance for large datasets, and async-native.
 * Falls back to localStorage if IndexedDB is unavailable.
 */
import { openDB, type IDBPDatabase } from 'idb';

const DB_NAME = 'agentys_cache';
const DB_VERSION = 1;
const STORE_NAME = 'kv';

const CACHE_TTL_MS = 120 * 1000;           // 120 s → stale (WS invalide sur new_email)
const CACHE_MAX_AGE_MS = 10 * 60 * 1000;  // 10 min → evict

interface CacheEntry<T> {
  key: string;
  data: T;
  timestamp: number;
}

// Singleton DB promise (opened once, reused)
let dbPromise: Promise<IDBPDatabase> | null = null;

function getDB(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'key' });
        }
      },
    });
  }
  return dbPromise;
}

// ─────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────

export async function cacheRead<T>(key: string): Promise<CacheEntry<T> | null> {
  try {
    const db = await getDB();
    const entry = await db.get(STORE_NAME, key) as CacheEntry<T> | undefined;
    if (!entry) return null;

    // Evict if older than max age
    if (Date.now() - entry.timestamp > CACHE_MAX_AGE_MS) {
      await db.delete(STORE_NAME, key);
      return null;
    }
    return entry;
  } catch {
    // IndexedDB unavailable — try localStorage fallback
    return localRead<T>(key);
  }
}

export async function cacheWrite<T>(key: string, data: T): Promise<void> {
  const entry: CacheEntry<T> = { key, data, timestamp: Date.now() };
  try {
    const db = await getDB();
    await db.put(STORE_NAME, entry);
  } catch {
    // Fallback to localStorage
    localWrite(key, data);
  }
}

export function cacheIsStale(entry: CacheEntry<unknown>): boolean {
  return Date.now() - entry.timestamp > CACHE_TTL_MS;
}

export async function cacheInvalidatePrefix(prefix: string): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    let cursor = await store.openCursor();

    while (cursor) {
      if (typeof cursor.key === 'string' && cursor.key.startsWith(prefix)) {
        await cursor.delete();
      }
      cursor = await cursor.continue();
    }

    await tx.done;
  } catch {
    // Fallback: clear localStorage keys
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key?.startsWith(prefix)) localStorage.removeItem(key);
    }
  }
}

// ─────────────────────────────────────────────────────────────
// Sync-friendly wrappers (for hot paths that can't await)
// ─────────────────────────────────────────────────────────────

/**
 * Fire-and-forget write — queues the write without blocking.
 */
export function cacheWriteSync<T>(key: string, data: T): void {
  void cacheWrite(key, data);
}

// ─────────────────────────────────────────────────────────────
// localStorage fallback
// ─────────────────────────────────────────────────────────────

function localRead<T>(key: string): CacheEntry<T> | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() - entry.timestamp > CACHE_MAX_AGE_MS) {
      localStorage.removeItem(key);
      return null;
    }
    return { ...entry, key };
  } catch {
    return null;
  }
}

function localWrite<T>(key: string, data: T): void {
  try {
    localStorage.setItem(key, JSON.stringify({ data, timestamp: Date.now() }));
  } catch {
    // Storage full — ignore
  }
}
