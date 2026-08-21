/**
 * pendingActions — « agis d'abord, annule si besoin » généralisé.
 *
 * Un ami n'demande pas trois confirmations : en Drive Mode, archive/delete/
 * envoi JOUENT leur earcon et avancent IMMÉDIATEMENT, mais l'appel API réel
 * part après un court délai (UNDO_*_MS). Pendant cette fenêtre, « annule » /
 * le chip undo récupère l'action. Passé le délai, l'action s'exécute.
 *
 * Crash-safety : chaque action programmée est journalisée dans SecureStore.
 * Si l'app meurt pendant la fenêtre (l'utilisateur croit son mail envoyé !),
 * `flushJournal(executors)` au prochain boot exécute les actions orphelines —
 * même filet que sendQueue pour le réseau. Le journal est petit (≤ 10 items,
 * ids uniquement, pas de contenu).
 */

import * as SecureStore from "expo-secure-store";
import { reportError } from "./errors";

export type PendingKind = "archive" | "delete" | "send";

export interface PendingActionMeta {
  id: string;
  kind: PendingKind;
  /** email_id (archive/delete) ou draft_id (send). */
  targetId: string;
  createdAt: number;
}

export interface ScheduledAction extends PendingActionMeta {
  timer: ReturnType<typeof setTimeout>;
  execute: () => Promise<void>;
  onError?: (err: unknown) => void;
}

const JOURNAL_KEY = "pending_actions_v1";
/** Une entrée de journal plus vieille que ça au boot = exécutée sans délai. */
const JOURNAL_MAX_AGE_MS = 24 * 60 * 60 * 1000;

// Sérialise les read-modify-write du journal (M-P2h). Sans ça, deux
// schedule() quasi-simultanés (ex: executeAgentActions [ARCHIVE, APPROVE])
// font des RMW concurrents sur la même clé SecureStore → une entrée perdue
// (trou de crash-safety), ou pire : un cancelLast qui court contre son propre
// journalAdd laisse une action ANNULÉE dans le journal, rejouée au boot
// suivant (envoi d'un brouillon que l'utilisateur avait annulé). Toutes les
// mutations passent par cette chaîne de promesses.
let journalChain: Promise<unknown> = Promise.resolve();
function withJournalLock<T>(op: () => Promise<T>): Promise<T> {
  const run = journalChain.then(op, op);
  // Ne casse pas la chaîne si `op` rejette.
  journalChain = run.then(() => undefined, () => undefined);
  return run;
}

