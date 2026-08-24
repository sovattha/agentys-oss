# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Auth API Blueprint — Magic Link + JWT authentication.

Endpoints:
  POST /api/auth/request-magic-link  — envoie un magic link via Resend
  POST /api/auth/verify              — échange un magic token contre un JWT
  GET  /api/auth/me                  — retourne l'utilisateur courant (JWT requis)
"""

import hashlib
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from functools import wraps

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import jwt
from flask import Blueprint, request, jsonify, g

from app.account_identity import user_id_from_email as _canonical_user_id_from_email
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# JWT secret — en production utiliser une variable d'env
_DEFAULT_DEV_JWT_SECRET = "agentys-dev-secret-change-in-prod"  # nosec B105 — explicit dev sentinel
JWT_SECRET = os.environ.get("JWT_SECRET", _DEFAULT_DEV_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 jours

# Audit 2026-04-25 (P0-1): centralized prod detection + denylist of weak
# defaults. Same hardening as `_validate_prod_oauth_secret` in oauth.py.
from app.api._auth_helpers import is_production as _is_production
_is_production_env = _is_production()
if _is_production_env:
    from app.api.oauth import WEAK_DEFAULT_SECRETS as _WEAK_SECRETS
    _normalized_jwt = (JWT_SECRET or "").strip().lower()
    if not JWT_SECRET:
        raise RuntimeError(
            "[SECURITY] JWT_SECRET is unset in a production environment. "
            "Set JWT_SECRET to a secure random string."
        )
    if _normalized_jwt in _WEAK_SECRETS or _normalized_jwt.startswith("agentys-dev-"):
        raise RuntimeError(
            "[SECURITY] JWT_SECRET is a known placeholder default. "
            "Refusing to start. Generate a fresh value via "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
        )
    if len(JWT_SECRET) < 32:
        raise RuntimeError(
            "[SECURITY] JWT_SECRET must be >= 32 chars in production."
        )

# F-13 (audit issue #209, 2026-04-29): defense-in-depth against CSRF
# on auth endpoints. SESSION_COOKIE_SAMESITE=Lax permits top-nav cross-site
# POSTs, so a sibling-subdomain attacker page could trigger /request-magic-link
# or /oauth-login bound to the victim's session cookie. Even though /verify
# still requires the email-delivered token, the noise + log pollution + magic
# link enumeration is a real abuse path.
#
# Approach: require Origin or Referer header on POST auth endpoints to match
# an allow-list. Loopback callers (Tauri desktop) and missing Origin (curl /
# server-to-server) are still allowed in non-prod. In prod, an allow-list miss
# returns 403.
_ALLOWED_ORIGINS_ENV = "ALLOWED_AUTH_ORIGINS"


def _trusted_auth_origin() -> bool:
    """Return True if the inbound request's Origin/Referer is on the
    allow-list (or there's no Origin header, e.g. curl/Tauri/desktop)."""
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()

    # No Origin header — happens for non-browser callers (curl, Tauri,
    # mobile native HTTP). Allow; the JWT/magic-link flow is still
    # protected by the token itself. Browsers always set Origin on
    # cross-origin POSTs.
    if not origin and not referer:
        return True

    allowed_csv = os.environ.get(_ALLOWED_ORIGINS_ENV, "")
    allowed = {o.strip().rstrip("/") for o in allowed_csv.split(",") if o.strip()}

    # Default-allow these in non-prod even without env var.
    if not _is_production_env:
        allowed.update({
            "http://localhost:1420",  # Tauri dev
            "http://localhost:5173",  # Vite dev
            "http://localhost:5050",  # Backend dev
            "http://127.0.0.1:1420",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5050",
        })

    if not allowed:
        # Allow-list unset in prod = mis-config. Don't lock everyone
        # out; log loudly so ops sees it.
        logger.error(
            "[F-13] %s unset in production; auth Origin check disabled. "
            "Set %s=https://app.agentys.io,https://www.agentys.io to enable.",
            _ALLOWED_ORIGINS_ENV, _ALLOWED_ORIGINS_ENV,
        )
        return True

    candidate = origin or referer
    candidate = candidate.rstrip("/")
    # Match exact origin or scheme+host of referer.
    for allowed_origin in allowed:
        if candidate == allowed_origin:
            return True
        if candidate.startswith(allowed_origin + "/"):
            return True
    return False


# In-memory store for magic link tokens (dev only — production uses DB/Redis)
# Format: { token: { email, created_at } }
_magic_tokens: dict[str, dict] = {}
_magic_tokens_lock = threading.Lock()
MAGIC_LINK_TTL = 10 * 60  # 10 minutes (CASA SAQ #24 — OOB verifier max 10 min)

# Cache of already-verified tokens → JWT response (grace period for page reloads)
# Format: { token: { response_json, verified_at } }
_verified_cache: dict[str, dict] = {}
_VERIFIED_GRACE_SECONDS = 60  # allow re-verify within 60s

# SMTP config for magic link emails (reuses existing SMTP credentials from .env)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "") or SMTP_USER
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Agentys")


def _send_magic_link_email(to_email: str, magic_url: str) -> bool:
    """Envoie le magic link par email via SMTP."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("[AUTH] SMTP non configuré, email non envoyé")
        return False

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
      <div style="text-align: center; margin-bottom: 32px;">
        <svg width="48" height="48" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 2.5L1.5 29.5h29L16 2.5z" stroke="#2dd4bf" stroke-width="2" stroke-linejoin="round" fill="none" opacity="0.7"/>
          <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
        </svg>
        <h1 style="color: #1a1a2e; font-size: 24px; margin: 16px 0 8px;">Agentys</h1>
      </div>
      <p style="color: #555; font-size: 15px; line-height: 1.6;">
        Cliquez sur le bouton ci-dessous pour vous connecter à votre compte Agentys.
        Ce lien est valable 15 minutes.
      </p>
      <div style="text-align: center; margin: 32px 0;">
        <a href="{magic_url}"
           style="display: inline-block; padding: 12px 32px; background: #0d9488; color: #fff;
                  text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px;">
          Se connecter
        </a>
      </div>
      <p style="color: #999; font-size: 12px; line-height: 1.5;">
        Si vous n'avez pas demandé ce lien, ignorez cet email.<br>
        <a href="{magic_url}" style="color: #999; word-break: break-all;">{magic_url}</a>
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Votre lien de connexion Agentys"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, [to_email], msg.as_string())
        server.quit()
        logger.info(f"[AUTH] Email envoyé à {to_email} via SMTP")
        return True
    except Exception as e:
        logger.error(f"[AUTH] Erreur SMTP pour {to_email}: {e}")
        return False


# Audit 2026-04-29 (P1-005 follow-up of TODO LOW-03): widened the user_id
# hash from `% 100000` (~17 bits, birthday collision ~316 users) to the
# full 32-bit space derived from sha256[:8]. Birthday collision now ~65k
# users — gives multi-tenant prod the headroom needed. Use the helper
# below as the SINGLE source so no future caller can drift back to mod
# 100000. The User-table migration that would make this fully unique is
# out of scope here; this is the cheap intermediate.
def user_id_from_email(email: str) -> int:
    """Compatibility wrapper for the canonical account identity helper."""
    return _canonical_user_id_from_email(email)


# AUTH-VULN-03 (Shannon pentest 2026-05-05, issue #557): in-memory JWT
# revocation blocklist. Maps jti → exp_timestamp. Pruned lazily on each
# decode to bound memory. Persisted to disk so a backend restart doesn't
# silently un-revoke tokens (a 7-day window is plenty for an attacker to
# notice and resume use).
#
# Note for Codex / senior dev review: yes, a single-process in-memory
# blocklist is racy across multi-worker gunicorn deploys. We persist to
# disk on every revoke and reload on startup; concurrent workers re-read
# on each decode via a 5-second mtime check, which is fast enough that
# the worst case is a sub-second window where a second worker still
# accepts a freshly-revoked token. Migration path: Redis. Out of scope
# here because the alternative (do nothing) leaves stolen JWTs valid for
# 7 days with NO recourse — a strictly worse posture.
_revoked_jtis: dict[str, float] = {}
_revoked_jtis_lock = threading.Lock()
_revoked_jtis_mtime: float = 0.0


def _revoked_jtis_file_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data",
        "revoked_jtis.json",
    )


def _prune_revoked_jtis_locked() -> None:
    """Drop expired entries. Caller MUST hold _revoked_jtis_lock."""
    now = time.time()
    expired = [jti for jti, exp in _revoked_jtis.items() if exp <= now]
    for jti in expired:
        _revoked_jtis.pop(jti, None)


def _load_revoked_jtis() -> None:
    """Reload blocklist from disk if the file changed. Idempotent."""
    global _revoked_jtis_mtime
    path = _revoked_jtis_file_path()
    if not os.path.exists(path):
        return
    try:
        mtime = os.path.getmtime(path)
        if mtime <= _revoked_jtis_mtime:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        with _revoked_jtis_lock:
            _revoked_jtis.clear()
            _revoked_jtis.update({str(k): float(v) for k, v in data.items()})
            _prune_revoked_jtis_locked()
        _revoked_jtis_mtime = mtime
    except (json.JSONDecodeError, IOError, OSError, ValueError):
        # Corruption is non-fatal — worst case we lose the blocklist
        # contents. Log loudly via the standard logger (not silent).
        logger.warning("[AUTH] _load_revoked_jtis: failed to load from %s", path)


def _persist_revoked_jtis_locked() -> None:
    """Persist blocklist to disk. Caller MUST hold _revoked_jtis_lock."""
    global _revoked_jtis_mtime
    path = _revoked_jtis_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Atomic write so a sibling worker reading mid-write sees either
        # the previous complete file or the new complete file.
        import tempfile as _tf
        fd, tmp_path = _tf.mkstemp(prefix=".rj-", suffix=".tmp", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_revoked_jtis, f)
            os.replace(tmp_path, path)
            _revoked_jtis_mtime = os.path.getmtime(path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (IOError, OSError):
        logger.warning("[AUTH] _persist_revoked_jtis: failed to write %s", path)


def revoke_jti(jti: str, exp: float) -> None:
    """Add a jti to the revocation blocklist until its natural expiry."""
    with _revoked_jtis_lock:
        _prune_revoked_jtis_locked()
        _revoked_jtis[jti] = float(exp)
        _persist_revoked_jtis_locked()


def is_jti_revoked(jti: str) -> bool:
    """Return True if `jti` is in the blocklist (or its entry is fresh)."""
    if not jti:
        return False
    _load_revoked_jtis()
    with _revoked_jtis_lock:
        _prune_revoked_jtis_locked()
        return jti in _revoked_jtis


def _create_jwt(user_id: int, email: str) -> str:
    """Crée un JWT signé."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
        # AUTH-VULN-03: per-token unique id so logout/revocation can target a
        # specific session instead of nuking JWT_SECRET (which would log out
        # every user globally).
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict | None:
    """Décode et vérifie un JWT. Retourne None si invalide ou révoqué."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if "sub" not in payload or "email" not in payload:
            return None
        payload["sub"] = int(payload["sub"])
        # AUTH-VULN-03 (issue #557): reject revoked JTIs. Tokens minted before
        # the jti claim was added (legacy 7-day window) bypass this check —
        # acceptable because (a) the blocklist starts empty and (b) the
        # population organically rotates within JWT_EXPIRY_SECONDS.
        jti = payload.get("jti")
        if jti and is_jti_revoked(str(jti)):
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None


def require_auth(f):
    """Décorateur : exige un JWT valide dans Authorization: Bearer <token>."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
        token = auth_header[7:]
        payload = _decode_jwt(token)
        if not payload:
            return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)
        g.auth_user = {"id": payload["sub"], "email": payload["email"]}
        return f(*args, **kwargs)
    return decorated


