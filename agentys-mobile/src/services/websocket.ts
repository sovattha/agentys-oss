/**
 * Service WebSocket (Socket.IO) pour les événements temps réel.
 *
 * Singleton strict : une seule instance Socket vivante à tout instant, y
 * compris sous appels concurrents (io() est synchrone, le garde suffit).
 * Le token est fourni via la forme fonction de `auth`, réévaluée par
 * Socket.IO à CHAQUE (re)connexion — un re-login n'envoie donc jamais un
 * token périmé. Reconnexion illimitée avec backoff plafonné : une session
 * drive peut durer 1h+ avec des trous réseau (tunnel, ascenseur) ; abandonner
 * après N tentatives dégradait silencieusement les drafts en polling pur.
 */

import { io, Socket } from "socket.io-client";
import { API_URL, WS_NAMESPACE } from "../config";
import { getToken, subscribeAuthChange } from "./auth";

let socket: Socket | null = null;
let cachedAccountId: number | null = null;

/** Résout l'`account_id` (int) du compte courant pour le handshake /daemon.
 *  Le backend exige un account_id résolu sur les connexions JWT distantes
 *  (audit P1, stt_stream.py:416) : sans lui, le proxy streaming Deepgram
 *  refuse le stream ("Compte non résolu") et la dictée retombe en batch.
 *  Le serveur VÉRIFIE l'ownership (account.email == JWT email) avant de
 *  l'honorer (websocket.py:376), donc l'envoyer est sûr. Caché pour la
 *  session — l'account ne change pas en cours de route sur mobile. */
async function resolveAccountId(token: string): Promise<number | null> {
  if (cachedAccountId != null) return cachedAccountId;
  try {
    const res = await fetch(`${API_URL}/api/accounts`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return null;
    const data = await res.json();
    const raw = data?.accounts?.[0]?.id;
    const id = typeof raw === "number" ? raw : Number(raw);
    if (Number.isFinite(id)) {
      cachedAccountId = id;
      return id;
    }
    return null;
  } catch {
    // fallback légitime : account id indisponible → room par défaut
    return null;
  }
}

export async function connectSocket(): Promise<Socket> {
  // Socket existant (connecté ou en cours de reconnexion gérée par Socket.IO) :
  // on le réutilise — en créer un second laisserait l'ancien retenter en fuite.
  if (socket) return socket;

  socket = io(`${API_URL}${WS_NAMESPACE}`, {
    // Forme fonction (#1120) : appelée à chaque tentative de (re)connexion →
    // token TOUJOURS frais après un re-login. On y résout aussi l'account_id
    // exigé par le handshake /daemon (audit P1, stt_stream.py:416) — le
    // serveur vérifie l'ownership avant de l'honorer (websocket.py:376).
    auth: (cb) => {
      getToken()
        .then(async (token) => {
          const accountId = token ? await resolveAccountId(token) : null;
          cb({ token, ...(accountId != null ? { account_id: accountId } : {}) });
        })
        .catch(() => cb({ token: null }));
    },
    // Transport : polling d'abord (le socket se connecte de façon fiable et
    // alimente les features temps-réel : draft_complete, daemon_event…).
    // ⚠️ WebSocket NE FONCTIONNE PAS en prod : le worker gunicorn `gthread`
    // ne supporte pas l'upgrade WebSocket (HTTP 400 sur /socket.io/?...=
    // websocket), donc `["websocket"…]` échoue ("websocket error") depuis
    // l'appareil. Conséquence : le STT streaming (audio binaire continu) ne
    // peut PAS marcher tant que prod ne passe pas à un worker WS-capable
    // (gevent + GeventWebSocketWorker). Voir docs/voice-first-redesign.md.
    transports: ["polling", "websocket"],
    reconnection: true,
    reconnectionDelay: 2000,
    reconnectionDelayMax: 15_000,
  });

  return socket;
}

/** Invalide le cache account_id (ex: déconnexion / changement de compte). */
export function resetAccountIdCache(): void {
  cachedAccountId = null;
}

export function disconnectSocket(): void {
  socket?.disconnect();
  socket = null;
}

export function getSocket(): Socket | null {
  return socket;
}

// Réagit au cycle de vie de l'auth :
//  - logout / token purgé → fermer le socket (sinon il retente avec un token mort) ;
//  - re-login avec un socket existant → forcer une reconnexion pour que la
//    fonction `auth` soit réévaluée avec le nouveau token.
subscribeAuthChange((hasToken) => {
  if (!hasToken) {
    resetAccountIdCache();
    disconnectSocket();
    return;
  }
  if (socket) {
    socket.disconnect().connect();
  }
});
