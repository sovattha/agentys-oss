# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour l'authentification OAuth.

Endpoints:
- GET /api/oauth/config - Configuration OAuth pour le frontend (sans secrets)
- GET /api/oauth/gmail/callback - Callback OAuth Gmail (échange tokens côté serveur)
- GET /api/oauth/outlook/callback - Callback OAuth Outlook (échange tokens côté serveur)
- GET /api/oauth/tokens/<account_id>/status - Vérifie si un compte a des tokens valides
- POST /api/oauth/tokens/<account_id>/refresh - Rafraîchit les tokens d'un compte
- POST /api/oauth/<id>/disconnect - Déconnecte un compte

Migration Web: Les tokens sont maintenant échangés et stockés côté serveur.
Le frontend n'a plus accès aux client_secret.
"""

import os
import time
import logging
import hashlib
import hmac
import json
import uuid
import base64
from threading import Lock
from flask import Blueprint, request, jsonify, redirect, g
from cryptography.fernet import Fernet
import requests

# Import config first to ensure dotenv is loaded
import app.config  # noqa: F401

from app.account_identity import user_id_from_email as _canonical_user_id_from_email
from app.multi_accounts import get_account_manager, ProviderType, AccountStatus
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

oauth_bp = Blueprint("oauth", __name__)

# P1-009 (2026-04-28): 4xx codes that are TRANSIENT, not permanent.
# Without this set, _refresh_tokens_server treated ANY 4xx as terminal and
# forced the user to re-auth on a single 429 throttle from Google/Microsoft.
# 408 Request Timeout, 425 Too Early, 429 Too Many Requests all warrant a
# retry — the refresh_token itself is still valid.
TRANSIENT_4XX = {408, 425, 429}


# F-05 (regression audit, 2026-04-29): allowlist of OAuth error codes that
# are safe to log + return verbatim. Anything outside the allowlist is
# replaced with the generic "token_exchange_failed" sentinel — prevents
# attacker-controlled fragments (via crafted code/redirect_uri/etc that
# Google/Microsoft sometimes echo back in `error_description`) from
# landing in our logs and response bodies.
_OAUTH_SAFE_ERROR_CODES = frozenset({
    "invalid_grant", "invalid_request", "invalid_client", "invalid_scope",
    "unauthorized_client", "unsupported_grant_type", "access_denied",
    "server_error", "temporarily_unavailable",
})

_GMAIL_REQUIRED_SCOPE_GROUPS = (
    ("gmail.readonly", {"gmail.readonly", "https://www.googleapis.com/auth/gmail.readonly"}),
    ("gmail.send", {"gmail.send", "https://www.googleapis.com/auth/gmail.send"}),
    ("gmail.modify", {"gmail.modify", "https://www.googleapis.com/auth/gmail.modify"}),
    ("gmail.compose", {"gmail.compose", "https://www.googleapis.com/auth/gmail.compose"}),
    ("gmail.settings.basic", {
        "gmail.settings.basic",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    }),
    ("userinfo.email", {
        "userinfo.email",
        "https://www.googleapis.com/auth/userinfo.email",
    }),
)

_OUTLOOK_REQUIRED_SCOPE_GROUPS = (
    ("Mail.Read", {"Mail.Read", "https://graph.microsoft.com/Mail.Read"}),
    ("Mail.Send", {"Mail.Send", "https://graph.microsoft.com/Mail.Send"}),
    ("Mail.ReadWrite", {"Mail.ReadWrite", "https://graph.microsoft.com/Mail.ReadWrite"}),
    ("User.Read", {"User.Read", "https://graph.microsoft.com/User.Read"}),
    ("Calendars.ReadWrite", {
        "Calendars.ReadWrite",
        "https://graph.microsoft.com/Calendars.ReadWrite",
    }),
    ("People.Read", {"People.Read", "https://graph.microsoft.com/People.Read"}),
    ("Contacts.Read", {"Contacts.Read", "https://graph.microsoft.com/Contacts.Read"}),
)

_OAUTH_SCOPE_LABELS = {
    "gmail.readonly": "Lecture des emails",
    "gmail.send": "Envoi des emails",
    "gmail.modify": "Classement et modification des emails",
    "gmail.compose": "Création de brouillons Gmail",
    "gmail.settings.basic": "Réglages Gmail",
    "userinfo.email": "Adresse email du compte",
    "Mail.Read": "Lecture des emails",
    "Mail.Send": "Envoi des emails",
    "Mail.ReadWrite": "Création et modification des brouillons",
    "User.Read": "Profil Microsoft",
    "Calendars.ReadWrite": "Calendrier",
    "People.Read": "Contacts fréquents",
    "Contacts.Read": "Carnet d'adresses",
    "offline_access": "Connexion durable",
}


def _sleep_before_db_sync_retry(delay: float) -> None:
    time.sleep(delay)

def user_id_from_email(email: str) -> int:
    """Compatibility wrapper for the canonical account identity helper."""
    return _canonical_user_id_from_email(email)


def _normalize_oauth_scope(scope: str) -> set[str]:
    value = (scope or "").strip()
    if not value:
        return set()

    normalized = {value}
    google_prefix = "https://www.googleapis.com/auth/"
    graph_prefix = "https://graph.microsoft.com/"
    if value.startswith(google_prefix):
        normalized.add(value.removeprefix(google_prefix))
    if value.startswith(graph_prefix):
        normalized.add(value.removeprefix(graph_prefix))
    return normalized


def _extract_scopes_from_outlook_access_token(access_token: str | None) -> set[str]:
    if not access_token or access_token.count(".") < 2:
        return set()
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded.decode("utf-8"))
    except Exception:
        return set()

    raw_scopes = claims.get("scp") or ""
    if isinstance(raw_scopes, str):
        return set(raw_scopes.split())
    return set()


def _oauth_scope_set(token_data: dict) -> set[str]:
    raw_scopes = token_data.get("scope") or ""
    scope_values: set[str] = set()
    if isinstance(raw_scopes, str):
        scope_values.update(raw_scopes.split())
    elif isinstance(raw_scopes, list):
        scope_values.update(str(scope) for scope in raw_scopes if scope)

    provider = (token_data.get("provider") or "").strip().lower()
    if provider == "outlook":
        scope_values.update(_extract_scopes_from_outlook_access_token(
            token_data.get("access_token")
        ))

    normalized: set[str] = set()
    for scope in scope_values:
        normalized.update(_normalize_oauth_scope(scope))
    return normalized


def _oauth_required_scope_groups(provider: str | None) -> tuple[tuple[str, set[str]], ...]:
    provider_name = (provider or "").strip().lower()
    if provider_name == "gmail":
        return _GMAIL_REQUIRED_SCOPE_GROUPS
    if provider_name == "outlook":
        return _OUTLOOK_REQUIRED_SCOPE_GROUPS
    return ()


def _oauth_provider_permissions_url(provider: str | None) -> str | None:
    provider_name = (provider or "").strip().lower()
    if provider_name == "gmail":
        return "https://myaccount.google.com/permissions"
    if provider_name == "outlook":
        return "https://account.live.com/consent/Manage"
    return None


def _build_oauth_readiness(account_id: str, token_data: dict | None) -> dict:
    if not token_data:
        return {
            "ready": False,
            "needs_reauth": True,
            "problem": "no_tokens",
            "account_id": account_id,
            "provider": None,
            "email": None,
            "missing_scopes": [],
            "missing_scope_labels": [],
            "granted_scopes": [],
            "repair_url": None,
        }

    provider = (token_data.get("provider") or "").strip().lower()
    required_groups = _oauth_required_scope_groups(provider)
    if not required_groups:
        return {
            "ready": False,
            "needs_reauth": True,
            "problem": "unsupported_provider",
            "account_id": account_id,
            "provider": provider or None,
            "email": token_data.get("email"),
            "missing_scopes": [],
            "missing_scope_labels": [],
            "granted_scopes": sorted(_oauth_scope_set(token_data)),
            "repair_url": _oauth_provider_permissions_url(provider),
    }

    granted_scopes = _oauth_scope_set(token_data)
    if not granted_scopes and token_data.get("source") == "db_account":
        return {
            "ready": True,
            "needs_reauth": False,
            "problem": None,
            "account_id": account_id,
            "provider": provider,
            "email": token_data.get("email"),
            "missing_scopes": [],
            "missing_scope_labels": [],
            "granted_scopes": [],
            "scope_verified": False,
            "repair_url": _oauth_provider_permissions_url(provider),
        }

    missing_scopes = [
        name
        for name, accepted_scopes in required_groups
        if not granted_scopes.intersection(accepted_scopes)
    ]
    if not token_data.get("refresh_token"):
        missing_scopes.append("offline_access")

    missing_labels = [
        _OAUTH_SCOPE_LABELS.get(scope, scope)
        for scope in missing_scopes
    ]
    return {
        "ready": not missing_scopes,
        "needs_reauth": bool(missing_scopes),
        "problem": "missing_scopes" if missing_scopes else None,
        "account_id": account_id,
        "provider": provider,
        "email": token_data.get("email"),
        "missing_scopes": missing_scopes,
        "missing_scope_labels": missing_labels,
        "granted_scopes": sorted(granted_scopes),
        "scope_verified": True,
        "repair_url": _oauth_provider_permissions_url(provider),
    }


def _sync_oauth_account_manager(
    manager,
    *,
    account_id: str,
    email: str,
    provider: ProviderType,
    user_id: int,
    display_name: str | None = None,
) -> None:
    """Create/update AccountConfig and bind OAuth accounts to the web user.

    Tokens live in oauth_tokens.json, but calendar routes resolve accounts
    through AccountManager and enforce AccountConfig.user_id ownership. A
    reconnect for new scopes must therefore update both stores.
    """
    existing = manager.get_account(account_id)
    if existing:
        manager.update_account_status(account_id, AccountStatus.ACTIVE)
        if getattr(existing, "user_id", None) != user_id:
            manager.update_account(account_id, user_id=user_id)
    else:
        manager.add_account(
            name=display_name or email.split("@")[0],
            email=email,
            provider=provider,
            id=account_id,
            user_id=user_id,
        )

    current_for_user = None
    try:
        current_for_user = manager.get_current_for_user(user_id)
    except Exception as e:
        logger.debug(f"Could not read current OAuth account for user {user_id}: {e}")
    if current_for_user is not None and not isinstance(current_for_user, str):
        current_for_user = None

    if not current_for_user:
        manager.switch_to(account_id, user_id=user_id)


def _safe_oauth_error(
    error_data: dict, *, provider: str = "oauth"
) -> tuple[str, str]:
    """Extract a safe-to-log/return error code + correlation retry-id.

    F-05: previously the raw upstream error body was logged (`response={error_data}`)
    and the upstream `error_description` was echoed back to the client. The
    raw body can contain fragments of the attacker-controlled request, and
    the `error_description` is an English human-readable string with no
    contract — both are unsafe.

    Now: log/return only an OAuth error code from a fixed allowlist, plus
    a short random retry-id so support can correlate a client report with
    the matching log line.

    Audit follow-up 2026-04-29 (P2): also push the retry_id and safe_code
    onto the Sentry scope so a client report ("retry_id=abc12345 / OAuth
    failed") can be matched to the breadcrumb in Sentry without depending
    on Railway log retention windows.
    """
    raw_code = ""
    if isinstance(error_data, dict):
        raw_code = (error_data.get("error") or "").strip().lower()
    safe_code = raw_code if raw_code in _OAUTH_SAFE_ERROR_CODES else "token_exchange_failed"
    retry_id = uuid.uuid4().hex[:8]

    # Tag the active Sentry scope so the resulting breadcrumb is greppable
    # by retry_id. Best-effort: any failure here must NOT block the OAuth
    # error path.
    try:
        import sentry_sdk as _sentry
        _scope = _sentry.get_current_scope()
        if _scope is not None:
            _scope.set_tag("oauth.retry_id", retry_id)
            _scope.set_tag("oauth.error_code", safe_code)
            _scope.set_tag("oauth.provider", provider)
    except Exception:  # noqa: BLE001 — never crash the OAuth path on telemetry
        pass

    return safe_code, retry_id


def _outlook_identity_rejection_reason_key(reason: str) -> str:
    """Normalize internal Outlook identity rejection reasons for telemetry tags."""
    reason_lc = (reason or "").lower()
    if "id_token" in reason_lc and "absent" in reason_lc:
        return "id_token_absent"
    if "id_token" in reason_lc and "illisible" in reason_lc:
        return "id_token_unreadable"
    if "tenant" in reason_lc and "non autorisé" in reason_lc:
        return "tenant_not_allowed"
    if "oid" in reason_lc and "userinfo.id" in reason_lc:
        return "oid_userinfo_mismatch"
    return "identity_invalid"


def _capture_oauth_identity_rejection(*, provider: str, flow: str, reason: str) -> None:
    """Capture handled OAuth identity rejections in Sentry without PII."""
    reason_key = _outlook_identity_rejection_reason_key(reason)
    try:
        import sentry_sdk as _sentry

        scope_factory = getattr(_sentry, "new_scope", None) or _sentry.push_scope
        with scope_factory() as scope:
            scope.set_tag("oauth.provider", provider)
            scope.set_tag("oauth.flow", flow)
            scope.set_tag("oauth.error_code", "identity_invalid")
            scope.set_tag("oauth.identity_reject_reason", reason_key)
            _sentry.capture_message("OAuth identity rejected", level="warning")
    except Exception:  # noqa: BLE001 — telemetry must never block OAuth
        pass


def _check_token_ownership(account_id: str, token_data: dict) -> tuple | None:
    """ISO-01 fix — verify the JWT caller owns the OAuth tokens.

    Returns:
        None if the caller is authorized to access the tokens.
        A `(response_json, status_code)` tuple to return immediately if not.

    Authorization rules:
      - Loopback (Tauri desktop, no JWT) is trusted: single-user host.
      - JWT caller: `g.auth_user.email` MUST equal `token_data['email']`
        (case-insensitive). Returning 403 would leak existence; we return 404
        as if the account didn't exist.
      - Anything else (no JWT, remote IP) → 401.
    """
    from app.api.auth import is_trusted_loopback

    auth_user = getattr(g, "auth_user", None)

    # Loopback: trust the local Tauri client.
    if is_trusted_loopback() and auth_user is None:
        return None

    if not auth_user or not auth_user.get("email"):
        # Auth guard let us through (loopback) but auth_user is None and
        # we're NOT loopback → reject. Belt-and-suspenders.
        if not is_trusted_loopback():
            return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
        return None

    stored_email = (token_data.get("email") or "").lower()
    caller_email = (auth_user.get("email") or "").lower()
    if not stored_email or stored_email != caller_email:
        # Don't disclose whether the account_id exists — return 404.
        logger.warning(
            "[OAuth] Cross-user token access blocked: caller=%s stored=%s account=%s",
            caller_email or "<empty>", stored_email or "<empty>", account_id,
        )
        return jsonify({"error": "No tokens found for account"}), 404

    return None

# Outbound HTTP timeout (seconds) for token exchange / userinfo / refresh.
# OAuth endpoints normally respond in ~1s; 30s gives generous headroom while
# preventing worker starvation if Google/Microsoft become unresponsive.
_HTTP_TIMEOUT = 30


def _oauth_frontend_code_fallback_url(provider: str, code: str, state: str, redirect_uri: str) -> str:
    """Return the SPA fallback URL for OAuth code completion.

    Used when the server-side token exchange cannot be trusted to have
    completed, for example a transient TLS/socket failure before any response.
    The frontend still has the PKCE verifier in localStorage and can attempt
    the existing /complete flow instead of leaving the user on server_error.
    """
    from urllib.parse import quote_plus

    return (
        f"{FRONTEND_URL}/oauth/callback?provider={quote_plus(provider)}"
        f"&code={quote_plus(code)}&state={quote_plus(state)}"
        f"&auth_redirect_uri={quote_plus(redirect_uri)}"
    )


def _oauth_mobile_completion_url(
    provider: str,
    state: str | None,
    *,
    success: bool = False,
    error: str | None = None,
    reason: str | None = None,
) -> str:
    """Return the mobile deep link used after server-side OAuth completion.

    Only non-secret flow metadata is sent through the custom scheme. The app
    must still poll /api/oauth/session/<state>/poll over HTTPS to receive the
    Agentys JWT.
    """
    from urllib.parse import urlencode

    params = {
        "provider": provider,
        "state": state or "",
    }
    if success:
        params["success"] = "true"
    else:
        params["error"] = error or "oauth_failed"
    if reason:
        params["reason"] = reason
    return f"{MOBILE_OAUTH_REDIRECT_URL}?{urlencode(params)}"


def _oauth_client_type_for_state(state: str | None) -> str:
    if not state:
        return "web"
    data = _lookup_verifier_with_disk_fallback(state) or {}
    return "mobile" if data.get("client_type") == "mobile" else "web"


def _redirect_oauth_completion(
    provider: str,
    state: str | None,
    client_type: str,
    *,
    success: bool = False,
    email: str | None = None,
    account_id: str | None = None,
    error: str | None = None,
    reason: str | None = None,
    retry_id: str | None = None,
):
    from urllib.parse import quote_plus

    if client_type == "mobile":
        return redirect(
            _oauth_mobile_completion_url(
                provider,
                state,
                success=success,
                error=error,
                reason=reason,
            )
        )

    if success:
        return redirect(
            f"{FRONTEND_URL}/oauth/callback?provider={quote_plus(provider)}&success=true"
            f"&email={quote_plus(email or '')}"
            f"&account_id={quote_plus(account_id or '')}"
            f"&state={quote_plus(state or '')}"
        )

    params = f"provider={quote_plus(provider)}&error={quote_plus(error or 'oauth_failed')}"
    if retry_id:
        params += f"&retry_id={quote_plus(retry_id)}"
    if reason:
        params += f"&reason={quote_plus(reason)}"
    if email:
        params += f"&email={quote_plus(email)}"
    if state:
        params += f"&state={quote_plus(state)}"
    return redirect(f"{FRONTEND_URL}/oauth/callback?{params}")


# In-memory store for pending OAuth sessions (state -> result)
# Results expire after 5 minutes
_pending_oauth_sessions: dict[str, dict] = {}
_pending_oauth_lock = Lock()
OAUTH_SESSION_TTL = 300  # 5 minutes
# Audit 2026-04-25 (sub-report 01 LOW-02 / HIGH-05): bound the in-memory
# OAuth dicts so a flood of /pkce/store or /session/store requests can't
# exhaust memory or disk. FIFO eviction keeps the cheapest semantics.
_OAUTH_PENDING_MAX = 10_000

# S-04 fix (2026-04-24): honor AGENTYS_DATA_DIR for OAuth persistence so
# tokens / PKCE verifiers live on the persistent Railway volume
# (`/data/agentys/`) instead of the ephemeral container FS. Without this,
# every redeploy wiped oauth_tokens.json and forced every user through
# re-OAuth before sync could resume.
_DATA_ROOT_ENV = os.environ.get("AGENTYS_DATA_DIR", "").strip()
_LEGACY_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
)

# In-memory store for PKCE code verifiers (state -> code_verifier)
# Persisted to file so backend restarts don't invalidate in-flight OAuth flows
_pending_code_verifiers: dict[str, dict] = {}
_code_verifier_lock = Lock()

# AUTH-VULN-01 (Shannon pentest 2026-05-05, issue #557): bind every `state`
# value to the IP+UA fingerprint of the initiator (the agent that called
# /pkce/store). When /session/<state>/poll is called, we verify the caller's
# fingerprint matches before returning a JWT. This blocks the JWT-theft race
# where an attacker who learns `state` from the URL bar / Referer / access
# logs polls faster than the legitimate frontend.
#
# Stored OUT-OF-BAND from `_pending_code_verifiers` so the existing pop-on-
# read semantics (single-use verifier) don't also delete the fingerprint
# before the poll arrives. Same TTL as code verifiers.
_state_fingerprints: dict[str, dict] = {}
_state_fingerprint_lock = Lock()

if _DATA_ROOT_ENV:
    _PKCE_FILE = os.path.join(_DATA_ROOT_ENV, "pkce_verifiers.json")
else:
    _PKCE_FILE = os.path.join(_LEGACY_DATA_DIR, "pkce_verifiers.json")

# Server-side token storage (account_id -> encrypted tokens)
# Persisted to file for survival across restarts
_server_tokens: dict[str, dict] = {}
_server_token_deletions: set[str] = set()
_server_tokens_lock = Lock()
# Audit 2026-04-25 (CRIT-Iso-2): track the disk file mtime so a sibling
# gunicorn worker's write is picked up by THIS worker on the next read.
# Without this, worker A revokes a token while worker B still serves it
# from its boot-time in-memory snapshot.
_server_tokens_mtime: float = 0.0
# Audit 2026-04-25 (CRIT-Iso-2 Caveat B): also track file size so two writes
# within the same filesystem mtime tick (coarse-grained FS or high-throughput
# gunicorn) don't silently skip a reload.  Size is O(1) via stat; no hashing.
_server_tokens_fsize: int = 0

# Token storage file path.
if _DATA_ROOT_ENV:
    _TOKENS_FILE = os.path.join(_DATA_ROOT_ENV, "oauth_tokens.json")
else:
    _TOKENS_FILE = os.path.join(_LEGACY_DATA_DIR, "oauth_tokens.json")
logger.info(f"OAuth tokens file: {_TOKENS_FILE}")

# Environment variables for Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:5050/api/oauth/gmail/callback"
)

# Environment variables for Microsoft OAuth (Outlook)
# Support both MICROSOFT_* and AZURE_* env var names for consistency with outlook_adapter.py
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET", "")
MICROSOFT_REDIRECT_URI = os.getenv(
    "MICROSOFT_REDIRECT_URI", "http://localhost:5050/api/oauth/outlook/callback"
)

# Frontend URL for post-OAuth redirect
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:1420")
MOBILE_OAUTH_REDIRECT_URL = os.getenv("MOBILE_OAUTH_REDIRECT_URL", "agentys://oauth-complete")

# Token URLs
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
MICROSOFT_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"

# AUTH-VULN-04 (Shannon pentest 2026-05-05, issue #557): allowlist of Azure AD
# tenants accepted for Outlook OAuth. Empty / unset = any tenant accepted (the
# legacy behaviour and what `common` authority means). Set
# `MICROSOFT_TENANT_ALLOWLIST` to a comma-separated list of tenant IDs to
# restrict (e.g. when running a single-tenant deployment).
#
# Operational note (2026-05-15): keep this UNSET for the public SaaS deployment.
# Setting it would lock out every personal MSA (tid=9188040d-…) and every Azure
# AD tenant not explicitly listed, manifesting as `identity_invalid` /
# `tenant_not_allowed` on legitimate sign-ins. The startup log line below makes
# the active configuration auditable from Railway logs.
_MICROSOFT_TENANT_ALLOWLIST = frozenset(
    t.strip() for t in os.getenv("MICROSOFT_TENANT_ALLOWLIST", "").split(",")
    if t.strip()
)
if _MICROSOFT_TENANT_ALLOWLIST:
    logger.warning(
        "[AUTH-VULN-04] MICROSOFT_TENANT_ALLOWLIST is active (%d tenant(s)). "
        "Any user outside the allowlist will be rejected with `tenant_not_allowed`. "
        "Verify this is intentional — public SaaS deployments should leave it unset.",
        len(_MICROSOFT_TENANT_ALLOWLIST),
    )


def _decode_id_token_claims(id_token: str) -> dict:
    """Decode an id_token's payload WITHOUT signature verification.

    Used as a defense-in-depth read of claims minted by Microsoft. The
    signature would only matter if we read the token from an untrusted
    source — here we got it from a TLS connection to
    `login.microsoftonline.com`, which is itself the issuer. Returns {}
    on any parse failure.
    """
    try:
        import base64
        parts = id_token.split(".")
        if len(parts) < 2:
            return {}
        # JWT base64url payload — pad to 4-byte boundary for b64decode.
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        return {}


# Microsoft's published signing keys (JWKS) for the multi-tenant /common
# authority. PyJWKClient caches fetched keys in-process.
_MS_JWKS_URI = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
_ms_jwks_client = None


def _verify_microsoft_id_token(id_token: str) -> dict:
    """Cryptographically verify a Microsoft id_token and return its claims.

    Unlike `_decode_id_token_claims` (which NEVER verifies the signature), this
    validates the RS256 signature against Microsoft's published JWKS plus the
    audience and expiry. It is used ONLY on the `MICROSOFT_TENANT_ALLOWLIST`
    path, where the `tid` claim is a security decision (which tenants may sign
    in) and therefore must not be trusted from an unverified JWT body. Raises on
    any verification failure.
    """
    global _ms_jwks_client
    import jwt
    from jwt import PyJWKClient

    if _ms_jwks_client is None:
        _ms_jwks_client = PyJWKClient(_MS_JWKS_URI)
    signing_key = _ms_jwks_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=MICROSOFT_CLIENT_ID,
        # /common is multi-tenant: the issuer is per-tenant
        # (https://login.microsoftonline.com/{tid}/v2.0), so a single issuer
        # cannot be pinned here. `tid` is validated against the allowlist by the
        # caller AFTER this signature check proves the token authentic.
        options={"verify_iss": False},
    )


def _validate_outlook_identity(tokens: dict, userinfo: dict) -> tuple[bool, str]:
    """
    Defense against the nOAuth class of attacks (AUTH-VULN-04).

    Microsoft's `mail` and `userPrincipalName` Graph fields are
    administrator-mutable in the source tenant; an attacker who controls
    a tenant can set their user's `mail` to victim@victim.com and claim
    that mailbox identity if the relying party trusts those fields.

    Defenses applied here:
      1. Validate that the `id_token` is present and parseable.
      2. (Logging) cross-check the id_token's `oid` (per-tenant immutable
         user ID) against the Graph userinfo's `id`. These are NOT
         guaranteed equal for every legitimate Microsoft account type
         (personal MSA, B2B guests, v1/v2 token nuances), so a divergence
         is logged for observability but is NOT fatal — see the inline
         note at the check below for the full rationale.
      3. If `MICROSOFT_TENANT_ALLOWLIST` is configured, refuse tokens
         from tenants outside the allowlist.
      4. (Logging) cross-check that id_token's `email` claim matches
         userinfo's `mail` — divergence is suspicious but not fatal
         (some tenants sync these asynchronously).

    Returns (ok, reason). On reject, reason is operator-safe.
    """
    id_token = tokens.get("id_token") or ""
    if not id_token:
        # Without id_token we can't validate immutable claims. Refuse in prod
        # (where the harm lands), allow in dev to keep Tauri-loopback tests
        # easy.
        from app.api._auth_helpers import is_production
        if is_production():
            return False, "id_token absent — refus nOAuth-defense"
        return True, "id_token absent (dev — allowed)"

    claims = _decode_id_token_claims(id_token)
    if not claims:
        return False, "id_token illisible"

    tid = claims.get("tid")
    oid = claims.get("oid")

    if _MICROSOFT_TENANT_ALLOWLIST:
        # The tenant allowlist is a security gate, so `tid` must come from a
        # signature-VERIFIED token — never from the unverified body decode above
        # (2026-06-02 #12 — the audit flagged that the allowlist previously
        # gated on an unverified `tid`). Default deployments leave the allowlist
        # empty and skip this branch entirely, so normal /common users incur no
        # extra verification and no lockout risk.
        try:
            verified_claims = _verify_microsoft_id_token(id_token)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[AUTH-VULN-04] id_token signature verification failed "
                "(allowlist active): %s",
                exc,
            )
            return False, "id_token signature invalide"
        tid = verified_claims.get("tid")
        if tid not in _MICROSOFT_TENANT_ALLOWLIST:
            return False, f"Tenant Azure AD non autorisé: {tid}"

    # 2026-05-20 regression fix: do NOT hard-reject when the id_token's `oid`
    # differs from the Graph `/me` `id`. That equality was added as an nOAuth
    # guard (AUTH-VULN-04) but it is the wrong control:
    #   • It gives no protection against the actual nOAuth attack. There the
    #     attacker is a real user in a tenant they control, so their id_token
    #     `oid` and their Graph `id` agree — the equality passes — while the
    #     mutable `mail`/`userPrincipalName` (the true attack vector) is still
    #     trusted as the account key downstream.
    #   • Microsoft does NOT guarantee `oid == /me.id` for every legitimate
    #     account (personal MSA, B2B guests, v1/v2 token nuances), so real
    #     users were locked out with `oid_userinfo_mismatch` (HTTP 400).
    # The genuine nOAuth mitigation — keying the account on the immutable
    # `oid` rather than the mutable email — is tracked separately. Here we
    # only log the divergence so it stays observable without blocking sign-in.
    userinfo_id = userinfo.get("id")
    if oid and userinfo_id and oid != userinfo_id:
        logger.warning(
            "[AUTH-VULN-04] Outlook oid/userinfo divergence (non-fatal): "
            "id_token.oid=%s vs userinfo.id=%s",
            oid, userinfo_id,
        )

    # Soft check: divergence between id_token.email and userinfo.mail is
    # logged but not blocked — some tenants sync these asynchronously.
    id_email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    ui_mail = (userinfo.get("mail") or userinfo.get("userPrincipalName") or "").lower()
    if id_email and ui_mail and id_email != ui_mail:
        logger.info(
            "[AUTH-VULN-04] Outlook email drift: id_token=%s userinfo=%s",
            id_email, ui_mail,
        )

    return True, "ok"

# Encryption key for token storage (deterministic from SECRET_KEY)
# In production, use a proper secret management solution
_ENCRYPTION_KEY = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY")


# Audit 2026-04-25 (P0-1, sub-report 05 F-CRIT-2): the post-S-15 length-only
# guard let the literal placeholder `agentys-dev-secret-change-in-prod` (35
# chars) pass silently. Reject any value in this denylist or starting with
# the `agentys-dev-` prefix in addition to the length floor.
WEAK_DEFAULT_SECRETS = frozenset({
    "agentys-dev-secret-change-in-prod",
    "change-me",
    "changeme",
    "secret",
    "dev",
    "default",
    "test",
    "password",
})


def _validate_prod_oauth_secret(base_secret: str, is_prod: bool) -> None:
    """Fail-closed in prod when the SECRET_KEY/OAUTH key is too weak.

    Audit 2026-04-25 hardened this guard from a length-only check to also
    reject the literal placeholders the dev pipeline ships with. The
    SHA-256-derived Fernet key is otherwise deterministic from a public
    string — anyone who reads the open-source repo can decrypt every
    OAuth token at rest if the placeholder ever leaks back into prod.
    """
    if not is_prod:
        return
    secret = base_secret or ""
    if not secret:
        raise RuntimeError(
            "CRITICAL: OAUTH_TOKEN_ENCRYPTION_KEY or SECRET_KEY must be set "
            "in production. OAuth tokens are encrypted with this key."
        )
    normalized = secret.strip().lower()
    if normalized in WEAK_DEFAULT_SECRETS or normalized.startswith("agentys-dev-"):
        raise RuntimeError(
            "CRITICAL: OAUTH_TOKEN_ENCRYPTION_KEY/SECRET_KEY is a known "
            "placeholder default. Generate a fresh value via "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and set it in the production environment."
        )
    if len(secret) < 32:
        raise RuntimeError(
            "CRITICAL: OAUTH_TOKEN_ENCRYPTION_KEY or SECRET_KEY must be set "
            "to a strong (>= 32 chars) value in production. OAuth tokens "
            "are encrypted with this key — short or default values are a "
            "security risk (S-15)."
        )


if not _ENCRYPTION_KEY:
    import base64
    _base_secret = os.getenv("SECRET_KEY", "agentys-dev-secret-change-in-prod")
    # Security: fail-closed if the default or weak secret is used in production.
    from app.api._auth_helpers import is_production as _is_prod_helper
    _is_prod_oauth = _is_prod_helper()
    _validate_prod_oauth_secret(_base_secret, _is_prod_oauth)
    _key_bytes = hashlib.sha256(_base_secret.encode()).digest()
    _ENCRYPTION_KEY = base64.urlsafe_b64encode(_key_bytes)
_fernet = Fernet(_ENCRYPTION_KEY)


# =============================================================================
# Server-side Token Storage Functions (with file persistence)
# =============================================================================


def _ensure_data_dir():
    """Ensure the data directory exists."""
    data_dir = os.path.dirname(_TOKENS_FILE)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)


def _load_tokens_from_file():
    """Load tokens from persistent file storage."""
    global _server_tokens, _server_tokens_mtime, _server_tokens_fsize
    try:
        if os.path.exists(_TOKENS_FILE):
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                _server_tokens = json.load(f)
            try:
                stat = os.stat(_TOKENS_FILE)
                _server_tokens_mtime = stat.st_mtime
                _server_tokens_fsize = stat.st_size
            except OSError:
                _server_tokens_mtime = 0.0
                _server_tokens_fsize = 0
            logger.info(f"Loaded {len(_server_tokens)} OAuth tokens from file")
    except Exception as e:
        logger.error(f"Failed to load tokens from file: {e}")
        _server_tokens = {}
        _server_tokens_mtime = 0.0
        _server_tokens_fsize = 0


def _reload_tokens_if_disk_newer():
    """Audit 2026-04-25 (CRIT-Iso-2): refresh in-memory state when another
    worker has written to the tokens file since the last load.

    Cheap O(1) stat call; only re-parses JSON on actual mtime change. Safe
    under the existing lock — caller MUST hold `_server_tokens_lock`.
    """
    global _server_tokens, _server_tokens_mtime, _server_tokens_fsize
    try:
        if not os.path.exists(_TOKENS_FILE):
            return
        stat = os.stat(_TOKENS_FILE)
        cur_mtime = stat.st_mtime
        cur_size = stat.st_size
        if cur_mtime > _server_tokens_mtime or cur_size != _server_tokens_fsize:
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                _server_tokens = json.load(f)
            _server_tokens_mtime = cur_mtime
            _server_tokens_fsize = cur_size
            logger.debug(
                f"OAuth tokens reloaded from disk (mtime/size change, count={len(_server_tokens)})"
            )
    except Exception as e:
        logger.warning(f"Failed to reload OAuth tokens from disk: {e}")


def _save_tokens_to_file():
    """Save tokens to persistent file storage.

    Silent-failure fix (issue #318) :
    - Écriture atomique (tempfile + os.replace) pour qu'un crash ne laisse
      jamais un fichier partiellement écrit / corrompu sur disque.
    - L'erreur I/O est PROPAGÉE au caller (`store_tokens_server`,
      `delete_tokens_server`) qui décide quoi faire — sans cela, le user
      pense ses tokens persistés alors qu'ils sont perdus au prochain boot
      Railway (filesystem éphémère).
    """
    import tempfile

    _ensure_data_dir()  # may raise if path invalide / perms insuffisantes
    dir_ = os.path.dirname(_TOKENS_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tokens-", suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_server_tokens, f, indent=2)
        os.replace(tmp_path, _TOKENS_FILE)
        # Restrict file permissions to owner only (0o600)
        try:
            import stat
            os.chmod(_TOKENS_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows — limited chmod support
        # Audit 2026-04-25 (CRIT-Iso-2): record the new mtime so we don't
        # immediately re-read what we just wrote. Sibling workers will see
        # a different mtime and reload as expected.
        global _server_tokens_mtime, _server_tokens_fsize
        try:
            _st = os.stat(_TOKENS_FILE)
            _server_tokens_mtime = _st.st_mtime
            _server_tokens_fsize = _st.st_size
        except OSError:
            _server_tokens_mtime = 0.0
            _server_tokens_fsize = 0
        logger.debug(f"Saved {len(_server_tokens)} OAuth tokens to file (atomic)")
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_verifiers_from_file():
    """Load PKCE verifiers from disk (survives backend restarts)."""
    global _pending_code_verifiers
    try:
        if os.path.exists(_PKCE_FILE):
            with open(_PKCE_FILE, "r", encoding="utf-8") as f:
                _pending_code_verifiers = json.load(f)
            logger.debug(f"Loaded {len(_pending_code_verifiers)} PKCE verifiers from file")
    except Exception as e:
        logger.warning(f"Failed to load PKCE verifiers: {e}")
        _pending_code_verifiers = {}


def _lookup_verifier_with_disk_fallback(state: str) -> dict | None:
    """Find a PKCE verifier by state with multi-worker safety.

    Production scenario (Railway with N gunicorn workers): worker A serves
    /pkce/store and writes to disk + its in-memory dict. Worker B serves
    the OAuth callback — its in-memory dict was loaded at boot and never
    saw worker A's write. Without a disk re-read, the callback falls back
    to the frontend localStorage path, which adds a redirect hop and is
    fragile when the corporate browser truncates the long auth code.

    Strategy: lookup in-memory first (fast path, preserves test injections),
    then merge fresh disk entries on miss without clobbering in-memory state.
    """
    with _code_verifier_lock:
        data = _pending_code_verifiers.get(state)
        if data:
            return data
    # In-memory miss — reload from disk and merge.
    try:
        if os.path.exists(_PKCE_FILE):
            with open(_PKCE_FILE, "r", encoding="utf-8") as f:
                disk_verifiers = json.load(f)
            with _code_verifier_lock:
                for k, v in disk_verifiers.items():
                    _pending_code_verifiers.setdefault(k, v)
                return _pending_code_verifiers.get(state)
    except Exception as e:
        logger.warning(f"Failed to reload PKCE verifiers from disk: {e}")
    return None


# Load tokens and verifiers on module initialization
_load_tokens_from_file()
_load_verifiers_from_file()


def store_tokens_server(account_id: str, provider: str, tokens: dict, email: str) -> bool:
    """
    Store OAuth tokens securely on the server.

    Args:
        account_id: Unique account identifier
        provider: 'gmail' or 'outlook'
        tokens: Token data (access_token, refresh_token, expires_in, etc.)
        email: User's email address

    Returns:
        True if stored successfully
    """
    try:
        # Calculate expiration timestamp
        expires_in = tokens.get("expires_in", 3600)
        expires_at = time.time() + expires_in

        token_data = {
            "provider": provider,
            "email": email,
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": expires_at,
            "token_type": tokens.get("token_type", "Bearer"),
            "scope": tokens.get("scope", ""),
            "stored_at": time.time(),
        }

        # Encrypt the token data
        encrypted = _fernet.encrypt(json.dumps(token_data).encode())

        with _server_tokens_lock:
            _server_token_deletions.discard(account_id)
            _server_tokens[account_id] = {
                "encrypted_data": encrypted.decode() if isinstance(encrypted, bytes) else encrypted,
                "provider": provider,
                "email": email,
            }

        # Persist to file
        _save_tokens_to_file()

        # Cross-service DB write-back (deep audit 2026-06-02 M). The connect/OAuth
        # flows write tokens to the canonical DB account row, but the REFRESH path
        # also routes through here and historically updated only the in-memory dict
        # + local oauth_tokens.json. On a multi-service deploy (web + worker on
        # separate filesystems) the provider rotates the refresh_token on every
        # refresh; without this, the DB keeps the OLD refresh_token, the worker
        # reads it via _get_tokens_server_from_db (the documented cross-service
        # source of truth), and its next refresh fails with invalid_grant -> silent
        # logout. Best-effort: the token store already succeeded above, so a DB
        # hiccup must not fail it.
        try:
            from datetime import datetime as _datetime
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as _db_session:
                _db_account = (
                    AccountRepository(_db_session).get_by_email(email) if email else None
                )
                if _db_account is not None:
                    _db_account.access_token = tokens.get("access_token")
                    # Only overwrite the refresh_token when the provider returned a
                    # new one — a refresh response often omits it (the old one stays
                    # valid), and nulling it would itself trigger invalid_grant.
                    _new_refresh = tokens.get("refresh_token")
                    if _new_refresh:
                        _db_account.refresh_token = _new_refresh
                    # Naive-local datetime to match the existing read
                    # (_token_data_from_db_account does token_expires_at.timestamp()).
                    _db_account.token_expires_at = _datetime.fromtimestamp(expires_at)
        except Exception as _db_exc:  # noqa: BLE001
            logger.warning(
                "OAuth DB token write-back failed for account %s: %s", account_id, _db_exc
            )

        # Drop the contact-photo scope-probe cache so ContactPhotosBanner
        # re-evaluates on the next /api/contacts/avatar-status poll instead
        # of waiting for the 6h TTL after re-consent. Cheap (in-memory dict
        # mutation) and safe to call on every token store including refresh.
        try:
            from app.services.oauth_scope_check import invalidate as _invalidate_scope_cache
            try:
                _invalidate_scope_cache(int(account_id))
            except (TypeError, ValueError):
                # Hash-form account_id (multi_accounts.json key) — flush the
                # whole cache rather than skip; cost is one extra probe per
                # cached account on next poll.
                _invalidate_scope_cache(None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("oauth_scope_check invalidate skipped: %s", exc)

        logger.info(f"Tokens stored for account {account_id} ({provider})")
        return True

    except Exception as e:
        logger.error(f"Failed to store tokens for {account_id}: {e}")
        return False


def _oauth_hash_for_account(provider: str | None, email: str | None) -> str | None:
    provider_name = (provider or "").strip().lower()
    email_value = (email or "").strip()
    provider_name = {
        "google": "gmail",
        "microsoft": "outlook",
    }.get(provider_name, provider_name)
    if provider_name not in {"gmail", "outlook"} or not email_value:
        return None
    return hashlib.sha256(f"{provider_name}:{email_value}".encode()).hexdigest()[:16]


def _token_data_from_db_account(db_account, requested_account_id: str) -> dict | None:
    if db_account is None:
        return None
    provider = (getattr(db_account, "provider", "") or "").strip().lower()
    provider = {
        "google": "gmail",
        "microsoft": "outlook",
    }.get(provider, provider)
    email = (getattr(db_account, "email", "") or "").strip()
    access_token = getattr(db_account, "access_token", None)
    refresh_token = getattr(db_account, "refresh_token", None)
    if not email or provider not in {"gmail", "outlook"}:
        return None
    if not access_token and not refresh_token:
        return None

    expires_at = 0.0
    token_expires_at = getattr(db_account, "token_expires_at", None)
    if token_expires_at is not None:
        try:
            expires_at = float(token_expires_at.timestamp())
        except Exception:
            expires_at = 0.0
    elif refresh_token:
        # Older rows did not persist token_expires_at. Force the caller's
        # normal refresh path so a worker never relies on a stale access token.
        expires_at = 1.0

    return {
        "provider": provider,
        "email": email,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "token_type": "Bearer",
        "scope": "",
        "stored_at": 0,
        "source": "db_account",
        "requested_account_id": requested_account_id,
    }


def _get_tokens_server_from_db(account_id: str) -> dict | None:
    """Load OAuth tokens from the canonical DB account row.

    Railway web and worker services do not share the same local
    oauth_tokens.json. The DB row is the cross-service source of truth.
    """
    requested_account_id = str(account_id or "").strip()
    if not requested_account_id:
        return None

    try:
        from app.db.database import get_db_session
        from app.db.repositories.account_repository import AccountRepository

        with get_db_session() as session:
            repo = AccountRepository(session)
            db_account = None
            try:
                db_id = int(requested_account_id)
            except (TypeError, ValueError):
                db_id = None

            if db_id is not None and db_id > 0:
                db_account = repo.get(db_id)
            else:
                for candidate in repo.get_active_accounts():
                    if _oauth_hash_for_account(
                        getattr(candidate, "provider", None),
                        getattr(candidate, "email", None),
                    ) == requested_account_id:
                        db_account = candidate
                        break

            token_data = _token_data_from_db_account(db_account, requested_account_id)
            if token_data:
                logger.info("OAuth tokens loaded from DB fallback for account %s", requested_account_id)
            return token_data
    except Exception as exc:
        logger.warning("OAuth DB token fallback failed for account %s: %s", requested_account_id, exc)
        return None


def get_tokens_server(account_id: str) -> dict | None:
    """
    Retrieve OAuth tokens from server storage.

    Args:
        account_id: Unique account identifier

    Returns:
        Token data dict or None if not found/expired
    """
    try:
        with _server_tokens_lock:
            # Audit 2026-04-25 (CRIT-Iso-2): pick up writes from sibling
            # gunicorn workers so a revoke on worker A propagates to worker B.
            _reload_tokens_if_disk_newer()
            if account_id in _server_token_deletions:
                return None
            stored = _server_tokens.get(account_id)
            if not stored:
                return _get_tokens_server_from_db(account_id)

        # Decrypt the token data (handle string from JSON or bytes from memory)
        encrypted_data = stored["encrypted_data"]
        if isinstance(encrypted_data, str):
            encrypted_data = encrypted_data.encode()
        decrypted = _fernet.decrypt(encrypted_data)
        token_data = json.loads(decrypted.decode())

        return token_data

    except Exception as e:
        logger.error(f"Failed to retrieve tokens for {account_id}: {e}")
        return None


def delete_tokens_server(account_id: str) -> bool:
    """
    Delete OAuth tokens from server storage.

    Args:
        account_id: Unique account identifier

    Returns:
        True if deleted (or not found)
    """
    try:
        with _server_tokens_lock:
            _server_token_deletions.add(account_id)
            if account_id in _server_tokens:
                del _server_tokens[account_id]
                logger.info(f"Tokens deleted for account {account_id}")
                # Persist to file
                _save_tokens_to_file()
        return True
    except Exception as e:
        logger.error(f"Failed to delete tokens for {account_id}: {e}")
        return False


def revoke_token_at_provider(token_data: dict) -> bool:
    """FIX MIGRATE-002 (audit P0): revoke a refresh_token at the OAuth provider.

    Without this, account deletion only removes the local copy. Anyone who
    captured the refresh_token from a prior log line, memory dump, or
    backup of `oauth_tokens.json` can mint fresh access tokens against
    Gmail/Outlook indefinitely (until the user manually revokes in
    Google/Microsoft Account settings, which they have no reason to do).

    Best-effort: any failure (network, provider 5xx, missing endpoint
    for the provider) is logged but never raised — the caller MUST still
    proceed with the local delete because the alternative is leaving
    BOTH a live local copy AND a live provider-side credential.

    Returns True if the provider acknowledged the revocation (HTTP 2xx),
    False otherwise.
    """
    if not isinstance(token_data, dict):
        return False
    refresh_token = token_data.get("refresh_token") or ""
    provider = (token_data.get("provider") or "").lower()
    if not refresh_token or not provider:
        return False
    try:
        if provider == "gmail":
            # https://developers.google.com/identity/protocols/oauth2/web-server#tokenrevoke
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_HTTP_TIMEOUT,
            )
        elif provider == "outlook":
            # Microsoft doesn't expose a public refresh_token revocation
            # endpoint for personal / work accounts the same way Google
            # does. The closest documented path is the OAuth2 logout URL,
            # which severs the SSO session but doesn't always revoke
            # offline refresh tokens. We hit it best-effort; the
            # fallback for Outlook is the user's "Apps with access"
            # console at https://account.live.com/consent/Manage.
            response = requests.post(
                "https://login.microsoftonline.com/common/oauth2/v2.0/logout",
                data={
                    "refresh_token": refresh_token,
                    "client_id": MICROSOFT_CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_HTTP_TIMEOUT,
            )
        else:
            logger.debug(f"revoke_token_at_provider: unknown provider {provider!r}, skipping")
            return False
        ok = 200 <= response.status_code < 300
        if not ok:
            logger.warning(
                f"OAuth revoke at {provider} returned HTTP "
                f"{response.status_code}: {response.text[:200]}"
            )
        else:
            logger.info(f"OAuth refresh_token revoked at {provider}")
        return ok
    except Exception as e:
        logger.warning(f"OAuth revoke at {provider} failed: {e}")
        return False


def _refresh_tokens_server(account_id: str) -> dict | None:
    """
    Refresh OAuth tokens using the stored refresh_token.

    Args:
        account_id: Unique account identifier

    Returns:
        Updated token data or None if refresh failed
    """
    token_data = get_tokens_server(account_id)
    if not token_data or not token_data.get("refresh_token"):
        return None

    # Audit F-06 (2026-05-16): mirror revoke_token_at_provider's
    # defensive .lower() (line 814). Without it, a caller passing
    # provider="Gmail" / "GMAIL" (matches the casing in
    # app/config.py:498) silently falls through to the "Unknown
    # provider" log + None return below, forcing re-OAuth despite a
    # valid refresh_token. Latent today (all callers pass lowercase)
    # but trivial to trip on any future migration.
    provider = (token_data.get("provider") or "").lower()
    refresh_token = token_data.get("refresh_token")

    try:
        if provider == "gmail":
            response = requests.post(GOOGLE_TOKEN_URL, data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }, timeout=_HTTP_TIMEOUT)
        elif provider == "outlook":
            refresh_data = {
                "client_id": MICROSOFT_CLIENT_ID,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/People.Read https://graph.microsoft.com/Contacts.Read https://graph.microsoft.com/MailboxSettings.Read https://graph.microsoft.com/User.Read offline_access",
            }
            # Only include client_secret for confidential clients
            if MICROSOFT_CLIENT_SECRET:
                refresh_data["client_secret"] = MICROSOFT_CLIENT_SECRET
            response = requests.post(MICROSOFT_TOKEN_URL, data=refresh_data, timeout=_HTTP_TIMEOUT)
        else:
            logger.error(f"Unknown provider: {provider}")
            return None

        if not response.ok:
            try:
                error_body = response.json()
                error_code = str(error_body.get("error", "unknown"))
                error_desc = str(error_body.get("error_description", response.text))[:500]
            except Exception:
                error_code = "parse_error"
                error_desc = response.text[:500]
            # Audit R-003 (2026-04-27): emit token_expired on ANY 4xx refresh
            # failure (not just invalid_grant). Revoked refresh tokens, deleted
            # apps, blocked tenants surface as invalid_client / unauthorized_client
            # / access_denied — all permanent and indistinguishable from the user's
            # POV. Without this signal, the account became a sync zombie ("connected"
            # in UI but never refreshing) until a manual disconnect.
            # 5xx (transient) is excluded — keep retrying instead.
            # P1-009 (2026-04-28): 408/425/429 are also transient (timeout,
            # early, throttling). Don't burn the refresh_token over a rate
            # limit — log Retry-After if present and bail without emitting.
            permanent_codes = {
                "invalid_grant", "invalid_client", "unauthorized_client",
                "access_denied", "consent_required", "interaction_required",
                "AADSTS50173",  # token expired, re-auth required
                "AADSTS70008",  # refresh token expired
            }
            is_4xx = 400 <= response.status_code < 500
            is_transient_4xx = response.status_code in TRANSIENT_4XX
            permanent_4xx = is_4xx and not is_transient_4xx
            # Body-level codes always permanent regardless of HTTP status
            # (some IdPs return 200 with error= for revoked grants).
            is_permanent = permanent_4xx or error_code in permanent_codes
            refresh_log = logger.warning if is_permanent else logger.error
            refresh_log(
                f"Token refresh failed for {account_id} (HTTP {response.status_code}): "
                f"{error_code} — {error_desc}"
            )
            if is_transient_4xx and error_code not in permanent_codes:
                retry_after = response.headers.get("Retry-After", "")
                logger.warning(
                    "[OAuth] Transient %s for %s (Retry-After=%r) — keeping refresh_token, "
                    "no token_expired emitted",
                    response.status_code, account_id, retry_after,
                )
                return None
            if is_permanent:
                try:
                    from app.api.websocket import emit_token_expired
                    email = token_data.get("email", "")
                    # Audit B-01 (2026-05-12): token_data does not always
                    # carry the email field (depends on which IdP call last
                    # touched the row). If it is missing, emit goes to
                    # room="" — a silent noop. Resolve the email so the
                    # "reconnect your account" banner actually reaches the
                    # user.
                    #
                    # Audit F-04 (2026-05-16): the B-01 fix called
                    # ``AccountRepository.get(account_id)`` with the hex
                    # ``account_id`` (e.g. ``"be1262ad08733d9a"``), which
                    # routes to ``session.get(Account, hex)``. ``Account.id``
                    # is ``Mapped[int]`` — SQLAlchemy returns ``None``
                    # silently, the bare except never fires, and the banner
                    # never reaches the user. The hex id is the
                    # ``AccountConfig.id`` key in ``multi_accounts.json``,
                    # so resolve via the account manager first; fall back
                    # to DB-by-email only if the multi-account lookup misses.
                    if not email:
                        try:
                            from app.multi_accounts import get_account_manager
                            _cfg = get_account_manager().accounts.get(account_id)
                            if _cfg is not None:
                                email = (getattr(_cfg, "email", "") or "").strip()
                        except Exception as _mc_err:
                            logger.warning(
                                "[OAuth] email multi_accounts lookup failed "
                                "for account_id=%s: %s",
                                account_id, _mc_err,
                            )
                    if not email:
                        # Defensive fallback: DB query by email candidate
                        # gleaned from token_data (some providers store it
                        # under different keys).
                        candidate = (
                            token_data.get("user_email")
                            or token_data.get("account_email")
                            or ""
                        )
                        if candidate:
                            email = candidate.strip()
                    if not email:
                        logger.error(
                            "[OAuth] cannot emit token_expired for account_id=%s: "
                            "no email in token_data nor in DB — banner skipped",
                            account_id,
                        )
                    else:
                        emit_token_expired(account_id, email, provider)
                except Exception as _emit_err:
                    logger.warning(
                        "[OAuth] emit_token_expired failed for account_id=%s "
                        "provider=%s: %s",
                        account_id, provider, _emit_err,
                    )
            return None

        new_tokens = response.json()

        # Validate that we got an access_token
        new_access_token = new_tokens.get("access_token", "")
        if not new_access_token:
            logger.error("Token refresh returned no access_token")
            return None

        # Keep the old refresh token if not provided
        if not new_tokens.get("refresh_token"):
            new_tokens["refresh_token"] = refresh_token
        if not new_tokens.get("scope") and token_data.get("scope"):
            new_tokens["scope"] = token_data.get("scope")

        # Store the new tokens
        store_tokens_server(
            account_id,
            provider,
            new_tokens,
            token_data.get("email", "")
        )

        return get_tokens_server(account_id)

    except Exception as e:
        logger.error(f"Token refresh error for {account_id}: {e}")
        return None


# =============================================================================
# OAuth Config Endpoint (NO SECRETS!)
# =============================================================================


@oauth_bp.route("/config", methods=["GET"])
def get_oauth_config():
    """
    Retourne la configuration OAuth pour le frontend.

    SECURITE: Ne retourne PAS les client_secret.
    Le frontend n'en a pas besoin car l'échange de tokens
    se fait côté serveur.
    ---
    tags:
      - OAuth
    summary: Configuration OAuth (sans secrets)
    responses:
      200:
        description: Configuration OAuth
        content:
          application/json:
            schema:
              type: object
    """
    from app.config import is_placeholder
    gmail_configured = bool(
        GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
        and not is_placeholder(GOOGLE_CLIENT_ID)
        and not is_placeholder(GOOGLE_CLIENT_SECRET)
    )
    outlook_configured = bool(MICROSOFT_CLIENT_ID and not is_placeholder(MICROSOFT_CLIENT_ID))

    return jsonify({
        # Gmail OAuth config (NO client_secret)
        "gmail": {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "configured": gmail_configured,
        },
        # Outlook OAuth config (NO client_secret)
        "outlook": {
            "client_id": MICROSOFT_CLIENT_ID,
            "redirect_uri": MICROSOFT_REDIRECT_URI,
            "configured": outlook_configured,
        },
        # Legacy fields for backwards compatibility (NO client_secret)
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "configured": gmail_configured,
    })


# =============================================================================
# OAuth Callbacks (Server-side token exchange)
# =============================================================================


@oauth_bp.route("/gmail/callback", methods=["GET"])
def gmail_oauth_callback():
    """
    Callback OAuth pour Gmail.

    Google redirige ici après le consentement utilisateur.
    Le serveur échange le code contre les tokens, les stocke,
    puis redirige vers le frontend avec le résultat.
    ---
    tags:
      - OAuth
    summary: Callback OAuth Gmail (échange côté serveur)
    """
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    error_description = request.args.get("error_description")

    # Handle error from Google.
    # Audit 2026-04-25 (sub-report 01 MED-05): URL-encode error_description and
    # state — the Outlook flow already does so via quote(...). Inconsistency
    # here let a Google-side malformed string break the redirect URL.
    from urllib.parse import quote_plus
    if error:
        logger.warning(f"Gmail OAuth error: {error} - {error_description}")
        client_type = _oauth_client_type_for_state(state)
        if client_type == "mobile":
            return _redirect_oauth_completion(
                "gmail", state, client_type, error=error
            )
        params = f"provider=gmail&error={quote_plus(error)}"
        if error_description:
            params += f"&error_description={quote_plus(error_description)}"
        if state:
            params += f"&state={quote_plus(state)}"
        return redirect(f"{FRONTEND_URL}/oauth/callback?{params}")

    if not code or not state:
        client_type = _oauth_client_type_for_state(state)
        return _redirect_oauth_completion(
            "gmail", state, client_type, error="missing_code"
        )

    try:
        # Get the code_verifier stored during OAuth initiation.
        # Multi-worker safety: fall back to disk if the in-memory dict misses
        # (e.g. /pkce/store was served by a different gunicorn worker).
        _cleanup_expired_verifiers()
        verifier_data = _lookup_verifier_with_disk_fallback(state)
        if not verifier_data:
            logger.warning(f"Code verifier not found for state: {state[:8]}... — redirecting to frontend for localStorage fallback")
            # Fallback: let the frontend complete the exchange using its localStorage verifier.
            # Pass the auth-time redirect_uri so the frontend can re-send it identically at
            # /complete (OAuth 2.0 RFC 6749 §4.1.3 requires byte-identical URIs).
            from urllib.parse import quote_plus
            return redirect(_oauth_frontend_code_fallback_url("gmail", code, state, GOOGLE_REDIRECT_URI))
        client_type = "mobile" if verifier_data.get("client_type") == "mobile" else "web"
        code_verifier = verifier_data["code_verifier"]
        # Remove after use (one-time use) and persist deletion across workers.
        with _code_verifier_lock:
            _pending_code_verifiers.pop(state, None)
            _save_verifiers_to_file()

        # Exchange code for tokens (SERVER-SIDE - secure)
        try:
            token_response = requests.post(GOOGLE_TOKEN_URL, data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            }, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            logger.warning(
                "Gmail callback token exchange network error (%s) — "
                "falling back to frontend /complete for state=%s",
                e.__class__.__name__,
                state[:8],
            )
            if client_type == "mobile":
                return _redirect_oauth_completion(
                    "gmail", state, client_type, error="token_exchange_failed"
                )
            return redirect(_oauth_frontend_code_fallback_url("gmail", code, state, GOOGLE_REDIRECT_URI))

        if not token_response.ok:
            try:
                error_data = token_response.json()
            except Exception:
                error_data = {}
            safe_code, retry_id = _safe_oauth_error(error_data, provider="gmail")
            logger.error(
                "Gmail callback token exchange failed: status=%d code=%s retry_id=%s "
                "code_len=%d verifier_len=%d",
                token_response.status_code, safe_code, retry_id,
                len(code), len(code_verifier),
            )
            return _redirect_oauth_completion(
                "gmail", state, client_type, error=safe_code, retry_id=retry_id
            )

        tokens = token_response.json()

        # Get user email
        userinfo_response = requests.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        }, timeout=_HTTP_TIMEOUT)

        if not userinfo_response.ok:
            return _redirect_oauth_completion(
                "gmail", state, client_type, error="userinfo_failed"
            )

        userinfo = userinfo_response.json()
        email = userinfo.get("email", "")

        # F-08 (regression audit, 2026-04-29): compute user_id ONCE up
        # front so the manager.switch_to call below can pass it. Without
        # the user_id arg, two concurrent OAuth completions race-overwrite
        # _current_per_user[None] and background sync paths leak across
        # tenants.
        _db_user_id = user_id_from_email(email)

        # Generate account_id from email hash for consistency
        account_id = hashlib.sha256(f"gmail:{email}".encode()).hexdigest()[:16]

        # Store tokens server-side
        if not store_tokens_server(account_id, "gmail", tokens, email):
            return _redirect_oauth_completion(
                "gmail", state, client_type, error="storage_failed"
            )

        # Create/update account in manager
        # Audit regressions (2026-05-18 batch5) F-01: previously a manager
        # failure only logged .error and fell through. AccountManager-not-
        # populated then breaks `_resolve_account_id_for_email` for every
        # subsequent request — FE shows "logged in" but every mutation 403s.
        # Mirror the Outlook GET callback fix (oauth.py:1759, B-07 from batch4)
        # to surface the failure as a clean storage_failed redirect.
        try:
            manager = get_account_manager()
            _sync_oauth_account_manager(
                manager,
                account_id=account_id,
                email=email,
                provider=ProviderType.GMAIL,
                user_id=_db_user_id,
                display_name=email.split("@")[0],
            )
        except Exception as e:
            logger.exception(f"Gmail OAuth callback: Account manager error for {email}: {e}")
            return _redirect_oauth_completion(
                "gmail", state, client_type, error="storage_failed"
            )

        # Create/update account in SQLite DB (needed for sync service).
        # IMPORTANT: set user_id so multi-user isolation queries scope this
        # account to the right JWT user. Must match the user_id computed
        # below for the JWT — same formula.
        db_sync_failed = False
        db_sync_attempts = 3
        for attempt in range(1, db_sync_attempts + 1):
            try:
                from app.db.database import get_db_session
                from app.db.repositories.account_repository import AccountRepository
                with get_db_session() as session:
                    account_repo = AccountRepository(session)
                    db_account = account_repo.get_by_email(email)
                    if db_account:
                        db_account.is_active = True
                        db_account.access_token = tokens.get("access_token")
                        db_account.refresh_token = tokens.get("refresh_token")
                        if db_account.user_id != _db_user_id:
                            db_account.user_id = _db_user_id
                    else:
                        from app.db.models.account import Account as AccountModel
                        db_account = AccountModel(
                            email=email,
                            provider="gmail",
                            display_name=userinfo.get("name", email.split("@")[0]),
                            access_token=tokens.get("access_token"),
                            refresh_token=tokens.get("refresh_token"),
                            is_active=True,
                            user_id=_db_user_id,
                        )
                        session.add(db_account)
                    session.commit()
                    logger.info(f"DB account synced for {email} (user_id={_db_user_id})")
                    # ISO-12 fix: a fresh DB id was just minted (or reactivated) for
                    # this email — drop any stale resolver cache entry so the next
                    # JWT-routed request picks up the new id immediately.
                    try:
                        from app.api.routes_helpers import _invalidate_account_id_cache
                        _invalidate_account_id_cache(email)
                    except Exception:
                        pass
                break
            except Exception as exc:
                is_locked = "database is locked" in str(exc).lower()
                if is_locked and attempt < db_sync_attempts:
                    delay = float(attempt)
                    logger.warning(
                        "Gmail OAuth callback: DB account sync locked for %s, retry %d/%d in %.1fs",
                        email, attempt, db_sync_attempts, delay,
                    )
                    _sleep_before_db_sync_retry(delay)
                    continue
                # Silent-failure fix (issue #320): ne plus rediriger success=true si le
                # compte n'est pas en base. Sinon le sync service ne le verra jamais
                # et l'utilisateur pensera être connecté sans recevoir aucun email.
                logger.exception("Gmail OAuth callback: DB account sync failed for %s", email)
                db_sync_failed = True
                break

        if not db_sync_failed:
            # Auto-import profile photo in background (best-effort, non-blocking)
            _at = tokens.get("access_token", "")
            _aid = account_id
            _em = email
            def _bg_import_gmail_avatar(_token=_at, _aid=_aid, _em=_em):
                try:
                    from app.api.accounts import fetch_and_store_provider_avatar, _persist_avatar_url
                    url = fetch_and_store_provider_avatar(_em, _token, "gmail", _aid)
                    if url:
                        _persist_avatar_url(_em, _aid, url)
                except Exception as _e:
                    logger.debug(f"[AVATAR] Auto-import Gmail failed: {_e}")
            import threading
            threading.Thread(target=_bg_import_gmail_avatar, daemon=True).start()

            # Enrol the Gmail Pub/Sub watch so this freshly-connected account
            # gets near-realtime push immediately, instead of waiting up to 24h
            # for the daily renew-due cron. Best-effort — no-op without a topic.
            try:
                from app.api.gmail_push import enroll_gmail_watch_async
                enroll_gmail_watch_async(email)
            except Exception:
                logger.debug("[WATCH] Gmail watch enrolment dispatch failed", exc_info=True)

        if db_sync_failed:
            return _redirect_oauth_completion(
                "gmail",
                state,
                client_type,
                error="db_sync_failed",
                email=email,
            )

        # Generate JWT FIRST so the polling fallback can return it.
        # When the popup → opener postMessage path is severed (incognito + COOP),
        # the parent window only learns about the OAuth result by polling
        # /api/oauth/session/<state>/poll — and that response was previously
        # token-less, forcing a brittle dependency on the popup writing JWT
        # to localStorage before the parent reads it. Including the JWT in the
        # session payload makes the poll response self-sufficient.
        _early_jwt: str | None = None
        try:
            from app.api.auth import _create_jwt as _jwt_make, _register_known_user as _jwt_reg
            _jwt_reg(email)
            _early_user_id = user_id_from_email(email)
            _early_jwt = _jwt_make(_early_user_id, email)
        except Exception as _e:
            logger.warning(f"Could not pre-generate JWT for poll session: {_e}")

        # Also store session for legacy polling flow (Tauri compatibility +
        # incognito web popup fallback when window.opener.postMessage is blocked).
        with _pending_oauth_lock:
            _pending_oauth_sessions[state] = {
                "tokens": tokens,
                "email": email,
                "account_id": account_id,
                "jwt": _early_jwt,
                "timestamp": time.time(),
            }

        # Fetch and store email signature from Gmail (skip if user has custom signature)
        try:
            _skip_signature = False
            try:
                from app.db.database import get_db_session as get_sig_check_session
                from app.db.models.account import Account as AccountModel
                with get_sig_check_session() as check_session:
                    existing_acc = check_session.query(AccountModel).filter_by(email=email).first()
                    if existing_acc and getattr(existing_acc, 'signature_user_modified', False):
                        _skip_signature = True
                        logger.info(f"Signature custom préservée pour {email} (user_modified=True)")
            except Exception as check_err:
                logger.warning(f"Could not check signature_user_modified: {check_err}")

            if not _skip_signature:
                from app.providers.gmail_adapter import GmailAdapter
                from app.utils.signature import fetch_and_store_signature

                gmail_provider = GmailAdapter()
                # Set up credentials from tokens
                from google.oauth2.credentials import Credentials
                creds = Credentials(
                    token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET,
                )
                gmail_provider._credentials = creds
                gmail_provider._authenticated = True
                from googleapiclient.discovery import build
                gmail_provider._service = build("gmail", "v1", credentials=creds)

                # Fetch and store signature (pass email for DB lookup since account_id is a string hash)
                fetch_and_store_signature(gmail_provider, account_id, email=email)

                # Sync signature back to AccountConfig (JSON) so frontend can read it
                try:
                    from app.db.database import get_db_session as get_sig_session
                    from app.db.models.account import Account as AccountModel
                    with get_sig_session() as sig_session:
                        db_acc = sig_session.query(AccountModel).filter_by(email=email).first()
                        if db_acc and (db_acc.signature_html or db_acc.signature_text):
                            sig_updates = {}
                            if db_acc.signature_text:
                                sig_updates["signature"] = db_acc.signature_text
                            if db_acc.signature_html:
                                sig_updates["signature_html"] = db_acc.signature_html
                            if sig_updates:
                                manager.update_account(account_id, **sig_updates)
                except Exception as sync_err:
                    logger.warning(f"Could not sync signature to AccountConfig: {sync_err}")

                logger.info(f"Gmail signature migrated for {email}")
        except Exception as sig_error:
            logger.warning(f"Could not migrate Gmail signature: {sig_error}")
            # Continue - signature is optional

        # Auto-import Google profile photo (best-effort, needs profile scope)
        try:
            _picture_url = userinfo.get("picture")
            if _picture_url:
                from app.api.accounts import _save_avatar_from_url, _persist_avatar_url
                _avatar_url = _save_avatar_from_url(_picture_url, account_id)
                if _avatar_url:
                    _persist_avatar_url(email, account_id, _avatar_url)
                    logger.info(f"[AVATAR] Imported Google profile photo for {email}")
        except Exception as _av_e:
            logger.warning(f"[AVATAR] Gmail auto-import failed: {_av_e}")

        logger.info(f"Gmail OAuth successful for {email}")

        # FIX AUTH-004 (audit P1): do NOT pass the JWT in the redirect URL —
        # query params land in browser history, server access logs, and the
        # Referer header on any third-party resource the callback page loads.
        # The JWT was already stored in the polling session above; the
        # frontend retrieves it via /session/<state>/poll (HTTPS body, not URL).
        return _redirect_oauth_completion(
            "gmail",
            state,
            client_type,
            success=True,
            email=email,
            account_id=account_id,
        )

    except Exception as e:
        logger.error(f"Gmail OAuth callback error: {e}")
        client_type = _oauth_client_type_for_state(state)
        return _redirect_oauth_completion(
            "gmail", state, client_type, error="server_error"
        )


@oauth_bp.route("/gmail/complete", methods=["POST"])
def gmail_oauth_complete():
    """
    Échange le code OAuth Gmail contre des tokens côté serveur.

    Appelé par OAuthCallback.tsx quand Google redirige directement vers le frontend
    (flow découplé du backend au démarrage). Le code_verifier peut venir du body
    (localStorage du frontend) ou du store backend (fallback).
    ---
    tags:
      - OAuth
    summary: Complétion OAuth Gmail (échange code → token via POST)
    """
    data = request.get_json() or {}
    code = (data.get("code") or "").strip()
    state = (data.get("state") or "").strip()
    code_verifier = (data.get("code_verifier") or "").strip()
    redirect_uri = (data.get("redirect_uri") or GOOGLE_REDIRECT_URI).strip()

    if not code:
        return jsonify({"error": "code manquant"}), 400

    if not code_verifier:
        # Fallback : chercher dans le store backend (stocké lors de l'initiation si le backend était up).
        # Multi-worker safety: fall back to disk if the in-memory dict misses
        # (e.g. /pkce/store was served by a different gunicorn worker).
        _cleanup_expired_verifiers()
        verifier_data = _lookup_verifier_with_disk_fallback(state) or {}
        code_verifier = verifier_data.get("code_verifier", "")
        if code_verifier:
            with _code_verifier_lock:
                _pending_code_verifiers.pop(state, None)
                _save_verifiers_to_file()

    if not code_verifier:
        return jsonify({"error": "code_verifier manquant"}), 400

    try:
        # Échange code → tokens (côté serveur, client_secret reste confidentiel)
        token_response = requests.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, timeout=_HTTP_TIMEOUT)

        if not token_response.ok:
            try:
                error_data = token_response.json()
            except Exception:
                error_data = {}
            # F-05 (regression audit, 2026-04-29): never log/echo raw upstream
            # body or error_description (attacker-controllable). Only the
            # OAuth error code from a fixed allowlist + a retry-id.
            safe_code, retry_id = _safe_oauth_error(error_data, provider="gmail")
            logger.error(
                "Gmail complete token exchange failed: status=%d code=%s retry_id=%s "
                "code_len=%d verifier_len=%d",
                token_response.status_code, safe_code, retry_id,
                len(code), len(code_verifier),
            )
            return jsonify({"error": safe_code, "retry_id": retry_id}), 400

        tokens = token_response.json()

        # Récupérer l'email de l'utilisateur
        userinfo_response = requests.get(GOOGLE_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        }, timeout=_HTTP_TIMEOUT)
        if not userinfo_response.ok:
            return jsonify({"error": "userinfo_failed"}), 400

        userinfo = userinfo_response.json()
        email = userinfo.get("email", "")
        account_id = hashlib.sha256(f"gmail:{email}".encode()).hexdigest()[:16]

        # F-08 (regression audit, 2026-04-29): compute user_id BEFORE
        # the manager block so switch_to gets it.
        _db_user_id = user_id_from_email(email)

        # Stocker les tokens côté serveur
        if not store_tokens_server(account_id, "gmail", tokens, email):
            return jsonify({"error": "storage_failed"}), 500

        # Créer/mettre à jour le compte dans le manager
        # Audit regressions (2026-05-18 batch5) F-05: same defect as F-01 at
        # this Tauri/desktop-complete endpoint. Manager error must surface as
        # storage_failed (500) so the FE can prompt the user to retry instead
        # of issuing a JWT against a non-existent AccountManager entry.
        try:
            manager = get_account_manager()
            _sync_oauth_account_manager(
                manager,
                account_id=account_id,
                email=email,
                provider=ProviderType.GMAIL,
                user_id=_db_user_id,
                display_name=email.split("@")[0],
            )
        except Exception as e:
            logger.exception(f"Gmail OAuth complete: Account manager error for {email}: {e}")
            return jsonify({"error": "storage_failed"}), 500

        # Synchroniser avec la DB SQLite — bake the user_id so multi-user
        # isolation queries later can scope this account to the JWT user.
        # B-03 (famille #320, audit 2026-06-11): un échec ici ne doit plus
        # être avalé en warning pendant que le flow retourne succès — le
        # front/la session de polling reçoivent db_synced=false (le JWT est
        # quand même émis, l'utilisateur reste connecté).
        db_synced = True
        try:
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                account_repo = AccountRepository(session)
                db_account = account_repo.get_by_email(email)
                if db_account:
                    db_account.is_active = True
                    db_account.access_token = tokens.get("access_token")
                    db_account.refresh_token = tokens.get("refresh_token")
                    if db_account.user_id != _db_user_id:
                        db_account.user_id = _db_user_id
                else:
                    from app.db.models.account import Account as AccountModel
                    db_account = AccountModel(
                        email=email,
                        provider="gmail",
                        display_name=userinfo.get("name", email.split("@")[0]),
                        access_token=tokens.get("access_token"),
                        refresh_token=tokens.get("refresh_token"),
                        is_active=True,
                        user_id=_db_user_id,
                    )
                    session.add(db_account)
                session.commit()
                logger.info(f"DB account synced in gmail/complete for {email} (user_id={_db_user_id})")
                # ISO-12 symmetry (2026-04-24): same defense-in-depth as the
                # Gmail callback and outlook flows. Drop resolver cache after
                # fresh DB write so JWT-routed requests pick up the new id.
                try:
                    from app.api.routes_helpers import _invalidate_account_id_cache
                    _invalidate_account_id_cache(email)
                except Exception:
                    pass
        except Exception:
            db_synced = False
            logger.error(
                "Could not sync DB account in gmail/complete for %s",
                email, exc_info=True,
            )

        if db_synced:
            # Enrol the Gmail Pub/Sub watch so this freshly-connected account
            # gets near-realtime push immediately, instead of waiting up to 24h
            # for the daily renew-due cron. Best-effort — no-op without a topic.
            try:
                from app.api.gmail_push import enroll_gmail_watch_async
                enroll_gmail_watch_async(email)
            except Exception:
                logger.debug("[WATCH] Gmail watch enrolment dispatch failed", exc_info=True)

        # Generate JWT FIRST so we can include it in the polling session payload
        # (poll fallback for incognito popups where postMessage to opener is COOP-blocked).
        token_jwt = None
        try:
            from app.api.auth import _create_jwt, _register_known_user
            _register_known_user(email)
            user_id = user_id_from_email(email)
            token_jwt = _create_jwt(user_id, email)
        except Exception as jwt_err:
            logger.warning(f"Could not generate JWT in gmail/complete: {jwt_err}")

        # Stocker la session pour le polling Tauri (compatibilité) +
        # incognito web popup fallback (postMessage may be severed by COOP).
        if state:
            with _pending_oauth_lock:
                _pending_oauth_sessions[state] = {
                    "tokens": tokens,
                    "email": email,
                    "account_id": account_id,
                    "jwt": token_jwt,
                    "db_synced": db_synced,
                    "timestamp": time.time(),
                }

        logger.info(f"Gmail OAuth complete successful for {email}")
        return jsonify({
            "success": True,
            "email": email,
            "account_id": account_id,
            "token": token_jwt,
            "db_synced": db_synced,
        })

    except Exception as e:
        logger.error(f"Gmail OAuth complete error: {e}")
        return jsonify({"error": "server_error"}), 500


@oauth_bp.route("/outlook/callback", methods=["GET"])
def outlook_oauth_callback():
    """
    Callback OAuth pour Outlook.

    Microsoft redirige ici après le consentement utilisateur.
    Le serveur échange le code contre les tokens, les stocke,
    puis redirige vers le frontend avec le résultat.
    ---
    tags:
      - OAuth
    summary: Callback OAuth Outlook (échange côté serveur)
    """
    from urllib.parse import quote
    code = (request.args.get("code") or "").strip()
    state = (request.args.get("state") or "").strip()
    error = request.args.get("error")
    error_description = request.args.get("error_description")

    # Handle error from Microsoft. Use quote() (RFC 3986 — spaces become %20)
    # for the error fields so callers can reliably parse them; quote_plus()
    # would emit "+" which is form-encoding (RFC 1866) and slightly less standard.
    if error:
        logger.warning(f"Outlook OAuth error: {error} - {error_description}")
        client_type = _oauth_client_type_for_state(state)
        if client_type == "mobile":
            return _redirect_oauth_completion(
                "outlook", state, client_type, error=error
            )
        params = f"provider=outlook&error={quote(error, safe='')}"
        if error_description:
            params += f"&error_description={quote(error_description, safe='')}"
        if state:
            params += f"&state={quote(state, safe='')}"
        return redirect(f"{FRONTEND_URL}/oauth/callback?{params}")

    if not code or not state:
        client_type = _oauth_client_type_for_state(state)
        return _redirect_oauth_completion(
            "outlook", state, client_type, error="missing_code"
        )

    try:
        # Get the code_verifier stored during OAuth initiation.
        # Multi-worker safety: fall back to disk if the in-memory dict misses
        # (e.g. /pkce/store was served by a different gunicorn worker whose
        # in-memory _pending_code_verifiers dict is invisible to this worker).
        _cleanup_expired_verifiers()
        verifier_data = _lookup_verifier_with_disk_fallback(state)
        if not verifier_data:
            logger.warning(f"Code verifier not found for state: {state[:8]}... — redirecting to frontend for localStorage fallback")
            # Pass the auth-time redirect_uri so the frontend re-sends it identically at /complete.
            return redirect(_oauth_frontend_code_fallback_url("outlook", code, state, MICROSOFT_REDIRECT_URI))
        client_type = "mobile" if verifier_data.get("client_type") == "mobile" else "web"
        code_verifier = verifier_data["code_verifier"]
        # Remove after use (one-time use) and persist deletion across workers.
        with _code_verifier_lock:
            _pending_code_verifiers.pop(state, None)
            _save_verifiers_to_file()

        # Exchange code for tokens (SERVER-SIDE - secure)
        token_data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": MICROSOFT_REDIRECT_URI,
        }
        if MICROSOFT_CLIENT_SECRET:
            token_data["client_secret"] = MICROSOFT_CLIENT_SECRET
        try:
            token_response = requests.post(MICROSOFT_TOKEN_URL, data=token_data, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            logger.warning(
                "Outlook callback token exchange network error (%s) — "
                "falling back to frontend /complete for state=%s",
                e.__class__.__name__,
                state[:8],
            )
            if client_type == "mobile":
                return _redirect_oauth_completion(
                    "outlook", state, client_type, error="token_exchange_failed"
                )
            return redirect(_oauth_frontend_code_fallback_url("outlook", code, state, MICROSOFT_REDIRECT_URI))

        if not token_response.ok:
            try:
                error_data = token_response.json()
            except Exception:
                error_data = {}
            # F-05 (regression audit, 2026-04-29): see Gmail variant above.
            safe_code, retry_id = _safe_oauth_error(error_data, provider="outlook")
            logger.error(
                "Outlook callback token exchange failed: status=%d code=%s retry_id=%s "
                "code_len=%d verifier_len=%d",
                token_response.status_code, safe_code, retry_id,
                len(code), len(code_verifier),
            )
            return _redirect_oauth_completion(
                "outlook", state, client_type, error=safe_code, retry_id=retry_id
            )

        tokens = token_response.json()

        # Get user email
        userinfo_response = requests.get(MICROSOFT_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        }, timeout=_HTTP_TIMEOUT)

        if not userinfo_response.ok:
            return _redirect_oauth_completion(
                "outlook", state, client_type, error="userinfo_failed"
            )

        userinfo = userinfo_response.json()

        # AUTH-VULN-04 (Shannon pentest 2026-05-05, issue #557): defense
        # against nOAuth — verify id_token claims align with Graph userinfo
        # before trusting the email for identity.
        _id_ok, _id_reason = _validate_outlook_identity(tokens, userinfo)
        if not _id_ok:
            logger.warning("[AUTH-VULN-04] Outlook identity rejected: %s", _id_reason)
            _capture_oauth_identity_rejection(
                provider="outlook",
                flow="callback",
                reason=_id_reason,
            )
            # Include the normalized reason key (stable, no PII, same set as
            # Sentry's `oauth.identity_reject_reason` tag) so the SPA can map
            # it to a user-actionable message instead of showing the opaque
            # `identity_invalid` literal (#557 follow-up).
            _reason_key = _outlook_identity_rejection_reason_key(_id_reason)
            # Also publish the rejection so the Tauri polling client (and
            # incognito web users whose postMessage is severed by COOP)
            # learn the error instead of hitting the 5-minute poll timeout.
            if state:
                with _pending_oauth_lock:
                    _pending_oauth_sessions[state] = {
                        "error": "identity_invalid",
                        "reason": _reason_key,
                        "timestamp": time.time(),
                    }
            return _redirect_oauth_completion(
                "outlook",
                state,
                client_type,
                error="identity_invalid",
                reason=_reason_key,
            )

        email = userinfo.get("mail") or userinfo.get("userPrincipalName", "")

        # 2026-06-02 #13: a custom-domain mailbox normally has `mail`
        # populated (alice@customdomain.com). When it is absent (mail-disabled /
        # unlicensed Entra identity) we fall back to the userPrincipalName, which
        # can be a non-routable alice@tenant.onmicrosoft.com — a valid account
        # key but a confusing reply-from address. Surface it for operators
        # instead of silently keying the account on it.
        if not userinfo.get("mail") and email.lower().endswith(".onmicrosoft.com"):
            logger.warning(
                "[OAUTH] Outlook identity has no `mail` attribute; keying account "
                "on userPrincipalName %s (likely mail-disabled/unlicensed Entra "
                "identity — reply-from address may be confusing)",
                email,
            )

        # F-08 (regression audit, 2026-04-29): compute user_id up front.
        _db_user_id = user_id_from_email(email)

        # Generate account_id from email hash for consistency
        account_id = hashlib.sha256(f"outlook:{email}".encode()).hexdigest()[:16]

        # Store tokens server-side
        if not store_tokens_server(account_id, "outlook", tokens, email):
            return _redirect_oauth_completion(
                "outlook", state, client_type, error="storage_failed"
            )

        # Create/update account in manager
        # Audit Cluster D (2026-05-17) B-07: previously a manager failure
        # only logged .error then fell through to issue a JWT + write a
        # session for polling. AccountManager-not-populated then breaks
        # `_resolve_account_id_for_email` for every subsequent request —
        # FE shows "logged in" but every mutation 403s. Treat manager
        # failure the same as storage failure and surface to the user.
        try:
            manager = get_account_manager()
            _sync_oauth_account_manager(
                manager,
                account_id=account_id,
                email=email,
                provider=ProviderType.OUTLOOK,
                user_id=_db_user_id,
                display_name=email.split("@")[0],
            )
        except Exception as e:
            logger.exception(f"Outlook OAuth callback: Account manager error for {email}: {e}")
            return _redirect_oauth_completion(
                "outlook", state, client_type, error="storage_failed"
            )

        # Create/update account in SQLite DB (needed for signature storage & sync).
        # Audit Cluster D (2026-05-17) B-01: previously a DB failure here was
        # only logged at .warning and the flow fell through to success — user
        # got a JWT but the sync service never saw the account, so inbox was
        # silently empty. Mirror the Gmail callback (PR #321 / issue #320):
        # retry on "database is locked", and on terminal failure redirect to
        # `&error=db_sync_failed` instead of pretending success.
        db_sync_failed = False
        db_sync_attempts = 3
        for attempt in range(1, db_sync_attempts + 1):
            try:
                from app.db.database import get_db_session
                from app.db.repositories.account_repository import AccountRepository
                with get_db_session() as session:
                    account_repo = AccountRepository(session)
                    db_account = account_repo.get_by_email(email)
                    if db_account:
                        db_account.is_active = True
                        db_account.access_token = tokens.get("access_token")
                        db_account.refresh_token = tokens.get("refresh_token")
                        if db_account.user_id != _db_user_id:
                            db_account.user_id = _db_user_id
                    else:
                        from app.db.models.account import Account as AccountModel
                        db_account = AccountModel(
                            email=email,
                            provider="outlook",
                            display_name=userinfo.get("displayName", email.split("@")[0]),
                            access_token=tokens.get("access_token"),
                            refresh_token=tokens.get("refresh_token"),
                            is_active=True,
                            user_id=_db_user_id,
                        )
                        session.add(db_account)
                    session.commit()
                    logger.info(f"DB account synced for {email} (user_id={_db_user_id})")
                    # ISO-12 symmetry (2026-04-24): same defense-in-depth as the Gmail
                    # callback. A fresh DB account_id was just minted (or reactivated)
                    # for this email — drop the resolver cache so the next JWT-routed
                    # request picks up the new id immediately instead of waiting 60s
                    # for the TTL to expire.
                    try:
                        from app.api.routes_helpers import _invalidate_account_id_cache
                        _invalidate_account_id_cache(email)
                    except Exception:
                        pass
                break
            except Exception as exc:
                is_locked = "database is locked" in str(exc).lower()
                if is_locked and attempt < db_sync_attempts:
                    delay = float(attempt)
                    logger.warning(
                        "Outlook OAuth callback: DB account sync locked for %s, retry %d/%d in %.1fs",
                        email, attempt, db_sync_attempts, delay,
                    )
                    _sleep_before_db_sync_retry(delay)
                    continue
                logger.exception("Outlook OAuth callback: DB account sync failed for %s", email)
                db_sync_failed = True
                break

        if not db_sync_failed:
            # Auto-import profile photo in background (best-effort, non-blocking)
            _at = tokens.get("access_token", "")
            _aid = account_id
            _em = email
            def _bg_import_outlook_avatar(_token=_at, _aid=_aid, _em=_em):
                try:
                    from app.api.accounts import fetch_and_store_provider_avatar, _persist_avatar_url
                    url = fetch_and_store_provider_avatar(_em, _token, "outlook", _aid)
                    if url:
                        _persist_avatar_url(_em, _aid, url)
                except Exception as _e:
                    logger.debug(f"[AVATAR] Auto-import Outlook failed: {_e}")
            import threading
            threading.Thread(target=_bg_import_outlook_avatar, daemon=True).start()

        if db_sync_failed:
            return _redirect_oauth_completion(
                "outlook",
                state,
                client_type,
                error="db_sync_failed",
                email=email,
            )

        # Generate JWT FIRST so the polling fallback can return it
        # (incognito popup → opener postMessage is severed by Google's COOP).
        _early_jwt: str | None = None
        try:
            from app.api.auth import _create_jwt as _jwt_make, _register_known_user as _jwt_reg
            _jwt_reg(email)
            _early_user_id = user_id_from_email(email)
            _early_jwt = _jwt_make(_early_user_id, email)
        except Exception as _e:
            logger.warning(f"Could not pre-generate JWT for poll session: {_e}")

        # Also store session for legacy polling flow (Tauri compatibility +
        # incognito web popup fallback when window.opener.postMessage is blocked).
        with _pending_oauth_lock:
            _pending_oauth_sessions[state] = {
                "tokens": tokens,
                "email": email,
                "account_id": account_id,
                "jwt": _early_jwt,
                "timestamp": time.time(),
            }

        # Fetch and store email signature from Outlook (skip if user has custom signature)
        try:
            _skip_signature = False
            try:
                from app.db.database import get_db_session as get_sig_check_session
                from app.db.models.account import Account as AccountModel
                with get_sig_check_session() as check_session:
                    existing_acc = check_session.query(AccountModel).filter_by(email=email).first()
                    if existing_acc and getattr(existing_acc, 'signature_user_modified', False):
                        _skip_signature = True
                        logger.info(f"Signature custom préservée pour {email} (user_modified=True)")
            except Exception as check_err:
                logger.warning(f"Could not check signature_user_modified: {check_err}")

            if not _skip_signature:
                from app.providers.outlook_adapter import OutlookAdapter
                from app.utils.signature import fetch_and_store_signature

                # Construct via the OAuth-web path (account_id) so the adapter
                # loads the just-stored server tokens (store_tokens_server ran
                # above at line ~1869) and builds a real Graph client through
                # authenticate(). The prior call passed
                # `OutlookAdapter(access_token=..., refresh_token=...)` — kwargs
                # the constructor does NOT accept (swallowed by **kwargs) — so
                # with no AZURE_* env it raised ValueError, caught by the except
                # below, making signature auto-import a silent no-op for every
                # web OAuth user. Forcing `_authenticated = True` afterwards
                # never helped because no `_client` was ever built.
                outlook_provider = OutlookAdapter(account_id=account_id)

                # Fetch and store signature (pass email for DB lookup since account_id is a string hash)
                fetch_and_store_signature(outlook_provider, account_id, email=email)

                # Sync signature back to AccountConfig (JSON) so frontend can read it
                try:
                    from app.db.database import get_db_session as get_sig_session
                    from app.db.models.account import Account as AccountModel
                    with get_sig_session() as sig_session:
                        db_acc = sig_session.query(AccountModel).filter_by(email=email).first()
                        if db_acc and (db_acc.signature_html or db_acc.signature_text):
                            sig_updates = {}
                            if db_acc.signature_text:
                                sig_updates["signature"] = db_acc.signature_text
                            if db_acc.signature_html:
                                sig_updates["signature_html"] = db_acc.signature_html
                            if sig_updates:
                                manager.update_account(account_id, **sig_updates)
                except Exception as sync_err:
                    logger.warning(f"Could not sync signature to AccountConfig: {sync_err}")

                logger.info(f"Outlook signature migrated for {email}")
        except Exception as sig_error:
            logger.warning(f"Could not migrate Outlook signature: {sig_error}")
            # Continue - signature is optional

        # Auto-import Microsoft profile photo (best-effort, User.Read scope covers this)
        try:
            from app.api.accounts import fetch_and_store_provider_avatar, _persist_avatar_url
            _avatar_url = fetch_and_store_provider_avatar(email, tokens.get("access_token", ""), "outlook", account_id)
            if _avatar_url:
                _persist_avatar_url(email, account_id, _avatar_url)
                logger.info(f"[AVATAR] Imported Outlook profile photo for {email}")
        except Exception as _av_e:
            logger.warning(f"[AVATAR] Outlook auto-import failed: {_av_e}")

        logger.info(f"Outlook OAuth successful for {email}")

        # FIX AUTH-004 (audit P1): do NOT pass the JWT in the redirect URL —
        # see the Gmail callback comment above. The frontend retrieves the
        # JWT via /session/<state>/poll (HTTPS body, not URL).
        return _redirect_oauth_completion(
            "outlook",
            state,
            client_type,
            success=True,
            email=email,
            account_id=account_id,
        )

    except Exception as e:
        logger.error(f"Outlook OAuth callback error: {e}")
        client_type = _oauth_client_type_for_state(state)
        return _redirect_oauth_completion(
            "outlook", state, client_type, error="server_error"
        )


# =============================================================================
# Token Management Endpoints
# =============================================================================


@oauth_bp.route("/tokens/<account_id>/status", methods=["GET"])
def get_token_status(account_id: str):
    """
    Vérifie l'état des tokens pour un compte.

    Returns:
        - has_tokens: bool
        - is_valid: bool (not expired)
        - email: str (if has_tokens)
        - provider: str (if has_tokens)
        - expires_in: int seconds (if has_tokens)
    ---
    tags:
      - OAuth
    summary: État des tokens d'un compte
    """
    token_data = get_tokens_server(account_id)

    if not token_data:
        return jsonify({
            "has_tokens": False,
            "is_valid": False,
        })

    # ISO-01: ownership check before exposing email/scopes/expiration.
    _denied = _check_token_ownership(account_id, token_data)
    if _denied is not None:
        return _denied

    # Check if tokens are expired (with 5 min buffer)
    expires_at = token_data.get("expires_at", 0)
    buffer = 5 * 60  # 5 minutes
    is_valid = time.time() < (expires_at - buffer)
    expires_in = max(0, int(expires_at - time.time()))

    # Parse scopes to determine capabilities
    scope_list = sorted(_oauth_scope_set(token_data))

    # Check for email capability (Gmail or Outlook)
    has_email = any(
        s in scope_list for s in [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://graph.microsoft.com/Mail.Read",
            "https://graph.microsoft.com/Mail.Send",
            "gmail.readonly",
            "gmail.send",
            "Mail.Read",
            "Mail.Send",
        ]
    )

    # Check for calendar capability
    has_calendar = any(
        s in scope_list for s in [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://graph.microsoft.com/Calendars.Read",
            "https://graph.microsoft.com/Calendars.ReadWrite",
            "calendar.readonly",
            "calendar.events",
            "Calendars.Read",
            "Calendars.ReadWrite",
        ]
    )

    return jsonify({
        "has_tokens": True,
        "is_valid": is_valid,
        "email": token_data.get("email"),
        "provider": token_data.get("provider"),
        "expires_in": expires_in,
        "has_email": has_email,
        "has_calendar": has_calendar,
        "scopes": scope_list,
    })


@oauth_bp.route("/tokens/<account_id>/readiness", methods=["GET"])
def get_token_readiness(account_id: str):
    """
    Vérifie que le compte OAuth possède toutes les permissions critiques.

    Le status brut dit seulement si un token existe et n'est pas expiré.
    Cette route protège le parcours utilisateur : si le provider a accepté
    une connexion partielle, l'app bloque l'entrée et demande une reconnexion
    avec toutes les autorisations.
    """
    token_data = get_tokens_server(account_id)
    if token_data:
        _denied = _check_token_ownership(account_id, token_data)
        if _denied is not None:
            return _denied

    return jsonify(_build_oauth_readiness(account_id, token_data))


@oauth_bp.route("/tokens/<account_id>/refresh", methods=["POST"])
def refresh_account_tokens(account_id: str):
    """
    Rafraîchit les tokens d'un compte.
    ---
    tags:
      - OAuth
    summary: Rafraîchir les tokens
    """
    token_data = get_tokens_server(account_id)

    if not token_data:
        return jsonify({"error": "No tokens found for account"}), 404

    # ISO-01: ownership check before honoring the refresh.
    _denied = _check_token_ownership(account_id, token_data)
    if _denied is not None:
        return _denied

    new_tokens = _refresh_tokens_server(account_id)

    if not new_tokens:
        return jsonify({"error": "Token refresh failed"}), 500

    return jsonify({
        "success": True,
        "expires_in": int(new_tokens.get("expires_at", 0) - time.time()),
    })


@oauth_bp.route("/tokens/<account_id>/access", methods=["GET"])
def get_access_token(account_id: str):
    """
    Récupère l'access token pour un compte (avec auto-refresh).

    ATTENTION: Cet endpoint est pour usage interne backend uniquement.
    Ne pas exposer directement aux clients web.
    ---
    tags:
      - OAuth
    summary: Récupérer l'access token (usage interne)
    """
    token_data = get_tokens_server(account_id)

    if not token_data:
        return jsonify({"error": "No tokens found for account"}), 404

    # ISO-01: ownership check — without this, an unauthenticated remote
    # attacker who guesses or sniffs an account_id can pull a live OAuth
    # access_token for the victim's mailbox.
    _denied = _check_token_ownership(account_id, token_data)
    if _denied is not None:
        return _denied

    # Check if refresh needed
    expires_at = token_data.get("expires_at", 0)
    buffer = 5 * 60  # 5 minutes

    if time.time() > (expires_at - buffer):
        token_data = _refresh_tokens_server(account_id)
        if not token_data:
            return jsonify({"error": "Token refresh failed"}), 500

    return jsonify({
        "access_token": token_data.get("access_token"),
        "expires_in": int(token_data.get("expires_at", 0) - time.time()),
    })


# =============================================================================
# Legacy Endpoints (Tauri compatibility)
# =============================================================================


def _cleanup_expired_sessions():
    """Remove expired OAuth sessions."""
    current_time = time.time()
    with _pending_oauth_lock:
        expired = [
            state for state, data in _pending_oauth_sessions.items()
            if current_time - data.get("timestamp", 0) > OAUTH_SESSION_TTL
        ]
        for state in expired:
            del _pending_oauth_sessions[state]




def _save_verifiers_to_file():
    """Persist PKCE verifiers to disk.

    Audit 2026-04-25 (sub-report 02 M-8): chmod 0o600 so other users on the
    same host cannot read in-flight PKCE verifiers (window <= 5 min, but
    sufficient to complete an OAuth dance with a stolen authorization code).

    FIX COMMIT-001 (audit P1): atomic write via tempfile + os.replace().
    The previous `open(_PKCE_FILE, "w")` truncated the file to 0 bytes
    BEFORE writing the new content. A sibling gunicorn worker calling
    `_lookup_verifier_with_disk_fallback` concurrently could open the
    truncated file mid-write and `json.load` raised JSONDecodeError —
    silently caught, returning None, falling to the localStorage path
    that breaks behind corporate proxies (M365 enterprise users).
    Atomic replace guarantees the reader sees either the previous
    complete file or the new complete file, never a partial state.
    """
    import tempfile
    try:
        _ensure_data_dir()
        dir_ = os.path.dirname(_PKCE_FILE) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".pkce-", suffix=".tmp", dir=dir_)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(_pending_code_verifiers, f)
            os.replace(tmp_path, _PKCE_FILE)
            try:
                import stat
                os.chmod(_PKCE_FILE, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass  # Windows — limited chmod support
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.warning(f"Failed to save PKCE verifiers: {e}")


def _cleanup_expired_verifiers():
    """Remove expired code verifiers."""
    current_time = time.time()
    with _code_verifier_lock:
        expired = [
            state for state, data in _pending_code_verifiers.items()
            if current_time - data.get("timestamp", 0) > OAUTH_SESSION_TTL
        ]
        for state in expired:
            del _pending_code_verifiers[state]
        if expired:
            _save_verifiers_to_file()


def _state_fingerprint_from_request() -> str:
    """
    Compute the initiator fingerprint for the current request.

    AUTH-VULN-01 (issue #557): we hash IP + User-Agent so the value is
    safe to log and stable across the brief OAuth window. We tolerate IP
    drift only as far as the /24 prefix (mobile networks change last
    octet on cell handover; corporate proxies pool addresses).
    """
    ip = (request.remote_addr or "").strip()
    # Reduce IPv4 to /24, IPv6 to /48 — keeps mobile carriers stable enough
    # to avoid false-rejects without weakening cross-network protection.
    ip_prefix = ip
    try:
        import ipaddress as _ip
        addr = _ip.ip_address(ip)
        if isinstance(addr, _ip.IPv4Address):
            ip_prefix = str(_ip.ip_network(f"{ip}/24", strict=False).network_address)
        elif isinstance(addr, _ip.IPv6Address):
            ip_prefix = str(_ip.ip_network(f"{ip}/48", strict=False).network_address)
    except (ValueError, TypeError):
        pass

    ua = request.headers.get("User-Agent", "")[:512]
    raw = f"{ip_prefix}|{ua}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cleanup_expired_state_fingerprints():
    """Remove expired state→fingerprint bindings."""
    current_time = time.time()
    with _state_fingerprint_lock:
        expired = [
            state for state, data in _state_fingerprints.items()
            if current_time - data.get("timestamp", 0) > OAUTH_SESSION_TTL
        ]
        for state in expired:
            del _state_fingerprints[state]


def _record_state_fingerprint(state: str) -> None:
    """Bind the state to the current request's fingerprint (idempotent)."""
    fp = _state_fingerprint_from_request()
    with _state_fingerprint_lock:
        # FIFO cap mirrored on _pending_code_verifiers to bound memory.
        if len(_state_fingerprints) >= _OAUTH_PENDING_MAX:
            try:
                oldest_key = next(iter(_state_fingerprints))
                _state_fingerprints.pop(oldest_key, None)
            except StopIteration:
                pass
        _state_fingerprints[state] = {
            "fingerprint": fp,
            "timestamp": time.time(),
        }


def _verify_state_fingerprint(state: str) -> tuple[bool, str]:
    """
    Verify the current request's fingerprint matches the one bound to `state`.

    Returns:
        (ok, reason). ok=True means the caller is the same agent that
        called /pkce/store (same /24 IP + UA). On miss we treat it as
        "unbound" — older clients may not have stored a fingerprint, so we
        return ok=True with reason="unbound" and let the caller decide
        whether to allow or warn.
    """
    _cleanup_expired_state_fingerprints()
    with _state_fingerprint_lock:
        bound = _state_fingerprints.get(state)
    if not bound:
        return True, "unbound"
    expected = bound.get("fingerprint")
    actual = _state_fingerprint_from_request()
    if expected and hmac.compare_digest(str(expected), str(actual)):
        return True, "match"
    return False, "mismatch"


@oauth_bp.route("/pkce/store", methods=["POST"])
def store_code_verifier():
    """
    Store PKCE code verifier for OAuth flow.

    The frontend calls this to store the code_verifier before opening
    the OAuth consent page. The backend retrieves it during callback.

    Audit follow-up 2026-04-29 (P1 punch-list): per-IP rate limit so an
    attacker can't flood ``_pending_code_verifiers`` and FIFO-evict
    legitimate users mid-flow. The global ``_OAUTH_PENDING_MAX`` cap is
    kept as defense-in-depth.
    ---
    tags:
      - OAuth
    summary: Store PKCE code verifier
    """
    # Per-IP rate limit (audit 2026-04-29): 20 stores per minute per IP.
    # Legitimate OAuth flows do 1-2 stores per minute (initial + retry on
    # cancel) — 20/min is generous. Attacker flood becomes ~1k/hour/IP
    # which the FIFO cap of 10k absorbs without evicting recent legit
    # users (assuming <10 attackers in the same minute).
    from app.api.routes_helpers import _rate_limited
    _ip = (request.remote_addr or "unknown").strip()
    _allowed, _retry = _rate_limited(
        f"pkce_store:{_ip}", max_calls=20, window_seconds=60
    )
    if not _allowed:
        logger.warning("[PKCE-DoS] /pkce/store rate-limited for ip=%s", _ip)
        return jsonify({"error": "rate limit exceeded", "retry_after": _retry}), 429

    _cleanup_expired_verifiers()

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    state = data.get("state")
    code_verifier = data.get("code_verifier")
    client_type = data.get("client_type")

    if not state or not code_verifier:
        return jsonify({"error": "state and code_verifier are required"}), 400

    # Audit 2026-04-25 (sub-report 01 HIGH-05): basic shape check + length
    # cap so a malicious caller can't store huge values.
    if not isinstance(state, str) or not isinstance(code_verifier, str):
        return jsonify({"error": "state and code_verifier must be strings"}), 400
    if client_type is not None and not isinstance(client_type, str):
        return jsonify({"error": "client_type must be a string"}), 400
    if len(state) > 256 or len(code_verifier) > 1024:
        return jsonify({"error": "state or code_verifier exceeds maximum length"}), 400
    if client_type and len(client_type) > 32:
        return jsonify({"error": "client_type exceeds maximum length"}), 400

    with _code_verifier_lock:
        # FIFO eviction guard (sub-report 01 LOW-02): if the dict is at the
        # cap, drop the oldest entry. We use insertion order which is
        # deterministic in Python 3.7+.
        if len(_pending_code_verifiers) >= _OAUTH_PENDING_MAX:
            try:
                oldest_key = next(iter(_pending_code_verifiers))
                _pending_code_verifiers.pop(oldest_key, None)
            except StopIteration:
                pass
        _pending_code_verifiers[state] = {
            "code_verifier": code_verifier,
            "client_type": "mobile" if client_type == "mobile" else "web",
            "timestamp": time.time(),
        }
        _save_verifiers_to_file()

    # AUTH-VULN-01 (issue #557): bind state to the initiator's IP/24 + UA so
    # that /session/<state>/poll later refuses callers who learned the state
    # from URL bar / Referer / access logs.
    _record_state_fingerprint(state)

    logger.info(f"PKCE code verifier stored for state: {state[:8]}...")
    return jsonify({"success": True})


@oauth_bp.route("/pkce/<state>", methods=["GET"])
def get_code_verifier(state: str):
    """
    Retrieve PKCE code verifier.

    NOTE: This endpoint is kept for backward compatibility but
    the server now uses the verifier directly in the callback.
    ---
    tags:
      - OAuth
    summary: Get PKCE code verifier (legacy)
    """
    _cleanup_expired_verifiers()

    # FIX AUTH-002 (audit P0): single-use semantics. The previous "keep for
    # retry" behavior let an attacker who observed the `state` value (URL
    # bar / Referer / access logs during the OAuth dance) read the verifier
    # for the full 5-minute TTL and race the victim's callback to steal the
    # auth code. Pop on first read + persist deletion to the disk fallback
    # so other gunicorn workers don't serve a stale copy.
    with _code_verifier_lock:
        data = _pending_code_verifiers.pop(state, None)
        if data is not None:
            try:
                _save_verifiers_to_file()
            except Exception:
                logger.exception("get_code_verifier: persist after pop failed")

    if not data:
        return jsonify({"error": "Code verifier not found"}), 404

    return jsonify({"code_verifier": data["code_verifier"]})


@oauth_bp.route("/session/store", methods=["POST"])
def store_oauth_session():
    """
    Store OAuth result for polling by Tauri app.

    NOTE: This endpoint is kept for backward compatibility.
    The new flow stores tokens server-side automatically.
    ---
    tags:
      - OAuth
    summary: Store OAuth session result (legacy)
    """
    _cleanup_expired_sessions()

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    state = data.get("state")
    if not state:
        return jsonify({"error": "state is required"}), 400

    # Audit 2026-04-25 (sub-report 01 HIGH-05): shape + length cap.
    if not isinstance(state, str) or len(state) > 256:
        return jsonify({"error": "state must be a string <= 256 chars"}), 400

    with _pending_oauth_lock:
        # FIFO eviction guard.
        if len(_pending_oauth_sessions) >= _OAUTH_PENDING_MAX:
            try:
                oldest_key = next(iter(_pending_oauth_sessions))
                _pending_oauth_sessions.pop(oldest_key, None)
            except StopIteration:
                pass
        _pending_oauth_sessions[state] = {
            "tokens": data.get("tokens"),
            "email": data.get("email"),
            "error": data.get("error"),
            "timestamp": time.time(),
        }

    logger.info(f"OAuth session stored for state: {state[:8]}...")
    return jsonify({"success": True, "message": "Session stored"})


@oauth_bp.route("/session/<state>/poll", methods=["GET"])
def poll_oauth_session(state: str):
    """
    Poll for OAuth result.

    The Tauri app calls this to check if the OAuth flow has completed.

    AUTH-VULN-01 (Shannon pentest 2026-05-05, issue #557): the JWT used to
    leak to anyone who knew `state` (URL bar, Referer, access logs). We now
    bind state→fingerprint at /pkce/store and refuse polls from a different
    initiator. Mismatch returns 403 — the legitimate frontend will retry
    with the same fingerprint, an attacker won't.
    ---
    tags:
      - OAuth
    summary: Poll OAuth session result
    """
    _cleanup_expired_sessions()

    # Per-IP rate limit on polls — defense-in-depth alongside the fingerprint
    # check. An attacker farming many states can't burn through them via
    # parallel polls.
    from app.api.routes_helpers import _rate_limited
    _ip = (request.remote_addr or "unknown").strip()
    _allowed, _retry = _rate_limited(
        f"oauth_poll:{_ip}", max_calls=120, window_seconds=60
    )
    if not _allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": _retry}), 429

    # AUTH-VULN-01: refuse if the caller's fingerprint differs from the one
    # bound at /pkce/store. Returning 404-shaped response avoids confirming
    # whether `state` is known to the server (anti-enumeration).
    fp_ok, fp_reason = _verify_state_fingerprint(state)
    if not fp_ok:
        logger.warning(
            "OAuth poll fingerprint mismatch for state=%s... — refusing",
            state[:8] if state else "?",
        )
        return jsonify({"status": "pending"}), 200

    with _pending_oauth_lock:
        session = _pending_oauth_sessions.get(state)
        if not session:
            # "pending" is the correct semantic for a session still being built —
            # 404 was polluting the browser console with [ERROR] every 2s until the
            # user completed the OAuth consent. Return 200 + status=pending so the
            # polling loop stays quiet and the frontend knows to keep waiting.
            return jsonify({"status": "pending"}), 200

        # Remove session after retrieval (one-time use)
        del _pending_oauth_sessions[state]
    # Drop the fingerprint binding now that the state has been consumed.
    with _state_fingerprint_lock:
        _state_fingerprints.pop(state, None)

    if session.get("error"):
        # Surface `reason` alongside the error code so the SPA can humanize
        # identity_invalid sub-cases (id_token_absent triggers a stale-bundle
        # auto-recovery; the others map to user-actionable hints — #557).
        return jsonify({
            "status": "error",
            "error": session["error"],
            "reason": session.get("reason"),
        })

    # FIX AUTH-001 (audit P0): never return raw OAuth access/refresh tokens
    # over this endpoint — it is in `public_endpoints` (no auth guard) and
    # anyone who observes the 32-hex `state` (URL bar, Referer, access logs)
    # could otherwise harvest a live mailbox token pair. The JWT below is
    # sufficient for the frontend; the raw tokens stay server-side and are
    # accessed via the auth-guarded /api/oauth/tokens/* endpoints.
    return jsonify({
        "status": "success",
        "email": session.get("email"),
        "account_id": session.get("account_id"),
        # JWT included so the parent window can authenticate without depending
        # on the popup's localStorage write propagating to the opener — that
        # propagation is blocked in incognito when COOP severs the opener
        # relationship between popup and parent.
        "token": session.get("jwt"),
        # B-03: surfaced by the /complete routes when the accounts-DB write
        # failed (famille #320). Default True for sessions written by paths
        # that don't track it.
        "db_synced": session.get("db_synced", True),
    })


@oauth_bp.route("/outlook/complete", methods=["POST"])
def complete_outlook_oauth():
    """
    Échange le code OAuth Outlook contre des tokens côté serveur.

    Appelé par OAuthCallback.tsx quand Microsoft redirige directement vers le frontend
    (flow SPA découplé). Le code_verifier peut venir du body (localStorage du frontend)
    ou du store backend (fallback).
    ---
    tags:
      - OAuth
    summary: Complétion OAuth Outlook (échange code → token via POST)
    """
    data = request.get_json() or {}
    code = (data.get("code") or "").strip()
    state = (data.get("state") or "").strip()
    code_verifier = (data.get("code_verifier") or "").strip()
    redirect_uri = (data.get("redirect_uri") or MICROSOFT_REDIRECT_URI).strip()

    if not code:
        return jsonify({"error": "code manquant"}), 400

    if not code_verifier:
        # Fallback : chercher dans le store backend.
        # Multi-worker safety: fall back to disk if the in-memory dict misses
        # (e.g. /pkce/store was served by a different gunicorn worker).
        _cleanup_expired_verifiers()
        verifier_data = _lookup_verifier_with_disk_fallback(state) or {}
        code_verifier = verifier_data.get("code_verifier", "")
        if code_verifier:
            with _code_verifier_lock:
                _pending_code_verifiers.pop(state, None)
                _save_verifiers_to_file()

    if not code_verifier:
        return jsonify({"error": "code_verifier manquant"}), 400

    try:
        # Échange code → tokens côté serveur.
        # Toutes les redirect URIs doivent être enregistrées comme "Web" dans Azure
        # Portal (pas "SPA") car l'échange se fait serveur-à-serveur sans header Origin.
        token_data = {
            "client_id": MICROSOFT_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if MICROSOFT_CLIENT_SECRET:
            token_data["client_secret"] = MICROSOFT_CLIENT_SECRET

        token_response = requests.post(MICROSOFT_TOKEN_URL, data=token_data, timeout=_HTTP_TIMEOUT)

        if not token_response.ok:
            try:
                error_data = token_response.json()
            except Exception:
                error_data = {}
            # F-05 (regression audit, 2026-04-29): see Gmail variant above.
            safe_code, retry_id = _safe_oauth_error(error_data, provider="outlook")
            logger.error(
                "Outlook complete token exchange failed: status=%d code=%s retry_id=%s "
                "code_len=%d verifier_len=%d",
                token_response.status_code, safe_code, retry_id,
                len(code), len(code_verifier),
            )
            return jsonify({"error": safe_code, "retry_id": retry_id}), 400

        tokens = token_response.json()

        # Récupérer l'email de l'utilisateur
        userinfo_response = requests.get(MICROSOFT_USERINFO_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        }, timeout=_HTTP_TIMEOUT)
        if not userinfo_response.ok:
            return jsonify({"error": "userinfo_failed"}), 400

        userinfo = userinfo_response.json()

        # AUTH-VULN-04 (issue #557): nOAuth defense — same as the redirect
        # callback path above.
        _id_ok, _id_reason = _validate_outlook_identity(tokens, userinfo)
        if not _id_ok:
            logger.warning("[AUTH-VULN-04] Outlook identity rejected: %s", _id_reason)
            _capture_oauth_identity_rejection(
                provider="outlook",
                flow="complete",
                reason=_id_reason,
            )
            _reason_key = _outlook_identity_rejection_reason_key(_id_reason)
            # Also publish the rejection to the polling endpoint so an
            # incognito web user whose `postMessage` was severed by COOP
            # (the popup-fallback path) doesn't sit on a 5-minute spinner
            # before timing out. The poll endpoint will surface the same
            # error code + reason, letting the SPA auto-recover from
            # stale-bundle cases.
            if state:
                with _pending_oauth_lock:
                    _pending_oauth_sessions[state] = {
                        "error": "identity_invalid",
                        "reason": _reason_key,
                        "timestamp": time.time(),
                    }
            # Return the normalized reason key (same set as Sentry's
            # `oauth.identity_reject_reason` tag) so the SPA can map it to a
            # user-actionable message. The raw French reason is unsafe to
            # surface verbatim and the SPA can't switch on it.
            return jsonify({
                "error": "identity_invalid",
                "reason": _reason_key,
            }), 400

        email = userinfo.get("mail") or userinfo.get("userPrincipalName", "")
        account_id = hashlib.sha256(f"outlook:{email}".encode()).hexdigest()[:16]

        # F-08 (regression audit, 2026-04-29): compute user_id up front.
        _db_user_id = user_id_from_email(email)

        # Stocker les tokens côté serveur
        if not store_tokens_server(account_id, "outlook", tokens, email):
            return jsonify({"error": "storage_failed"}), 500

        # Créer/mettre à jour le compte dans le manager
        # Audit regressions (2026-05-18 batch5) F-05: same defect as F-01 at
        # this Tauri/desktop-complete endpoint for Outlook. Manager error must
        # surface as storage_failed (500) — see Gmail callback fix at l.1212.
        try:
            manager = get_account_manager()
            _sync_oauth_account_manager(
                manager,
                account_id=account_id,
                email=email,
                provider=ProviderType.OUTLOOK,
                user_id=_db_user_id,
                display_name=email.split("@")[0],
            )
        except Exception as e:
            logger.exception(f"Outlook OAuth complete: Account manager error for {email}: {e}")
            return jsonify({"error": "storage_failed"}), 500

        # Synchroniser avec la DB SQLite — bake the user_id for multi-user isolation.
        # B-03 (famille #320, audit 2026-06-11): même traitement que
        # gmail/complete — l'échec de sync DB est propagé via db_synced=false
        # au lieu d'être avalé pendant que le flow retourne succès.
        db_synced = True
        try:
            from app.db.database import get_db_session
            from app.db.repositories.account_repository import AccountRepository
            with get_db_session() as session:
                account_repo = AccountRepository(session)
                db_account = account_repo.get_by_email(email)
                if db_account:
                    db_account.is_active = True
                    db_account.access_token = tokens.get("access_token")
                    db_account.refresh_token = tokens.get("refresh_token")
                    if db_account.user_id != _db_user_id:
                        db_account.user_id = _db_user_id
                else:
                    from app.db.models.account import Account as AccountModel
                    db_account = AccountModel(
                        email=email,
                        provider="outlook",
                        display_name=userinfo.get("displayName", email.split("@")[0]),
                        access_token=tokens.get("access_token"),
                        refresh_token=tokens.get("refresh_token"),
                        is_active=True,
                        user_id=_db_user_id,
                    )
                    session.add(db_account)
                session.commit()
                logger.info(f"DB account synced in outlook/complete for {email} (user_id={_db_user_id})")
                # ISO-12 symmetry (2026-04-24): same defense-in-depth as Gmail
                # and outlook/callback. Drop resolver cache after fresh DB write.
                try:
                    from app.api.routes_helpers import _invalidate_account_id_cache
                    _invalidate_account_id_cache(email)
                except Exception:
                    pass
        except Exception:
            db_synced = False
            logger.error(
                "Could not sync DB account in outlook/complete for %s",
                email, exc_info=True,
            )

        # Generate JWT FIRST so we can include it in the polling session payload
        # (poll fallback for incognito popups where postMessage to opener is COOP-blocked).
        token_jwt = None
        try:
            from app.api.auth import _create_jwt, _register_known_user
            _register_known_user(email)
            user_id = user_id_from_email(email)
            token_jwt = _create_jwt(user_id, email)
        except Exception as jwt_err:
            logger.warning(f"Could not generate JWT in outlook/complete: {jwt_err}")

        # Stocker la session pour le polling Tauri (compatibilité) +
        # incognito web popup fallback (postMessage may be severed by COOP).
        if state:
            with _pending_oauth_lock:
                _pending_oauth_sessions[state] = {
                    "tokens": tokens,
                    "email": email,
                    "account_id": account_id,
                    "jwt": token_jwt,
                    "db_synced": db_synced,
                    "timestamp": time.time(),
                }

        logger.info(f"Outlook OAuth complete successful for {email}")
        return jsonify({
            "success": True,
            "email": email,
            "account_id": account_id,
            "token": token_jwt,
            "db_synced": db_synced,
        })

    except Exception as e:
        logger.error(f"Error in outlook/complete: {e}")
        return jsonify({"error": str(e)}), 500


@oauth_bp.route("/<account_id>/disconnect", methods=["POST"])
def disconnect_account(account_id: str):
    """
    Déconnecte un compte OAuth.
    ---
    tags:
      - OAuth
    summary: Déconnecte un compte
    """
    # Audit 2026-04-25 (P0-2 / sub-report 02 C-1): the sibling token endpoints
    # (status/refresh/access) call _check_token_ownership before reading tokens.
    # disconnect_account previously deleted the tokens FIRST and only checked
    # account existence after, so any authenticated user could wipe another
    # user's OAuth state by guessing the 16-hex account_id (or seeing it in a
    # screenshot / log). Resolve ownership BEFORE any mutation.
    token_data = get_tokens_server(account_id)
    if token_data:
        _denied = _check_token_ownership(account_id, token_data)
        if _denied is not None:
            return _denied
    else:
        # No tokens — still ensure the JWT caller owns the underlying account
        # before we flip its status. We cannot compare emails (no token row),
        # so fall back to the AccountManager email metadata.
        manager = get_account_manager()
        account = manager.get_account(account_id)
        if not account:
            # Don't disclose existence — same envelope as ownership-mismatch.
            return jsonify({"error": "Account not found"}), 404
        from app.api.auth import is_trusted_loopback
        auth_user = getattr(g, "auth_user", None)
        if not (is_trusted_loopback() and auth_user is None):
            if not auth_user or not auth_user.get("email"):
                return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
            stored_email = (getattr(account, "email", "") or "").lower()
            caller_email = (auth_user.get("email") or "").lower()
            if not stored_email or stored_email != caller_email:
                logger.warning(
                    "[OAuth] Cross-user disconnect blocked: caller=%s stored=%s account=%s",
                    caller_email or "<empty>", stored_email or "<empty>", account_id,
                )
                return jsonify({"error": "Account not found"}), 404

    # FIX MIGRATE-002 (audit P0): revoke at provider before removing the
    # local token. token_data is already loaded above for ownership check.
    if token_data:
        try:
            revoke_token_at_provider(token_data)
        except Exception as e:
            logger.warning(f"[DISCONNECT] provider-side revoke failed for {account_id}: {e}")

    # Delete tokens from server storage (idempotent)
    delete_tokens_server(account_id)

    manager = get_account_manager()
    account = manager.get_account(account_id)

    if not account:
        return jsonify({"error": "Account not found"}), 404

    # Update status to inactive
    manager.update_account_status(account_id, AccountStatus.INACTIVE)

    # FIX MIGRATE-005 (audit P1): also reset SQLite-side state. Without
    # this, `Account.is_active=True` persists → sync_service keeps
    # polling a token-less account every 2 min (auth-backoff burn + log
    # spam), AND `last_history_id` from the disconnected session is
    # replayed on the next reconnect, producing historyExpired and
    # phantom email_labels rows pointing at GC'd email_ids.
    db_acct_id: int | None = None
    try:
        from app.db.database import get_db_session
        from app.db.models.account import Account
        with get_db_session() as session:
            db_acct = (
                session.query(Account)
                .filter(Account.email.ilike(account.email))
                .first()
            )
            if db_acct is not None:
                db_acct.is_active = False
                db_acct.last_history_id = None
                session.commit()
                db_acct_id = db_acct.id
                logger.info(
                    f"[DISCONNECT] reset SQLite state for {account.email} "
                    f"(db_id={db_acct.id})"
                )
    except Exception as e:
        logger.warning(f"[DISCONNECT] SQLite cleanup failed for {account_id}: {e}")

    # Drop any auth-backoff entry to avoid spurious cooldown logs.
    try:
        from app.services.sync_service import get_sync_service
        svc = get_sync_service()
        if svc is not None and hasattr(svc, "evict_auth_backoff"):
            svc.evict_auth_backoff(account_id)
    except Exception as e:
        logger.debug(f"[DISCONNECT] evict_auth_backoff skipped: {e}")

    # Drop cached contact-photo bytes for this account so a re-connect under
    # a different identity can't surface the previous owner's avatars.
    try:
        from app.services.contact_avatar_service import invalidate_cache as _avatar_invalidate
        if db_acct_id is not None:
            _avatar_invalidate(db_acct_id)
    except Exception as e:
        logger.debug(f"[DISCONNECT] avatar cache evict skipped: {e}")

    logger.info(f"Account {account_id} disconnected")
    return jsonify({
        "success": True,
        "message": "Account disconnected",
        "account_id": account_id,
    })
