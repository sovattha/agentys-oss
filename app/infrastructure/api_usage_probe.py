"""Outbound API usage probes for admin cost/ops visibility.

The dashboard needs real provider usage, not just LLM token accounting. This
module instruments the common Python HTTP stacks at process boundary and writes
one metadata-only row per authenticated external API call.

Safety rules:
- never store request/response bodies;
- never store query strings;
- redact secret-bearing path segments (Telegram bot tokens, Slack webhooks,
  long opaque IDs);
- best-effort only: telemetry must never break the provider call.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_INSTALLED = False
_SECRETISH_SEGMENT_RE = re.compile(r"^(bot)?[A-Za-z0-9_\-:.]{16,}$")
_AUTH_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "client_secret",
    "key",
    "token",
}
_AUTH_HEADER_KEYS = {
    "authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "x-goog-api-key",
    "ocp-apim-subscription-key",
    "xi-api-key",
    "stripe-signature",
}
_KNOWN_PROVIDERS = {
    "anthropic": ("anthropic.com",),
    "openai": ("api.openai.com", "openai.azure.com"),
    "telegram": ("api.telegram.org",),
    "gmail": ("gmail.googleapis.com", "googleapis.com"),
    "google": ("googleapis.com", "oauth2.googleapis.com"),
    "outlook": ("graph.microsoft.com", "login.microsoftonline.com"),
    "stripe": ("api.stripe.com", "stripe.com"),
    "paypal": ("api-m.paypal.com", "api.paypal.com"),
    "pinterest": ("api.pinterest.com",),
    "deepgram": ("api.deepgram.com",),
    "elevenlabs": ("api.elevenlabs.io",),
    "expo": ("exp.host", "api.expo.dev"),
    "firebase": ("fcm.googleapis.com", "firebaseio.com"),
    "github": ("api.github.com", "github.com"),
    "slack": ("hooks.slack.com", "slack.com"),
    "teams": ("webhook.office.com", "office.com"),
}


def install_api_usage_probes() -> None:
    """Install all available outbound HTTP probes once per process."""
    global _INSTALLED
    if _INSTALLED or os.environ.get("API_USAGE_PROBES_ENABLED", "1").lower() in {"0", "false", "no", "off"}:
        return
    _INSTALLED = True
    _install_requests_probe()
    _install_httpx_probe()
    _install_urllib_probe()
    _install_httplib2_probe()
    _install_aiohttp_probe()


def _install_requests_probe() -> None:
    try:
        import requests

        original = requests.sessions.Session.request
        if getattr(original, "_agentys_api_probe", False):
            return

        @wraps(original)
        def wrapped(self, method, url, **kwargs):
            started = time.perf_counter()
            status_code = None
            try:
                response = original(self, method, url, **kwargs)
                status_code = getattr(response, "status_code", None)
                return response
            except Exception:
                _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, False)
                raise
            finally:
                if status_code is not None:
                    _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, 200 <= int(status_code) < 400)

        wrapped._agentys_api_probe = True  # type: ignore[attr-defined]
        requests.sessions.Session.request = wrapped
    except Exception as exc:
        logger.debug("requests API probe skipped: %s", exc)


def _install_httpx_probe() -> None:
    try:
        import httpx

        original_sync = httpx.Client.request
        if not getattr(original_sync, "_agentys_api_probe", False):

            @wraps(original_sync)
            def wrapped_sync(self, method, url, **kwargs):
                started = time.perf_counter()
                status_code = None
                try:
                    response = original_sync(self, method, url, **kwargs)
                    status_code = getattr(response, "status_code", None)
                    return response
                except Exception:
                    _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, False)
                    raise
                finally:
                    if status_code is not None:
                        _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, 200 <= int(status_code) < 400)

            wrapped_sync._agentys_api_probe = True  # type: ignore[attr-defined]
            httpx.Client.request = wrapped_sync

        original_async = httpx.AsyncClient.request
        if not getattr(original_async, "_agentys_api_probe", False):

            @wraps(original_async)
            async def wrapped_async(self, method, url, **kwargs):
                started = time.perf_counter()
                status_code = None
                try:
                    response = await original_async(self, method, url, **kwargs)
                    status_code = getattr(response, "status_code", None)
                    return response
                except Exception:
                    _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, False)
                    raise
                finally:
                    if status_code is not None:
                        _record_api_usage(method, url, _merge_headers(getattr(self, "headers", None), kwargs.get("headers")), status_code, started, 200 <= int(status_code) < 400)

            wrapped_async._agentys_api_probe = True  # type: ignore[attr-defined]
            httpx.AsyncClient.request = wrapped_async
    except Exception as exc:
        logger.debug("httpx API probe skipped: %s", exc)


def _install_urllib_probe() -> None:
    try:
        import urllib.request

        original = urllib.request.OpenerDirector.open
        if getattr(original, "_agentys_api_probe", False):
            return

        @wraps(original)
        def wrapped(self, fullurl, data=None, timeout=urllib.request._GLOBAL_DEFAULT_TIMEOUT):
            method = getattr(fullurl, "method", None) or ("POST" if data is not None else "GET")
            url = getattr(fullurl, "full_url", fullurl)
            headers = getattr(fullurl, "headers", None)
            started = time.perf_counter()
            status_code = None
            try:
                response = original(self, fullurl, data=data, timeout=timeout)
                status_code = getattr(response, "status", None) or getattr(response, "code", None)
                return response
            except Exception:
                _record_api_usage(method, url, headers, status_code, started, False)
                raise
            finally:
                if status_code is not None:
                    _record_api_usage(method, url, headers, status_code, started, 200 <= int(status_code) < 400)

        wrapped._agentys_api_probe = True  # type: ignore[attr-defined]
        urllib.request.OpenerDirector.open = wrapped
    except Exception as exc:
        logger.debug("urllib API probe skipped: %s", exc)


def _install_httplib2_probe() -> None:
    try:
        import httplib2

        original = httplib2.Http.request
        if getattr(original, "_agentys_api_probe", False):
            return

        @wraps(original)
        def wrapped(self, uri, method="GET", body=None, headers=None, **kwargs):
            started = time.perf_counter()
            status_code = None
            try:
                response, content = original(self, uri, method=method, body=body, headers=headers, **kwargs)
                status_code = getattr(response, "status", None)
                return response, content
            except Exception:
                _record_api_usage(method, uri, headers, status_code, started, False)
                raise
            finally:
                if status_code is not None:
                    _record_api_usage(method, uri, headers, status_code, started, 200 <= int(status_code) < 400)

        wrapped._agentys_api_probe = True  # type: ignore[attr-defined]
        httplib2.Http.request = wrapped
    except Exception as exc:
        logger.debug("httplib2 API probe skipped: %s", exc)


def _install_aiohttp_probe() -> None:
    try:
        import aiohttp

        original = aiohttp.ClientSession._request
        if getattr(original, "_agentys_api_probe", False):
            return

        @wraps(original)
        async def wrapped(self, method, str_or_url, **kwargs):
            started = time.perf_counter()
            status_code = None
            try:
                response = await original(self, method, str_or_url, **kwargs)
                status_code = getattr(response, "status", None)
                return response
            except Exception:
                _record_api_usage(method, str_or_url, kwargs.get("headers"), status_code, started, False)
                raise
            finally:
                if status_code is not None:
                    _record_api_usage(method, str_or_url, kwargs.get("headers"), status_code, started, 200 <= int(status_code) < 400)

        wrapped._agentys_api_probe = True  # type: ignore[attr-defined]
        aiohttp.ClientSession._request = wrapped
    except Exception as exc:
        logger.debug("aiohttp API probe skipped: %s", exc)


def _record_api_usage(
    method: str,
    url: Any,
    headers: Mapping[str, Any] | None,
    status_code: int | None,
    started: float,
    success: bool,
) -> None:
    try:
        parsed = urlparse(str(url))
        host = (parsed.hostname or "").lower()
        if not host or _is_local_host(host):
            return
        auth_present, auth_type = _detect_auth(headers, parsed.query)
        provider = _infer_provider(host)
        if not auth_present and provider == "unknown":
            return
        account_id, user_id, feature = _current_context()
        _write_api_usage(
            account_id=account_id,
            user_id=user_id,
            feature=feature,
            provider=provider,
            method=(method or "GET").upper(),
            url_host=host,
            url_path=_sanitize_path(parsed.path or "/"),
            status_code=int(status_code) if status_code is not None else None,
            success=success,
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            auth_present=auth_present,
            auth_type=auth_type,
        )
    except Exception as exc:
        logger.debug("api_usage probe write skipped: %s", exc)


def _write_api_usage(
    *,
    account_id: int | None,
    user_id: int | None,
    feature: str,
    provider: str,
    method: str,
    url_host: str,
    url_path: str,
    status_code: int | None,
    success: bool,
    duration_ms: int,
    auth_present: bool,
    auth_type: str,
) -> None:
    if os.environ.get("API_USAGE_PERSIST", "1").lower() in {"0", "false", "no", "off"}:
        return
    from app.infrastructure.database import db

    if user_id is None and account_id is not None:
        user_id = _resolve_user_id_from_account(account_id)

    db.execute(
        """
        INSERT INTO api_usage_log (
            account_id, user_id, feature, provider, method, url_host, url_path,
            status_code, success, duration_ms, auth_present, auth_type,
            process_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            user_id,
            feature or "unknown",
            provider or "unknown",
            method,
            url_host[:255],
            url_path[:500],
            status_code,
            1 if success else 0,
            duration_ms,
            1 if auth_present else 0,
            auth_type[:80],
            os.environ.get("AGENTYS_PROCESS_NAME", "backend")[:120],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    db.commit()


def _resolve_user_id_from_account(account_id: int | None) -> int | None:
    if account_id is None:
        return None
    try:
        from app.infrastructure.database import db

        row = db.fetchone("SELECT user_id FROM accounts WHERE id = ?", (account_id,))
        if row and row["user_id"] is not None:
            return int(row["user_id"])
    except Exception:
        return None
    return None


def _current_context() -> tuple[int | None, int | None, str]:
    try:
        from app.infrastructure.cost_manager import get_usage_context

        return get_usage_context()
    except Exception:
        return None, None, "unknown"


def _detect_auth(headers: Mapping[str, Any] | None, query: str) -> tuple[bool, str]:
    found: list[str] = []
    for key, value in _iter_headers(headers):
        key_lower = key.lower()
        if key_lower in _AUTH_HEADER_KEYS and value:
            found.append(f"header:{key_lower}")
        elif key_lower in {"cookie", "x-slack-signature"} and value:
            found.append(f"header:{key_lower}")
    query_keys = {key.lower() for key in parse_qs(query, keep_blank_values=False)}
    for key in sorted(query_keys & _AUTH_QUERY_KEYS):
        found.append(f"query:{key}")
    if not found:
        return False, "none"
    return True, ",".join(found[:3])


def _iter_headers(headers: Mapping[str, Any] | None):
    if not headers:
        return []
    try:
        return [(str(k), str(v)) for k, v in headers.items()]
    except Exception:
        return []


def _merge_headers(*sources: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        for key, value in _iter_headers(source):
            merged[key] = value
    return merged


def _infer_provider(host: str) -> str:
    for provider, suffixes in _KNOWN_PROVIDERS.items():
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in suffixes):
            return provider
    return "unknown"


def _sanitize_path(path: str) -> str:
    if not path or path == "/":
        return "/"
    safe_segments = []
    for segment in path.split("/"):
        if not segment:
            safe_segments.append("")
        elif _SECRETISH_SEGMENT_RE.match(segment):
            safe_segments.append("[redacted]")
        else:
            safe_segments.append(segment[:80])
    return "/".join(safe_segments) or "/"


def _is_local_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")
