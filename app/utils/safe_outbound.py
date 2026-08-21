# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Safe outbound HTTP — SSRF defense helper.

Centralizes the rules every server-side fetch MUST follow before reaching the
network, in response to Shannon pentest 2026-05-05 (issue #557 — SSRF-VULN-01,
SSRF-VULN-02, SSRF-VULN-03, SSRF-VULN-06, AUTHZ-VULN-08, AUTHZ-VULN-09).

Defenses (defense-in-depth):
  1. Scheme allowlist (http/https only — no file://, gopher://, dict://, ftp://).
  2. Hostname → IP resolution + RFC 1918 / loopback / link-local /
     multicast / cloud-metadata (169.254.169.254, fd00:ec2::254) blocklist.
  3. allow_redirects=False — every redirect is re-validated by re-calling
     this helper (the kernel never silently follows into an internal IP).
  4. Hard timeout cap.
  5. Optional hostname allowlist for ultra-sensitive callers (admin LLM
     settings).

Use `safe_get` / `safe_post` for one-shot calls; use `validate_outbound_url`
when a different HTTP client is unavoidable (urllib3 stream, httpx async, …).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15  # seconds, hard cap
ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTNAMES = frozenset({
    "localhost", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "metadata.goog",
})


class SsrfBlocked(ValueError):
    """Raised when a URL is rejected by SSRF defenses. Message is operator-safe."""


@dataclass(frozen=True)
class _ResolvedTarget:
    scheme: str
    host: str
    port: int
    ip: str  # canonical resolved IP


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if ip_str is a private / loopback / link-local / metadata IP."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # malformed → treat as blocked

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    # AWS / GCP / Azure metadata endpoints (canonicalized)
    if ip_str in {"169.254.169.254", "fd00:ec2::254", "::1"}:
        return True
    return False


def validate_outbound_url(
    url: str,
    *,
    allowed_hostnames: Optional[Iterable[str]] = None,
) -> _ResolvedTarget:
    """
    Parse + DNS-resolve `url` and ensure it is safe to fetch.

    Args:
        url: The URL to validate. Must be a non-empty string.
        allowed_hostnames: If provided, hostname must match (case-insensitive).
            Useful for ultra-sensitive callers (admin LLM endpoints).

    Returns:
        Resolved scheme/host/port/ip — caller can pass `host` in Host header
        if pinning the IP.

    Raises:
        SsrfBlocked: if the URL fails any defense.
    """
    if not url or not isinstance(url, str):
        raise SsrfBlocked("URL absente ou invalide")

    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SsrfBlocked(f"Scheme non autorisé: {scheme or '<vide>'}")

    host = (parsed.hostname or "").lower()
    if not host:
        raise SsrfBlocked("Hôte manquant dans l'URL")
    if host in _BLOCKED_HOSTNAMES:
        raise SsrfBlocked(f"Hôte interdit: {host}")

    if allowed_hostnames is not None:
        normalized = {h.lower() for h in allowed_hostnames}
        if host not in normalized:
            raise SsrfBlocked(f"Hôte hors allowlist: {host}")

    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    if port < 1 or port > 65535:
        raise SsrfBlocked(f"Port invalide: {port}")

    # DNS resolve — block if ANY resolved address is private/internal.
    # Defends against DNS rebinding to a degree (a single-resolution snapshot
    # is still racy at TCP-connect time; for callers that need stronger
    # guarantees, pin the resolved IP and pass `Host: <hostname>`).
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SsrfBlocked(f"DNS resolution échouée pour {host}: {e}") from e

    if not infos:
        raise SsrfBlocked(f"Aucune IP résolue pour {host}")

    resolved_ips = {info[4][0] for info in infos}
    for ip in resolved_ips:
        if _is_blocked_ip(ip):
            raise SsrfBlocked(
                f"Hôte {host} résout vers IP interne/privée ({ip}) — bloqué"
            )

    # Pick the first IPv4-or-IPv6 address as canonical
    canonical_ip = next(iter(resolved_ips))
    return _ResolvedTarget(scheme=scheme, host=host, port=port, ip=canonical_ip)


def safe_request(
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    allowed_hostnames: Optional[Iterable[str]] = None,
    max_redirects: int = 3,
    **kwargs,
) -> requests.Response:
    """
    Perform an HTTP request with SSRF defenses.

    Crucially: redirects are NOT followed automatically by `requests`. Instead,
    we re-validate every Location header through `validate_outbound_url` before
    re-calling, so a public-but-malicious endpoint cannot 302 us into AWS
    metadata.

    Args:
        method: HTTP method (GET, POST, PUT, …).
        url: Initial URL.
        timeout: Hard cap (seconds).
        allowed_hostnames: Strict hostname allowlist (per call).
        max_redirects: How many redirect hops to follow (each re-validated).
        **kwargs: Forwarded to `requests.request` (headers, json, data…).
            `allow_redirects` is FORCED to False and will be ignored if passed.

    Returns:
        The final `requests.Response`.

    Raises:
        SsrfBlocked: any defense failure.
        requests.RequestException: network/transport errors.
    """
    kwargs.pop("allow_redirects", None)  # never trust the caller for this

    current_url = url
    for hop in range(max_redirects + 1):
        validate_outbound_url(current_url, allowed_hostnames=allowed_hostnames)
        resp = requests.request(
            method,
            current_url,
            timeout=timeout,
            allow_redirects=False,
            **kwargs,
        )
        if resp.status_code not in (301, 302, 303, 307, 308):
            return resp
        location = resp.headers.get("Location")
        if not location:
            return resp
        # Resolve relative redirects against the previous URL
        from urllib.parse import urljoin
        current_url = urljoin(current_url, location)
        logger.debug("safe_request: hop %d → %s", hop, current_url)

    raise SsrfBlocked(f"Trop de redirections (>{max_redirects}) pour {url}")


def safe_get(url: str, **kwargs) -> requests.Response:
    """Shortcut for `safe_request("GET", url, **kwargs)`."""
    return safe_request("GET", url, **kwargs)


def safe_post(url: str, **kwargs) -> requests.Response:
    """Shortcut for `safe_request("POST", url, **kwargs)`."""
    return safe_request("POST", url, **kwargs)


__all__ = [
    "SsrfBlocked",
    "validate_outbound_url",
    "safe_request",
    "safe_get",
    "safe_post",
    "DEFAULT_TIMEOUT",
]
