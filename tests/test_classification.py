# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour la classification et la priorisation des emails.

Ces tests valident l'architecture Clean (entities, ports, adapters, use cases).
"""

import pytest
from unittest.mock import Mock

from app.domain.entities import (
    Email,
    EmailCategory,
    Classification,
    Priority,
    EmailAnalysis,
)
from app.domain.ports import (
    ClassifierPort,
    PrioritizationPort,
    EmailAnalyzerPort,
    LLMPort,
    LLMResponse,
)
from app.adapters.classification import (
    LLMClassifierAdapter,
    LLMPrioritizationAdapter,
    LLMEmailAnalyzerAdapter,
)
from app.application.analyze_email import (
    ClassifyEmailUseCase,
    PrioritizeEmailUseCase,
    AnalyzeEmailUseCase,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_email():
    """Email de test."""
    return Email(
        id="test-email-001",
        sender="client@example.com",
        subject="Question urgente sur ma commande",
        body="Bonjour, j'ai besoin d'une réponse urgente concernant ma commande.",
        recipients=["support@company.com"],
        thread_id="thread-123",
    )


@pytest.fixture
def newsletter_email():
    """Email newsletter de test."""
    return Email(
        id="test-email-002",
        sender="newsletter@marketing.com",
        subject="Nos dernières offres",
        body="Découvrez nos promotions. Cliquez ici pour vous désinscrire.",
        recipients=["user@company.com"],
    )


@pytest.fixture
def mock_llm():
    """Mock LLM pour les tests."""
    llm = Mock(spec=LLMPort)
    llm.name = "mock"
    llm.model = "mock-model"
    return llm


# ============================================================================
# TESTS DES ENTITÉS
# ============================================================================

class TestEmailCategory:
    """Tests pour l'enum EmailCategory."""

    def test_all_categories_exist(self):
        """Toutes les catégories doivent être définies."""
        expected = ["URGENT", "IMPORTANT", "NORMAL", "NEWSLETTER", "PROMO", "CC_ONLY", "SPAM"]
        for category in expected:
            assert hasattr(EmailCategory, category)

    def test_category_values(self):
        """Les valeurs doivent correspondre aux noms."""
        assert EmailCategory.URGENT.value == "URGENT"
        assert EmailCategory.NORMAL.value == "NORMAL"


class TestClassification:
    """Tests pour l'entité Classification."""

    def test_create_classification(self):
        """Création d'une classification."""
        c = Classification(
            category=EmailCategory.URGENT,
            confidence=0.95,
            reason="Mot-clé urgent détecté"
        )
        assert c.category == EmailCategory.URGENT
        assert c.confidence == 0.95
        assert c.reason == "Mot-clé urgent détecté"

    def test_default_classification(self):
        """Classification par défaut."""
        c = Classification.default()
        assert c.category == EmailCategory.NORMAL
        assert c.confidence == 0.5
        assert c.reason == "Classification par défaut"

    def test_should_skip_newsletter(self):
        """Newsletter doit être ignorée."""
        c = Classification(
            category=EmailCategory.NEWSLETTER,
            confidence=0.9,
            reason=""
        )
        assert c.should_skip() is True

    def test_should_skip_spam(self):
        """Spam doit être ignoré."""
        c = Classification(category=EmailCategory.SPAM, confidence=0.9, reason="")
        assert c.should_skip() is True

    def test_should_not_skip_urgent(self):
        """Urgent ne doit pas être ignoré."""
        c = Classification(category=EmailCategory.URGENT, confidence=0.9, reason="")
        assert c.should_skip() is False

    def test_should_not_skip_normal(self):
        """Normal ne doit pas être ignoré."""
        c = Classification(category=EmailCategory.NORMAL, confidence=0.9, reason="")
        assert c.should_skip() is False

    def test_to_dict(self):
        """Conversion en dictionnaire."""
        c = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="Client VIP"
        )
        d = c.to_dict()
        assert d["category"] == "IMPORTANT"
        assert d["confidence"] == 0.85
        assert d["reason"] == "Client VIP"


