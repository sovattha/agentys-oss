"""Privacy regression tests for learned-pattern storage."""

from __future__ import annotations

import json
import threading

import pytest

from app.domain.entities.learning import LearnedPattern, PatternType
from app.infrastructure.adapters.sqlite_learning_store import SqliteLearningPatternStore
from app.infrastructure.learning_store import JsonLearningPatternStore
from app.infrastructure.database import Database


@pytest.fixture
def temp_db(tmp_path):
    Database._initialized = False
    Database._local = threading.local()
    db = Database(tmp_path / "learning-patterns.db")
    yield db
    db.close()


def _private_pattern() -> LearnedPattern:
    return LearnedPattern.create(
        pattern_type=PatternType.BAD,
        trigger="Réponses trop longues",
        correction="Répondre en deux phrases maximum",
        examples=[
            "Bonjour Alice, voici le contexte confidentiel du client ACME...",
            "Comme discuté avec Jean au sujet du contrat privé...",
        ],
    )


def test_save_metadata_only_drops_examples(temp_db, monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    store = SqliteLearningPatternStore(temp_db)

    pattern_id = store.save(_private_pattern())

    row = temp_db.fetchone("SELECT * FROM learned_patterns WHERE id = ?", (pattern_id,))
    assert json.loads(row["examples"]) == []
    assert row["pattern_value"] == "Réponses trop longues"
    assert row["correction"] == "Répondre en deux phrases maximum"

    loaded = store.get_by_id(pattern_id)
    assert loaded is not None
    assert loaded.examples == []
    assert loaded.trigger == "Réponses trop longues"
    assert loaded.correction == "Répondre en deux phrases maximum"


def test_update_metadata_only_drops_examples_from_existing_row(temp_db, monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
    store = SqliteLearningPatternStore(temp_db)
    pattern = _private_pattern()
    pattern_id = store.save(pattern)

    row = temp_db.fetchone("SELECT examples FROM learned_patterns WHERE id = ?", (pattern_id,))
    assert json.loads(row["examples"]) == pattern.examples

    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    pattern.id = pattern_id
    pattern.examples.append("Nouvel exemple privé")

    assert store.update(pattern) is True

    row = temp_db.fetchone("SELECT examples FROM learned_patterns WHERE id = ?", (pattern_id,))
    assert json.loads(row["examples"]) == []
    loaded = store.get_by_id(pattern_id)
    assert loaded is not None
    assert loaded.examples == []


def test_json_save_metadata_only_drops_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    path = tmp_path / "learned_patterns.json"
    store = JsonLearningPatternStore(path)

    pattern_id = store.save(_private_pattern())

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw[0]["examples"] == []

    loaded = store.get_by_id(pattern_id)
    assert loaded is not None
    assert loaded.examples == []
    assert loaded.trigger == "Réponses trop longues"
    assert loaded.correction == "Répondre en deux phrases maximum"


def test_json_metadata_only_rewrites_legacy_examples_on_open(tmp_path, monkeypatch):
    path = tmp_path / "learned_patterns.json"
    legacy = _private_pattern().to_dict()
    path.write_text(json.dumps([legacy]), encoding="utf-8")

    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
    store = JsonLearningPatternStore(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw[0]["examples"] == []

    loaded = store.get_by_id(legacy["id"])
    assert loaded is not None
    assert loaded.examples == []
    assert loaded.trigger == "Réponses trop longues"


def test_json_legacy_full_cache_preserves_examples(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
    path = tmp_path / "learned_patterns.json"
    store = JsonLearningPatternStore(path)
    pattern = _private_pattern()

    pattern_id = store.save(pattern)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw[0]["examples"] == pattern.examples

    loaded = store.get_by_id(pattern_id)
    assert loaded is not None
    assert loaded.examples == pattern.examples
