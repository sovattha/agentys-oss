/**
 * sendQueue — file d'attente persistante pour les envois d'emails.
 *
 * Contexte : utilisation en voiture ou en marche, réseau instable. Un message
 * perdu = un message silencieusement raté = expérience cassée. Cette queue :
 *
 *   1. enqueue() — sauvegarde un payload de send dans SecureStore
 *   2. sendNewEmailSafe() — essaie d'envoyer immédiatement, enqueue en fallback
 *   3. flushQueue() — vide la queue en essayant chaque item (à l'ouverture
 *      de l'app, ou sur AppState foreground)
 *
 * SecureStore suffit ici : payload typique = 500 bytes, limite iOS ~1 MB par
 * item, on stocke toute la liste sérialisée JSON sous une seule clé.
 * Les corps d'emails expirent localement pour éviter une rétention indéfinie.
 */

import * as SecureStore from "expo-secure-store";
import { reportError } from "./errors";
import { sendNewEmail } from "../services/api";

const QUEUE_KEY = "outbox_v1";
export const OUTBOX_QUEUE_MAX_AGE_DAYS = 7;
const OUTBOX_QUEUE_MAX_AGE_MS = OUTBOX_QUEUE_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;

export interface QueuedMessage {
  id: string;
  to: string;
  subject: string;
  body: string;
  cc?: string;
  createdAt: string;
  attempts: number;
  lastError?: string;
}

export type SendPayload = Omit<QueuedMessage, "id" | "createdAt" | "attempts" | "lastError">;

function isFreshQueuedMessage(msg: Partial<QueuedMessage>, nowMs = Date.now()): boolean {
  const createdAtMs = Date.parse(msg.createdAt || "");
  if (!Number.isFinite(createdAtMs)) return false;
  return nowMs - createdAtMs <= OUTBOX_QUEUE_MAX_AGE_MS;
}

async function readQueue(): Promise<QueuedMessage[]> {
  try {
    const raw = await SecureStore.getItemAsync(QUEUE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];

    const fresh = parsed.filter((msg): msg is QueuedMessage =>
      Boolean(msg && typeof msg === "object" && isFreshQueuedMessage(msg))
    );
    if (fresh.length !== parsed.length) {
      await writeQueue(fresh);
    }
    return fresh;
  } catch {
    // fallback légitime : file illisible → repartir vide (les messages sont perdus,
    // mais un JSON corrompu ne doit pas bloquer tous les envois futurs)
    return [];
  }
}

async function writeQueue(q: QueuedMessage[]): Promise<void> {
  try {
    if (q.length === 0) {
      await SecureStore.deleteItemAsync(QUEUE_KEY);
    } else {
      await SecureStore.setItemAsync(QUEUE_KEY, JSON.stringify(q));
    }
  } catch (e) {
    // Une écriture ratée = message en file potentiellement PERDU au kill de
    // l'app — tracé pour corréler avec les « envois disparus ».
    reportError(e, { domain: "api", op: "sendQueue.persist" }, { userFacing: "silent" });
  }
}

export async function enqueue(payload: SendPayload): Promise<QueuedMessage> {
  const q = await readQueue();
  const msg: QueuedMessage = {
    ...payload,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date(Date.now()).toISOString(),
    attempts: 0,
  };
  q.push(msg);
  await writeQueue(q);
  return msg;
}

export async function getQueue(): Promise<QueuedMessage[]> {
  return readQueue();
}

export async function getQueueSize(): Promise<number> {
  const q = await readQueue();
  return q.length;
}

/** Vide la queue en tentant chaque envoi. Callbacks optionnels pour la notif UI. */
export async function flushQueue(callbacks?: {
  onSuccess?: (m: QueuedMessage) => void;
  onFailed?: (m: QueuedMessage, error: string) => void;
}): Promise<{ sent: number; failed: number; total: number }> {
  const q = await readQueue();
  if (q.length === 0) return { sent: 0, failed: 0, total: 0 };

  const remaining: QueuedMessage[] = [];
  let sent = 0;
  let failed = 0;

  for (const m of q) {
    try {
      const res = await sendNewEmail({
        to: m.to,
        subject: m.subject,
        body: m.body,
        cc: m.cc,
      });
      if (res.success) {
        sent++;
        callbacks?.onSuccess?.(m);
      } else {
        const error = res.error || "send failed";
        remaining.push({ ...m, attempts: m.attempts + 1, lastError: error });
        callbacks?.onFailed?.(m, error);
        failed++;
      }
    } catch (err: any) {
      const error = err?.message || String(err);
      remaining.push({ ...m, attempts: m.attempts + 1, lastError: error });
      callbacks?.onFailed?.(m, error);
      failed++;
    }
  }

  await writeQueue(remaining);
  return { sent, failed, total: q.length };
}

/** Heuristique : l'erreur est-elle "réseau" (→ enqueue) vs "validation" (→ fail). */
function isNetworkError(err: any): boolean {
  const msg = (err?.message || String(err) || "").toLowerCase();
  return (
    msg.includes("network") ||
    msg.includes("timeout") ||
    msg.includes("fetch") ||
    msg.includes("abort") ||
    msg.includes("failed to") ||
    msg.includes("offline") ||
    msg.includes("connexion")
  );
}

/** Wrapper autour de sendNewEmail avec fallback queue. Résout toujours avec
 *  `success: true` si enqueué (l'app peut rassurer l'utilisateur) — le champ
 *  `queued: true` indique que l'envoi est différé. */
export async function sendNewEmailSafe(payload: SendPayload): Promise<{
  success: boolean;
  queued: boolean;
  error?: string;
}> {
  try {
    const res = await sendNewEmail({
      to: payload.to,
      subject: payload.subject,
      body: payload.body,
      cc: payload.cc,
    });
    if (res.success) return { success: true, queued: false };
    // Échec backend explicite — ne PAS enqueue (probablement validation)
    return { success: false, queued: false, error: res.error };
  } catch (err: any) {
    // Erreur réseau → enqueue pour retry plus tard
    if (isNetworkError(err)) {
      await enqueue(payload);
      return { success: true, queued: true };
    }
    return { success: false, queued: false, error: err?.message || String(err) };
  }
}
