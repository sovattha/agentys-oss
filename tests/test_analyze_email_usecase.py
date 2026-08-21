# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests unitaires pour les use cases d'analyse d'email."""

from unittest.mock import MagicMock

from app.domain.entities import (
    Email, Classification, EmailCategory, Priority, EmailAnalysis,
)
from app.domain.ports import ClassifierPort, PrioritizationPort
from app.application.analyze_email import (
    ClassifyEmailUseCase,
    PrioritizeEmailUseCase,
    AnalyzeEmailUseCase,
)


# --- Helpers ---

def _make_email(**overrides) -> Email:
    defaults = dict(
        id="email-analysis-001",
        subject="Facture impayée",
        body="Merci de régler la facture #1234 au plus vite.",
        sender="comptabilite@fournisseur.com",
    )
    defaults.update(overrides)
    return Email(**defaults)


def _make_classification(
    category=EmailCategory.URGENT, confidence=0.9, reason="Facture impayée"
) -> Classification:
    return Classification(category=category, confidence=confidence, reason=reason)


def _make_priority(urgency=80, vip=60, sentiment=-0.3, priority_score=70) -> Priority:
    return Priority(
        urgency=urgency, vip=vip, sentiment=sentiment,
        deadline=None, priority_score=priority_score
    )


# --- ClassifyEmailUseCase ---

class TestClassifyEmailUseCase:
    """Tests pour la classification d'emails."""

    def test_execute_delegates_to_classifier(self):
        """execute() délègue au ClassifierPort."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification()
        uc = ClassifyEmailUseCase(classifier=classifier)
        email = _make_email()

        result = uc.execute(email)

        classifier.classify.assert_called_once_with(email, False)
        assert isinstance(result, Classification)
        assert result.category == EmailCategory.URGENT

    def test_execute_passes_is_cc_flag(self):
        """execute() transmet le flag is_cc."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification(
            category=EmailCategory.CC_ONLY
        )
        uc = ClassifyEmailUseCase(classifier=classifier)

        uc.execute(_make_email(), is_cc=True)

        classifier.classify.assert_called_once_with(_make_email(), True)

    def test_execute_returns_classifier_result(self):
        """Le résultat est exactement celui du classifier."""
        expected = _make_classification(
            category=EmailCategory.NEWSLETTER, confidence=0.95, reason="Digest hebdo"
        )
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = expected
        uc = ClassifyEmailUseCase(classifier=classifier)

        result = uc.execute(_make_email())

        assert result is expected


# --- PrioritizeEmailUseCase ---

class TestPrioritizeEmailUseCase:
    """Tests pour la priorisation d'emails."""

    def test_execute_delegates_to_prioritizer(self):
        """execute() délègue au PrioritizationPort."""
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority()
        uc = PrioritizeEmailUseCase(prioritizer=prioritizer)
        email = _make_email()

        result = uc.execute(email)

        prioritizer.analyze.assert_called_once_with(email)
        assert isinstance(result, Priority)

    def test_execute_returns_prioritizer_result(self):
        """Le résultat est celui du prioritizer."""
        expected = _make_priority(urgency=30, priority_score=25)
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = expected
        uc = PrioritizeEmailUseCase(prioritizer=prioritizer)

        result = uc.execute(_make_email())

        assert result is expected


# --- AnalyzeEmailUseCase ---

class TestAnalyzeEmailUseCase:
    """Tests pour l'analyse combinée (classification + priorité)."""

    def test_execute_combines_classification_and_priority(self):
        """execute() retourne un EmailAnalysis avec les deux résultats."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification()
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority()
        uc = AnalyzeEmailUseCase(classifier=classifier, prioritizer=prioritizer)
        email = _make_email()

        result = uc.execute(email)

        assert isinstance(result, EmailAnalysis)
        assert result.email_id == email.id
        assert result.classification.category == EmailCategory.URGENT
        assert result.priority.urgency == 80

    def test_execute_passes_is_cc_to_classifier(self):
        """execute() passe is_cc au classifier mais pas au prioritizer."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification()
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority()
        uc = AnalyzeEmailUseCase(classifier=classifier, prioritizer=prioritizer)

        uc.execute(_make_email(), is_cc=True)

        classifier.classify.assert_called_once()
        _, kwargs = classifier.classify.call_args
        # is_cc should be True
        assert classifier.classify.call_args[0][1] is True or kwargs.get("is_cc") is True

    def test_execute_calls_both_ports(self):
        """execute() appelle classifier et prioritizer."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification()
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority()
        uc = AnalyzeEmailUseCase(classifier=classifier, prioritizer=prioritizer)

        uc.execute(_make_email())

        classifier.classify.assert_called_once()
        prioritizer.analyze.assert_called_once()

    def test_execute_result_should_process_for_urgent(self):
        """Un email URGENT doit être traité (should_process=True)."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification(category=EmailCategory.URGENT)
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority()
        uc = AnalyzeEmailUseCase(classifier=classifier, prioritizer=prioritizer)

        result = uc.execute(_make_email())

        assert result.should_process() is True

    def test_execute_result_should_skip_newsletter(self):
        """Un email NEWSLETTER ne doit pas être traité."""
        classifier = MagicMock(spec=ClassifierPort)
        classifier.classify.return_value = _make_classification(
            category=EmailCategory.NEWSLETTER
        )
        prioritizer = MagicMock(spec=PrioritizationPort)
        prioritizer.analyze.return_value = _make_priority(urgency=5, vip=5, priority_score=5)
        uc = AnalyzeEmailUseCase(classifier=classifier, prioritizer=prioritizer)

        result = uc.execute(_make_email())

        assert result.should_process() is False
