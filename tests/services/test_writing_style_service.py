# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour le WritingStyleService."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from app.db.models.email import Email
from app.domain.entities.writing_style import FormalityLevel, WritingStyleProfile
from app.domain.ports.writing_style_port import WritingStyleAnalyzerPort, WritingStyleStorePort
from app.domain.services.writing_style_service import WritingStyleService


class MockWritingStyleStore(WritingStyleStorePort):
    """Mock implementation of WritingStyleStorePort."""

    def __init__(self):
        self._profiles: Dict[int, WritingStyleProfile] = {}

    def save(self, profile: WritingStyleProfile) -> bool:
        self._profiles[profile.account_id] = profile
        return True

    def load(self, account_id: int) -> Optional[WritingStyleProfile]:
        return self._profiles.get(account_id)

    def exists(self, account_id: int) -> bool:
        return account_id in self._profiles

    def delete(self, account_id: int) -> bool:
        if account_id in self._profiles:
            del self._profiles[account_id]
            return True
        return False

    def list_all(self) -> List[int]:
        return list(self._profiles.keys())


class MockWritingStyleAnalyzer(WritingStyleAnalyzerPort):
    """Mock implementation of WritingStyleAnalyzerPort."""

    def __init__(self):
        self.analyze_result: Optional[WritingStyleProfile] = None
        self.analyze_single_result: Dict[str, Any] = {}
        self.analyze_called = False
        self.analyze_single_called = False

    async def analyze(
        self,
        account_id: int,
        emails: Sequence[Email],
        timeout_seconds: int = 30,
    ) -> WritingStyleProfile:
        self.analyze_called = True
        if self.analyze_result:
            return self.analyze_result
        return WritingStyleProfile(
            account_id=account_id,
            analyzed_at=datetime.utcnow(),
            email_count=len(emails),
            formality_level=FormalityLevel.FORMAL,
            common_words=["merci", "bonjour"],
            preferred_greetings=["Bonjour"],
            preferred_closings=["Cordialement"],
            analysis_duration_ms=500,
        )

    async def analyze_single(self, email: Email) -> Dict[str, Any]:
        self.analyze_single_called = True
        return self.analyze_single_result or {
            "common_words": ["test"],
            "greetings": ["Salut"],
            "closings": ["A+"],
            "sentence_length": 10.0,
            "email_length": 100,
        }


@pytest.fixture
def mock_store():
    return MockWritingStyleStore()


@pytest.fixture
def mock_analyzer():
    return MockWritingStyleAnalyzer()


@pytest.fixture
def service(mock_analyzer, mock_store):
    return WritingStyleService(analyzer=mock_analyzer, store=mock_store)


@pytest.fixture
def sample_emails():
    """Crée une liste d'emails de test."""
    emails = []
    for i in range(5):
        email = MagicMock(spec=Email)
        email.id = i
        email.subject = f"Test email {i}"
        email.body_text = f"This is the body of email {i}. It has some content."
        email.date = datetime(2024, 1, i + 1)
        email.is_sent = True
        emails.append(email)
    return emails


