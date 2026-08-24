# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Tests TDD pour la détection passive des nouveaux patterns.

La détection passive identifie automatiquement les patterns récurrents
dans les corrections utilisateur et les marque comme "appris" quand
ils atteignent un seuil de fiabilité (3+ occurrences par défaut).

Ces tests vérifient:
1. Les patterns sont marqués comme "nouvellement fiables" quand ils atteignent le seuil
2. get_newly_reliable_patterns() retourne les patterns non encore notifiés
3. mark_patterns_as_notified() empêche les notifications dupliquées
4. Le seuil de détection est configurable (défaut: 3)
"""

import pytest

from app.draft_correction import DraftCorrectionManager, CorrectionPattern


@pytest.fixture(autouse=True)
def legacy_email_content_storage(monkeypatch):
    """Ces tests couvrent les patterns legacy contenant du texte utilisateur."""
    monkeypatch.setenv("AGENTYS_EMAIL_CONTENT_STORAGE_MODE", "legacy_full_cache")


class TestPassivePatternDetection:
    """Tests pour la détection passive des nouveaux patterns."""

    def setup_method(self):
        """Crée une instance fraîche pour chaque test."""
        self.manager = DraftCorrectionManager()
        self.manager.patterns = []
        self.manager.corrections = []

    def test_pattern_becomes_reliable_at_threshold(self):
        """Un pattern devient fiable quand il atteint 3 occurrences."""
        pattern = CorrectionPattern(
            id="test_1",
            pattern_type="phrase_replacement",
            original_pattern="Cordialement",
            replacement="Bien cordialement",
            occurrences=2,
            confidence=0.4,
        )
        self.manager.patterns.append(pattern)

        reliable_before = self.manager.get_newly_reliable_patterns()
        assert len(reliable_before) == 0

        pattern.occurrences = 3
        pattern.confidence = 0.6

        reliable_after = self.manager.get_newly_reliable_patterns()
        assert len(reliable_after) == 1
        assert reliable_after[0].original_pattern == "Cordialement"

    def test_get_newly_reliable_patterns_excludes_already_notified(self):
        """Les patterns déjà notifiés ne sont pas retournés."""
        pattern = CorrectionPattern(
            id="test_2",
            pattern_type="tone_adjustment",
            original_pattern="formel",
            replacement="informel",
            occurrences=5,
            confidence=1.0,
        )
        self.manager.patterns.append(pattern)

        reliable = self.manager.get_newly_reliable_patterns()
        assert len(reliable) == 1

        self.manager.mark_patterns_as_notified([pattern.id])

        reliable_after = self.manager.get_newly_reliable_patterns()
        assert len(reliable_after) == 0

    def test_mark_patterns_as_notified_persists(self):
        """Le marquage des patterns notifiés est persistant."""
        pattern = CorrectionPattern(
            id="test_3",
            pattern_type="phrase_replacement",
            original_pattern="Bonjour",
            replacement="Salut",
            occurrences=4,
            confidence=0.8,
        )
        self.manager.patterns.append(pattern)

        self.manager.mark_patterns_as_notified([pattern.id])

        reloaded = self.manager.get_newly_reliable_patterns()
        assert len(reloaded) == 0

    def test_custom_reliability_threshold(self):
        """Le seuil de fiabilité peut être personnalisé."""
        pattern = CorrectionPattern(
            id="test_4",
            pattern_type="phrase_replacement",
            original_pattern="Merci",
            replacement="Je vous remercie",
            occurrences=2,
            confidence=0.4,
        )
        self.manager.patterns.append(pattern)

        default_reliable = self.manager.get_newly_reliable_patterns()
        assert len(default_reliable) == 0

        custom_reliable = self.manager.get_newly_reliable_patterns(min_occurrences=2)
        assert len(custom_reliable) == 1

    def test_multiple_patterns_reach_threshold_simultaneously(self):
        """Plusieurs patterns peuvent devenir fiables en même temps."""
        patterns = [
            CorrectionPattern(
                id="multi_1",
                pattern_type="phrase_replacement",
                original_pattern="Ok",
                replacement="D'accord",
                occurrences=3,
                confidence=0.6,
            ),
            CorrectionPattern(
                id="multi_2",
                pattern_type="phrase_replacement",
                original_pattern="Cdt",
                replacement="Cordialement",
                occurrences=4,
                confidence=0.8,
            ),
            CorrectionPattern(
                id="multi_3",
                pattern_type="phrase_replacement",
                original_pattern="test",
                replacement="Test",
                occurrences=1,
                confidence=0.2,
            ),
        ]
        self.manager.patterns.extend(patterns)

        reliable = self.manager.get_newly_reliable_patterns()
        assert len(reliable) == 2

    def test_pattern_notified_flag_added_to_dataclass(self):
        """CorrectionPattern a un attribut notified."""
        pattern = CorrectionPattern(
            id="test_flag",
            pattern_type="phrase_replacement",
            original_pattern="test",
            replacement="Test",
            occurrences=3,
            confidence=0.6,
        )
        assert hasattr(pattern, "notified")
        assert pattern.notified is False


class TestPatternDetectionIntegration:
    """Tests d'intégration pour la détection passive."""

    def setup_method(self):
        """Crée une instance fraîche pour chaque test."""
        self.manager = DraftCorrectionManager()
        self.manager.patterns = []
        self.manager.corrections = []

    def test_learning_correction_triggers_detection(self):
        """L'enregistrement de corrections détecte les nouveaux patterns fiables."""
        for i in range(3):
            self.manager._add_or_update_pattern(
                pattern_type="phrase_replacement",
                original="Cdt",
                replacement="Cordialement",
                context={"email_type": "professionnel"},
            )

        reliable = self.manager.get_newly_reliable_patterns()
        assert len(reliable) == 1
        assert reliable[0].original_pattern == "Cdt"

    def test_get_pattern_summary_for_notification(self):
        """Génère un résumé lisible des patterns pour notification."""
        pattern = CorrectionPattern(
            id="summary_test",
            pattern_type="phrase_replacement",
            original_pattern="asap",
            replacement="dès que possible",
            occurrences=5,
            confidence=1.0,
        )
        self.manager.patterns.append(pattern)

        reliable = self.manager.get_newly_reliable_patterns()
        summaries = self.manager.get_pattern_summaries(reliable)

        assert len(summaries) == 1
        assert "asap" in summaries[0]
        assert "dès que possible" in summaries[0]
