# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression tests — 9-commit auth chain du 2026-04-21.

Ce fichier protège les invariants backend de la chaîne ayant causé
"onboarding figé à 0%" en prod web. Cf. :
  - régression historique : onboarding figé à 0% faute de CORS sur la
    réponse d'auth (chaîne de 9 commits pour la corriger)
  - tasks/lessons.md §"[Architecture] Auth error escalation"

Invariants couverts
-------------------
1. apply_auth_guard bypass OPTIONS (auth.py:190-199, commit dea586d9)
   → Sinon le browser reçoit 401 sans headers CORS sur chaque preflight
     et toute l'app devient injoignable avec "No Access-Control-Allow-Origin".

2. apply_auth_guard bloque non-loopback sans Bearer (auth.py:222-225)
   → Contrôle de base : la protection ne doit pas être assouplie par
     erreur en essayant de fixer (1).

3. apply_auth_guard laisse passer loopback sans Bearer (auth.py:223-226)
   → Mode Tauri desktop trusté : ne doit pas casser en corrigeant (1)/(2).

4. Access-Control-Max-Age: 600 sur les preflights (app.py:238, 268 — commit dea586d9)
   → Sans ce cache, chaque requête API avec X-Account-Id déclenche un
     preflight. Pendant une rotation Railway (~15-30s), le burst de
     preflights noyaute l'edge proxy.

5. Defaults CORS incluent app.agentys.io (app.py:168 — commit ce08f06d)
   → Root cause #1 de l'onboarding 0%. Si quelqu'un nettoie la string
     par défaut, la prod tombe silencieusement dès qu'API_CORS_ORIGINS
     est absent ou reset par un deploy Railway.
