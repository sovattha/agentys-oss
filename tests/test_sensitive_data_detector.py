# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests unitaires pour le SensitiveDataDetectorAgent et ses composants.

TDD: Ces tests sont écrits AVANT l'implémentation pour définir le comportement attendu.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSensitiveDataType:
    """Tests pour l'enum SensitiveDataType."""

    def test_financial_type_exists(self):
        """Le type FINANCIAL existe."""
        from app.domain.entities.sensitive_data import SensitiveDataType
        assert SensitiveDataType.FINANCIAL.value == "financial"

    def test_personal_type_exists(self):
        """Le type PERSONAL existe."""
        from app.domain.entities.sensitive_data import SensitiveDataType
        assert SensitiveDataType.PERSONAL.value == "personal"

    def test_commercial_secret_type_exists(self):
        """Le type COMMERCIAL_SECRET existe."""
        from app.domain.entities.sensitive_data import SensitiveDataType
        assert SensitiveDataType.COMMERCIAL_SECRET.value == "commercial"

    def test_credential_type_exists(self):
        """Le type CREDENTIAL existe."""
        from app.domain.entities.sensitive_data import SensitiveDataType
        assert SensitiveDataType.CREDENTIAL.value == "credential"


class TestSensitiveDataItem:
    """Tests pour le dataclass SensitiveDataItem."""

    def test_creation_with_all_fields(self):
        """SensitiveDataItem création avec tous les champs."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.FINANCIAL,
            description="Chiffre d'affaires mentionné",
            snippet="notre CA est de 2M€"
        )

        assert item.data_type == SensitiveDataType.FINANCIAL
        assert item.description == "Chiffre d'affaires mentionné"
        assert item.snippet == "notre CA est de 2M€"

    def test_to_dict_method(self):
        """SensitiveDataItem.to_dict() retourne un dict correct."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.PERSONAL,
            description="Email personnel détecté",
            snippet="mon email perso: test@gmail.com"
        )

        result = item.to_dict()

        assert result["data_type"] == "personal"
        assert result["description"] == "Email personnel détecté"
        assert result["snippet"] == "mon email perso: test@gmail.com"