def apply_auth_guard(bp, public_endpoints: frozenset | None = None):
    """Ajoute un before_request auth guard à un Blueprint.

    Même logique que routes.py._enforce_auth_or_local :
    - JWT présent → valide, extrait email, set g.auth_user
    - Pas de JWT + localhost → mode Tauri desktop, g.auth_user = None
    - Pas de JWT + remote → 401 Unauthorized

    Args:
        bp: Blueprint Flask à protéger.
        public_endpoints: frozenset d'endpoint names exemptés d'auth (optionnel).
    """
    # Idempotent: skip if already guarded (avoids Flask error on repeated create_app in tests)
    if getattr(bp, '_auth_guard_applied', False):
        return
    # Flask 2.x sets _got_registered_once=True after register_blueprint().
    # After that, calling before_request raises AssertionError. Check this as
    # a second safety net in case _auth_guard_applied was lost (e.g. module reload).
    if getattr(bp, '_got_registered_once', False):
        bp._auth_guard_applied = True  # Prevent future attempts
        return
    bp._auth_guard_applied = True

    @bp.before_request
    def _enforce_auth():
        # Never intercept CORS preflight — the browser strips Authorization on
        # OPTIONS requests, and returning 401 here yields a response without
        # CORS headers which the browser then blocks, surfacing as cryptic
        # "No 'Access-Control-Allow-Origin' header is present" errors across
        # every protected endpoint. The top-level handle_preflight in app.py
        # already returns the correct 200 CORS response before we get here —
        # this is belt-and-suspenders in case of blueprint registration races.
        if request.method == "OPTIONS":
            return None

        if public_endpoints and request.endpoint in public_endpoints:
            return  # Route publique

        auth_header = request.headers.get("Authorization", "")
        remote_addr = request.remote_addr or ""

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = _decode_jwt(token)
            if payload:
                g.auth_user = {"id": payload["sub"], "email": payload["email"]}
                return
            # Sentinelle e2e/dev-bypass ("dev:<email>", posée par
            # setupBaseMocks et useAuth DEV) : REFUSER même en loopback.
            # Audit 2026-06-09 : des requêtes e2e fuyaient vers le backend
            # réel pendant le teardown Playwright (routes démontées) et le
            # fallback loopback les servait comme l'utilisateur réel — le
            # backend a interrogé la vraie API Google Calendar avec l'id de
            # fixture « cal-1 ». Un vrai JWT expiré (mode Tauri) n'a jamais
            # ce préfixe ; pour une session dev réelle, utiliser
            # /api/auth/dev-login qui minte un vrai JWT.
            if token.startswith("dev:"):
                logger.warning(
                    f"[AUTH] Token sentinelle e2e refusé pour {request.path} "
                    "(fuite de mock probable — pas de fallback loopback)"
                )
                return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)
            # JWT invalide — si localhost, fallback mode Tauri (token périmé/dev).
            # Intentionnel: l'app desktop peut avoir un JWT expiré mais reste trustée via loopback.
            if is_trusted_loopback():
                logger.warning(f"[AUTH] JWT invalide pour {request.path} — fallback loopback (token périmé?)")
                g.auth_user = None
                return
            token_fp = hashlib.sha256(token.encode()).hexdigest()[:8]
            logger.warning(f"[AUTH] JWT invalide pour {request.path} (token_fp: {token_fp})")
            return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)
        else:
            if not is_trusted_loopback():
                logger.warning(f"[AUTH] Pas de Bearer pour {request.path} (remote: {remote_addr})")
                return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
            g.auth_user = None