"""

import pytest
from flask import Blueprint, Flask, jsonify

from app.api.auth import apply_auth_guard


# ============================================================================
# Group 1 — apply_auth_guard : comportement OPTIONS vs GET/PATCH
# ============================================================================


class TestAuthGuardOptionsBypass:
    """apply_auth_guard doit JAMAIS 401 sur une OPTIONS (cf. auth.py:198)."""

    @pytest.fixture
    def guarded_client(self):
        """Flask app minimal avec un blueprint fraîchement guardé.

        apply_auth_guard est idempotent via `_auth_guard_applied`, donc on
        crée un Blueprint neuf par fixture pour éviter tout état partagé
        entre tests.
        """
        app = Flask(__name__)
        app.config["TESTING"] = True

        bp = Blueprint("regression_guarded", __name__, url_prefix="/api/guarded")

        @bp.route("/ping", methods=["GET", "POST", "PATCH", "DELETE"])
        def ping():
            return jsonify({"ok": True})

        # MUST: apply_auth_guard before register_blueprint (Flask 2.x locks
        # before_request registration after first register_blueprint()).
        apply_auth_guard(bp)
        app.register_blueprint(bp)

        return app.test_client()

    def test_options_preflight_from_browser_never_returns_401(self, guarded_client):
        """OPTIONS sans Authorization depuis une IP non-loopback ≠ 401.

        Régression prod : si ce test échoue, le browser reçoit un 401 sans
        les headers CORS → "No 'Access-Control-Allow-Origin'" cryptique →
        TOUS les endpoints protégés tombent simultanément.
        """
        resp = guarded_client.options(
            "/api/guarded/ping",
            environ_overrides={"REMOTE_ADDR": "185.41.23.7"},
        )
        assert resp.status_code != 401, (
            f"Régression auth_guard : OPTIONS a retourné 401 (body={resp.data!r}). "
            f"Cf. commit dea586d9 + auth.py:198. Le browser strip Authorization "
            f"sur preflight ; un 401 ici drop les headers CORS et tue toute la prod."
        )

    def test_get_without_auth_from_remote_ip_returns_401(self, guarded_client):
        """Contrôle : la protection de base fonctionne toujours pour un GET réel."""
        resp = guarded_client.get(
            "/api/guarded/ping",
            environ_overrides={"REMOTE_ADDR": "185.41.23.7"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        # Audit 2026-05-18 i18n sweep: backend now ships error_code +
        # English fallback (was hardcoded French). Test asserts on the
        # stable error_code, which the FE will translate via
        # i18n.t("errors:not_authenticated").
        assert data and data.get("error_code") == "NOT_AUTHENTICATED"
        assert data.get("error") == "Not authenticated"

    def test_patch_without_auth_from_remote_ip_returns_401(self, guarded_client):
        """PATCH sans Bearer doit être refusé (cf. commit 2c535a0a : createSettingHook
        PATCHait sans Authorization et passait silencieusement).
        """
        resp = guarded_client.patch(
            "/api/guarded/ping",
            environ_overrides={"REMOTE_ADDR": "185.41.23.7"},
            json={"key": "value"},
        )
        assert resp.status_code == 401

    def test_get_without_auth_from_loopback_passes_through(self, guarded_client):
        """Loopback sans Bearer → mode Tauri desktop (trusté via localhost).

        Ce cas ne doit pas régresser en essayant de durcir (1) ou (2).
        """
        resp = guarded_client.get(
            "/api/guarded/ping",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}


# ============================================================================
# Group 2 — CORS : preflight cache + defaults prod
# ============================================================================


@pytest.fixture
def app_with_default_cors(monkeypatch):
    """create_app() avec API_CORS_ORIGINS absent → defaults in-code utilisés.

    On force l'absence de l'env var pour tester le comportement prod worst-case :
    si Railway perd la var (ou si quelqu'un la reset lors d'un deploy), les
    defaults doivent couvrir app.agentys.io.
    """
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

    from app.api.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


class TestCorsPreflightCache:
    """Access-Control-Max-Age: 600 sur les preflights (commit dea586d9)."""

    def test_preflight_from_prod_web_sets_max_age_600(self, app_with_default_cors):
        """OPTIONS depuis app.agentys.io → Access-Control-Max-Age: 600.

        Sans ça, chaque requête avec X-Account-Id re-preflight toutes les
        quelques secondes. Pendant une rotation Railway (~15-30s), le burst
        tombe sur l'edge proxy en 502/CORS fails.
        """
        client = app_with_default_cors.test_client()
        resp = client.options(
            "/api/health",
            headers={"Origin": "https://app.agentys.io"},
        )
        max_age = resp.headers.get("Access-Control-Max-Age")
        assert max_age == "600", (
            f"Access-Control-Max-Age attendu à '600', obtenu {max_age!r}. "
            f"Régression commit dea586d9 : preflight storm pendant rotations Railway."
        )

    def test_preflight_echoes_prod_origin(self, app_with_default_cors):
        """Le preflight doit echo l'Origin (pas de wildcard en mode credentials)."""
        client = app_with_default_cors.test_client()
        resp = client.options(
            "/api/health",
            headers={"Origin": "https://app.agentys.io"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") == "https://app.agentys.io"
        assert resp.headers.get("Access-Control-Allow-Credentials") == "true"
        # X-Account-Id DOIT être dans allow_headers — cf. commentaire app.py:173-176.
        assert "X-Account-Id" in resp.headers.get("Access-Control-Allow-Headers", "")


class TestCorsDefaultOrigins:
    """Defaults in-code doivent couvrir la prod web (commit ce08f06d)."""

    @pytest.mark.parametrize(
        "origin",
        [
            "https://app.agentys.io",   # root cause #1 de l'onboarding 0%
            "https://agentys.io",        # apex
            "https://www.agentys.io",    # www
        ],
    )
    def test_default_origins_allow_prod_web_domains(self, app_with_default_cors, origin):
        """Sans API_CORS_ORIGINS env var, les 3 domaines prod sont acceptés.

        Défense-en-profondeur : si la var Railway est dropée lors d'un deploy,
        le frontend prod doit rester joignable grâce aux defaults in-code.
        """
        client = app_with_default_cors.test_client()
        resp = client.options("/api/health", headers={"Origin": origin})
        assert resp.headers.get("Access-Control-Allow-Origin") == origin, (
            f"Origin {origin} non autorisé par les defaults. "
            f"Régression commit ce08f06d : onboarding figé à 0%."
        )

    def test_unknown_origin_is_not_echoed(self, app_with_default_cors):
        """Sécurité : une origine non-whitelistée ne doit PAS être reflétée,
        même après avoir durci/ajouté les defaults prod.
        """
        client = app_with_default_cors.test_client()
        resp = client.options(
            "/api/health",
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"