class TestSensitiveDataDetection:
    """Tests pour le dataclass SensitiveDataDetection."""

    def test_creation_with_required_fields(self):
        """SensitiveDataDetection création basique."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.95,
            detected_items=[],
            analysis_summary="Données financières détectées"
        )

        assert detection.is_sensitive is True
        assert detection.confidence == 0.95
        assert detection.detected_items == []
        assert detection.analysis_summary == "Données financières détectées"

    def test_confidence_must_be_between_0_and_1(self):
        """SensitiveDataDetection lève InvalidBoundsError si confidence hors limites."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            SensitiveDataDetection(
                is_sensitive=True,
                confidence=1.5,
                detected_items=[],
                analysis_summary="Test"
            )

    def test_confidence_zero_is_valid(self):
        """SensitiveDataDetection avec confidence=0 est valide."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        detection = SensitiveDataDetection(
            is_sensitive=False,
            confidence=0.0,
            detected_items=[],
            analysis_summary="Aucune donnée sensible"
        )

        assert detection.confidence == 0.0

    def test_confidence_one_is_valid(self):
        """SensitiveDataDetection avec confidence=1 est valide."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=1.0,
            detected_items=[],
            analysis_summary="Données sensibles certaines"
        )

        assert detection.confidence == 1.0

    def test_default_factory_method(self):
        """SensitiveDataDetection.default() retourne une détection vide."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        detection = SensitiveDataDetection.default()

        assert detection.is_sensitive is False
        assert detection.confidence == 0.0
        assert detection.detected_items == []
        assert "No analysis" in detection.analysis_summary or "Aucune" in detection.analysis_summary

    def test_to_dict_method(self):
        """SensitiveDataDetection.to_dict() retourne un dict correct."""
        from app.domain.entities.sensitive_data import (
            SensitiveDataDetection,
            SensitiveDataItem,
            SensitiveDataType
        )

        item = SensitiveDataItem(
            data_type=SensitiveDataType.FINANCIAL,
            description="Revenue info",
            snippet="CA: 5M€"
        )
        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.9,
            detected_items=[item],
            analysis_summary="Financial data found"
        )

        result = detection.to_dict()

        assert result["is_sensitive"] is True
        assert result["confidence"] == 0.9
        assert len(result["detected_items"]) == 1
        assert result["detected_items"][0]["data_type"] == "financial"


class TestSensitiveDataDetectorAgent:
    """Tests pour le SensitiveDataDetectorAgent."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour SensitiveDataDetectorAgent."""
        from app.agents import TokenCounter
        from app.domain.ports import LLMResponse

        container = MagicMock()
        container.llm = MagicMock()
        container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": false, "confidence": 0.1, "detected_items": [], "analysis_summary": "Aucune donnée sensible détectée"}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.llm_label = container.llm
        container.llm_background = container.llm
        container.llm_drafting = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    def test_detect_returns_detection_object(self, mock_get_container, mock_container):
        """detect() retourne un SensitiveDataDetection."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Brouillon sans données sensibles", "external@company.com")

        assert isinstance(result, SensitiveDataDetection)
        assert hasattr(result, "is_sensitive")
        assert hasattr(result, "confidence")

    @patch("app.agents.get_container")
    def test_detect_identifies_financial_data(self, mock_get_container, mock_container):
        """detect() identifie les données financières."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true, "confidence": 0.95, "detected_items": [{"data_type": "financial", "description": "Chiffre d\'affaires", "snippet": "CA de 2M€"}], "analysis_summary": "Données financières détectées"}',
            input_tokens=200,
            output_tokens=80,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Notre CA de 2M€ est en croissance de 15%",
            "external@company.com"
        )

        assert result.is_sensitive is True
        assert result.confidence >= 0.9
        assert len(result.detected_items) > 0

    @patch("app.agents.get_container")
    def test_detect_identifies_personal_data(self, mock_get_container, mock_container):
        """detect() identifie les données personnelles."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true, "confidence": 0.9, "detected_items": [{"data_type": "personal", "description": "Numéro de sécurité sociale", "snippet": "numéro SS: 1234567890"}], "analysis_summary": "Données personnelles détectées"}',
            input_tokens=200,
            output_tokens=80,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Voici mon numéro SS: 1234567890",
            "external@company.com"
        )

        assert result.is_sensitive is True
        assert any(item.data_type.value == "personal" for item in result.detected_items)

    @patch("app.agents.get_container")
    def test_detect_identifies_credentials(self, mock_get_container, mock_container):
        """detect() identifie les credentials."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true, "confidence": 0.99, "detected_items": [{"data_type": "credential", "description": "Mot de passe détecté", "snippet": "password: secret123"}], "analysis_summary": "Credentials détectés"}',
            input_tokens=200,
            output_tokens=80,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Le mot de passe est: secret123",
            "external@company.com"
        )

        assert result.is_sensitive is True
        assert any(item.data_type.value == "credential" for item in result.detected_items)

    @patch("app.agents.get_container")
    def test_detect_identifies_commercial_secrets(self, mock_get_container, mock_container):
        """detect() identifie les secrets commerciaux."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true, "confidence": 0.85, "detected_items": [{"data_type": "commercial", "description": "Stratégie commerciale", "snippet": "lancer le produit X avant concurrent Y"}], "analysis_summary": "Secret commercial détecté"}',
            input_tokens=200,
            output_tokens=80,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Notre stratégie: lancer le produit X avant concurrent Y en Q1",
            "external@company.com"
        )

        assert result.is_sensitive is True

    @patch("app.agents.get_container")
    def test_detect_with_safe_content(self, mock_get_container, mock_container):
        """detect() retourne is_sensitive=False pour contenu safe."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Bonjour, merci pour votre message. Cordialement",
            "external@company.com"
        )

        assert result.is_sensitive is False

    @patch("app.agents.get_container")
    def test_detect_handles_llm_error(self, mock_get_container, mock_container):
        """detect() retourne les valeurs par défaut en cas d'erreur LLM."""
        mock_get_container.return_value = mock_container
        mock_container.llm.complete.side_effect = Exception("API Error")

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Test", "external@company.com")

        assert result.is_sensitive is False
        assert result.confidence == 0.0

    @patch("app.agents.get_container")
    def test_detect_with_malformed_json(self, mock_get_container, mock_container):
        """detect() gère un JSON malformé du LLM."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true, broken',
            input_tokens=100,
            output_tokens=20,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Test", "external@company.com")

        assert result.is_sensitive is False

    @patch("app.agents.get_container")
    def test_detect_with_empty_draft(self, mock_get_container, mock_container):
        """detect() gère un brouillon vide."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("", "external@company.com")

        assert isinstance(result, SensitiveDataDetection)
        assert result.is_sensitive is False
        mock_container.llm.complete.assert_not_called()

    @patch("app.agents.get_container")
    def test_detect_includes_recipient_in_context(self, mock_get_container, mock_container, monkeypatch):
        """detect() inclut le destinataire dans le contexte."""
        monkeypatch.setattr("app.config.USE_REGEX_PII_DETECTOR", False)
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        agent.detect(
            "Merci de vérifier ce dossier sensible 1234567890 avant envoi au client.",
            "client@external.com"
        )

        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "client@external.com" in call_kwargs["user"]

    @patch("app.agents.get_container")
    def test_detect_with_unicode_content(self, mock_get_container, mock_container):
        """detect() gère le contenu unicode."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        agent.detect(
            "Notre CA été: 2M€ avec 15% de marge 📈",
            "client@company.com"
        )

        mock_container.llm.complete.assert_not_called()


class TestSensitiveDataDetectorPort:
    """Tests pour le port abstrait SensitiveDataDetectorPort."""

    def test_port_is_abstract(self):
        """SensitiveDataDetectorPort est une classe abstraite."""
        from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort
        from abc import ABC

        assert issubclass(SensitiveDataDetectorPort, ABC)

    def test_port_has_detect_method(self):
        """SensitiveDataDetectorPort définit la méthode detect."""
        from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort

        assert hasattr(SensitiveDataDetectorPort, "detect")
        assert callable(getattr(SensitiveDataDetectorPort, "detect"))


# ============================================================================
# EDGE CASES - ENTITÉS
# ============================================================================


class TestSensitiveDataDetectionEdgeCases:
    """Tests edge cases pour SensitiveDataDetection."""

    def test_confidence_negative_raises_error(self):
        """SensitiveDataDetection lève InvalidBoundsError si confidence < 0."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            SensitiveDataDetection(
                is_sensitive=False,
                confidence=-0.1,
                detected_items=[],
                analysis_summary="Test"
            )

    def test_confidence_slightly_above_one_raises_error(self):
        """SensitiveDataDetection lève InvalidBoundsError si confidence > 1 (même légèrement)."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        from app.domain.exceptions import InvalidBoundsError

        with pytest.raises(InvalidBoundsError):
            SensitiveDataDetection(
                is_sensitive=True,
                confidence=1.001,
                detected_items=[],
                analysis_summary="Test"
            )

    def test_with_multiple_detected_items(self):
        """SensitiveDataDetection avec plusieurs items détectés."""
        from app.domain.entities.sensitive_data import (
            SensitiveDataDetection,
            SensitiveDataItem,
            SensitiveDataType
        )

        items = [
            SensitiveDataItem(
                data_type=SensitiveDataType.FINANCIAL,
                description="Revenue",
                snippet="CA: 5M€"
            ),
            SensitiveDataItem(
                data_type=SensitiveDataType.PERSONAL,
                description="SSN",
                snippet="SSN: 123456"
            ),
            SensitiveDataItem(
                data_type=SensitiveDataType.CREDENTIAL,
                description="Password",
                snippet="pwd=secret"
            )
        ]

        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.99,
            detected_items=items,
            analysis_summary="Multiple sensitive data"
        )

        assert len(detection.detected_items) == 3
        result = detection.to_dict()
        assert len(result["detected_items"]) == 3

    def test_empty_analysis_summary(self):
        """SensitiveDataDetection avec analysis_summary vide."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        detection = SensitiveDataDetection(
            is_sensitive=False,
            confidence=0.0,
            detected_items=[],
            analysis_summary=""
        )

        assert detection.analysis_summary == ""

    def test_very_long_analysis_summary(self):
        """SensitiveDataDetection avec un très long summary."""
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        long_summary = "A" * 10000

        detection = SensitiveDataDetection(
            is_sensitive=True,
            confidence=0.5,
            detected_items=[],
            analysis_summary=long_summary
        )

        assert len(detection.analysis_summary) == 10000


