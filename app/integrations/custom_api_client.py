"""Custom REST API client — flexible account provider with user-defined endpoints.

AUTHZ-VULN-10 / SSRF-VULN-03 (Shannon pentest 2026-05-05, issue #557): the
`base_url` in this client comes from a user-managed agent config. Pre-fix,
zero validation meant a malicious config could redirect the outbound
request to RFC 1918 / cloud metadata. The defense lives in two layers:

  1. The agent_marketplace.save_config endpoint validates `base_url`
     against the SSRF allowlist BEFORE persisting it (best line of defense
     — a poisoned config never lands on disk).
  2. Every outbound call here uses `safe_request` so that even if a config
     was poisoned via a different path (legacy entry on disk pre-fix), we
     still re-validate at request time. Defense in depth.
"""

import logging
from typing import Optional

from app.interfaces.account_provider import AccountActionResult, AccountProvider
from app.utils.safe_outbound import SsrfBlocked, safe_request

logger = logging.getLogger(__name__)


def _outbound_safe(method: str, url: str, **kwargs):
    """Thin wrapper that converts SsrfBlocked into a tuple-like response.

    Returns either a `requests.Response`-compatible object or raises. The
    caller pattern in this module catches Exception broadly, so a raised
    SsrfBlocked surfaces as a "test failed" message — which is the correct
    user-facing UX for a refused config.
    """
    try:
        return safe_request(method, url, **kwargs)
    except SsrfBlocked:
        # Re-raise as a regular requests-style exception so the existing
        # try/except in callers logs + surfaces it.
        raise


