# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le flow 2-call spécialité de POST /api/refine-text.

Couvre :
- use_specialty=false → flow standard (aucun specialty_info dans la réponse)
- use_specialty=true + aucune spécialité active → warning "no_active_specialty"
- use_specialty=true + actives mais pas de match → warning "no_match"
- use_specialty=true + match → specialty_info complet + applied_sources
  (les sources sont citées INLINE par le LLM, pas en footnote server-side)
- use_specialty=true + Sonnet plan échoue → fallback dégradé avec warning

Le rate limit 3/60s n'est pas testé ici : `_rate_limited` bypass en testing=True
(voir routes_helpers.py).
"""

import time
from unittest.mock import MagicMock, patch

import jwt as _pyjwt
import pytest

from app.api.auth import JWT_ALGORITHM, JWT_SECRET
from app.specialty_engine import SpecialtyMatch


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _auth_headers(email: str = "test@agentys.app", sub: str = "12345") -> dict:
    """Mint a JWT and wrap as Authorization header.

    /api/refine-text is gated by @require_auth (audit-2026-05-11, commit f6e8803b)
    — all tests in this file must pass a valid Bearer token or get 401.
    """
    token = _pyjwt.encode(
        {
            "sub": sub,
            "email": email,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_llm_response(text: str) -> MagicMock:
    """Simule un retour LLMPort.complete() : objet avec .content (str)."""
    r = MagicMock()
    r.content = text
    return r


def _mock_container_with_llms(haiku_text: str, sonnet_text: str = "") -> MagicMock:
    """Container mocké avec llm_drafting (Haiku) et llm_drafting_smart (Sonnet)."""
    c = MagicMock()
    c.llm_drafting.complete.return_value = _make_llm_response(haiku_text)
    c.llm_drafting_smart.complete.return_value = _make_llm_response(sonnet_text)
    c.get_writing_style_profile.return_value = None
    return c


# Sample valid specialty plan (ce que Sonnet renverrait pour un vice caché)
SAMPLE_PLAN = """## Points clés
- Client découvre un vice de pyrite après l'achat
- Besoin d'orientation juridique (notaire/avocat)

## Cadre légal applicable
- CCQ art. 1726-1733 : garantie légale contre les vices cachés
- CCQ art. 1729 : vendeur professionnel présumé connaître le vice

## Ton et formalité
- Professionnel, prudent, non-directif

## Garde-fous obligatoires
- Orienter vers un notaire ou avocat
- Ne pas donner d'avis juridique

## Sources à citer en footnote
CCQ art. 1726-1733, CCQ art. 1729
"""

SAMPLE_DRAFT_INLINE_SOURCES = """Bonjour Marc,

Le vice de pyrite découvert après la vente est exactement le genre de défaut que couvre le régime des vices cachés (arts. 1726-1733 CCQ). Le vendeur, s'il est professionnel, est même présumé l'avoir connu (art. 1729 CCQ) — ce qui renverse la charge de la preuve à votre avantage.

Concrètement, je te suggère de prendre rendez-vous cette semaine avec un avocat en droit immobilier pour structurer la mise en demeure.