class TestPriority:
    """Tests pour l'entité Priority."""

    def test_create_priority(self):
        """Création d'une priorité."""
        p = Priority(
            urgency=80,
            vip=60,
            sentiment=-0.5,
            deadline="2024-01-20",
            priority_score=70
        )
        assert p.urgency == 80
        assert p.vip == 60
        assert p.sentiment == -0.5
        assert p.deadline == "2024-01-20"
        assert p.priority_score == 70

    def test_default_priority(self):
        """Priorité par défaut."""
        p = Priority.default()
        assert p.urgency == 50
        assert p.vip == 50
        assert p.sentiment == 0.0
        assert p.deadline is None
        assert p.priority_score == 50

    def test_from_components(self):
        """Création avec calcul automatique du score."""
        p = Priority.from_components(
            urgency=80,  # 80 * 0.4 = 32
            vip=60,      # 60 * 0.3 = 18
            sentiment=0.5,  # (0.5 + 1) * 15 = 22.5
        )
        # Total = 32 + 18 + 22.5 = 72.5 → 72
        assert p.priority_score == 72

    def test_from_components_with_negative_sentiment(self):
        """Calcul avec sentiment négatif."""
        p = Priority.from_components(
            urgency=50,
            vip=50,
            sentiment=-1.0,  # (-1 + 1) * 15 = 0
        )
        # Total = 20 + 15 + 0 = 35
        assert p.priority_score == 35

    def test_is_high_priority(self):
        """Détection haute priorité."""
        high = Priority(urgency=80, vip=80, sentiment=0.5, deadline=None, priority_score=85)
        low = Priority(urgency=30, vip=30, sentiment=0, deadline=None, priority_score=30)
        assert high.is_high_priority() is True
        assert low.is_high_priority() is False

    def test_is_low_priority(self):
        """Détection basse priorité."""
        low = Priority(urgency=20, vip=20, sentiment=0, deadline=None, priority_score=20)
        high = Priority(urgency=80, vip=80, sentiment=0.5, deadline=None, priority_score=85)
        assert low.is_low_priority() is True
        assert high.is_low_priority() is False

    def test_to_dict(self):
        """Conversion en dictionnaire."""
        p = Priority(
            urgency=70,
            vip=50,
            sentiment=0.2,
            deadline="2024-01-25",
            priority_score=65
        )
        d = p.to_dict()
        assert d["urgency"] == 70
        assert d["vip"] == 50
        assert d["sentiment"] == 0.2
        assert d["deadline"] == "2024-01-25"
        assert d["priority_score"] == 65


class TestEmailAnalysis:
    """Tests pour l'entité EmailAnalysis."""

    def test_create_email_analysis(self):
        """Création d'une analyse."""
        classification = Classification(
            category=EmailCategory.URGENT,
            confidence=0.9,
            reason="Urgent"
        )
        priority = Priority.from_components(80, 60, 0.5)

        analysis = EmailAnalysis(
            email_id="test-001",
            classification=classification,
            priority=priority
        )

        assert analysis.email_id == "test-001"
        assert analysis.classification.category == EmailCategory.URGENT
        assert analysis.priority.urgency == 80
        assert analysis.analyzed_at  # Auto-rempli

    def test_should_process_urgent(self):
        """Email urgent doit être traité."""
        analysis = EmailAnalysis(
            email_id="test-001",
            classification=Classification(
                category=EmailCategory.URGENT,
                confidence=0.9,
                reason=""
            ),
            priority=Priority.default()
        )
        assert analysis.should_process() is True

    def test_should_not_process_spam(self):
        """Spam ne doit pas être traité."""
        analysis = EmailAnalysis(
            email_id="test-001",
            classification=Classification(
                category=EmailCategory.SPAM,
                confidence=0.9,
                reason=""
            ),
            priority=Priority.default()
        )
        assert analysis.should_process() is False

    def test_to_dict(self):
        """Conversion en dictionnaire."""
        analysis = EmailAnalysis(
            email_id="test-001",
            classification=Classification(
                category=EmailCategory.NORMAL,
                confidence=0.8,
                reason="Standard"
            ),
            priority=Priority.default()
        )
        d = analysis.to_dict()
        assert d["email_id"] == "test-001"
        assert "classification" in d
        assert "priority" in d
        assert "analyzed_at" in d


# ============================================================================
# TESTS DES ADAPTERS
# ============================================================================