class TestWritingStyleService:
    """Tests pour WritingStyleService."""

    @pytest.mark.asyncio
    async def test_analyze_and_store_calls_analyzer(self, service, mock_analyzer, sample_emails):
        """Test que analyze_and_store appelle l'analyseur."""
        await service.analyze_and_store(account_id=1, emails=sample_emails)

        assert mock_analyzer.analyze_called is True

    @pytest.mark.asyncio
    async def test_analyze_and_store_saves_profile(self, service, mock_store, sample_emails):
        """Test que analyze_and_store sauvegarde le profil."""
        await service.analyze_and_store(account_id=1, emails=sample_emails)

        assert mock_store.exists(1) is True
        profile = mock_store.load(1)
        assert profile.email_count == 5

    @pytest.mark.asyncio
    async def test_analyze_and_store_returns_profile(self, service, sample_emails):
        """Test que analyze_and_store retourne le profil."""
        profile = await service.analyze_and_store(account_id=1, emails=sample_emails)

        assert profile is not None
        assert profile.account_id == 1

    @pytest.mark.asyncio
    async def test_analyze_and_store_empty_emails_not_saved(self, service, mock_store, mock_analyzer):
        """Test que analyze_and_store avec 0 emails ne sauvegarde pas."""
        mock_analyzer.analyze_result = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=0,
        )

        await service.analyze_and_store(account_id=1, emails=[])

        # Avec email_count=0, le profil ne devrait pas être sauvegardé
        assert mock_store.exists(1) is False

    @pytest.mark.asyncio
    async def test_update_with_sent_email_calls_analyze_single(
        self, service, mock_analyzer, mock_store
    ):
        """Test que update_with_sent_email appelle analyze_single."""
        email = MagicMock(spec=Email)
        email.body_text = "Test email content"

        await service.update_with_sent_email(account_id=1, email=email)

        assert mock_analyzer.analyze_single_called is True

    @pytest.mark.asyncio
    async def test_update_with_sent_email_merges_data(self, service, mock_analyzer, mock_store):
        """Test que update_with_sent_email fusionne les données."""
        # Créer un profil existant
        existing = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
            avg_email_length=100,
            preferred_greetings=["Bonjour"],
        )
        mock_store.save(existing)

        mock_analyzer.analyze_single_result = {
            "common_words": ["nouveau"],
            "greetings": ["Salut"],
            "closings": ["Bye"],
            "sentence_length": 12.0,
            "email_length": 200,
        }

        email = MagicMock(spec=Email)
        email.body_text = "Test"

        profile = await service.update_with_sent_email(account_id=1, email=email)

        assert profile.email_count == 6
        assert "Salut" in profile.preferred_greetings

    @pytest.mark.asyncio
    async def test_update_with_sent_email_creates_new_profile(self, service, mock_analyzer):
        """Test que update_with_sent_email crée un nouveau profil si inexistant."""
        email = MagicMock(spec=Email)
        email.body_text = "Test"

        profile = await service.update_with_sent_email(account_id=99, email=email)

        assert profile.account_id == 99
        assert profile.email_count == 1

    def test_get_profile_returns_existing(self, service, mock_store):
        """Test que get_profile retourne un profil existant."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
        )
        mock_store.save(profile)

        result = service.get_profile(1)

        assert result is not None
        assert result.email_count == 5

    def test_get_profile_returns_none_when_missing(self, service):
        """Test que get_profile retourne None si profil inexistant."""
        result = service.get_profile(999)
        assert result is None

    def test_get_or_create_profile_returns_existing(self, service, mock_store):
        """Test que get_or_create_profile retourne le profil existant."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
        )
        mock_store.save(profile)

        result = service.get_or_create_profile(1)

        assert result.email_count == 5

    def test_get_or_create_profile_creates_new(self, service, mock_store):
        """Test que get_or_create_profile crée un nouveau profil si inexistant."""
        result = service.get_or_create_profile(1)

        assert result.account_id == 1
        assert result.email_count == 0
        assert mock_store.exists(1) is True

    def test_get_prompt_context_returns_context(self, service, mock_store):
        """PR3 follow-up — `get_prompt_context` delegates to the unified
        renderer ``build_style_guidance_from_profile``. The output is the
        continuous-metric narrative + anonymized few-shot, not the legacy
        categorical "Ton formel / Salutations préférées" prose."""
        from app.domain.entities.writing_style import ReferenceExample

        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour"],
            formality_score=0.8,
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Cordialement.",
                    subject="OK",
                    anonymized=True,
                    word_count=1,
                ),
            ],
        )
        mock_store.save(profile)

        context = service.get_prompt_context(1)

        assert "STYLE OBSERVÉ" in context
        assert "Formalité" in context
        assert "<STYLE_EXAMPLES>" in context

    def test_get_prompt_context_empty_when_insufficient(self, service, mock_store):
        """Test que get_prompt_context retourne chaîne vide si profil insuffisant."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=1,  # Moins que le seuil de 3
        )
        mock_store.save(profile)

        context = service.get_prompt_context(1)

        assert context == ""

    def test_get_prompt_context_empty_when_missing(self, service):
        """Test que get_prompt_context retourne chaîne vide si profil manquant."""
        context = service.get_prompt_context(999)
        assert context == ""

    def test_has_sufficient_data_true(self, service, mock_store):
        """Test has_sufficient_data retourne True avec assez d'emails."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
        )
        mock_store.save(profile)

        assert service.has_sufficient_data(1) is True

    def test_has_sufficient_data_false_when_insufficient(self, service, mock_store):
        """Test has_sufficient_data retourne False avec trop peu d'emails."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=2,
        )
        mock_store.save(profile)

        assert service.has_sufficient_data(1) is False

    def test_has_sufficient_data_false_when_missing(self, service):
        """Test has_sufficient_data retourne False si profil manquant."""
        assert service.has_sufficient_data(999) is False

    def test_delete_profile(self, service, mock_store):
        """Test suppression de profil."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.utcnow(),
            email_count=5,
        )
        mock_store.save(profile)

        result = service.delete_profile(1)

        assert result is True
        assert mock_store.exists(1) is False

    def test_delete_profile_returns_false_when_missing(self, service):
        """Test delete_profile retourne False si profil manquant."""
        result = service.delete_profile(999)
        assert result is False

    def test_list_profiles(self, service, mock_store):
        """Test liste des profils."""
        for account_id in [1, 5, 10]:
            profile = WritingStyleProfile(
                account_id=account_id,
                analyzed_at=datetime.utcnow(),
                email_count=5,
            )
            mock_store.save(profile)

        result = service.list_profiles()

        assert sorted(result) == [1, 5, 10]

    def test_get_stats_returns_stats(self, service, mock_store):
        """Test get_stats retourne les statistiques."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime(2024, 6, 15, 10, 0, 0),
            email_count=10,
            formality_level=FormalityLevel.FORMAL,
            avg_sentence_length=15.0,
            avg_email_length=500,
            analysis_duration_ms=1000,
            common_words=["a", "b", "c"],
            preferred_greetings=["Bonjour"],
            preferred_closings=["Cordialement", "Bien à vous"],
        )
        mock_store.save(profile)

        stats = service.get_stats(1)

        assert stats["exists"] is True
        assert stats["email_count"] == 10
        assert stats["is_sufficient"] is True
        assert stats["formality_level"] == "formal"
        assert stats["avg_sentence_length"] == 15.0
        assert stats["avg_email_length"] == 500
        assert stats["analysis_duration_ms"] == 1000
        assert stats["common_words_count"] == 3
        assert stats["greetings_count"] == 1
        assert stats["closings_count"] == 2

    def test_get_stats_returns_empty_stats_when_missing(self, service):
        """Test get_stats retourne stats vides si profil manquant."""
        stats = service.get_stats(999)

        assert stats["exists"] is False
        assert stats["email_count"] == 0
        assert stats["is_sufficient"] is False
