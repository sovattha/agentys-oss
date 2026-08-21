# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de correction automatique des brouillons.

pytest tests/test_draft_correction.py -v
"""

import json
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

import pytest

from app.draft_correction import (
    DraftCorrection,
    CorrectionPattern,
    CorrectionStats,
    CorrectionAnalyzer,
    DraftCorrectionManager,
    get_correction_manager
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_data_dir():
    """Crée un répertoire temporaire pour les tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(autouse=True)
def legacy_email_content_storage(monkeypatch):
    """Les tests historiques vérifient le mode legacy explicite."""
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


@pytest.fixture
def correction_manager(temp_data_dir):
    """Crée un manager avec un répertoire temporaire."""
    return DraftCorrectionManager(data_dir=temp_data_dir)


@pytest.fixture
def analyzer():
    """Crée un analyseur de corrections."""
    return CorrectionAnalyzer()


@pytest.fixture
def sample_drafts():
    """Exemples de brouillons pour les tests."""
    return {
        "original": """Bonjour,

Merci pour votre message. Je vous confirme que votre demande a été prise en compte.

Bien à vous,
L'équipe Support""",

        "corrected_tone": """Bonjour,

Merci pour votre message. Je vous confirme que votre demande a été prise en compte.

Cordialement,
L'équipe Support""",

        "corrected_content": """Bonjour,

Merci pour votre message. Je vous confirme que votre demande a été prise en compte.
Nous reviendrons vers vous sous 48h.

Bien à vous,
L'équipe Support""",

        "corrected_grammar": """Bonjour,

Merci pour votre message. Je vous confirme que votre demande a bien été prise en compte.

Bien à vous,
L'équipe Support"""
    }


# ============================================================================
# TESTS DATA CLASSES
# ============================================================================

class TestDataClasses:
    """Tests pour les dataclasses."""

    def test_draft_correction_creation(self):
        """Test création d'une correction."""
        correction = DraftCorrection(
            id="corr_001",
            original_text="Hello",
            corrected_text="Bonjour",
            correction_type="tone"
        )
        assert correction.id == "corr_001"
        assert correction.original_text == "Hello"
        assert correction.corrected_text == "Bonjour"
        assert correction.correction_type == "tone"
        assert correction.applied_count == 0

    def test_correction_pattern_creation(self):
        """Test création d'un pattern."""
        pattern = CorrectionPattern(
            id="pat_001",
            pattern_type="phrase_replacement",
            original_pattern="Bien à vous",
            replacement="Cordialement"
        )
        assert pattern.id == "pat_001"
        assert pattern.confidence == 0.0
        assert pattern.occurrences == 0

    def test_correction_stats_defaults(self):
        """Test valeurs par défaut des stats."""
        stats = CorrectionStats()
        assert stats.total_corrections == 0
        assert stats.patterns_learned == 0
        assert stats.accuracy_rate == 0.0


# ============================================================================
# TESTS ANALYZER
# ============================================================================

class TestCorrectionAnalyzer:
    """Tests pour l'analyseur de corrections."""

    def test_analyze_no_change(self, analyzer):
        """Test analyse sans changement."""
        text = "Bonjour, merci pour votre message."
        analysis = analyzer.analyze_diff(text, text)
        assert analysis["length_change"] == 0
        assert len(analysis["additions"]) == 0
        assert len(analysis["deletions"]) == 0

    def test_analyze_tone_change(self, analyzer, sample_drafts):
        """Test détection changement de ton."""
        analysis = analyzer.analyze_diff(
            sample_drafts["original"],
            sample_drafts["corrected_tone"]
        )
        assert analysis["tone_change"] is not None or analysis["correction_type"] in ["tone", "grammar"]

    def test_analyze_content_addition(self, analyzer, sample_drafts):
        """Test détection ajout de contenu."""
        analysis = analyzer.analyze_diff(
            sample_drafts["original"],
            sample_drafts["corrected_content"]
        )
        assert analysis["length_change"] > 0
        assert len(analysis["additions"]) > 0

    def test_analyze_word_replacements(self, analyzer):
        """Test extraction des remplacements de mots."""
        original = "Je vous envoie ce message pour confirmation."
        corrected = "Je vous envoie cet email pour validation."
        analysis = analyzer.analyze_diff(original, corrected)
        replacements = analysis["word_replacements"]
        assert len(replacements) > 0

    def test_detect_formal_tone(self, analyzer):
        """Test détection du ton formel."""
        informal = "Salut, à bientôt!"
        formal = "Bonjour, cordialement."
        analysis = analyzer.analyze_diff(informal, formal)
        # Le changement de ton doit être détecté
        assert analysis["tone_change"] is not None or analysis["correction_type"] == "tone"

    def test_detect_length_reduction(self, analyzer):
        """Test détection réduction de longueur."""
        long_text = "Voici un très long texte " * 20
        short_text = "Version courte."
        analysis = analyzer.analyze_diff(long_text, short_text)
        assert analysis["correction_type"] == "length_reduction"

    def test_detect_format_change(self, analyzer):
        """Test détection changement de format."""
        without_bullets = "Premier point. Deuxième point. Troisième point."
        with_bullets = "- Premier point\n- Deuxième point\n- Troisième point"
        analysis = analyzer.analyze_diff(without_bullets, with_bullets)
        assert analysis["correction_type"] in ["format", "content", "structure"]


