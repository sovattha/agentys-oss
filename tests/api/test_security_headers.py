# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests — HTTP security headers (CASA V14.4, GitHub #208).

Le scanner CASA Tier 2 vérifie explicitement la présence des 6 headers
sécurité standards. Avant cette PR, 3 sur 6 étaient envoyés (XCTO, XFO,
Referrer-Policy). Ce fichier protège l'invariant "tous les 6 sont présents
sur toute réponse" pour éviter qu'un futur refactor en supprime un en
silence.

Le backend Agentys est JSON-only + redirects OAuth (cf. oauth.py) — pas
de rendering HTML — donc CSP peut être ultra-strict (`default-src 'none'`).
"""

import pytest


@pytest.fixture
def app_with_default_cors(monkeypatch):
    """create_app() minimal pour inspecter les headers d'une réponse réelle."""
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


class TestCasaSecurityHeaders:
    """Les 6 headers CASA V14.4 doivent être présents sur toute réponse."""

    def test_hsts_header_present(self, app_with_default_cors):
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        hsts = resp.headers.get("Strict-Transport-Security")
        assert hsts is not None, "HSTS missing — CASA V14.4 fail"
        assert "max-age=" in hsts
        # Min 1 an recommandé par OWASP / Mozilla observatory
        max_age = int(hsts.split("max-age=")[1].split(";")[0].split(",")[0].strip())
        assert max_age >= 31536000, f"HSTS max-age too short: {max_age}"
        assert "includeSubDomains" in hsts

    def test_csp_header_present_and_strict(self, app_with_default_cors):
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        csp = resp.headers.get("Content-Security-Policy")
        assert csp is not None, "CSP missing — CASA V14.4 fail"
        # API-only backend → 'none' default est attendu
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_permissions_policy_present(self, app_with_default_cors):
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        pp = resp.headers.get("Permissions-Policy")
        assert pp is not None, "Permissions-Policy missing — CASA V14.4 fail"
        # Les 3 features les plus à risque doivent être désactivées
        for feature in ("camera=()", "microphone=()", "geolocation=()"):
            assert feature in pp, f"Permissions-Policy missing {feature}"

    def test_existing_headers_preserved(self, app_with_default_cors):
        """Régression : la PR HSTS/CSP/PP ne doit pas casser les 3 anciens."""
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_headers_present_on_404(self, app_with_default_cors):
        """Les headers doivent s'appliquer même sur les réponses d'erreur.

        CASA scanne plusieurs endpoints — un 404 sans header est aussi un fail.
        """
        client = app_with_default_cors.test_client()
        resp = client.get("/api/this-endpoint-does-not-exist-zzz")
        assert resp.status_code == 404
        assert resp.headers.get("Strict-Transport-Security") is not None
        assert resp.headers.get("Content-Security-Policy") is not None
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


class TestCasaProxyDisclosure:
    """CASA 2026-04-30 — CWE-204 Proxy Disclosure remediation.

    The Tier 2 ZAP scan detected `Server: railway-edge` and used TRACE/OPTIONS
    method probes to fingerprint the upstream stack. These tests guard the
    three mitigations: Server header override, TRACE/TRACK/CONNECT block,
    and OPTIONS-without-origin rejection.
    """

    def test_server_header_overridden(self, app_with_default_cors):
        """Server header must NOT leak Werkzeug/gunicorn/railway-edge banner."""
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        server = resp.headers.get("Server", "")
        # Generic value only — no version, no infra fingerprint.
        assert server == "Agentys", f"Server header leaks fingerprint: {server!r}"
        # Some middlewares add X-Powered-By; it must be stripped.
        assert resp.headers.get("X-Powered-By") is None

    def test_trace_method_blocked(self, app_with_default_cors):
        """TRACE must be blocked at the app layer (XST attack vector)."""
        client = app_with_default_cors.test_client()
        resp = client.open("/api/health", method="TRACE")
        assert resp.status_code == 405
        # Allow header must be fixed (no per-route enumeration leak).
        assert resp.headers.get("Allow") == "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    def test_track_method_blocked(self, app_with_default_cors):
        """TRACK (IIS variant of TRACE) must also be blocked."""
        client = app_with_default_cors.test_client()
        resp = client.open("/api/health", method="TRACK")
        assert resp.status_code == 405

    def test_connect_method_blocked(self, app_with_default_cors):
        """CONNECT (HTTPS tunneling) is never legitimate on a JSON-API."""
        client = app_with_default_cors.test_client()
        resp = client.open("/api/health", method="CONNECT")
        assert resp.status_code == 405

    def test_options_without_origin_rejected(self, app_with_default_cors):
        """Non-CORS OPTIONS probes must not leak per-route Allow lists."""
        client = app_with_default_cors.test_client()
        # No Origin header → not a CORS preflight → 405 with fixed Allow.
        resp = client.open("/api/health", method="OPTIONS")
        assert resp.status_code == 405
        assert resp.headers.get("Allow") == "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    def test_options_with_valid_origin_still_works(self, monkeypatch):
        """Regression: legitimate CORS preflight from allowed origin succeeds."""
        monkeypatch.setenv("API_CORS_ORIGINS", "https://app.agentys.io")
        from app.api.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.open(
            "/api/health",
            method="OPTIONS",
            headers={"Origin": "https://app.agentys.io"},
        )
        # Either 200 (preflight handled) — what matters is it's NOT a 405.
        assert resp.status_code != 405
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.agentys.io"


class TestCasaCacheControl:
    """CASA 2026-04-30 — CWE-524 Storable / CWE-525 Cache-Control remediation.

    Backend serves only JSON + OAuth redirects (zero static assets), so all
    responses must be marked uncacheable to prevent shared/proxy caches from
    storing user-specific data.
    """

    def test_cache_control_on_root_index(self, app_with_default_cors):
        """The root / endpoint (CASA evidence URL) must have no-cache."""
        client = app_with_default_cors.test_client()
        resp = client.get("/")
        cc = resp.headers.get("Cache-Control", "")
        # OWASP Session Management Cheat Sheet recommends all 4 directives.
        for directive in ("no-store", "no-cache", "must-revalidate", "private"):
            assert directive in cc, f"Cache-Control missing {directive!r}: {cc!r}"
        assert resp.headers.get("Pragma") == "no-cache"
        assert resp.headers.get("Expires") == "0"

    def test_cache_control_on_api_endpoint(self, app_with_default_cors):
        """Regression: /api/* paths still uncacheable after refactor."""
        client = app_with_default_cors.test_client()
        resp = client.get("/api/health")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc
        assert "private" in cc

    def test_cache_control_on_404(self, app_with_default_cors):
        """Even error responses (CASA scanned /robots.txt, /sitemap.xml)
        must not be cacheable."""
        client = app_with_default_cors.test_client()
        resp = client.get("/robots.txt")
        # Whether 404 or other — Cache-Control must be present.
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc, f"404 missing no-store: {cc!r}"
        assert resp.headers.get("Pragma") == "no-cache"
