# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour le FileWritingStyleStore."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.entities.writing_style import (
    FormalityLevel,
    ReferenceExample,
    WritingStyleProfile,
)
from app.infrastructure.writing_style_store import FileWritingStyleStore


@pytest.fixture
def temp_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def store(temp_dir):
    """Crée un store avec répertoire temporaire."""
    return FileWritingStyleStore(data_dir=temp_dir)


@pytest.fixture
def sample_profile():
    """Crée un profil exemple."""
    return WritingStyleProfile(
        account_id=1,
        analyzed_at=datetime(2024, 6, 15, 10, 0, 0),
        email_count=10,
        common_words=["bonjour", "merci"],
        avg_sentence_length=15.0,
        formality_level=FormalityLevel.FORMAL,
        preferred_greetings=["Bonjour"],
        preferred_closings=["Cordialement"],
        typical_signature="Jean Dupont",
        avg_email_length=500,
        analysis_duration_ms=1000,
    )


class TestFileWritingStyleStore:
    """Tests pour FileWritingStyleStore."""

    def test_init_creates_directory(self, temp_dir):
        """Test que l'init crée le répertoire."""
        data_dir = temp_dir / "subdir" / "learning"
        FileWritingStyleStore(data_dir=data_dir)
        assert data_dir.exists()

    def test_save_creates_file(self, store, sample_profile, temp_dir):
        """Test que save crée le fichier."""
        result = store.save(sample_profile)

        assert result is True
        filepath = temp_dir / "style_profile_1.json"
        assert filepath.exists()

    def test_save_content_is_valid_json(self, store, sample_profile, temp_dir):
        """Test que le fichier sauvegardé est du JSON valide."""
        store.save(sample_profile)

        filepath = temp_dir / "style_profile_1.json"
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)

        assert data["account_id"] == 1
        assert data["email_count"] == 10
        assert data["formality_level"] == "formal"

    def test_load_returns_profile(self, store, sample_profile):
        """Test que load retourne le profil sauvegardé."""
        store.save(sample_profile)

        loaded = store.load(1)

        assert loaded is not None
        assert loaded.account_id == 1
        assert loaded.email_count == 10
        assert loaded.formality_level == FormalityLevel.FORMAL
        assert loaded.common_words == ["bonjour", "merci"]
        assert loaded.typical_signature == "Jean Dupont"

    def test_load_returns_none_for_nonexistent(self, store):
        """Test que load retourne None si le fichier n'existe pas."""
        loaded = store.load(999)
        assert loaded is None

    def test_load_returns_none_for_invalid_json(self, store, temp_dir):
        """Test que load retourne None si le JSON est invalide."""
        filepath = temp_dir / "style_profile_1.json"
        filepath.write_text("not valid json", encoding="utf-8")

        loaded = store.load(1)
        assert loaded is None

    def test_exists_true_when_file_exists(self, store, sample_profile):
        """Test exists retourne True si le fichier existe."""
        assert store.exists(1) is False

        store.save(sample_profile)

        assert store.exists(1) is True

    def test_exists_false_when_no_file(self, store):
        """Test exists retourne False si pas de fichier."""
        assert store.exists(999) is False

    def test_delete_removes_file(self, store, sample_profile, temp_dir):
        """Test que delete supprime le fichier."""
        store.save(sample_profile)
        filepath = temp_dir / "style_profile_1.json"
        assert filepath.exists()

        result = store.delete(1)

        assert result is True
        assert not filepath.exists()

    def test_delete_returns_false_when_no_file(self, store):
        """Test que delete retourne False si pas de fichier."""
        result = store.delete(999)
        assert result is False

    def test_list_all_returns_account_ids(self, store, temp_dir):
        """Test que list_all retourne les IDs de comptes."""
        # Créer plusieurs profils
        for account_id in [1, 5, 10]:
            profile = WritingStyleProfile(
                account_id=account_id,
                analyzed_at=datetime.now(),
                email_count=5,
            )
            store.save(profile)

        result = store.list_all()

        assert sorted(result) == [1, 5, 10]

    def test_list_all_empty_when_no_profiles(self, store):
        """Test que list_all retourne liste vide sans profils."""
        result = store.list_all()
        assert result == []

    def test_update_overwrites_existing(self, store, sample_profile):
        """Test que update écrase le profil existant."""
        store.save(sample_profile)

        # Modifier le profil
        sample_profile.email_count = 20
        sample_profile.common_words = ["nouveau"]

        result = store.update(sample_profile)

        assert result is True

        loaded = store.load(1)
        assert loaded.email_count == 20
        assert loaded.common_words == ["nouveau"]

    def test_get_or_create_empty_creates_new(self, store):
        """Test que get_or_create_empty crée un profil si inexistant."""
        profile = store.get_or_create_empty(42)

        assert profile.account_id == 42
        assert profile.email_count == 0
        assert store.exists(42) is True

    def test_get_or_create_empty_returns_existing(self, store, sample_profile):
        """Test que get_or_create_empty retourne le profil existant."""
        store.save(sample_profile)

        profile = store.get_or_create_empty(1)

        assert profile.account_id == 1
        assert profile.email_count == 10  # Pas 0

    def test_multiple_accounts_isolation(self, store):
        """Test que les profils de différents comptes sont isolés."""
        profile1 = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=5,
            formality_level=FormalityLevel.FORMAL,
        )
        profile2 = WritingStyleProfile(
            account_id=2,
            analyzed_at=datetime.now(),
            email_count=10,
            formality_level=FormalityLevel.CASUAL,
        )

        store.save(profile1)
        store.save(profile2)

        loaded1 = store.load(1)
        loaded2 = store.load(2)

        assert loaded1.email_count == 5
        assert loaded1.formality_level == FormalityLevel.FORMAL
        assert loaded2.email_count == 10
        assert loaded2.formality_level == FormalityLevel.CASUAL

    def test_special_characters_in_content(self, store):
        """Test que les caractères spéciaux sont correctement gérés."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=5,
            common_words=["été", "français", "naïf"],
            preferred_greetings=["Cher/Chère"],
            typical_signature="Jean-François Müller",
        )

        store.save(profile)
        loaded = store.load(1)

        assert "été" in loaded.common_words
        assert "français" in loaded.common_words
        assert loaded.typical_signature == "Jean-François Müller"

    def test_metadata_only_drops_non_anonymized_reference_examples(
        self,
        store,
        temp_dir,
        monkeypatch,
    ):
        """Les extraits de style non anonymisés ne doivent pas être persistés."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=2,
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Bonjour Alice, secret client alice@example.com",
                    subject="Contrat ACME secret",
                    anonymized=False,
                    word_count=6,
                ),
                ReferenceExample(
                    length_bucket="medium",
                    body_excerpt="Bonjour Alice, contact alice@example.com",
                    subject="Point alice@example.com",
                    anonymized=True,
                    word_count=5,
                    collected_at=datetime.now(timezone.utc).isoformat(),
                    source_email_id="provider-msg-1",
                ),
            ],
        )

        assert store.save(profile) is True

        data = json.loads((temp_dir / "style_profile_1.json").read_text())
        serialized = json.dumps(data, ensure_ascii=False)

        assert len(data["reference_examples"]) == 1
        assert data["reference_examples"][0]["anonymized"] is True
        assert data["reference_examples"][0]["source_email_id"] == "provider-msg-1"
        # Audit regressions (2026-05-18 batch5) F-07: persisted excerpts now
        # always empty — the regex-based scrub used previously was not a
        # content-safety guarantee, and the trip through Drafter prompts
        # opened a self-prompt-injection vector. Metadata (length_bucket,
        # word_count) preserves the style signal without persisting content.
        assert data["reference_examples"][0]["body_excerpt"] == ""
        assert data["reference_examples"][0]["subject"] == ""
        assert "secret client" not in serialized
        assert "alice@example.com" not in serialized

    def test_metadata_only_load_sanitizes_legacy_reference_examples(
        self,
        store,
        temp_dir,
        monkeypatch,
    ):
        """Un fichier legacy sans flag anonymized ne doit pas réhydrater un extrait."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        (temp_dir / "style_profile_1.json").write_text(
            json.dumps({
                "account_id": 1,
                "analyzed_at": "2026-05-15T12:00:00",
                "email_count": 2,
                "reference_examples": [
                    {
                        "length_bucket": "short",
                        "body_excerpt": "Texte legacy confidentiel",
                        "subject": "Sujet legacy",
                        "word_count": 3,
                    },
                    {
                        "length_bucket": "medium",
                        "body_excerpt": "Contact bob@example.com",
                        "subject": "RE: bob@example.com",
                        "anonymized": True,
                        "word_count": 2,
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    },
                ],
            }),
            encoding="utf-8",
        )

        loaded = store.load(1)

        assert loaded is not None
        assert len(loaded.reference_examples) == 1
        # Audit regressions (2026-05-18 batch5) F-07: legacy excerpts get
        # purged on load — the file's stored text is ignored and replaced
        # by empty strings to match the post-batch5 persistence contract.
        assert loaded.reference_examples[0].body_excerpt == ""
        assert loaded.reference_examples[0].subject == ""

    def test_metadata_only_expires_old_reference_examples(
        self,
        store,
        temp_dir,
        monkeypatch,
    ):
        """Les extraits dérivés d'emails sont bornés par la rétention IA."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        monkeypatch.setenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", "30")
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=7,
            formality_score=0.8,
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Ancien exemple anonymisé",
                    subject="Ancien",
                    anonymized=True,
                    word_count=3,
                    collected_at=old,
                ),
                ReferenceExample(
                    length_bucket="medium",
                    body_excerpt="Récent exemple anonymisé",
                    subject="Récent",
                    anonymized=True,
                    word_count=3,
                    collected_at=recent,
                ),
            ],
        )

        assert store.save(profile) is True

        data = json.loads((temp_dir / "style_profile_1.json").read_text())
        assert data["formality_score"] == 0.8
        assert len(data["reference_examples"]) == 1
        # Audit regressions (2026-05-18 batch5) F-07: body/subject persist as
        # empty strings; recency is verified via length_bucket + collected_at.
        assert data["reference_examples"][0]["length_bucket"] == "medium"
        assert data["reference_examples"][0]["body_excerpt"] == ""
        assert data["reference_examples"][0]["subject"] == ""

    def test_metadata_only_drops_undated_reference_examples(
        self,
        store,
        temp_dir,
        monkeypatch,
    ):
        """Un extrait legacy sans timestamp ne doit pas rester indéfiniment."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        (temp_dir / "style_profile_1.json").write_text(
            json.dumps({
                "account_id": 1,
                "analyzed_at": "2026-05-15T12:00:00",
                "email_count": 1,
                "reference_examples": [
                    {
                        "length_bucket": "short",
                        "body_excerpt": "Extrait anonymisé mais non daté",
                        "subject": "Legacy",
                        "anonymized": True,
                        "word_count": 4,
                    },
                ],
            }),
            encoding="utf-8",
        )

        loaded = store.load(1)

        assert loaded is not None
        assert loaded.reference_examples == []

    def test_legacy_full_cache_keeps_expired_reference_examples(
        self,
        store,
        monkeypatch,
    ):
        """Le mode legacy explicite conserve l'ancien comportement."""
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")
        monkeypatch.setenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", "30")
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=1,
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Ancien exemple",
                    subject="Ancien",
                    anonymized=False,
                    word_count=2,
                    collected_at="2000-01-01T00:00:00",
                ),
            ],
        )

        assert store.save(profile) is True
        loaded = store.load(1)

        assert loaded is not None
        assert len(loaded.reference_examples) == 1
        assert loaded.reference_examples[0].body_excerpt == "Ancien exemple"