Au plaisir,
"""


# ── Tests ───────────────────────────────────────────────────────────────────


class TestRefineTextStandard:
    """use_specialty=false → flow standard, aucun specialty_info."""

    def test_no_specialty_info_in_response(self, client):
        c = _mock_container_with_llms("Texte raffiné standard.")
        with patch("app.api.routes_helpers._get_container", return_value=c):
            resp = client.post(
                "/api/refine-text",
                json={"text": "Bonjour", "instruction": "Rends plus formel"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "specialty_info" not in data
        # Sonnet ne doit PAS avoir été appelé en mode standard
        c.llm_drafting_smart.complete.assert_not_called()


class TestRefineTextExpertNoActive:
    """use_specialty=true + aucune spécialité active → warning no_active_specialty."""

    def test_warning_no_active_specialty(self, client):
        c = _mock_container_with_llms("Texte raffiné.")
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.settings.load_settings", return_value={"active_specialties": []}):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Bonjour",
                    "instruction": "Rends plus formel",
                    "use_specialty": True,
                },
            headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["specialty_info"] == {"warning": "no_active_specialty"}
        # Sonnet ne doit PAS avoir été appelé si pas de spécialité active
        c.llm_drafting_smart.complete.assert_not_called()


class TestRefineTextLoadSettingsAccountScope:
    """Régression : load_settings DOIT être appelé avec account_id.

    Sans cela, les spécialités activées par l'utilisateur via l'UI (stockées
    per-compte dans account.settings_json) sont ignorées, et refine-text
    reporte toujours no_active_specialty sur Railway (fichier global éphémère).
    """

    def test_load_settings_called_with_account_id(self, client):
        c = _mock_container_with_llms("Texte raffiné.")
        mock_load = MagicMock(return_value={"active_specialties": []})
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.routes_helpers._resolve_account_id_for_user", return_value=42), \
             patch("app.api.settings.load_settings", mock_load):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Bonjour",
                    "instruction": "Rends plus formel",
                    "use_specialty": True,
                },
            headers=_auth_headers(),
            )
        assert resp.status_code == 200
        # load_settings doit avoir été appelé avec account_id=42 (pas None)
        # pour récupérer les overrides per-compte en DB.
        mock_load.assert_called_with(account_id=42)


class TestRefineTextExpertForceApply:
    """use_specialty=true + active mais keywords ne matchent pas →
    force l'application via build_default_match (Ctrl+Shift+G = demande
    utilisateur explicite, pas de no_match qui dégrade en générique)."""

    def test_force_apply_when_classifier_returns_none(self, client):
        c = _mock_container_with_llms(
            haiku_text=SAMPLE_DRAFT_INLINE_SOURCES,
            sonnet_text=SAMPLE_PLAN,
        )
        engine = MagicMock()
        engine.classify_email.return_value = None  # no keyword match
        engine.build_default_match.return_value = SpecialtyMatch(
            specialty_id="real-estate-qc",
            specialty_name="Immobilier Québec",
            category="general",
            expert_ids=["legal", "brokerage", "tax_finance"],
            expert_names=["Juridique", "Courtage", "Fiscalité"],
            risk_level="medium",
            confidence=1.0,
            keyword_hits=0,
        )
        engine.build_specialty_context.return_value = (
            "## Directives immobilier QC\n\nExpert context ici..."
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.settings.load_settings",
                   return_value={"active_specialties": ["real-estate-qc"]}), \
             patch("app.specialty_engine.get_specialty_engine", return_value=engine):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Bonjour comment vas-tu",
                    "instruction": "Rends plus formel",
                    "use_specialty": True,
                    "subject": "Hello",
                },
            headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        info = data["specialty_info"]
        # Pas de warning : le match forcé a fonctionné.
        assert "warning" not in info
        assert info["specialty_id"] == "real-estate-qc"
        assert info["category"] == "general"
        assert info["keyword_hits"] == 0  # forced, pas classifié
        # build_default_match appelé avec la 1re spécialité active
        engine.build_default_match.assert_called_once_with("real-estate-qc")
        # Le plan Sonnet DOIT avoir tourné (sinon la spécialité ne sert à rien)
        c.llm_drafting_smart.complete.assert_called_once()

    def test_specialty_unavailable_when_default_match_fails(self, client):
        """Si la spécialité active n'existe plus sur disque (fichiers supprimés
        sans nettoyer settings), build_default_match renvoie None → warning
        spécifique au lieu de crash."""
        c = _mock_container_with_llms("Texte raffiné.")
        engine = MagicMock()
        engine.classify_email.return_value = None
        engine.build_default_match.return_value = None  # spec introuvable
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.settings.load_settings",
                   return_value={"active_specialties": ["ghost-spec"]}), \
             patch("app.specialty_engine.get_specialty_engine", return_value=engine):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Bonjour",
                    "instruction": "Rends plus formel",
                    "use_specialty": True,
                },
            headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["specialty_info"] == {"warning": "specialty_unavailable"}
        c.llm_drafting_smart.complete.assert_not_called()


class TestRefineTextExpertMatch:
    """use_specialty=true + match complet → full specialty_info + plan + footnote."""

    def test_match_returns_full_specialty_info(self, client):
        c = _mock_container_with_llms(
            haiku_text=SAMPLE_DRAFT_INLINE_SOURCES,
            sonnet_text=SAMPLE_PLAN,
        )
        engine = MagicMock()
        engine.classify_email.return_value = SpecialtyMatch(
            specialty_id="real-estate-qc",
            specialty_name="Immobilier Québec",
            category="vice_cache",
            expert_ids=["legal", "construction"],
            expert_names=["Juridique immobilier", "Construction et inspection"],
            risk_level="medium",
            confidence=0.8,
            keyword_hits=4,
        )
        engine.build_specialty_context.return_value = (
            "## Expert legal content here with CCQ art. 1726-1733..."
        )
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.settings.load_settings",
                   return_value={"active_specialties": ["real-estate-qc"]}), \
             patch("app.specialty_engine.get_specialty_engine", return_value=engine):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Mon client a découvert un vice de pyrite",
                    "instruction": "Rédige un email professionnel",
                    "use_specialty": True,
                    "subject": "Vice caché - aide urgente",
                },
            headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.get_json()
        info = data["specialty_info"]
        assert info["specialty_id"] == "real-estate-qc"
        assert info["category"] == "vice_cache"
        assert info["risk_level"] == "medium"
        # applied_sources est exposé pour audit (badge debug, eval), même si
        # la footnote server-side a été retirée — les sources sont attendues
        # INLINE dans la prose Haiku, pas en footer.
        assert "CCQ art. 1726-1733" in info["applied_sources"]
        assert "CCQ art. 1729" in info["applied_sources"]
        assert "## Points clés" in info["plan_preview"]
        # Régression : aucune footnote "--- Sources : …" appendée par le serveur.
        # Le LLM est censé citer les articles inline ; ici notre mock Haiku le
        # fait correctement (cf. SAMPLE_DRAFT_INLINE_SOURCES).
        assert "\n---\nSources :" not in data["refined_text"]
        assert "(arts. 1726-1733 CCQ)" in data["refined_text"]
        # Les DEUX LLMs doivent avoir été appelés
        c.llm_drafting_smart.complete.assert_called_once()
        c.llm_drafting.complete.assert_called_once()


class TestRefineTextExpertSonnetFailure:
    """Si Sonnet plante, fallback vers injection directe de l'expertise dans Haiku."""

    def test_fallback_when_sonnet_fails(self, client):
        c = _mock_container_with_llms(haiku_text="Texte dégradé.")
        c.llm_drafting_smart.complete.side_effect = RuntimeError("Sonnet down")
        engine = MagicMock()
        engine.classify_email.return_value = SpecialtyMatch(
            specialty_id="real-estate-qc",
            specialty_name="Immobilier Québec",
            category="vice_cache",
            expert_ids=["legal"],
            expert_names=["Juridique immobilier"],
            risk_level="low",
            confidence=0.5,
            keyword_hits=2,
        )
        engine.build_specialty_context.return_value = "Expert context"
        with patch("app.api.routes_helpers._get_container", return_value=c), \
             patch("app.api.settings.load_settings",
                   return_value={"active_specialties": ["real-estate-qc"]}), \
             patch("app.specialty_engine.get_specialty_engine", return_value=engine):
            resp = client.post(
                "/api/refine-text",
                json={
                    "text": "Notes sur vice caché",
                    "instruction": "Rédige",
                    "use_specialty": True,
                },
            headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.get_json()
        info = data["specialty_info"]
        assert info["warning"] == "plan_failed_fallback"
        # Haiku doit quand même avoir été appelé (mode dégradé)
        c.llm_drafting.complete.assert_called_once()