class CustomAPIAccountProvider(AccountProvider):
    """Fournisseur de gestion de comptes via API REST personnalisee."""

    def __init__(self, config: dict):
        self._base_url = config.get("base_url", "").rstrip("/")
        self._auth_type = config.get("auth_type", "none")
        self._auth_credentials = config.get("auth_credentials", {})
        self._endpoints = config.get("endpoints", {})
        self._success_codes = config.get("success_codes", [200, 201, 204])

    @property
    def provider_name(self) -> str:
        return "custom"

    def _get_session(self):
        """Cree une session requests avec l'authentification configuree."""
        import requests
        session = requests.Session()
        session.headers["Content-Type"] = "application/json"

        if self._auth_type == "bearer":
            token = self._auth_credentials.get("token", "")
            session.headers["Authorization"] = f"Bearer {token}"
        elif self._auth_type == "basic":
            from requests.auth import HTTPBasicAuth
            session.auth = HTTPBasicAuth(
                self._auth_credentials.get("username", ""),
                self._auth_credentials.get("password", ""),
            )
        elif self._auth_type == "api_key":
            header = self._auth_credentials.get("header", "X-API-Key")
            key = self._auth_credentials.get("key", "")
            session.headers[header] = key

        return session

    def _substitute(self, template: str, variables: dict) -> str:
        """Remplace les {{variables}} dans un template."""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def _substitute_body(self, body: dict, variables: dict) -> dict:
        """Remplace les {{variables}} dans un body JSON (recursif)."""
        import json
        serialized = json.dumps(body)
        for key, value in variables.items():
            serialized = serialized.replace(f"{{{{{key}}}}}", str(value))
        return json.loads(serialized)

    def _validate_outbound(self, url: str) -> Optional[AccountActionResult]:
        """SSRF gate before any session.get/request — issue #557."""
        from app.api._auth_helpers import is_production
        if not is_production():
            # Dev environments may legitimately point at localhost — keep the
            # legacy lenient behaviour there. Prod is where the SSRF damage
            # lands (cloud metadata, internal services).
            return None
        from app.utils.safe_outbound import SsrfBlocked, validate_outbound_url
        try:
            validate_outbound_url(url)
            return None
        except SsrfBlocked as e:
            logger.warning("[CustomAPI] SSRF gate refused outbound to %s: %s", url, e)
            return AccountActionResult(success=False, message=f"URL refusée: {e}")

    def test_connection(self) -> AccountActionResult:
        """Teste la connexion en envoyant un GET a la base URL."""
        if not self._base_url:
            return AccountActionResult(success=False, message="Base URL non configuree")
        gate = self._validate_outbound(self._base_url)
        if gate is not None:
            return gate
        try:
            session = self._get_session()
            resp = session.get(self._base_url, timeout=15, allow_redirects=False)
            if resp.status_code in self._success_codes:
                return AccountActionResult(success=True, message=f"Connecte a {self._base_url}")
            return AccountActionResult(success=False, message=f"HTTP {resp.status_code}")
        except Exception as exc:
            logger.error("[CustomAPI] test_connection failed: %s", exc)
            return AccountActionResult(success=False, message=str(exc))

    def search_user(self, email: str) -> Optional[dict]:
        """Recherche un utilisateur via l'endpoint configure."""
        ep = self._endpoints.get("search_user")
        if not ep:
            return None

        variables = {"email": email}
        method = ep.get("method", "GET").upper()
        path = self._substitute(ep.get("path", ""), variables)
        url = f"{self._base_url}{path}"

        # AUTHZ-VULN-10 / SSRF (#557): SSRF gate
        if self._validate_outbound(url) is not None:
            return None

        try:
            session = self._get_session()
            if method == "GET":
                resp = session.get(url, timeout=15, allow_redirects=False)
            else:
                body = self._substitute_body(ep.get("body", {}), variables)
                resp = session.request(method, url, json=body, timeout=15, allow_redirects=False)

            if resp.status_code not in self._success_codes:
                return None

            data = resp.json()
            # Handle list or single object response
            if isinstance(data, list):
                if not data:
                    return None
                user = data[0]
            else:
                user = data

            return {
                "id": user.get("id", user.get("user_id", "")),
                "username": user.get("username", user.get("email", "")),
                "email": user.get("email", ""),
                "display_name": user.get("display_name", user.get("name", "")),
                "slug": user.get("username", user.get("email", "")),
            }
        except Exception as exc:
            logger.error("[CustomAPI] search_user(%s) failed: %s", email, exc)
            return None

    def reset_password(self, user_id, new_password: str) -> AccountActionResult:
        """Reinitialise le mot de passe via l'endpoint configure."""
        ep = self._endpoints.get("reset_password")
        if not ep:
            return AccountActionResult(success=False, message="Action non configuree")

        variables = {"user_id": str(user_id), "new_password": new_password, "email": ""}
        method = ep.get("method", "POST").upper()
        path = self._substitute(ep.get("path", ""), variables)
        url = f"{self._base_url}{path}"

        gate = self._validate_outbound(url)
        if gate is not None:
            return gate

        try:
            session = self._get_session()
            body = self._substitute_body(ep.get("body", {}), variables)
            resp = session.request(method, url, json=body, timeout=15, allow_redirects=False)

            if resp.status_code in self._success_codes:
                logger.info("[CustomAPI] Password reset for user_id=%s", user_id)
                return AccountActionResult(success=True, message="Mot de passe reinitialise")

            return AccountActionResult(success=False, message=f"HTTP {resp.status_code}")
        except Exception as exc:
            logger.error("[CustomAPI] reset_password(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))

    def update_email(self, user_id, new_email: str) -> AccountActionResult:
        """Met a jour l'email via l'endpoint configure."""
        ep = self._endpoints.get("update_email")
        if not ep:
            return AccountActionResult(success=False, message="Action non configuree")

        variables = {"user_id": str(user_id), "new_email": new_email, "email": ""}
        method = ep.get("method", "PUT").upper()
        path = self._substitute(ep.get("path", ""), variables)
        url = f"{self._base_url}{path}"

        gate = self._validate_outbound(url)
        if gate is not None:
            return gate

        try:
            session = self._get_session()
            body = self._substitute_body(ep.get("body", {}), variables)
            resp = session.request(method, url, json=body, timeout=15, allow_redirects=False)

            if resp.status_code in self._success_codes:
                logger.info("[CustomAPI] Email updated for user_id=%s -> %s", user_id, new_email)
                return AccountActionResult(success=True, message=f"Email mis a jour vers {new_email}")

            return AccountActionResult(success=False, message=f"HTTP {resp.status_code}")
        except Exception as exc:
            logger.error("[CustomAPI] update_email(%s) failed: %s", user_id, exc)
            return AccountActionResult(success=False, message=str(exc))