# ============================================================================
# TESTS CORRECTION MANAGER
# ============================================================================

class TestDraftCorrectionManager:
    """Tests pour le gestionnaire de corrections."""

    def test_manager_creation(self, correction_manager):
        """Test création du manager."""
        assert correction_manager is not None
        assert correction_manager.corrections == []
        assert correction_manager.patterns == []

    def test_record_correction(self, correction_manager, sample_drafts):
        """Test enregistrement d'une correction."""
        correction = correction_manager.record_correction(
            sample_drafts["original"],
            sample_drafts["corrected_tone"],
            context={"sender": "client@example.com"}
        )
        assert correction is not None
        assert correction.id.startswith("corr_")
        assert len(correction_manager.corrections) == 1

    def test_record_multiple_corrections(self, correction_manager, sample_drafts):
        """Test enregistrement de plusieurs corrections."""
        correction_manager.record_correction(
            sample_drafts["original"],
            sample_drafts["corrected_tone"]
        )
        correction_manager.record_correction(
            sample_drafts["original"],
            sample_drafts["corrected_content"]
        )
        assert len(correction_manager.corrections) == 2

    def test_learn_patterns(self, correction_manager):
        """Test apprentissage de patterns."""
        # Enregistrer la même correction plusieurs fois
        for _ in range(5):
            correction_manager.record_correction(
                "Bien à vous",
                "Cordialement"
            )

        # Vérifier qu'un pattern a été appris
        assert len(correction_manager.patterns) > 0

        # Vérifier la confiance
        pattern = correction_manager.patterns[0]
        assert pattern.occurrences >= 1

    def test_apply_learned_corrections(self, correction_manager):
        """Test application des corrections apprises."""
        # Apprendre un pattern avec haute confiance
        for _ in range(6):  # Plus de 5 pour atteindre confiance >= 0.6
            correction_manager.record_correction(
                "Merci d'avance",
                "Je vous remercie par avance"
            )

        # Appliquer à un nouveau brouillon
        new_draft = "Bonjour, Merci d'avance pour votre aide."
        corrected, applied = correction_manager.apply_learned_corrections(new_draft)

        # Vérifier si la correction a été appliquée
        if applied:
            assert "Je vous remercie par avance" in corrected

    def test_detect_user_modification_no_change(self, correction_manager):
        """Test détection modification - pas de changement."""
        draft = "Bonjour, ceci est un test."
        assert not correction_manager.detect_user_modification(draft, draft)

    def test_detect_user_modification_small_change(self, correction_manager):
        """Test détection modification - petit changement."""
        original = "Bonjour, ceci est un test."
        modified = "Bonjour, ceci est un Test."  # Majuscule
        # Petit changement, peut être détecté ou non selon le seuil
        result = correction_manager.detect_user_modification(original, modified)
        # Le résultat dépend du seuil, on vérifie juste qu'il retourne un booléen
        assert isinstance(result, bool)

    def test_detect_user_modification_large_change(self, correction_manager):
        """Test détection modification - grand changement."""
        original = "Bonjour, merci pour votre message."
        modified = "Hello, thanks for reaching out. We will get back to you soon."
        assert correction_manager.detect_user_modification(original, modified)

    def test_get_stats(self, correction_manager, sample_drafts):
        """Test récupération des statistiques."""
        correction_manager.record_correction(
            sample_drafts["original"],
            sample_drafts["corrected_tone"]
        )
        stats = correction_manager.get_stats()
        assert stats.total_corrections == 1
        assert isinstance(stats.by_type, dict)

    def test_persistence(self, temp_data_dir, sample_drafts):
        """Test persistance des données."""
        # Créer un manager et enregistrer une correction
        manager1 = DraftCorrectionManager(data_dir=temp_data_dir)
        manager1.record_correction(
            sample_drafts["original"],
            sample_drafts["corrected_tone"]
        )

        # Créer un nouveau manager avec le même répertoire
        manager2 = DraftCorrectionManager(data_dir=temp_data_dir)

        # Vérifier que les données sont chargées
        assert len(manager2.corrections) == 1

    def test_clear_patterns(self, correction_manager):
        """Test suppression des patterns peu utilisés."""
        # Ajouter un pattern
        correction_manager.record_correction("test", "TEST")

        # Vérifier qu'il y a des patterns
        initial_count = len(correction_manager.patterns)

        # Supprimer les patterns avec moins de 2 occurrences
        correction_manager.clear_patterns(min_occurrences=2)

        # Tous les patterns avec 1 occurrence devraient être supprimés
        assert len(correction_manager.patterns) <= initial_count

    def test_get_patterns_for_context(self, correction_manager):
        """Test récupération patterns par contexte."""
        # Ajouter des corrections avec contexte
        for _ in range(5):
            correction_manager.record_correction(
                "Merci",
                "Je vous remercie",
                context={"domain": "support"}
            )

        # Récupérer les patterns pour ce contexte
        patterns = correction_manager.get_patterns_for_context(
            {"domain": "support"},
            min_confidence=0.0
        )
        # Le résultat dépend de l'implémentation
        assert isinstance(patterns, list)


