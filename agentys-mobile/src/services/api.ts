/**
 * Client API pour le backend Agentys.
 *
 * Pattern similaire au desktop (agentys-app/src/services/api.ts).
 */

import { API_URL } from "../config";
import { getToken, clearToken } from "./auth";
import { getSocket } from "./websocket";
import i18n from "../i18n";
import { logEvent } from "../lib/eventLog";
import type { SpeakableEmail, VoiceDraftResponse, Draft, Email } from "../types";

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

interface ApiFetchOptions extends RequestInit {
  /** Timeout en ms. Défaut 10_000. Utilisé pour des endpoints lents comme
   *  `/api/emails?label=X` quand la liste est grande (75+ emails). */
  timeoutMs?: number;
  /** Nombre max de retries sur 5xx / network error.
   *  Défaut : 2 pour GET/HEAD, 0 pour les autres méthodes (non idempotentes).
   *  Pour forcer un retry sur un POST/PATCH idempotent, passer explicitement
   *  une valeur > 0. **Attention** : ne JAMAIS retrier un POST qui mute un
   *  état non-idempotent (envoi d'email, archivage, approval) — risque de
   *  duplication si la requête a abouti côté serveur mais que la réponse
   *  n'est pas revenue (Railway cold start, timeout 30s, etc.). Voir F01. */
  retries?: number;
}

const RETRY_BACKOFF_MS = [400, 1500, 3000]; // paliers pour 3 retries max

// ── Confirmation avant purge du token (#1121) ───────────────────────────────
// Un 401 isolé ne prouve pas que le token est mort : redéploiement Railway,
// endpoint qui renvoie 401 à tort, horloge. Purger immédiatement éjecte
// l'utilisateur au login — potentiellement en pleine session drive. On
// confirme d'abord contre GET /api/auth/me (authentifié, léger). Un seul
// probe en vol, partagé entre 401 concurrents.
const PROBE_TIMEOUT_MS = 5_000;
let probeInFlight: Promise<boolean> | null = null;

/** true ⇔ le token est réellement invalide (401 confirmé par /api/auth/me).
 *  Erreur réseau/timeout/5xx du probe ⇒ bénéfice du doute, on NE purge PAS
 *  (être hors ligne ne doit jamais déconnecter). */