async function readJournal(): Promise<PendingActionMeta[]> {
  try {
    const raw = await SecureStore.getItemAsync(JOURNAL_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((m) => m && m.id && m.kind && m.targetId) : [];
  } catch {
    // fallback légitime : journal illisible → repartir vide (filet, pas source de vérité)
    return [];
  }
}

async function writeJournal(items: PendingActionMeta[]): Promise<void> {
  try {
    if (items.length === 0) {
      await SecureStore.deleteItemAsync(JOURNAL_KEY);
    } else {
      await SecureStore.setItemAsync(JOURNAL_KEY, JSON.stringify(items.slice(-10)));
    }
  } catch {
    // no-op légitime : écriture du journal best-effort (filet, pas source de vérité)
  }
}

async function journalAdd(meta: PendingActionMeta): Promise<void> {
  await withJournalLock(async () => {
    const items = await readJournal();
    items.push(meta);
    await writeJournal(items);
  });
}

async function journalRemove(id: string): Promise<void> {
  await withJournalLock(async () => {
    const items = await readJournal();
    await writeJournal(items.filter((m) => m.id !== id));
  });
}

export class PendingActionManager {
  private actions: Map<string, ScheduledAction> = new Map();
  private seq = 0;
  private onChange: ((count: number) => void) | null = null;

  /** Abonne un observateur au nombre d'actions en attente (UI chip undo). */
  setOnChange(cb: ((count: number) => void) | null): void {
    this.onChange = cb;
  }

  private notify(): void {
    this.onChange?.(this.actions.size);
  }

  /** Programme `execute` dans `delayMs`. L'earcon/haptic/avance UI sont à la
   *  charge du caller — ici on ne gère que le différé + l'annulation. */
  schedule(
    kind: PendingKind,
    targetId: string,
    delayMs: number,
    execute: () => Promise<void>,
    onError?: (err: unknown) => void,
  ): string {
    const id = `${Date.now()}-${++this.seq}`;
    const meta: PendingActionMeta = { id, kind, targetId, createdAt: Date.now() };
    const timer = setTimeout(() => {
      this.actions.delete(id);
      this.notify();
      execute()
        .then(() => journalRemove(id))
        .catch((err) => {
          journalRemove(id);
          onError?.(err);
        });
    }, delayMs);
    this.actions.set(id, { ...meta, timer, execute, onError });
    journalAdd(meta).catch((e) => reportError(e, { domain: "unknown", op: "journalAdd" }, { userFacing: "silent" }));
    this.notify();
    return id;
  }

  /** Annule la PLUS RÉCENTE action en attente (optionnellement d'un kind
   *  donné). Retourne sa meta, ou null si rien à annuler. */
  cancelLast(kind?: PendingKind): PendingActionMeta | null {
    const candidates = [...this.actions.values()]
      .filter((a) => !kind || a.kind === kind)
      .sort((a, b) => b.createdAt - a.createdAt);
    const target = candidates[0];
    if (!target) return null;
    clearTimeout(target.timer);
    this.actions.delete(target.id);
    journalRemove(target.id).catch((e) => reportError(e, { domain: "unknown", op: "journalRemove" }, { userFacing: "silent" }));
    this.notify();
    return { id: target.id, kind: target.kind, targetId: target.targetId, createdAt: target.createdAt };
  }

  /** Nombre d'actions encore annulables. */
  count(kind?: PendingKind): number {
    if (!kind) return this.actions.size;
    let n = 0;
    for (const a of this.actions.values()) if (a.kind === kind) n++;
    return n;
  }

  /** Exécute IMMÉDIATEMENT tout ce qui est en attente (fin de session,
   *  démontage, passage en arrière-plan) — l'utilisateur croit ces actions
   *  faites, on ne les laisse pas mourir avec le composant. */
  async flushAll(): Promise<void> {
    const pending = [...this.actions.values()];
    this.actions.clear();
    this.notify();
    await Promise.all(
      pending.map(async (a) => {
        clearTimeout(a.timer);
        try {
          await a.execute();
        } catch (err) {
          a.onError?.(err);
        } finally {
          await journalRemove(a.id);
        }
      }),
    );
  }
}

/**
 * Filet de crash : exécute les actions journalisées orphelines (l'app est
 * morte pendant la fenêtre d'annulation). À appeler au boot (useOutboxFlush).
 * `executors` mappe chaque kind vers l'appel API réel — injecté pour éviter
 * un cycle de dépendances avec services/api.
 */
export async function flushJournal(
  executors: Record<PendingKind, (targetId: string) => Promise<void>>,
): Promise<{ executed: number; dropped: number }> {
  const items = await readJournal();
  if (items.length === 0) return { executed: 0, dropped: 0 };
  let executed = 0;
  let dropped = 0;
  const now = Date.now();
  for (const meta of items) {
    if (now - meta.createdAt > JOURNAL_MAX_AGE_MS) {
      dropped++;
      continue;
    }
    try {
      await executors[meta.kind](meta.targetId);
      executed++;
    } catch (e) {
      // L'API a refusé (déjà archivé, draft déjà envoyé…) — on n'insiste pas,
      // re-essayer en boucle serait pire (duplication). Mais un VRAI échec
      // d'envoi au replay disparaissait ici — tracé désormais.
      reportError(e, { domain: "api", op: `replay.${meta.kind}` }, { userFacing: "silent" });
      dropped++;
    }
  }
  await writeJournal([]);
  return { executed, dropped };
}
