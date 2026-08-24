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
 * Service d'authentification mobile (OAuth + Magic Link + SecureStore).
 */

import * as SecureStore from "expo-secure-store";
import { reportError } from "../lib/errors";
import * as WebBrowser from "expo-web-browser";
import * as Crypto from "expo-crypto";
import { API_URL, DEEP_LINK_SCHEME } from "../config";

const TOKEN_KEY = "agentys_auth_token";

type AuthListener = (hasToken: boolean) => void;
const listeners = new Set<AuthListener>();

export function subscribeAuthChange(fn: AuthListener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emitAuthChange(hasToken: boolean): void {
  listeners.forEach((l) => {
    try { l(hasToken); } catch (e) {
      // Un subscriber qui lève est un bug de l'app — visible, sans casser le fanout.
      reportError(e, { domain: "state", op: "authChangeListener" }, { userFacing: "silent" });
    }
  });
}

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
  emitAuthChange(true);
}

export async function clearToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  emitAuthChange(false);
}

// ---------------------------------------------------------------------------
// OAuth config
// ---------------------------------------------------------------------------
export interface OAuthConfig {
  gmail: { client_id: string; redirect_uri: string; configured: boolean };
  outlook: { client_id: string; redirect_uri: string; configured: boolean };
}

export async function getOAuthConfig(): Promise<OAuthConfig> {
  const res = await fetch(`${API_URL}/api/oauth/config`);
  if (!res.ok) throw new Error("Failed to fetch OAuth config");
  return res.json();
}

// ---------------------------------------------------------------------------
// OAuth flow (PKCE + session/poll)
// ---------------------------------------------------------------------------
async function generateState(): Promise<string> {
  // Hermes Math.random() is predictable across observed values (audit Codex
  // 2026-04-25 [F-OAUTH-04]). expo-crypto.getRandomBytesAsync is a CSPRNG.
  const bytes = await Crypto.getRandomBytesAsync(32);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function generateCodeVerifier(): Promise<{ verifier: string; challenge: string }> {
  const bytes = await Crypto.getRandomBytesAsync(32);
  const verifier = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 }
  );
  // Base64url encode
  const challenge = digest.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return { verifier, challenge };
}

export type OAuthProvider = "gmail" | "outlook";