async function confirmUnauthorized(): Promise<boolean> {
  if (probeInFlight) return probeInFlight;
  probeInFlight = (async () => {
    try {
      const token = await getToken();
      if (!token) return true; // rien à conserver
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
      try {
        // fetch direct — surtout pas apiFetch (récursion sur 401), pas de retry.
        const res = await fetch(`${API_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        return res.status === 401;
      } finally {
        clearTimeout(timeout);
      }
    } catch {
      // fallback légitime : probe injoignable → bénéfice du doute, on ne purge pas
      return false;
    } finally {
      probeInFlight = null;
    }
  })();
  return probeInFlight;
}

/** Chemin 401 commun : purge le token seulement si l'invalidité est confirmée. */
async function handleUnauthorized(): Promise<void> {
  if (await confirmUnauthorized()) {
    await clearToken();
  }
}

/** Méthodes HTTP idempotentes pour lesquelles un retry automatique est sûr. */
const IDEMPOTENT_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** Test exposé pour les unit tests : décide si une (méthode, status) est retryable
 *  par défaut. POST/PATCH/PUT/DELETE → jamais (risque duplication). GET + 5xx → oui.
 *  GET + 4xx → non (sauf 408/429 traités côté wrapper). */
export function shouldRetryByDefault(method: string | undefined, status: number): boolean {
  const m = (method || "GET").toUpperCase();
  if (!IDEMPOTENT_METHODS.has(m)) return false;
  return status >= 500 && status < 600;
}

async function apiFetchOnce<T>(path: string, options: ApiFetchOptions): Promise<T> {
  const { timeoutMs = 10_000, retries: _r, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  const isIdempotent = IDEMPOTENT_METHODS.has(method);
  const headers = await authHeaders();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...fetchOptions,
      headers: { ...headers, ...fetchOptions.headers },
      signal: controller.signal,
    });

    if (res.status === 401) {
      // Confirmation avant purge (#1121) — un 401 transitoire ne déconnecte plus.
      await handleUnauthorized();
      throw new Error("Unauthorized");
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      // Ne marque retryable que si la méthode est idempotente. POST/PATCH/PUT/DELETE
      // ne doivent JAMAIS être retriés automatiquement (F01) : si Railway accepte
      // le POST mais que la réponse arrive >timeoutMs plus tard, un retry causerait
      // un double envoi / double archive / double approval. L'appelant peut opt-in
      // via `retries: N` quand il sait que l'endpoint est idempotent.
      const err: any = new Error(body.error || `HTTP ${res.status}`);
      err.status = res.status;
      err.retryable = isIdempotent && res.status >= 500 && res.status < 600;
      throw err;
    }

    return res.json();
  } catch (err: any) {
    if (err.name === "AbortError") {
      const timeoutErr: any = new Error(`Timeout (${timeoutMs}ms) — ${API_URL}${path}`);
      // Timeout : retryable seulement si la méthode est idempotente. Sur un POST,
      // on ne peut pas savoir si le serveur a traité ou non la requête (côté
      // ELB Railway, on a déjà vu un POST « envoi email » réussir à T+31s alors
      // que le client avait abandonné à T+30s). Retrier = email envoyé en double.
      timeoutErr.retryable = isIdempotent;
      throw timeoutErr;
    }
    // Les erreurs réseau génériques (offline, DNS, reset) : pareil, on ne sait
    // pas si la requête est passée → retry uniquement sur GET/HEAD.
    if (!err.status && err.message && err.retryable === undefined) {
      err.retryable = isIdempotent && /network|fetch|connect/i.test(err.message);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/** Wrapper avec retry exponentiel sur 5xx / network error. Railway cold start
 *  peut rendre 502 pendant 10-30s au réveil ; un seul retry patient suffit souvent.
 *
 *  IMPORTANT (F01) : par défaut, seul GET/HEAD est retrié. Les méthodes non
 *  idempotentes (POST/PATCH/PUT/DELETE) ne sont JAMAIS retriées sauf si l'appelant
 *  passe explicitement `retries: N` ET que l'endpoint est idempotent côté serveur. */
async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const method = ((options.method || "GET") as string).toUpperCase();
  const isIdempotent = IDEMPOTENT_METHODS.has(method);
  // Default retries : 2 pour idempotent, 0 pour mutations non-idempotentes.
  // L'appelant peut forcer (idempotency-key custom, endpoint connu safe).
  const maxRetries = options.retries ?? (isIdempotent ? 2 : 0);
  let lastErr: any;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await apiFetchOnce<T>(path, options);
    } catch (err: any) {
      lastErr = err;
      // 401 Unauthorized → pas de retry, l'utilisateur doit se reconnecter
      if (err.message === "Unauthorized") throw err;
      // Non-retryable (4xx, ou méthode non-idempotente sur 5xx) → fail immédiat
      if (!err.retryable) throw err;
      // Dernière tentative → propager l'erreur
      if (attempt === maxRetries) throw err;
      const delay = RETRY_BACKOFF_MS[Math.min(attempt, RETRY_BACKOFF_MS.length - 1)];
      console.warn(`[api] ${path} ${err.message} — retry ${attempt + 1}/${maxRetries} in ${delay}ms`);
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr;
}

export function getEmails(label?: string, limit = 200): Promise<{ emails: Email[] }> {
  // #1134 : `filter=unread` — la session drive traite les emails « à faire »,
  // pas ceux déjà lus/traités. C'est le paramètre attendu par /api/emails
  // (routes_emails.list_emails : filter ∈ {all, unread}), tout comme le web
  // (agentys-app emails.ts). Aligne la liste sur les compteurs (unread_only).
  const params = new URLSearchParams({ limit: String(limit), filter: "unread" });
  if (label) params.set("label", label);
  // Timeout 30s : label filter + SQLite query + label enrichment peut être lent
  // sur cold start (backend Railway) ou gros inbox.
  return apiFetch(`/api/emails?${params}`, { timeoutMs: 30_000 });
}

/** Counts par label (Action, FYI, Noise, …) — aggregate SQL account-scoped. */
export function getLabelCounts(): Promise<{ counts: Record<string, number>; total: number }> {
  // #1134 : `unread_only=true` pour matcher EXACTEMENT le web (agentys-app
  // `useLabels.ts` COUNTS_UNREAD_ONLY = true). Les badges « Action/FYI à
  // traiter » comptent les emails NON LUS, pas le total labellisé (qui
  // incluait les déjà lus/traités → « 66 » côté mobile vs bien moins sur web).
  return apiFetch("/api/labels/counts?unread_only=true");
}

/** Endpoint alternatif : récupère juste la liste d'IDs pour un label donné.
 *  Utilisé comme fallback si `/api/emails?label=X` timeout ou échoue. */
export function getEmailIdsByLabel(labelName: string): Promise<{ email_ids: string[]; count: number }> {
  return apiFetch(`/api/labels/emails/${encodeURIComponent(labelName)}`);
}

export function getEmailDetail(emailId: string): Promise<Email> {
  return apiFetch(`/api/emails/${emailId}`);
}

export function getEmailSpeakable(emailId: string, conversational = false): Promise<SpeakableEmail> {
  // Langue du DEVICE : le registre parlé suit l'app (fr/en/es), pas la langue
  // de l'email reçu — le backend reformule dans la langue demandée.
  const lang = (i18n.language || "fr").split(/[-_]/)[0];
  const params = new URLSearchParams({ lang });
  if (conversational) params.set("conversational", "true");
  return apiFetch(`/api/emails/${emailId}/speakable?${params}`);
}

export function deleteEmail(emailId: string): Promise<{ success: boolean; email_id: string; message: string }> {
  return apiFetch(`/api/emails/${emailId}/delete`, { method: "POST" });
}

export function createVoiceDraft(emailId: string, transcription: string): Promise<VoiceDraftResponse> {
  return apiFetch(`/api/emails/${emailId}/voice-draft`, {
    method: "POST",
    body: JSON.stringify({ transcription }),
  });
}

/** Marker error : le backend a explicitement décidé de ne PAS générer de
 *  brouillon (auto-sender, noise, "no reply needed", body vide). À distinguer
 *  d'un timeout réseau — pas de retry, message utilisateur différent. */
export class DraftSkippedError extends Error {
  reason: string;
  constructor(reason: string, message?: string) {
    super(message || `Draft skipped: ${reason}`);
    this.name = "DraftSkippedError";
    this.reason = reason;
  }
}

/**
 * Wrapper haute performance : race WebSocket vs polling pour récupérer le
 * draft généré par /process. La WS gagne typiquement en ~3s (notification
 * dès que le LLM finit), vs polling 1.5-8s.
 *
 * Fallback gracieux : si la WS n'est pas connectée, on tombe sur le polling
 * pur. `draft_ready` porte l'ID persistant du PendingDraft ; `draft_complete`
 * ne porte que le contenu et déclenche donc un lookup sans jamais fabriquer
 * d'ID client non résolvable par l'endpoint `/validate`.
 *
 * Skip path : le backend peut décider de ne PAS générer de draft (auto-sender,
 * noise, "no reply needed"). Dans ce cas il émet `daemon_event` avec
 * `type=draft_skipped` au lieu de `draft_complete`. On écoute aussi cet
 * event pour rejeter immédiatement (sinon on poll 90s pour rien — vu le
 * 28/04/2026 sur drive mobile, mail no-reply@email.claude.com).
 */
export async function generateProcessDraftFast(
  emailId: string,
  instructions: string,
  replyType: "reply" | "reply_all" = "reply",
  onProgress?: (elapsedMs: number) => void,
): Promise<{ draft_id: string; content: string }> {
  // Static `getSocket` import en haut de fichier — websocket.ts ne dépend
  // pas de api.ts donc pas de circulaire. L'ancien dynamic import cassait
  // les tests Jest (require --experimental-vm-modules), bloquant toute
  // couverture de cette fonction.
  const socket = getSocket();

  // Cleanup partagé : appelé dès qu'une des paths (WS ou polling) résout,
  // pour détacher tous les listeners WS et arrêter le safety timeout.
  let wsListener: ((data: { email_id?: string; draft?: string; draft_id?: string }) => void) | null = null;
  let daemonListener: ((data: {
    type?: string;
    email_id?: string;
    payload?: { draft_id?: string; pending_draft_id?: string; draft_content?: string };
    data?: { email_id?: string; reason?: string };
  }) => void) | null = null;
  let safetyTimeout: ReturnType<typeof setTimeout> | null = null;
  const cleanup = () => {
    if (wsListener && socket) {
      socket.off("draft_complete", wsListener);
      wsListener = null;
    }
    if (daemonListener && socket) {
      socket.off("daemon_event", daemonListener);
      daemonListener = null;
    }
    if (safetyTimeout) {
      clearTimeout(safetyTimeout);
      safetyTimeout = null;
    }
  };

  // Promise WS : résout quand l'ID persistant arrive via draft_ready (ou via
  // le lookup déclenché par draft_complete), et rejette si le backend skippe.
  const wsPromise = socket
    ? new Promise<{ draft_id: string; content: string }>((resolve, reject) => {
        let settled = false;

        const resolveOnce = (draftId: string, content: string) => {
          if (settled) return;
          settled = true;
          resolve({ draft_id: draftId, content });
        };

        wsListener = (data: { email_id?: string; draft?: string; draft_id?: string }) => {
          if (data?.email_id !== emailId || !data?.draft) return;
          if (settled) return;
          if (data.draft_id) {
            resolveOnce(data.draft_id, data.draft);
            return;
          }
          // `draft_complete` legacy n'inclut pas toujours draft_id. Le lookup
          // peut être brièvement en retard sur l'event : s'il ne renvoie pas
          // encore l'ID persistant, le listener draft_ready ou le polling
          // poursuivent la course au lieu de fabriquer un ID `ws-*` invalide.
          getPendingDraftByEmail(emailId)
            .then((draft) => {
              const persistedId = draft?.id || draft?.draft_id;
              if (persistedId && draft?.draft_body) {
                resolveOnce(persistedId, draft.draft_body);
              }
            })
            .catch(() => {}); // no-op légitime : course/lookup best-effort (documenté ci-dessus)
        };

        daemonListener = (envelope: {
          type?: string;
          email_id?: string;
          payload?: { draft_id?: string; pending_draft_id?: string; draft_content?: string };
          data?: { email_id?: string; reason?: string };
        }) => {
          if (envelope?.type === "draft_ready") {
            if (envelope.email_id !== emailId) return;
            const draftId = envelope.payload?.draft_id || envelope.payload?.pending_draft_id;
            const content = envelope.payload?.draft_content;
            if (draftId && content) resolveOnce(draftId, content);
            return;
          }
          if (envelope?.type === "draft_skipped") {
            if (envelope.data?.email_id !== emailId || settled) return;
            settled = true;
            const reason = envelope.data?.reason || "unknown";
            reject(new DraftSkippedError(reason));
          }
        };

        socket.on("draft_complete", wsListener);
        socket.on("daemon_event", daemonListener);
        // Safety timeout : si rien n'arrive jamais sur la WS, reject pour
        // laisser le polling prendre le relai.
        safetyTimeout = setTimeout(() => {
          if (!settled) {
            settled = true;
            reject(new Error("WS draft timeout"));
          }
        }, 95_000);
      })
    : null;

  // Abort du polling quand la course est tranchée (#1128) : sans ce flag, la
  // WS gagnait mais le poll continuait jusqu'à 90s (une requête toutes les
  // 1.5s pour rien — batterie + réseau en drive mode, et worker leak Jest).
  let pollAborted = false;
  const pollPromise = generateProcessDraft(
    emailId, instructions, replyType, onProgress, () => pollAborted,
  );
  // Si la WS gagne, pollPromise rejettera « poll aborted » après coup —
  // handler préventif pour éviter l'unhandled rejection. `await pollPromise`
  // plus bas garde sa propre chaîne, ceci ne masque rien.
  pollPromise.catch(() => {}); // no-op légitime : course/lookup best-effort (documenté ci-dessus)

  try {
    if (wsPromise) {
      // Race : la première à résoudre gagne. Si l'une rejette avec un
      // DraftSkippedError, on propage immédiatement (pas de fallback poll
      // — le backend nous a explicitement dit "no draft will come").
      const result = await Promise.race([wsPromise, pollPromise]).catch(async (err) => {
        if (err instanceof DraftSkippedError) {
          throw err;
        }
        console.warn("[draft-race] one path failed:", err?.message || err);
        return await pollPromise;
      });
      return result;
    }
    return await pollPromise;
  } finally {
    pollAborted = true;
    cleanup();
  }
}

/**
 * Génère un brouillon via le pipeline complet (Drafter + Critic) — même
 * endpoint que le bouton "Processus IA" / Ctrl+G de la webapp.
 *
 * Diffère de `createVoiceDraft` (legacy mobile) :
 *  - `createVoiceDraft` → `/api/emails/<id>/voice-draft` → DrafterAgent seul,
 *    réponse synchrone, draft volatile (pas en `pending_drafts`).
 *  - `generateProcessDraft` → `/api/emails/<id>/process` → pipeline complet,
 *    réponse 202 + génération asynchrone, draft persisté en
 *    `pending_drafts` (visible côté webapp), Critic peut faire réécrire si
 *    le score initial est trop bas.
 *
 * Comme le mobile n'a pas de WebSocket attaché à la session de génération,
 * on **polle** `/api/pending-drafts/by-email/<id>` toutes les 1.5s jusqu'à
 * ce qu'un draft apparaisse, ou timeout à 90s.
 *
 * Coût latence : ~5-10s vs ~2-4s pour voice-draft (Critic ajoute un appel
 * LLM). Compromis assumé pour avoir la même qualité que la webapp.
 */
export async function generateProcessDraft(
  emailId: string,
  instructions: string,
  replyType: "reply" | "reply_all" = "reply",
  onProgress?: (elapsedMs: number) => void,
  /** Le caller (race WS/poll) peut demander l'arrêt du polling une fois la
   *  course tranchée — sinon le poll tourne 90s pour rien (#1128). */
  shouldAbort?: () => boolean,
): Promise<{ draft_id: string; content: string }> {
  // Trigger the pipeline (returns 202 Accepted with task_id, OR 200 with
  // status:"existing" if a fresh draft is already in the store)
  const startResp = await apiFetch<{
    success: boolean;
    draft_id?: string;
    status?: string;
    task_id?: string;
    draft_preview?: string;
  }>(`/api/emails/${emailId}/process`, {
    method: "POST",
    body: JSON.stringify({
      instructions,
      reply_type: replyType,
      force: true,
    }),
    // Le call lui-même répond vite (202 immediate ou 200 sync) ; le polling
    // gère la latence LLM.
    timeoutMs: 15_000,
  });

  // Cas synchrone (status:"existing" — improbable ici car force:true vient
  // d'evict le cache, mais conservé par défense en profondeur).
  if (startResp.status === "existing" && startResp.draft_id) {
    const draft = await getPendingDraftByEmail(emailId);
    if (draft?.draft_body) {
      return {
        draft_id: draft.id || draft.draft_id || startResp.draft_id,
        content: draft.draft_body,
      };
    }
  }

  // Cas asynchrone (202) : poll jusqu'à ce qu'un draft apparaisse.
  const startTime = Date.now();
  const TIMEOUT_MS = 90_000;
  const POLL_INTERVAL_MS = 1500;

  while (Date.now() - startTime < TIMEOUT_MS) {
    if (shouldAbort?.()) throw new Error("poll aborted");
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    if (shouldAbort?.()) throw new Error("poll aborted");
    const elapsed = Date.now() - startTime;
    onProgress?.(elapsed);
    try {
      const draft = await getPendingDraftByEmail(emailId);
      if (draft?.draft_body && typeof draft.draft_body === "string" && draft.draft_body.trim().length > 0) {
        const persistedId = draft.id || draft.draft_id;
        if (persistedId) {
          return { draft_id: persistedId, content: draft.draft_body };
        }
      }
    } catch {
      // no-op légitime : échec de poll intermittent — la boucle réessaie jusqu'au timeout
    }
  }

  throw new Error("Génération de brouillon trop longue (timeout 90s)");
}

export function getDrafts(): Promise<{ drafts: Draft[] }> {
  return apiFetch("/api/drafts");
}

export function getPendingDraftByEmail(emailId: string): Promise<any | null> {
  return apiFetch<{ draft: any | null } | null>(`/api/pending-drafts/by-email/${emailId}`)
    .then((resp) => resp?.draft ?? null)
    .catch(() => null);
}

/** Valide un PendingDraft : crée le brouillon Gmail, l'envoie, met à jour
 *  son status à SENT. Endpoint canonique partagé avec la webapp.
 *
 *  ⚠️ Ne JAMAIS appeler `/api/drafts/<id>/approve` — cet endpoint n'existe
 *  pas côté backend (404 silencieux). Bug live observé le 2026-04-28 sur
 *  mobile drive mode : tap "envoyer" / commande vocale "envoyer" → POST 404
 *  → toast "tts.sendFailed" → utilisateur croit que la commande n'a pas été
 *  reconnue alors qu'elle a frappé un fantôme.
 *
 *  Note : `retries: 0` explicite — cet endpoint envoie un email vrai, donc
 *  jamais retrié automatiquement (cf. F01 dans apiFetch). Si Railway renvoie
 *  500 après avoir réellement envoyé, un retry causerait un double envoi. */
export function approveDraft(draftId: string): Promise<{ success: boolean }> {
  return apiFetch(`/api/pending-drafts/${encodeURIComponent(draftId)}/validate`, {
    method: "POST",
    body: JSON.stringify({}),
    retries: 0,
  });
}

export interface LabelInfo {
  name: string;
  color: string | null;
  description: string;
  is_default: boolean;
}

export function getLabels(): Promise<{ labels: LabelInfo[]; count: number }> {
  return apiFetch("/api/labels");
}

export function archiveEmail(emailId: string): Promise<{ success: boolean; email_id: string; message: string }> {
  return apiFetch(`/api/emails/${emailId}/archive`, { method: "POST" });
}

export function sendNewEmail(payload: {
  to: string;
  subject: string;
  body: string;
  cc?: string;
  bcc?: string;
}): Promise<{ success: boolean; message_id?: string; error?: string }> {
  return apiFetch(`/api/emails/send-new`, {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 30_000,
  });
}

export interface SearchResult {
  id: string;
  sender: string;
  sender_name?: string;
  subject: string;
  snippet?: string;
  received_at: string;
}

export function searchEmails(query: string, limit = 50): Promise<{
  success: boolean;
  total: number;
  results: SearchResult[];
  has_more: boolean;
}> {
  return apiFetch(`/api/emails/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

export function checkHealth(): Promise<{ status: string }> {
  return apiFetch("/api/health");
}

export function getUserPreferences(): Promise<{ preferred_language: string | null }> {
  return apiFetch("/api/user/preferences", { timeoutMs: 8_000 });
}

export function updateUserPreferences(payload: {
  preferred_language?: string;
}): Promise<{ preferred_language: string | null }> {
  return apiFetch("/api/user/preferences", {
    method: "PATCH",
    body: JSON.stringify(payload),
    timeoutMs: 8_000,
  });
}

export async function getUserName(): Promise<string | null> {
  try {
    const data = await apiFetch<{ accounts: Array<{ name: string; email: string }> }>("/api/accounts");
    const first = data.accounts?.[0];
    if (!first) return null;
    const raw = first.name?.trim() || first.email?.split("@")[0] || "";
    const firstName = raw.split(/[\s._-]/)[0];
    return firstName ? firstName.charAt(0).toUpperCase() + firstName.slice(1).toLowerCase() : null;
  } catch {
    // fallback légitime : prénom indisponible → null (greeting générique)
    return null;
  }
}

export function rejectDraft(draftId: string, reason?: string): Promise<{ success: boolean }> {
  return apiFetch(`/api/drafts/${draftId}/feedback`, {
    method: "PATCH",
    body: JSON.stringify({ feedback: "rejected", reason }),
  });
}

export interface ContactHit {
  name: string;
  email: string;
}

/** Autocomplétion de contacts par nom ou fragment d'email.
 *  Renvoie jusqu'à `limit` résultats triés par fréquence d'interaction. */
export function autocompleteContacts(
  query: string,
  limit = 5,
): Promise<ContactHit[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return apiFetch(`/api/contacts/autocomplete?${params}`, { timeoutMs: 8_000 });
}

export interface ParsedComposeUtterance {
  recipients: string[];
  body: string | null;
}

/** Parse une phrase dictée en « destinataires + corps » via Claude Haiku.
 *  Utilisé en fallback quand le split regex côté client échoue. */
export function parseComposeUtterance(
  transcript: string,
): Promise<ParsedComposeUtterance> {
  return apiFetch(`/api/voice/parse-compose`, {
    method: "POST",
    body: JSON.stringify({ transcript }),
    timeoutMs: 10_000,
  });
}

/**
 * Reformule un corps de message dicté en corps d'email propre (Haiku).
 *
 * Device 2026-08-03 : « coucou comment ça va » partait VERBATIM — le compose
 * n'avait aucune passe de reformulation, contrairement au drive (Drafter).
 * Contrat : ne bloque JAMAIS l'envoi — toute erreur (réseau, 404 backend pas
 * encore déployé, timeout) renvoie le texte brut.
 */
export async function polishComposeBody(transcript: string): Promise<string> {
  try {
    const res = await apiFetch<{ body?: string }>(`/api/voice/polish-compose`, {
      method: "POST",
      body: JSON.stringify({ transcript }),
      timeoutMs: 10_000,
    });
    const polished = (res?.body || "").trim();
    return polished || transcript;
  } catch {
    return transcript; // fallback texte brut — la reformulation est best-effort
  }
}

/**
 * Classifie un transcript vocal en intent commande via Haiku côté backend.
 *
 * Plus robuste que le keyword matching côté client : couvre toutes les
 * variations naturelles ("vire-moi ça", "fous à la corbeille", "passe au
 * suivant"). Si la requête échoue ou timeout, le caller doit fallback
 * sur le keyword matcher local.
 *
 * Cost ~$0.0001 par call (Haiku, 200 input + 50 output tokens). Rate
 * limit 60/min/account côté backend.
 *
 * Timeout côté client : 5s. Fail-fast pour ne pas bloquer le flow vocal.
 */
export async function voiceIntent(
  transcript: string,
  state?: string,
): Promise<{
  intent: string | null;
  confidence: number;
  free_text: string | null;
}> {
  return apiFetch("/api/voice/intent", {
    method: "POST",
    body: JSON.stringify({ transcript, state }),
    timeoutMs: 5_000,
  });
}

// ─── Voice Agent — le cerveau conversationnel du Drive Mode ────────────────

export type VoiceAgentAction =
  | { type: "REPLY" | "REPLY_ALL" | "FORWARD" | "ARCHIVE" | "DELETE" | "NEXT"
        | "PREVIOUS" | "APPROVE" | "REJECT" | "REPEAT" | "READ_DRAFT"
        | "READ_EMAIL" | "PAUSE" | "RESUME" | "STOP" | "CANCEL_REPLY" }
  | { type: "DRAFT_REPLY"; content: string; reply_type: "reply" | "reply_all"; auto_send: boolean }
  | { type: "MODIFY"; instruction: string }
  | { type: "SAY"; text: string };

export interface VoiceAgentContext {
  state?: string;
  email_id?: string;
  has_draft?: boolean;
  draft_excerpt?: string;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface VoiceAgentResponse {
  actions: VoiceAgentAction[];
  confidence: number;
  source: "llm" | "unavailable";
}

/**
 * Dialogue conversationnel : transcript + contexte → liste d'actions ordonnée
 * (intents composés « archive ça et lis-moi le suivant »), dictée inline
 * (DRAFT_REPLY), et réponses parlées aux questions sur l'email courant (SAY).
 *
 * Remplace voiceIntent comme fallback LLM — `source: "unavailable"` ou un
 * échec réseau ⇒ le caller retombe sur ses keywords locaux. Timeout 6 s
 * (l'agent lit l'email courant côté serveur, un poil plus lent qu'intent).
 */
export async function voiceAgent(
  transcript: string,
  context: VoiceAgentContext = {},
): Promise<VoiceAgentResponse> {
  return apiFetch("/api/voice/agent", {
    method: "POST",
    body: JSON.stringify({ transcript, ...context }),
    timeoutMs: 6_000,
  });
}

export interface BriefingDigest {
  counts: { total: number; unread?: number; action?: number; fyi?: number; noise?: number };
  top?: Array<{ sender_name?: string; subject?: string; classification?: string }>;
  lang?: string;
}

/** Brief parlé d'entrée de session (« Salut — 12 nouveaux, 3 urgents… »).
 *  Le digest est calculé côté client (la liste est déjà chargée) ; le
 *  serveur ne fait que le rendu en registre parlé. */
export function getVoiceBriefing(digest: BriefingDigest): Promise<{ text: string; source: string }> {
  return apiFetch("/api/voice/briefing", {
    method: "POST",
    body: JSON.stringify(digest),
    timeoutMs: 8_000,
  });
}

/** Télémétrie voice-to-voice (durées + compteurs, zéro contenu). */
export function postVoiceMetrics(
  events: Array<{ kind: string; value_ms?: number; count?: number; state?: string }>,
): Promise<{ accepted: number }> {
  return apiFetch("/api/voice/metrics", {
    method: "POST",
    body: JSON.stringify({ events }),
    timeoutMs: 8_000,
  });
}

/** Mint a short-lived Deepgram token (backend → Deepgram /v1/auth/grant) so the
 *  mobile can open a WebSocket DIRECTLY to Deepgram for live STT, bypassing the
 *  Socket.IO /daemon proxy (which can't carry WS audio under prod's gthread
 *  gunicorn worker). The master Deepgram key never leaves the server. */
export function getDeepgramToken(ttlSeconds = 300): Promise<{ token: string; expires_in: number }> {
  return apiFetch("/api/stt/grant-token", {
    method: "POST",
    body: JSON.stringify({ ttl_seconds: ttlSeconds }),
    timeoutMs: 8_000,
  });
}

export async function transcribeAudio(audioUri: string, durationMs?: number): Promise<{ text: string }> {
  const token = await getToken();
  const formData = new FormData();
  // Diagnostic « transcripts vides » (device 2026-07-28, 15 s de voix → "") :
  // la durée arme le fallback Whisper du backend (substantiel ≥ 2 s) même si
  // le fichier est petit/tronqué, et la taille réelle part au ring buffer.
  if (durationMs && durationMs > 0) {
    formData.append("duration_seconds", String(Math.round(durationMs / 1000)));
  }
  let fileBytes = -1;
  try {
    const blob = await (await fetch(audioUri)).blob();
    fileBytes = blob.size;
  } catch { /* no-op légitime : taille = diagnostic best-effort */ }
  // #1134 : hint de langue pour Whisper/Deepgram — sans lui, l'auto-détection
  // sur un mot court part n'importe où (« suivant » → « Sigo » es, « Swivel » en).
  const sttLang = (i18n.language || "").split(/[-_]/)[0];
  if (sttLang) formData.append("lang", sttLang);
  formData.append("audio", {
    uri: audioUri,
    name: "audio.m4a",
    type: "audio/m4a",
  } as any);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const res = await fetch(`${API_URL}/api/transcribe`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
      signal: controller.signal,
    });
    if (res.status === 401) {
      // Même politique que apiFetchOnce (#1121) : confirmation avant purge.
      await handleUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      logEvent("api", { op: "transcribe", bytes: fileBytes, status: res.status, error: body.error ?? null });
      throw new Error(body.error || `HTTP ${res.status}`);
    }
    const data = await res.json();
    // Une ligne par upload : taille réelle envoyée vs texte reçu — tranche
    // « fichier tronqué » vs « provider muet » sans les logs backend.
    logEvent("api", {
      op: "transcribe", bytes: fileBytes, status: res.status,
      durS: durationMs ? Math.round(durationMs / 1000) : null,
      chars: ((data as { text?: string }).text ?? "").length,
    });
    return data;
  } catch (err: any) {
    if (err.name === "AbortError") {
      throw new Error(`Timeout — transcription trop longue ou réseau lent`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}