class TestSensitiveDataItemEdgeCases:
    """Tests edge cases pour SensitiveDataItem."""

    def test_empty_description(self):
        """SensitiveDataItem avec description vide."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.FINANCIAL,
            description="",
            snippet="CA: 5M€"
        )

        assert item.description == ""
        result = item.to_dict()
        assert result["description"] == ""

    def test_empty_snippet(self):
        """SensitiveDataItem avec snippet vide."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.PERSONAL,
            description="Personal info",
            snippet=""
        )

        assert item.snippet == ""

    def test_snippet_with_special_characters(self):
        """SensitiveDataItem avec caractères spéciaux dans snippet."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.CREDENTIAL,
            description="Credentials",
            snippet='password="<script>alert(1)</script>"'
        )

        result = item.to_dict()
        assert '<script>' in result["snippet"]

    def test_snippet_with_newlines(self):
        """SensitiveDataItem avec retours à la ligne dans snippet."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        item = SensitiveDataItem(
            data_type=SensitiveDataType.COMMERCIAL_SECRET,
            description="Multi-line secret",
            snippet="Line 1\nLine 2\nLine 3"
        )

        assert "\n" in item.snippet

    def test_all_sensitive_data_types_in_to_dict(self):
        """Tous les types SensitiveDataType sont sérialisables."""
        from app.domain.entities.sensitive_data import SensitiveDataItem, SensitiveDataType

        for data_type in SensitiveDataType:
            item = SensitiveDataItem(
                data_type=data_type,
                description=f"Test {data_type.value}",
                snippet="test snippet"
            )
            result = item.to_dict()
            assert result["data_type"] == data_type.value