def _is_loopback(addr: str) -> bool:
    """Vérifie si une adresse IP est loopback (127.x, ::1, ::ffff:127.x, localhost)."""
    if addr == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(addr)
        if ip.is_loopback:
            return True
        # IPv4-mapped IPv6 (dual-stack): ::ffff:127.0.0.1
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return ip.ipv4_mapped.is_loopback
    except ValueError:
        pass
    return False


def require_auth_or_local(f):
    """Décorateur hybride : JWT si présent, sinon fallback localhost (mode Tauri).

    - JWT présent → valide, extrait email, set g.auth_user
    - Pas de JWT + localhost → mode Tauri desktop, g.auth_user = None
    - Pas de JWT + remote → 401 Unauthorized
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = _decode_jwt(token)
            if not payload:
                return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)
            g.auth_user = {"id": payload["sub"], "email": payload["email"]}
        else:
            # Pas de JWT — autorisé seulement en mode local (Tauri desktop)
            is_local = is_trusted_loopback()
            if not is_local:
                return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)
            g.auth_user = None
        return f(*args, **kwargs)
    return decorated


def _cleanup_expired_tokens():
    """Nettoie les magic tokens expirés (thread-safe)."""
    now = time.time()
    with _magic_tokens_lock:
        expired = [t for t, data in _magic_tokens.items() if now - data["created_at"] > MAGIC_LINK_TTL]
        for t in expired:
            del _magic_tokens[t]


# Simple in-memory rate limiter for auth endpoints
_auth_rate_limit: dict[str, list[float]] = {}  # ip -> [timestamps]
_auth_rate_limit_lock = threading.Lock()
_AUTH_RATE_LIMIT_MAX = 15  # max 15 requests per window
_AUTH_RATE_LIMIT_WINDOW = 300  # 5 minutes


def _check_auth_rate_limit() -> bool:
    """Returns True if request is allowed, False if rate limited (thread-safe)."""
    ip = request.remote_addr or "unknown"
    now = time.time()
    with _auth_rate_limit_lock:
        if ip not in _auth_rate_limit:
            _auth_rate_limit[ip] = []
        # Prune old entries
        _auth_rate_limit[ip] = [t for t in _auth_rate_limit[ip] if now - t < _AUTH_RATE_LIMIT_WINDOW]
        # Bound the dict so one-shot IPs don't accumulate empty buckets forever
        # (audit 2026-05-29, CWE-770).
        if len(_auth_rate_limit) > 2048:
            for _k in [k for k, v in _auth_rate_limit.items()
                       if (not v or now - v[-1] >= _AUTH_RATE_LIMIT_WINDOW) and k != ip]:
                _auth_rate_limit.pop(_k, None)
        if len(_auth_rate_limit[ip]) >= _AUTH_RATE_LIMIT_MAX:
            return False
        _auth_rate_limit[ip].append(now)
        return True


# Known users registry — persistent JSON file
_KNOWN_USERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_KNOWN_USERS_FILE = os.path.join(_KNOWN_USERS_DIR, "known_users.json")
_known_users_lock = threading.Lock()


def _load_known_users() -> list[dict]:
    """Charge la liste des utilisateurs connus depuis le fichier JSON."""
    if not os.path.exists(_KNOWN_USERS_FILE):
        return []
    try:
        with open(_KNOWN_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_known_users(users: list[dict]) -> None:
    """Sauvegarde la liste des utilisateurs connus."""
    os.makedirs(_KNOWN_USERS_DIR, exist_ok=True)
    with open(_KNOWN_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def _register_known_user(email: str) -> None:
    """Enregistre ou met à jour un utilisateur connu (appelé après auth réussie)."""
    now = datetime.now(timezone.utc).isoformat()
    with _known_users_lock:
        users = _load_known_users()
        for user in users:
            if user["email"] == email:
                user["last_seen"] = now
                _save_known_users(users)
                return
        users.append({"email": email, "registered_at": now, "last_seen": now})
        _save_known_users(users)


def is_known_user(email: str) -> bool:
    """Vérifie si un email correspond à un utilisateur Agentys connu."""
    with _known_users_lock:
        users = _load_known_users()
    return any(u["email"] == email for u in users)


@auth_bp.route("/oauth-login", methods=["POST"])
def oauth_login():
    """
    Login via OAuth — vérifie que les tokens OAuth existent et retourne un JWT.
    Appelé après qu'un utilisateur a complété le flux OAuth depuis la page de login.
    ---
    tags: [Auth]
    """
    # Audit F-03 (2026-05-03): account_id is `sha256("gmail:" + email)[:16]` —
    # deterministic from a public input. The (account_id, email) tuple is NOT
    # proof of identity. Until a PKCE-style exchange-code is wired through the
    # OAuth callback, gate the endpoint on caller trust:
    #   - Browsers must come from an allow-listed Origin (Vercel frontend).
    #   - Non-browser callers (no Origin) must hit from a loopback IP (Tauri).
    # An attacker curl-ing from a remote IP has neither and is blocked.
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.headers.get("Referer") or "").strip()
    remote_addr = request.remote_addr or ""
    if origin or referer:
        if not _trusted_auth_origin():
            logger.warning("[F-03] oauth-login blocked, untrusted origin=%s", origin)
            return jsonify({"error": "untrusted origin"}), 403
    else:
        if not is_trusted_loopback():
            logger.warning("[F-03] oauth-login blocked, no Origin from non-loopback %s", remote_addr)
            return error_response("NOT_AUTHENTICATED", "Not authenticated", 401)

    if not _check_auth_rate_limit():
        return error_response("TOO_MANY_LOGIN_ATTEMPTS", "Too many attempts. Try again in a few minutes.", 429)

    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id", "").strip()
    email = data.get("email", "").strip()

    if not account_id or not email:
        return jsonify({"error": "account_id et email requis"}), 400

    # Verify account has valid OAuth tokens
    from app.api.oauth import get_tokens_server
    tokens = get_tokens_server(account_id)
    if not tokens:
        return jsonify({"error": "Aucune connexion OAuth valide pour ce compte"}), 401

    # Verify email matches the OAuth tokens
    token_email = tokens.get("email", "")
    if token_email.lower() != email.lower():
        return jsonify({"error": "L'email ne correspond pas au compte OAuth"}), 401

    user_id = user_id_from_email(email)
    access_token = _create_jwt(user_id, email)
    _register_known_user(email)

    logger.info(f"[AUTH] Connexion OAuth réussie pour {email} (account={account_id})")
    return jsonify({
        "access_token": access_token,
        "user": {"id": user_id, "email": email},
    })


_email_magic_link_limit: dict[str, list[float]] = {}  # email -> [timestamps]
_EMAIL_LINK_MAX = 5
_EMAIL_LINK_WINDOW = 3600  # 1 hour


def _check_email_link_rate_limit(email: str) -> bool:
    """Per-recipient throttle for magic-link sends (anti email-bombing).

    SECURITY (audit 2026-05-29, CWE-770): the per-IP limit alone lets one IP mail
    any address up to its budget; also cap sends per TARGET email so the agency's
    SMTP/domain reputation can't be abused to spam arbitrary third parties.
    """
    now = time.time()
    with _auth_rate_limit_lock:
        bucket = [t for t in _email_magic_link_limit.get(email, []) if now - t < _EMAIL_LINK_WINDOW]
        if len(bucket) >= _EMAIL_LINK_MAX:
            _email_magic_link_limit[email] = bucket
            return False
        bucket.append(now)
        _email_magic_link_limit[email] = bucket
        if len(_email_magic_link_limit) > 4096:
            for _k in [k for k, v in _email_magic_link_limit.items()
                       if (not v or now - v[-1] >= _EMAIL_LINK_WINDOW) and k != email]:
                _email_magic_link_limit.pop(_k, None)
        return True


@auth_bp.route("/request-magic-link", methods=["POST"])
def request_magic_link():
    """
    Envoie un magic link par email.
    En dev : log le token dans la console.
    ---
    tags: [Auth]
    """
    # F-13 (audit issue #209, 2026-04-29): block cross-origin POSTs.
    if not _trusted_auth_origin():
        logger.warning("[F-13] request-magic-link blocked, untrusted origin=%s", request.headers.get("Origin"))
        return jsonify({"error": "untrusted origin"}), 403
    if not _check_auth_rate_limit():
        return error_response("TOO_MANY_LOGIN_ATTEMPTS", "Too many attempts. Try again in a few minutes.", 429)

    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "Email invalide"}), 400

    # SECURITY (audit 2026-05-29, CWE-770): per-recipient throttle. Return a uniform
    # success so this can't be used to probe which addresses are being targeted.
    if not _check_email_link_rate_limit(email):
        logger.warning("[AUTH] Magic-link per-email rate limit hit (token suppressed)")
        return jsonify({"ok": True})

    _cleanup_expired_tokens()

    token = secrets.token_urlsafe(32)
    with _magic_tokens_lock:
        _magic_tokens[token] = {"email": email, "created_at": time.time()}

    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:1420")
    magic_url = f"{frontend_url}/?token={token}"

    # CASA V7.1 (#210): fail-closed — only enable dev convenience when
    # FLASK_ENV is EXPLICITLY "development". Previously we used
    # `!= "production"`, which meant an unset env var leaked tokens.
    is_dev = os.getenv("FLASK_ENV") == "development"
    if is_dev:
        # Never log the full magic_url (token = session takeover). Show only
        # the email + a short token id for support traceability.
        logger.info(f"[AUTH] Magic link issued for {email} (token_id={token[:8]}...)")
        # stdout for the local dev terminal — convenient for copy-paste during
        # manual testing. Note: Railway does NOT capture FLASK_ENV=development
        # so this branch never runs in prod.
        print(f"\n{'='*60}")
        print(f"  MAGIC LINK pour {email}")
        print(f"  {magic_url}")
        print(f"{'='*60}\n")

    # Envoyer l'email via Brevo (transactional API)
    sent = _send_magic_link_email(email, magic_url)
    if not sent and is_dev:
        logger.warning(f"[AUTH] Email send failed for {email} — token_id={token[:8]} (full URL on stdout above)")
    if is_dev:
        return jsonify({"ok": True, "dev_magic_url": magic_url})

    if not sent:
        # SECURITY (audit 2026-05-29, CWE-203): uniform {ok:true} even on SMTP
        # failure — the 503-vs-200 difference was a recipient-deliverability oracle.
        # Logged server-side for ops visibility.
        logger.warning("[AUTH] Magic-link email send failed (token_id=%s)", token[:8])
        return jsonify({"ok": True})

    return jsonify({"ok": True})


@auth_bp.route("/verify", methods=["POST"])
def verify_magic_token():
    """
    Vérifie un magic token et retourne un JWT.
    ---
    tags: [Auth]
    """
    # F-13 (audit issue #209, 2026-04-29): block cross-origin POSTs.
    if not _trusted_auth_origin():
        logger.warning("[F-13] verify blocked, untrusted origin=%s", request.headers.get("Origin"))
        return jsonify({"error": "untrusted origin"}), 403
    if not _check_auth_rate_limit():
        return error_response("TOO_MANY_LOGIN_ATTEMPTS", "Too many attempts. Try again in a few minutes.", 429)

    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"error": "Token manquant"}), 400

    # Audit 2026-04-25 (HIGH-Backend-7 / sub-report 01 HIGH-07): the verified
    # cache used to KEY the cached JWT under the magic token itself, which
    # meant any caller who replayed the same magic token within 60s got
    # back the same JWT. If the URL leaked (referer to a third-party CDN,
    # browser history on a shared device, server access log), an attacker
    # could race the legit user and mint an equivalent JWT.
    #
    # Fix: cache the response under a server-side replay key derived from
    # the JWT itself, so even if the magic token leaks, the cache lookup
    # cannot be poisoned by an attacker who only has the magic token.
    # In production, drop the cache entirely — page reloads should re-do
    # the magic-link flow rather than replay the token.
    is_dev_env = not _is_production_env

    # Check verified cache first (DEV ONLY — grace for HMR / StrictMode)
    if is_dev_env:
        cached = _verified_cache.get(token)
        if cached and time.time() - cached["verified_at"] < _VERIFIED_GRACE_SECONDS:
            return jsonify(cached["response_json"])

        # Clean up expired cache entries
        now = time.time()
        expired_cache = [t for t, v in _verified_cache.items() if now - v["verified_at"] > _VERIFIED_GRACE_SECONDS]
        for t in expired_cache:
            del _verified_cache[t]

    with _magic_tokens_lock:
        token_data = _magic_tokens.pop(token, None)
    if not token_data:
        return error_response("TOKEN_INVALID_OR_EXPIRED", "Invalid or expired token", 401)

    if time.time() - token_data["created_at"] > MAGIC_LINK_TTL:
        return error_response("TOKEN_EXPIRED", "Token expired", 401)

    email = token_data["email"]
    # User ID stable basé sur sha256(email)[:8] — voir `user_id_from_email`.
    user_id = user_id_from_email(email)

    access_token = _create_jwt(user_id, email)

    # Enregistrer l'utilisateur dans le registre
    _register_known_user(email)

    response_json = {"access_token": access_token, "user": {"id": user_id, "email": email}}

    # Cache the response for grace period (DEV ONLY).
    # In prod we don't cache: each /verify call REQUIRES a still-valid magic
    # token; a replayed token after first use returns 401 above.
    if is_dev_env:
        _verified_cache[token] = {"response_json": response_json, "verified_at": time.time()}

    logger.info(f"[AUTH] Connexion réussie pour {email}")
    return jsonify(response_json)


@auth_bp.route("/me", methods=["GET"])
@require_auth
def get_current_user():
    """
    Retourne l'utilisateur authentifié.
    ---
    tags: [Auth]
    """
    from .admin import _is_admin
    from app.billing.entitlements import BillingEntitlementService

    user_id = int(g.auth_user.get("id"))
    billing = BillingEntitlementService().get_for_user(user_id).to_dict()
    user_data = {
        **g.auth_user,
        "is_admin": _is_admin(g.auth_user.get("email", "")),
        "plan": billing["plan"],
        "subscription_status": billing["subscription_status"],
        "ai_enabled": billing["ai_enabled"],
        "billing": billing,
    }
    return jsonify({"user": user_data})


@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """
    Révoque le JWT courant en l'ajoutant à la blocklist jusqu'à son expiration
    naturelle. Tous les decodes ultérieurs de ce token retourneront None.

    AUTH-VULN-03 (Shannon pentest 2026-05-05, issue #557): avant ce fix, un
    JWT volé restait valide 7 jours sans recours côté serveur. La rotation
    de JWT_SECRET déconnectait globalement TOUS les utilisateurs — non
    actionnable en pratique. Désormais l'endpoint cible un seul jti.
    ---
    tags: [Auth]
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not token:
        return jsonify({"error": "Bearer token required"}), 400
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        # Idempotent: an already-expired or unparseable token is "logged out"
        # by definition — return success so the frontend can clear local state
        # without retrying.
        return jsonify({"success": True, "already_invalid": True})

    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti:
        # Legacy token without jti — we can't revoke a single session.
        # Tell the caller; it can decide to drop the token client-side.
        logger.info("[AUTH] logout requested for legacy token (no jti)")
        return jsonify({"success": True, "legacy_token": True})

    revoke_jti(str(jti), float(exp or (time.time() + JWT_EXPIRY_SECONDS)))
    logger.info("[AUTH] logout: revoked jti=%s for user=%s", str(jti)[:8], payload.get("email"))
    return jsonify({"success": True})


def _actual_peer_ip() -> str:
    """Return the real TCP peer IP, bypassing any ProxyFix rewriting.

    F-06 (regression audit, 2026-04-29): when ProxyFix is configured
    (app.py:262, ``x_for=1``), ``request.remote_addr`` is rewritten to
    the X-Forwarded-For value supplied by the upstream proxy — but XFF
    is *attacker-controlled* on the public internet (any client can set
    the header). Combined with ``DISABLE_DEV_LOGIN_IN_PROD=false``, this
    turned dev-login into a JWT-minting oracle: ``X-Forwarded-For:
    127.0.0.1`` made ``_is_loopback`` return True, and any victim email
    received a fresh JWT.

    Werkzeug's ProxyFix preserves the pre-rewrite values in
    ``environ['werkzeug.proxy_fix.orig']``; this helper reads the real
    REMOTE_ADDR from there. Falls back to ``request.remote_addr`` when
    ProxyFix isn't on the path (dev / loopback / direct).
    """
    orig = request.environ.get("werkzeug.proxy_fix.orig", {})
    real = orig.get("REMOTE_ADDR")
    if real:
        return real
    return request.remote_addr or ""


def is_trusted_loopback() -> bool:
    """Whether the request genuinely originates from the local host.

    SECURITY (audit 2026-05-29, CWE-290/CWE-348): use THIS — never
    ``_is_loopback(request.remote_addr)`` — for every loopback-trust decision
    (the Tauri no-JWT bypass, ownership-check skips, singleton-account
    fallbacks). ``request.remote_addr`` is rewritten by ProxyFix(x_for=1) to the
    attacker-controlled X-Forwarded-For value, so an off-edge caller (an SSRF
    primitive, a co-resident Railway service, or any future extra proxy hop)
    sending ``X-Forwarded-For: 127.0.0.1`` would otherwise be trusted as local
    and bypass per-tenant ownership. This reads the real pre-ProxyFix TCP peer
    via :func:`_actual_peer_ip` (the same hardening dev-login already uses).
    """
    return _is_loopback(_actual_peer_ip())


@auth_bp.route("/dev-login", methods=["POST"])
def dev_login():
    """
    Login rapide pour tests automatisés (localhost uniquement).
    Génère un JWT valide sans OAuth ni magic link.

    F-06 (regression audit, 2026-04-29): defense-in-depth hardening:
    - loopback check now reads the real TCP peer (pre-ProxyFix) so an
      ``X-Forwarded-For: 127.0.0.1`` spoof from the public internet
      cannot pass.
    - When ``DISABLE_DEV_LOGIN_IN_PROD=false`` (the docstring on the
      audit comment encourages this for "internal staging admin"), the
      ``email`` body field MUST be in ``DEV_LOGIN_ALLOWED_EMAILS`` (CSV
      env var, lowercased) — closes the JWT-oracle vector entirely.
    ---
    tags: [Auth]
    """
    _disable_in_prod = os.environ.get("DISABLE_DEV_LOGIN_IN_PROD", "true").lower() != "false"
    if _is_production_env and _disable_in_prod:
        return jsonify({"error": "dev-login disabled in production"}), 404

    # F-06: gate on the real TCP peer, not the XFF-rewritten remote_addr.
    real_peer = _actual_peer_ip()
    if not _is_loopback(real_peer):
        logger.warning(
            "[F-06] dev-login refused: real_peer=%s remote_addr=%s",
            real_peer, request.remote_addr,
        )
        return jsonify({"error": "dev-login is localhost-only"}), 403

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "nightly-test@agentys.local").strip().lower()

    # F-06: when the disable flag is off in prod, restrict to a fixed
    # allowlist. Empty allowlist = mint refused (fail-closed).
    if _is_production_env and not _disable_in_prod:
        allowed_csv = os.environ.get("DEV_LOGIN_ALLOWED_EMAILS", "")
        allowed = {e.strip().lower() for e in allowed_csv.split(",") if e.strip()}
        if not allowed or email not in allowed:
            logger.warning("[F-06] dev-login email not in allowlist: %s", email)
            return jsonify({"error": "email not allowed for dev-login"}), 403

    user_id = user_id_from_email(email)
    access_token = _create_jwt(user_id, email)

    logger.info(f"[AUTH] Dev login pour {email} (user_id={user_id})")
    return jsonify({
        "access_token": access_token,
        "user": {"id": user_id, "email": email},
    })