class TestLLMClassifierAdapter:
    """Tests pour l'adapter de classification LLM."""

    def test_classify_normal_email(self, sample_email, mock_llm):
        """Classification d'un email normal."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"category": "NORMAL", "confidence": 0.85, "reason": "Email standard"}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email)

        assert result.category == EmailCategory.NORMAL
        assert result.confidence == 0.85
        assert result.reason == "Email standard"

    def test_classify_urgent_email(self, sample_email, mock_llm):
        """Classification d'un email urgent."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"category": "URGENT", "confidence": 0.95, "reason": "Urgence détectée"}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email)

        assert result.category == EmailCategory.URGENT
        assert result.confidence == 0.95

    def test_classify_cc_email(self, sample_email, mock_llm):
        """Classification avec is_cc=True."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"category": "CC_ONLY", "confidence": 0.9, "reason": "En copie"}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email, is_cc=True)

        assert result.category == EmailCategory.CC_ONLY
        mock_llm.complete.assert_called_once()
        call_args = mock_llm.complete.call_args
        assert "[L'utilisateur est en COPIE]" in call_args.kwargs["user"]

    def test_classify_fallback_on_error(self, sample_email, mock_llm):
        """Fallback en cas d'erreur."""
        mock_llm.complete.side_effect = Exception("LLM Error")

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email)

        assert result.category == EmailCategory.NORMAL
        assert result.confidence == 0.5

    def test_classify_handles_invalid_json(self, sample_email, mock_llm):
        """Gestion du JSON invalide."""
        mock_llm.complete.return_value = LLMResponse(
            content="This is not JSON",
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email)

        assert result.category == EmailCategory.NORMAL  # Fallback

    def test_classify_handles_markdown_json(self, sample_email, mock_llm):
        """Gestion du JSON avec markdown."""
        mock_llm.complete.return_value = LLMResponse(
            content='```json\n{"category": "IMPORTANT", "confidence": 0.8, "reason": "VIP"}\n```',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMClassifierAdapter(llm=mock_llm)
        result = adapter.classify(sample_email)

        assert result.category == EmailCategory.IMPORTANT


class TestLLMPrioritizationAdapter:
    """Tests pour l'adapter de priorisation LLM."""

    def test_analyze_priority(self, sample_email, mock_llm):
        """Analyse de priorité standard."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"urgency": 70, "vip": 50, "sentiment": 0.3, "deadline": null, "priority_score": 60}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMPrioritizationAdapter(llm=mock_llm)
        result = adapter.analyze(sample_email)

        assert result.urgency == 70
        assert result.vip == 50
        assert result.sentiment == 0.3
        assert result.deadline is None
        assert result.priority_score == 60

    def test_analyze_with_deadline(self, sample_email, mock_llm):
        """Analyse avec deadline."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"urgency": 90, "vip": 70, "sentiment": -0.5, "deadline": "2024-01-20", "priority_score": 75}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMPrioritizationAdapter(llm=mock_llm)
        result = adapter.analyze(sample_email)

        assert result.deadline == "2024-01-20"

    def test_analyze_calculates_score_if_missing(self, sample_email, mock_llm):
        """Calcul du score si non fourni."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"urgency": 80, "vip": 60, "sentiment": 0.5, "deadline": null}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMPrioritizationAdapter(llm=mock_llm)
        result = adapter.analyze(sample_email)

        # Score calculé: 80*0.4 + 60*0.3 + (0.5+1)*15 = 32 + 18 + 22.5 = 72
        assert result.priority_score == 72

    def test_analyze_fallback_on_error(self, sample_email, mock_llm):
        """Fallback en cas d'erreur."""
        mock_llm.complete.side_effect = Exception("LLM Error")

        adapter = LLMPrioritizationAdapter(llm=mock_llm)
        result = adapter.analyze(sample_email)

        assert result.urgency == 50
        assert result.priority_score == 50

    def test_analyze_clamps_values(self, sample_email, mock_llm):
        """Les valeurs sont limitées aux bornes."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"urgency": 150, "vip": -20, "sentiment": 2.5, "deadline": null, "priority_score": 200}',
            input_tokens=100,
            output_tokens=50,
            model="mock"
        )

        adapter = LLMPrioritizationAdapter(llm=mock_llm)
        result = adapter.analyze(sample_email)

        assert result.urgency == 100  # Clamped
        assert result.vip == 0  # Clamped
        assert result.sentiment == 1.0  # Clamped
        assert result.priority_score == 100  # Clamped


class TestLLMEmailAnalyzerAdapter:
    """Tests pour l'adapter d'analyse combinée."""

    def test_analyze_combines_classification_and_priority(self, sample_email):
        """L'analyse combine classification et priorité."""
        mock_classifier = Mock(spec=ClassifierPort)
        mock_classifier.classify.return_value = Classification(
            category=EmailCategory.URGENT,
            confidence=0.9,
            reason="Urgent"
        )

        mock_prioritizer = Mock(spec=PrioritizationPort)
        mock_prioritizer.analyze.return_value = Priority(
            urgency=80,
            vip=60,
            sentiment=0.3,
            deadline=None,
            priority_score=70
        )

        adapter = LLMEmailAnalyzerAdapter(
            classifier=mock_classifier,
            prioritizer=mock_prioritizer
        )

        result = adapter.analyze(sample_email)

        assert result.email_id == sample_email.id
        assert result.classification.category == EmailCategory.URGENT
        assert result.priority.urgency == 80

        mock_classifier.classify.assert_called_once_with(sample_email, False)
        mock_prioritizer.analyze.assert_called_once_with(sample_email)


# ============================================================================
# TESTS DES USE CASES
# ============================================================================

class TestClassifyEmailUseCase:
    """Tests pour le use case de classification."""

    def test_execute_returns_classification(self, sample_email):
        """Execute retourne une classification."""
        mock_classifier = Mock(spec=ClassifierPort)
        mock_classifier.classify.return_value = Classification(
            category=EmailCategory.IMPORTANT,
            confidence=0.85,
            reason="Client VIP"
        )

        use_case = ClassifyEmailUseCase(classifier=mock_classifier)
        result = use_case.execute(sample_email)

        assert isinstance(result, Classification)
        assert result.category == EmailCategory.IMPORTANT
        mock_classifier.classify.assert_called_once_with(sample_email, False)

    def test_execute_with_is_cc(self, sample_email):
        """Execute avec is_cc=True."""
        mock_classifier = Mock(spec=ClassifierPort)
        mock_classifier.classify.return_value = Classification.default()

        use_case = ClassifyEmailUseCase(classifier=mock_classifier)
        use_case.execute(sample_email, is_cc=True)

        mock_classifier.classify.assert_called_once_with(sample_email, True)


class TestPrioritizeEmailUseCase:
    """Tests pour le use case de priorisation."""

    def test_execute_returns_priority(self, sample_email):
        """Execute retourne une priorité."""
        mock_prioritizer = Mock(spec=PrioritizationPort)
        mock_prioritizer.analyze.return_value = Priority(
            urgency=75,
            vip=60,
            sentiment=0.2,
            deadline=None,
            priority_score=65
        )

        use_case = PrioritizeEmailUseCase(prioritizer=mock_prioritizer)
        result = use_case.execute(sample_email)

        assert isinstance(result, Priority)
        assert result.urgency == 75
        mock_prioritizer.analyze.assert_called_once_with(sample_email)


class TestAnalyzeEmailUseCase:
    """Tests pour le use case d'analyse complète."""

    def test_execute_returns_email_analysis(self, sample_email):
        """Execute retourne une analyse complète."""
        mock_classifier = Mock(spec=ClassifierPort)
        mock_classifier.classify.return_value = Classification(
            category=EmailCategory.NORMAL,
            confidence=0.8,
            reason="Standard"
        )

        mock_prioritizer = Mock(spec=PrioritizationPort)
        mock_prioritizer.analyze.return_value = Priority.default()

        use_case = AnalyzeEmailUseCase(
            classifier=mock_classifier,
            prioritizer=mock_prioritizer
        )
        result = use_case.execute(sample_email)

        assert isinstance(result, EmailAnalysis)
        assert result.email_id == sample_email.id
        assert result.classification.category == EmailCategory.NORMAL
        assert result.priority.priority_score == 50

    def test_execute_propagates_is_cc(self, sample_email):
        """Execute propage is_cc au classifier."""
        mock_classifier = Mock(spec=ClassifierPort)
        mock_classifier.classify.return_value = Classification.default()

        mock_prioritizer = Mock(spec=PrioritizationPort)
        mock_prioritizer.analyze.return_value = Priority.default()

        use_case = AnalyzeEmailUseCase(
            classifier=mock_classifier,
            prioritizer=mock_prioritizer
        )
        use_case.execute(sample_email, is_cc=True)

        mock_classifier.classify.assert_called_once_with(sample_email, True)


# ============================================================================
# TESTS D'INTÉGRATION CONTAINER
# ============================================================================

class TestContainerIntegration:
    """Tests d'intégration avec le Container (avec mock LLM)."""

    @pytest.fixture(autouse=True)
    def setup_mock_container(self, mock_llm):
        """Configure le container avec un mock LLM."""
        from app.infrastructure.container import Container, reset_container
        reset_container()

        # Créer un container avec un LLM mocké
        self.container = Container()
        self.container._llm = mock_llm

    def test_container_provides_classifier(self):
        """Le container fournit un classifier."""
        classifier = self.container.get_classifier()
        assert isinstance(classifier, ClassifierPort)

    def test_container_provides_prioritizer(self):
        """Le container fournit un prioritizer."""
        prioritizer = self.container.get_prioritizer()
        assert isinstance(prioritizer, PrioritizationPort)

    def test_container_provides_email_analyzer(self):
        """Le container fournit un email analyzer."""
        analyzer = self.container.get_email_analyzer()
        assert isinstance(analyzer, EmailAnalyzerPort)

    def test_container_provides_analyze_use_case(self):
        """Le container fournit le use case d'analyse."""
        use_case = self.container.get_analyze_email_use_case()
        assert isinstance(use_case, AnalyzeEmailUseCase)

    def test_classifier_is_singleton(self):
        """Le classifier est un singleton."""
        c1 = self.container.get_classifier()
        c2 = self.container.get_classifier()
        assert c1 is c2

    def test_prioritizer_is_singleton(self):
        """Le prioritizer est un singleton."""
        p1 = self.container.get_prioritizer()
        p2 = self.container.get_prioritizer()
        assert p1 is p2