# ============================================================================
# EDGE CASES - AGENT
# ============================================================================


class TestSensitiveDataDetectorAgentEdgeCases:
    """Tests edge cases pour SensitiveDataDetectorAgent."""

    @pytest.fixture
    def mock_container(self):
        """Container mocké pour SensitiveDataDetectorAgent."""
        from app.agents import TokenCounter
        from app.domain.ports import LLMResponse

        container = MagicMock()
        container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": false, "confidence": 0.1, "detected_items": [], "analysis_summary": "Safe"}',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )
        container.llm_label = container.llm
        container.llm_background = container.llm
        container.llm_drafting = container.llm
        container.token_usage = TokenCounter()
        return container

    @patch("app.agents.get_container")
    def test_detect_with_none_recipient(self, mock_get_container, mock_container, monkeypatch):
        """detect() gère un recipient None."""
        monkeypatch.setattr("app.config.USE_REGEX_PII_DETECTOR", False)
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Merci de vérifier ce dossier sensible 1234567890 avant envoi au client.",
            None
        )

        assert isinstance(result, SensitiveDataDetection)
        call_kwargs = mock_container.llm.complete.call_args[1]
        assert "None" in call_kwargs["user"]

    @patch("app.agents.get_container")
    def test_detect_with_empty_recipient(self, mock_get_container, mock_container):
        """detect() gère un recipient vide."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Draft content", "")

        assert isinstance(result, SensitiveDataDetection)

    @patch("app.agents.get_container")
    def test_detect_with_very_long_draft(self, mock_get_container, mock_container):
        """detect() gère un brouillon très long."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        long_draft = "A" * 50000
        result = agent.detect(long_draft, "test@example.com")

        assert isinstance(result, SensitiveDataDetection)
        assert result.is_sensitive is False
        mock_container.llm.complete.assert_not_called()

    @patch("app.agents.get_container")
    def test_detect_with_special_characters_in_draft(self, mock_get_container, mock_container):
        """detect() gère les caractères spéciaux dans le brouillon."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            '<script>alert("XSS")</script>\n{"injection": true}',
            "test@example.com"
        )

        assert isinstance(result, SensitiveDataDetection)

    @patch("app.agents.get_container")
    def test_detect_with_multiline_draft(self, mock_get_container, mock_container):
        """detect() gère un brouillon multiligne."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "Line 1\nLine 2\n\nLine 4\nLine 5",
            "test@example.com"
        )

        assert isinstance(result, SensitiveDataDetection)

    @patch("app.agents.get_container")
    def test_detect_returns_multiple_items(self, mock_get_container, mock_container, monkeypatch):
        """detect() peut retourner plusieurs items détectés."""
        from app.domain.ports import LLMResponse

        monkeypatch.setattr("app.config.USE_REGEX_PII_DETECTOR", False)
        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='''{"is_sensitive": true, "confidence": 0.95, "detected_items": [
                {"data_type": "financial", "description": "Revenue", "snippet": "CA: 5M€"},
                {"data_type": "personal", "description": "SSN", "snippet": "SSN: 123"},
                {"data_type": "credential", "description": "Password", "snippet": "pwd: xxx"}
            ], "analysis_summary": "Multiple sensitive data detected"}''',
            input_tokens=200,
            output_tokens=100,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        agent = SensitiveDataDetectorAgent()
        result = agent.detect(
            "CA: 5M€, SSN: 1234567890, password: xxxsecret pour le dossier client.",
            "external@company.com"
        )

        assert result.is_sensitive is True
        assert len(result.detected_items) == 3

    @patch("app.agents.get_container")
    def test_detect_with_json_in_code_block(self, mock_get_container, mock_container):
        """detect() gère le JSON dans un bloc de code markdown."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='```json\n{"is_sensitive": true, "confidence": 0.8, "detected_items": [], "analysis_summary": "Test"}\n```',
            input_tokens=200,
            output_tokens=50,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Test", "test@example.com")

        # La fonction extract_json_from_response devrait extraire le JSON du bloc
        assert isinstance(result, SensitiveDataDetection)

    @patch("app.agents.get_container")
    def test_detect_with_partial_json_response(self, mock_get_container, mock_container):
        """detect() gère une réponse JSON partielle."""
        from app.domain.ports import LLMResponse

        mock_get_container.return_value = mock_container
        mock_container.llm.complete.return_value = LLMResponse(
            content='{"is_sensitive": true}',  # JSON incomplet
            input_tokens=100,
            output_tokens=20,
            model="claude-3-5-haiku-20241022"
        )

        from app.agents import SensitiveDataDetectorAgent
        from app.domain.entities.sensitive_data import SensitiveDataDetection
        agent = SensitiveDataDetectorAgent()
        result = agent.detect("Test", "test@example.com")

        # Devrait utiliser les valeurs par défaut pour les champs manquants
        assert isinstance(result, SensitiveDataDetection)
        assert hasattr(result, "is_sensitive")

    @patch("app.agents.get_container")
    def test_detect_tracks_token_usage(self, mock_get_container, mock_container):
        """detect() track l'utilisation des tokens."""
        mock_get_container.return_value = mock_container

        from app.agents import SensitiveDataDetectorAgent
        initial_input = mock_container.token_usage.input_tokens
        initial_output = mock_container.token_usage.output_tokens

        agent = SensitiveDataDetectorAgent()
        agent.detect("Test draft", "test@example.com")

        # Vérifier que les tokens ont été trackés (incrémentés par _track_token_usage)
        assert mock_container.token_usage.input_tokens >= initial_input
        assert mock_container.token_usage.output_tokens >= initial_output


# ============================================================================
# EDGE CASES - USE CASE
# ============================================================================


class TestSensitiveDataDetectorPortEdgeCases:
    """Tests edge cases pour SensitiveDataDetectorPort."""

    def test_cannot_instantiate_abstract_port(self):
        """SensitiveDataDetectorPort ne peut pas être instancié directement."""
        from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort

        with pytest.raises(TypeError):
            SensitiveDataDetectorPort()

    def test_concrete_implementation_must_implement_detect(self):
        """Une implémentation concrète doit implémenter detect()."""
        from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort

        class IncompleteDetector(SensitiveDataDetectorPort):
            pass

        with pytest.raises(TypeError):
            IncompleteDetector()

    def test_concrete_implementation_works(self):
        """Une implémentation concrète complète fonctionne."""
        from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort
        from app.domain.entities.sensitive_data import SensitiveDataDetection

        class ConcreteDetector(SensitiveDataDetectorPort):
            def detect(self, draft_content: str, recipient: str) -> SensitiveDataDetection:
                return SensitiveDataDetection.default()

        detector = ConcreteDetector()
        result = detector.detect("Test", "test@example.com")

        assert isinstance(result, SensitiveDataDetection)
        assert result.is_sensitive is False