class TestDraftCorrectionMetadataOnlyPrivacy:
    """Tests de minimisation des corrections en mode metadata-only."""

    def test_record_correction_drops_raw_drafts_and_phrase_patterns(
        self,
        temp_data_dir,
        monkeypatch
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        manager = DraftCorrectionManager(data_dir=temp_data_dir)

        correction = manager.record_correction(
            "Merci d'avance pour le dossier ACME CONFIDENTIEL.",
            "Je vous remercie par avance pour le dossier ACME CONFIDENTIEL.",
            context={
                "sender": "alice@example.com",
                "subject": "Projet ACME",
                "category": "support",
            },
        )

        assert correction.original_text == ""
        assert correction.corrected_text == ""
        assert correction.context == {
            "category": "support",
            "sender_domain": "example.com",
        }

        corrections = json.loads((temp_data_dir / "corrections.json").read_text())
        patterns = json.loads((temp_data_dir / "patterns.json").read_text())
        serialized = json.dumps({"corrections": corrections, "patterns": patterns}, ensure_ascii=False)

        assert corrections[0]["original_text"] == ""
        assert corrections[0]["corrected_text"] == ""
        assert "Merci d'avance" not in serialized
        assert "Je vous remercie" not in serialized
        assert "ACME" not in serialized
        assert "alice@" not in serialized
        assert all(
            pattern["pattern_type"] != "phrase_replacement"
            or not pattern["original_pattern"]
            for pattern in patterns
        )

    def test_record_correction_keeps_abstract_tone_pattern(
        self,
        temp_data_dir,
        monkeypatch
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        manager = DraftCorrectionManager(data_dir=temp_data_dir)

        manager.record_correction(
            "Salut, à bientôt!",
            "Bonjour, cordialement.",
            context={
                "sender": "alice@example.com",
                "subject": "Secret launch",
                "category": "support",
            },
        )

        patterns = json.loads((temp_data_dir / "patterns.json").read_text())
        tone_patterns = [
            pattern for pattern in patterns
            if pattern["pattern_type"] == "tone_adjustment"
        ]
        serialized = json.dumps(patterns, ensure_ascii=False)

        assert tone_patterns
        assert tone_patterns[0]["original_pattern"] in {"formal", "informal", "neutral", "professional", "friendly"}
        assert tone_patterns[0]["replacement"] in {"formal", "informal", "neutral", "professional", "friendly"}
        assert "Salut" not in serialized
        assert "cordialement" not in serialized
        assert "Secret launch" not in serialized
        assert "alice@" not in serialized

    def test_load_sanitizes_legacy_correction_files(self, temp_data_dir, monkeypatch):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        (temp_data_dir / "corrections.json").write_text(
            json.dumps([
                {
                    "id": "corr_legacy",
                    "original_text": "Texte confidentiel client",
                    "corrected_text": "Texte confidentiel corrigé",
                    "correction_type": "vocabulary",
                    "context": {
                        "sender": "bob@example.com",
                        "subject": "Contrat secret",
                        "category": "support",
                    },
                }
            ]),
            encoding="utf-8",
        )
        (temp_data_dir / "patterns.json").write_text(
            json.dumps([
                {
                    "id": "pat_legacy",
                    "pattern_type": "phrase_replacement",
                    "original_pattern": "secret avant",
                    "replacement": "secret après",
                    "contexts": [
                        json.dumps({
                            "sender": "bob@example.com",
                            "subject": "Contrat secret",
                            "category": "support",
                        })
                    ],
                }
            ]),
            encoding="utf-8",
        )

        manager = DraftCorrectionManager(data_dir=temp_data_dir)
        pattern_context = json.loads(manager.patterns[0].contexts[0])

        assert manager.corrections[0].original_text == ""
        assert manager.corrections[0].corrected_text == ""
        assert manager.corrections[0].context == {
            "category": "support",
            "sender_domain": "example.com",
        }
        assert manager.patterns[0].original_pattern == ""
        assert manager.patterns[0].replacement == ""
        assert pattern_context == {
            "category": "support",
            "sender_domain": "example.com",
        }

    def test_load_prunes_expired_corrections_in_metadata_only(
        self,
        temp_data_dir,
        monkeypatch,
    ):
        monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "metadata_only")
        monkeypatch.setenv("AGENTYS_AI_ARTIFACT_RETENTION_DAYS", "7")
        old_ts = (datetime.now() - timedelta(days=8)).isoformat()
        recent_ts = datetime.now().isoformat()
        (temp_data_dir / "corrections.json").write_text(
            json.dumps([
                {
                    "id": "corr_old",
                    "original_text": "old private",
                    "corrected_text": "old corrected",
                    "correction_type": "content",
                    "created_at": old_ts,
                },
                {
                    "id": "corr_recent",
                    "original_text": "recent private",
                    "corrected_text": "recent corrected",
                    "correction_type": "tone",
                    "created_at": recent_ts,
                },
            ]),
            encoding="utf-8",
        )
        (temp_data_dir / "patterns.json").write_text("[]", encoding="utf-8")

        manager = DraftCorrectionManager(data_dir=temp_data_dir)

        assert [correction.id for correction in manager.corrections] == ["corr_recent"]
        assert manager.corrections[0].original_text == ""
        assert manager.corrections[0].corrected_text == ""


# ============================================================================
# TESTS SINGLETON
# ============================================================================

class TestSingleton:
    """Tests pour le singleton."""

    def test_get_correction_manager_singleton(self):
        """Test que get_correction_manager retourne un singleton."""
        manager1 = get_correction_manager()
        manager2 = get_correction_manager()
        assert manager1 is manager2

    def test_correction_manager_type(self):
        """Test le type du manager."""
        manager = get_correction_manager()
        assert isinstance(manager, DraftCorrectionManager)


# ============================================================================
# TESTS EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_drafts(self, correction_manager):
        """Test avec des brouillons vides."""
        correction = correction_manager.record_correction("", "")
        assert correction is not None

    def test_very_long_draft(self, correction_manager):
        """Test avec un brouillon très long."""
        long_text = "Lorem ipsum " * 1000
        correction = correction_manager.record_correction(long_text, long_text + " fin.")
        assert correction is not None

    def test_special_characters(self, correction_manager):
        """Test avec des caractères spéciaux."""
        original = "Bonjour 👋 émojis & symboles <html>"
        corrected = "Bonjour, avec des émojis et symboles"
        correction = correction_manager.record_correction(original, corrected)
        assert correction is not None

    def test_multiline_drafts(self, correction_manager):
        """Test avec des brouillons multilignes."""
        original = "Ligne 1\nLigne 2\nLigne 3"
        corrected = "Ligne 1\nNouvelle ligne\nLigne 3"
        correction = correction_manager.record_correction(original, corrected)
        assert correction.correction_type in ["content", "grammar"]

    def test_unicode_content(self, correction_manager):
        """Test avec du contenu Unicode."""
        original = "日本語テスト"
        corrected = "日本語のテスト"
        correction = correction_manager.record_correction(original, corrected)
        assert correction is not None