export async function startOAuth(provider: OAuthProvider): Promise<{ success: boolean; email?: string }> {
  const config = await getOAuthConfig();
  const providerConfig = config[provider];
  if (!providerConfig.configured) {
    throw new Error(`${provider === "gmail" ? "Gmail" : "Outlook"} n'est pas configuré sur le serveur`);
  }

  const state = await generateState();
  const { verifier, challenge } = await generateCodeVerifier();

  // Store PKCE verifier server-side. We surface a non-OK response loudly
  // because a silent failure here cascades into a 5-min poll timeout that
  // the user perceives as "OAuth broken with no error" — exactly the
  // symptom that hid the audit-2026-04-25 regression where the route was
  // accidentally moved behind the JWT guard.
  const pkceRes = await fetch(`${API_URL}/api/oauth/pkce/store`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state, code_verifier: verifier, client_type: "mobile" }),
  });
  if (!pkceRes.ok) {
    const detail = await pkceRes.text().catch(() => "");
    throw new Error(
      `Impossible d'initier la connexion OAuth (PKCE store ${pkceRes.status}). ${detail}`.trim()
    );
  }

  // Build OAuth URL.
  //
  // ⚠️ SCOPES = MIROIR EXACT de la webapp (agentys-app/src/services/oauth.ts)
  // — garder les deux listes synchronisées. Avant le 2026-07-18, le mobile
  // demandait `https://mail.google.com/` (scope large, hors config CASA
  // auditée) SANS les scopes calendar → comptes connectés depuis le mobile
  // privés du calendrier (warning « missing calendar scopes » en boucle en
  // prod), et pour Outlook les scopes IMAP/SMTP legacy au lieu de Graph
  // (Mail.*/Calendars/Contacts/MailboxSettings) → fonctionnalités Graph
  // mortes pour ces comptes.
  const GMAIL_SCOPES = [
    // Email (granulaires, config CASA)
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    // Calendar (Issue #26)
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
  ];
  const OUTLOOK_SCOPES = [
    // OIDC — requis pour l'id_token (AUTH-VULN-04, issue #557)
    "openid",
    "email",
    "profile",
    // Email via Microsoft Graph
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "offline_access",
    // Calendar (Issue #26)
    "https://graph.microsoft.com/Calendars.ReadWrite",
    // Contacts (autocomplete + avatars)
    "https://graph.microsoft.com/People.Read",
    "https://graph.microsoft.com/Contacts.Read",
    // Signature côté serveur (get_signature sans 403)
    "https://graph.microsoft.com/MailboxSettings.Read",
  ];

  let authUrl: string;
  if (provider === "gmail") {
    const params = new URLSearchParams({
      client_id: providerConfig.client_id,
      redirect_uri: providerConfig.redirect_uri,
      response_type: "code",
      scope: GMAIL_SCOPES.join(" "),
      access_type: "offline",
      prompt: "select_account consent",
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    authUrl = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
  } else {
    const params = new URLSearchParams({
      client_id: providerConfig.client_id,
      redirect_uri: providerConfig.redirect_uri,
      response_type: "code",
      scope: OUTLOOK_SCOPES.join(" "),
      prompt: "select_account",
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    authUrl = `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${params}`;
  }

  // iOS suspends JS while the Safari auth session is foregrounded, so polling
  // "in parallel" is unreliable. The backend finishes OAuth first, redirects
  // to this non-secret deep link, then we poll the HTTPS session once the app
  // is foregrounded again.
  const redirectUrl = `${DEEP_LINK_SCHEME}://oauth-complete`;
  const authResult = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
  if (authResult.type !== "success" || !("url" in authResult)) {
    throw new Error("Connexion OAuth annulée.");
  }

  const callbackUrl = new URL(authResult.url);
  const returnedState = callbackUrl.searchParams.get("state");
  if (returnedState && returnedState !== state) {
    throw new Error("Session OAuth invalide. Réessayez.");
  }

  const callbackError = callbackUrl.searchParams.get("error");
  if (callbackError) {
    throw new Error(`Échec de la connexion OAuth (${callbackError}).`);
  }

  return pollOAuthSession(state);
}

async function pollOAuthSession(state: string, maxAttempts = 60): Promise<{ success: boolean; email?: string }> {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const res = await fetch(`${API_URL}/api/oauth/session/${state}/poll`);
      if (res.status === 404) continue;
      const data = await res.json();
      if (data.status === "success") {
        // data.token is our backend JWT (what apiFetch uses for Authorization).
        // data.tokens.access_token is the Google/Microsoft OAuth token — NOT for our auth.
        if (data.token) {
          await setToken(data.token);
        }
        return { success: true, email: data.email };
      }
      if (data.status === "error") {
        throw new Error(data.error || "Échec de la connexion OAuth");
      }
    } catch (err: any) {
      if (err.message.includes("Échec")) throw err;
      // Network error — retry
    }
  }
  throw new Error("Délai d'attente dépassé. Réessayez.");
}

// ---------------------------------------------------------------------------
// Magic Link (legacy fallback)
// ---------------------------------------------------------------------------
export async function requestMagicLink(email: string): Promise<{ success: boolean; access_token?: string }> {
  const res = await fetch(`${API_URL}/api/auth/request-magic-link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error("Failed to request magic link");
  const data = await res.json();

  if (data.dev_magic_url) {
    try {
      const url = new URL(data.dev_magic_url);
      const token = url.searchParams.get("token");
      if (token) {
        const verified = await verifyMagicToken(token);
        return { success: true, access_token: verified.access_token };
      }
    } catch {
      // fallback légitime : magic link invalide → flow de login normal
    }
  }

  return { success: true };
}

export async function verifyMagicToken(token: string): Promise<{ access_token: string }> {
  const res = await fetch(`${API_URL}/api/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) throw new Error("Invalid or expired magic link");
  const data = await res.json();
  await setToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  await clearToken();
}
