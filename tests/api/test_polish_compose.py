# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
POST /api/voice/polish-compose — reformulation du corps dicté (compose mobile).

Device 2026-08-03 : « coucou comment ça va » partait VERBATIM dans l'email —
le compose n'avait aucune passe de reformulation (contrairement au drive qui
passe par le Drafter). Contrat clé : l'endpoint ne BLOQUE jamais l'envoi —
toute erreur LLM (clé absente, exception, JSON invalide) renvoie 200 avec le
texte brut en fallback.
"""

import pytest
from unittest.mock import Mock, patch

pytest.importorskip("flask_cors")


@pytest.fixture
def app():
    from app.api.app import create_app
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_anthropic_returning(text: str):
    """Client anthropic mocké dont messages.create renvoie `text`."""
    block = Mock()
    block.text = text
    response = Mock()
    response.content = [block]
    instance = Mock()
    instance.messages.create.return_value = response
    return Mock(return_value=instance)


def test_transcript_manquant_400(client):
    resp = client.post("/api/voice/polish-compose", json={})
    assert resp.status_code == 400


def test_reformule_le_corps(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic", _mock_anthropic_returning("Coucou, comment ça va ?")):
        resp = client.post(
            "/api/voice/polish-compose",
            json={"transcript": "coucou comment ça va"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["body"] == "Coucou, comment ça va ?"


def test_erreur_llm_fallback_texte_brut(client, monkeypatch):
    # L'envoi ne doit JAMAIS être bloqué par la reformulation.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    boom = Mock(side_effect=RuntimeError("LLM down"))
    with patch("anthropic.Anthropic", boom):
        resp = client.post(
            "/api/voice/polish-compose",
            json={"transcript": "coucou comment ça va"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["body"] == "coucou comment ça va"


def test_cle_absente_fallback_texte_brut(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/voice/polish-compose",
        json={"transcript": "je rentre ce soir"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["body"] == "je rentre ce soir"
