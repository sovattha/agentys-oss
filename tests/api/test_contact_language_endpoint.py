# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests pour GET /api/contact-language — hint langue Whisper.

Ce endpoint est consommé par `useContactLanguage()` côté frontend pour passer
un `lang=` à `/api/transcribe` au lieu de l'auto-detect (qui ajoute 2-4s
sur audio court).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_container_with_profile(contact_profiles: dict):
    """Container DI qui retourne un Profile avec les contact_profiles donnés."""
    container = MagicMock()
    profile = MagicMock()
    profile.contact_profiles = contact_profiles
    container.get_writing_style_store.return_value.load.return_value = profile
    return container


class TestContactLanguageEndpoint:
    def test_returns_language_from_langue_variante(self, client):
        """`langue_variante=fr-CA` → renvoie `fr` (extraction du code à 2 lettres)."""
        container = _mock_container_with_profile({
            "alice@example.com": {"langue_variante": "fr-CA", "nickname": "Ali"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=alice@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": "fr"}

    def test_returns_language_from_langue_field(self, client):
        """Pas de `langue_variante` mais `langue=en` → renvoie `en`."""
        container = _mock_container_with_profile({
            "bob@example.com": {"langue": "en"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=bob@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": "en"}

    def test_unsupported_code_returns_null(self, client):
        """`xx` (code inconnu) → null pour ne pas faire exploser Whisper."""
        container = _mock_container_with_profile({
            "carol@example.com": {"langue": "xx"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=carol@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}

    def test_unknown_contact_returns_null(self, client):
        """Contact pas dans `contact_profiles` → null."""
        container = _mock_container_with_profile({
            "alice@example.com": {"langue": "fr"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=stranger@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}

    def test_no_account_returns_null(self, client):
        """Account_id non résolu (user pas authentifié) → null sans crash.

        Prod returns int -1 sentinel from _resolve_account_id_for_user (see
        routes_helpers.py:541). The previous mock return_value=None / "42"
        drifted from this contract — `bool(-1)` is True so the
        `if not account_id` guard never fired in prod (F-03).
        """
        with patch("app.api.routes_helpers._get_container", return_value=MagicMock()), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=-1):
            resp = client.get("/api/contact-language?email=alice@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}

    def test_zero_account_returns_null(self, client):
        """Account_id == 0 (corruption rare) → null."""
        with patch("app.api.routes_helpers._get_container", return_value=MagicMock()), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=0):
            resp = client.get("/api/contact-language?email=alice@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}

    def test_empty_email_param_returns_null(self, client):
        """Param `email` vide → null sans toucher la DB (early return)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            resp = client.get("/api/contact-language?email=")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}
        mock_container.assert_not_called()  # Pas de fetch DB

    def test_invalid_email_returns_null(self, client):
        """Param sans `@` → null (validation primitive)."""
        with patch("app.api.routes_helpers._get_container") as mock_container:
            resp = client.get("/api/contact-language?email=notanemail")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}
        mock_container.assert_not_called()

    def test_email_case_normalized(self, client):
        """Lookup case-insensitive : `Alice@EXAMPLE.com` matche `alice@example.com`."""
        container = _mock_container_with_profile({
            "alice@example.com": {"langue": "fr"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=Alice@EXAMPLE.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": "fr"}

    def test_display_name_email_extracted(self, client):
        """F-04: `Alex Smith <alex@example.com>` (Gmail display-name format)
        must extract the bracketed address before DB lookup."""
        container = _mock_container_with_profile({
            "alex@example.com": {"langue": "fr"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get(
                "/api/contact-language?email=Alex%20Smith%20%3Calex%40example.com%3E"
            )

        assert resp.status_code == 200
        assert resp.get_json() == {"language": "fr"}

    def test_db_exception_returns_null_not_500(self, client):
        """Exception DB inattendue → null, pas de 500. Le hint est best-effort,
        la dictée doit toujours marcher (auto-detect fallback côté Whisper)."""
        container = MagicMock()
        container.get_writing_style_store.side_effect = RuntimeError("DB locked")
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=alice@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": None}

    def test_variant_takes_priority_over_langue(self, client):
        """Si les deux fields sont présents, `langue_variante` gagne."""
        container = _mock_container_with_profile({
            "alice@example.com": {"langue_variante": "es-MX", "langue": "fr"},
        })
        with patch("app.api.routes_helpers._get_container", return_value=container), \
             patch("app.api.routes_helpers._resolve_account_id_cached", return_value=42):
            resp = client.get("/api/contact-language?email=alice@example.com")

        assert resp.status_code == 200
        assert resp.get_json() == {"language": "es"}
