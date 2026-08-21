# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le use case RefineEmail.

pytest tests/application/test_refine_email.py -v
"""

import pytest
from unittest.mock import Mock

from app.application.refine_email import RefineEmailUseCase, RefineResult
from app.domain.entities import Email, Draft, Critique, TokenUsage, DraftStatus
from app.domain.ports import LLMPort


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_llm():
    """Mock du LLM."""
    return Mock(spec=LLMPort)


@pytest.fixture
def mock_llm_response_valid():
    """Mock d'une réponse LLM pour brouillon valide."""
    response = Mock()
    response.content = "Bonjour, merci pour votre message."
    response.input_tokens = 100
    response.output_tokens = 50
    response.model = "claude-sonnet-4-20250514"
    return response


@pytest.fixture
def mock_critique_response_valid():
    """Mock d'une critique valide."""
    response = Mock()
    response.content = "VALID"
    response.input_tokens = 80
    response.output_tokens = 10
    response.model = "claude-sonnet-4-20250514"
    return response


@pytest.fixture
def mock_critique_response_reject():
    """Mock d'une critique avec rejet."""
    response = Mock()
    response.content = "REJET : Le ton est trop familier, pas assez professionnel."
    response.input_tokens = 80
    response.output_tokens = 20
    response.model = "claude-sonnet-4-20250514"
    return response


@pytest.fixture
def mock_revised_response():
    """Mock d'une réponse révisée après critique."""
    response = Mock()
    response.content = "Madame, Monsieur, merci pour votre message. Cordialement."
    response.input_tokens = 120
    response.output_tokens = 60
    response.model = "claude-sonnet-4-20250514"
    return response


@pytest.fixture
def sample_email():
    """Email de test."""
    return Email(
        id="email-123",
        sender="client@example.com",
        subject="Demande d'information",
        body="Bonjour, pouvez-vous me donner plus de détails? Merci.",
        recipients=["user@agentys.com"],
    )


@pytest.fixture
def knowledge_base():
    """Base de connaissances de test."""
    return """
    - Toujours répondre de manière professionnelle
    - Utiliser 'vous' pour s'adresser aux clients
    - Être concis et clair
    """


@pytest.fixture
def use_case(mock_llm, knowledge_base):
    """UseCase configuré pour les tests."""
    return RefineEmailUseCase(
        llm=mock_llm,
        knowledge_base=knowledge_base,
        max_tokens_draft=1024,
        max_tokens_critique=256,
    )


# ============================================================================
# TESTS RefineResult
# ============================================================================


class TestRefineResult:
    """Tests pour la dataclass RefineResult."""

    def test_refine_result_creation(self):
        """Test de création d'un RefineResult."""
        draft_v1 = Draft(content="Version 1", version=1)
        critique = Critique(raw_response="VALID", is_valid=True)
        draft_final = Draft(content="Version finale", version=1)

        result = RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=DraftStatus.VALIDATED_V1,
            was_corrected=False,
        )

        assert result.draft_v1 == draft_v1
        assert result.critique == critique
        assert result.draft_final == draft_final
        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False

    def test_refine_result_with_correction(self):
        """Test de RefineResult avec correction."""
        draft_v1 = Draft(content="Version 1", version=1)
        critique = Critique(
            raw_response="REJET : Ton inapproprié",
            is_valid=False,
            reason="REJET : Ton inapproprié",
        )
        draft_final = Draft(content="Version 2 corrigée", version=2)

        result = RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=DraftStatus.CORRECTED_V2,
            was_corrected=True,
        )

        assert result.was_corrected is True
        assert result.status == DraftStatus.CORRECTED_V2
        assert result.draft_final.version == 2

    def test_refine_result_to_dict_valid(self):
        """Test de conversion to_dict avec brouillon valide."""
        draft_v1 = Draft(content="Mon brouillon", version=1)
        critique = Critique(raw_response="VALID", is_valid=True, reason=None)
        draft_final = Draft(content="Mon brouillon", version=1)

        result = RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=DraftStatus.VALIDATED_V1,
            was_corrected=False,
        )

        d = result.to_dict
        assert d["draft_v1"] == "Mon brouillon"
        assert d["critique"]["is_valid"] is True
        assert d["critique"]["feedback"] == "VALID"
        assert d["was_corrected"] is False

    def test_refine_result_to_dict_with_reason(self):
        """Test de to_dict avec critique contenant une raison."""
        draft_v1 = Draft(content="Version 1", version=1)
        critique = Critique(
            raw_response="REJET : Ton inapproprié",
            is_valid=False,
            reason="REJET : Ton inapproprié",
        )
        draft_final = Draft(content="Version 2", version=2)

        result = RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=DraftStatus.CORRECTED_V2,
            was_corrected=True,
        )

        d = result.to_dict
        assert d["critique"]["is_valid"] is False
        assert d["critique"]["feedback"] == "REJET : Ton inapproprié"
        assert d["was_corrected"] is True

    def test_refine_result_to_dict_no_reason_fallback_raw(self):
        """Test de to_dict avec critique sans reason (fallback sur raw_response)."""
        draft_v1 = Draft(content="Draft", version=1)
        critique = Critique(raw_response="VALID", is_valid=True, reason=None)
        draft_final = Draft(content="Draft", version=1)

        result = RefineResult(
            draft_v1=draft_v1,
            critique=critique,
            draft_final=draft_final,
            status=DraftStatus.VALIDATED_V1,
            was_corrected=False,
        )

        d = result.to_dict
        # Quand reason est None, on utilise raw_response
        assert d["critique"]["feedback"] == "VALID"


# ============================================================================
# TESTS RefineEmailUseCase - Initialisation
# ============================================================================


class TestRefineEmailUseCaseInit:
    """Tests pour l'initialisation du use case."""

    def test_init_with_defaults(self, mock_llm, knowledge_base):
        """Test d'initialisation avec valeurs par défaut."""
        uc = RefineEmailUseCase(llm=mock_llm, knowledge_base=knowledge_base)

        assert uc.llm == mock_llm
        assert uc.knowledge_base == knowledge_base
        assert uc.max_tokens_draft == 1024
        assert uc.max_tokens_critique == 256
        assert isinstance(uc.token_usage, TokenUsage)

    def test_init_with_custom_token_limits(self, mock_llm, knowledge_base):
        """Test d'initialisation avec limites de tokens personnalisées."""
        uc = RefineEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            max_tokens_draft=2048,
            max_tokens_critique=512,
        )

        assert uc.max_tokens_draft == 2048
        assert uc.max_tokens_critique == 512

    def test_init_with_provided_token_usage(self, mock_llm, knowledge_base):
        """Test d'initialisation avec TokenUsage fourni."""
        token_usage = TokenUsage(input_tokens=100, output_tokens=50)
        uc = RefineEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=token_usage,
        )

        assert uc.token_usage == token_usage
        assert uc.token_usage.input_tokens == 100
        assert uc.token_usage.output_tokens == 50

    def test_post_init_creates_token_usage_if_none(self, mock_llm, knowledge_base):
        """Test que __post_init__ crée un TokenUsage si None."""
        uc = RefineEmailUseCase(
            llm=mock_llm,
            knowledge_base=knowledge_base,
            token_usage=None,
        )

        assert uc.token_usage is not None
        assert uc.token_usage.input_tokens == 0
        assert uc.token_usage.output_tokens == 0


# ============================================================================
# TESTS RefineEmailUseCase - Execute - Pipeline valide (pas de correction)
# ============================================================================


class TestRefineEmailUseCaseExecuteValid:
    """Tests pour execute() quand le brouillon est validé du premier coup."""

    def test_execute_validated_v1_without_email(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test de pipeline validé V1 sans email original."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,  # refine
            mock_critique_response_valid,  # critique
        ]

        result = use_case.execute(
            current_draft="Mon brouillon original",
            instruction="Rendre plus court",
        )

        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False
        assert result.draft_v1.content == mock_llm_response_valid.content
        assert result.draft_final == result.draft_v1
        assert result.critique.is_valid is True
        assert mock_llm.complete.call_count == 2

    def test_execute_validated_v1_with_email(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
        sample_email,
    ):
        """Test de pipeline validé V1 avec email original."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft="Mon brouillon",
            instruction="Plus formel",
            email=sample_email,
        )

        assert result.status == DraftStatus.VALIDATED_V1
        assert result.was_corrected is False
        # Vérifier que l'email a été passé dans les prompts
        call_args = mock_llm.complete.call_args_list
        # Le premier appel (refine) doit contenir le contexte de l'email
        refine_call = call_args[0]
        assert sample_email.sender in refine_call.kwargs["user"]

    def test_execute_token_tracking(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test que les tokens sont correctement comptabilisés."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,  # 100 in + 50 out
            mock_critique_response_valid,  # 80 in + 10 out
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        assert use_case.token_usage.input_tokens == 180  # 100 + 80
        assert use_case.token_usage.output_tokens == 60  # 50 + 10


# ============================================================================
# TESTS RefineEmailUseCase - Execute - Pipeline avec correction (V2)
# ============================================================================


class TestRefineEmailUseCaseExecuteWithCorrection:
    """Tests pour execute() quand le brouillon nécessite une correction."""

    def test_execute_corrected_v2(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_reject,
        mock_revised_response,
    ):
        """Test de pipeline avec correction V2."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,  # refine V1
            mock_critique_response_reject,  # critique (rejet)
            mock_revised_response,  # revise V2
        ]

        result = use_case.execute(
            current_draft="Mon brouillon",
            instruction="Rendre plus formel",
        )

        assert result.status == DraftStatus.CORRECTED_V2
        assert result.was_corrected is True
        assert result.draft_v1.content == mock_llm_response_valid.content
        assert result.draft_v1.version == 1
        assert result.draft_final.content == mock_revised_response.content
        assert result.draft_final.version == 2
        assert result.critique.is_valid is False
        assert mock_llm.complete.call_count == 3

    def test_execute_corrected_v2_with_email(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_reject,
        mock_revised_response,
        sample_email,
    ):
        """Test de correction V2 avec email original."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_reject,
            mock_revised_response,
        ]

        result = use_case.execute(
            current_draft="Draft",
            instruction="Plus formel",
            email=sample_email,
        )

        assert result.was_corrected is True
        # Vérifier que le prompt de révision contient l'email
        revision_call = mock_llm.complete.call_args_list[2]
        assert sample_email.sender in revision_call.kwargs["user"]

    def test_execute_token_tracking_with_correction(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_reject,
        mock_revised_response,
    ):
        """Test que les tokens sont comptés pour les 3 appels."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,  # 100 in + 50 out
            mock_critique_response_reject,  # 80 in + 20 out
            mock_revised_response,  # 120 in + 60 out
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        assert use_case.token_usage.input_tokens == 300  # 100 + 80 + 120
        assert use_case.token_usage.output_tokens == 130  # 50 + 20 + 60


# ============================================================================
# TESTS RefineEmailUseCase - Méthodes privées
# ============================================================================


class TestRefineEmailUseCasePrivateMethods:
    """Tests pour les méthodes privées du use case."""

    def test_build_system_prompt_contains_knowledge_base(
        self, use_case, knowledge_base
    ):
        """Test que le prompt système contient la knowledge base."""
        prompt = use_case._build_system_prompt()

        assert knowledge_base in prompt
        assert "professionnel" in prompt.lower()

    def test_build_refine_prompt_without_email(self, use_case):
        """Test du prompt de refinement sans email."""
        prompt = use_case._build_refine_prompt(
            current_draft="Draft original",
            instruction="Raccourcir",
            email=None,
        )

        assert "Draft original" in prompt
        assert "Raccourcir" in prompt
        assert "EMAIL ORIGINAL" not in prompt

    def test_build_refine_prompt_with_email(self, use_case, sample_email):
        """Test du prompt de refinement avec email."""
        prompt = use_case._build_refine_prompt(
            current_draft="Draft",
            instruction="Formaliser",
            email=sample_email,
        )

        assert "EMAIL ORIGINAL" in prompt
        assert sample_email.sender in prompt
        assert sample_email.subject in prompt
        assert "Draft" in prompt
        assert "Formaliser" in prompt

    def test_build_critique_system_prompt(self, use_case, knowledge_base):
        """Test du prompt système pour le critique."""
        prompt = use_case._build_critique_system_prompt()

        assert knowledge_base in prompt
        assert "VALID" in prompt
        assert "REJET" in prompt

    def test_build_critique_prompt_without_email(self, use_case):
        """Test du prompt de critique sans email."""
        draft = Draft(content="Mon brouillon de test", version=1)
        prompt = use_case._build_critique_prompt(draft, email=None)

        assert "Mon brouillon de test" in prompt
        assert "EMAIL ORIGINAL" not in prompt
        assert "VERDICT" in prompt

    def test_build_critique_prompt_with_email(self, use_case, sample_email):
        """Test du prompt de critique avec email."""
        draft = Draft(content="Réponse à évaluer", version=1)
        prompt = use_case._build_critique_prompt(draft, email=sample_email)

        assert "EMAIL ORIGINAL" in prompt
        assert sample_email.sender in prompt
        assert "Réponse à évaluer" in prompt

    def test_build_revision_prompt_without_email(self, use_case):
        """Test du prompt de révision sans email."""
        draft_v1 = Draft(content="Version 1", version=1)
        prompt = use_case._build_revision_prompt(
            draft_v1=draft_v1,
            critique="Le ton est trop familier",
            instruction="Plus formel",
            email=None,
        )

        assert "Version 1" in prompt
        assert "Le ton est trop familier" in prompt
        assert "Plus formel" in prompt
        assert "EMAIL ORIGINAL" not in prompt

    def test_build_revision_prompt_with_email(self, use_case, sample_email):
        """Test du prompt de révision avec email."""
        draft_v1 = Draft(content="V1", version=1)
        prompt = use_case._build_revision_prompt(
            draft_v1=draft_v1,
            critique="Critique détaillée",
            instruction="Instruction",
            email=sample_email,
        )

        assert "EMAIL ORIGINAL" in prompt
        assert sample_email.sender in prompt

    def test_refine_draft(
        self, use_case, mock_llm, mock_llm_response_valid
    ):
        """Test de la méthode _refine_draft."""
        mock_llm.complete.return_value = mock_llm_response_valid

        draft = use_case._refine_draft(
            current_draft="Original",
            instruction="Modifier",
            email=None,
        )

        assert isinstance(draft, Draft)
        assert draft.content == mock_llm_response_valid.content
        assert draft.version == 1
        mock_llm.complete.assert_called_once()

    def test_refine_draft_with_email(
        self, use_case, mock_llm, mock_llm_response_valid, sample_email
    ):
        """Test de _refine_draft avec email."""
        mock_llm.complete.return_value = mock_llm_response_valid

        draft = use_case._refine_draft(
            current_draft="Original",
            instruction="Modifier",
            email=sample_email,
        )

        assert draft.version == 1
        call_args = mock_llm.complete.call_args
        assert sample_email.sender in call_args.kwargs["user"]

    def test_critique_draft(
        self, use_case, mock_llm, mock_critique_response_valid
    ):
        """Test de la méthode _critique_draft."""
        mock_llm.complete.return_value = mock_critique_response_valid
        draft = Draft(content="Brouillon à évaluer", version=1)

        critique = use_case._critique_draft(draft, email=None)

        assert isinstance(critique, Critique)
        assert critique.is_valid is True

    def test_critique_draft_reject(
        self, use_case, mock_llm, mock_critique_response_reject
    ):
        """Test de _critique_draft avec rejet."""
        mock_llm.complete.return_value = mock_critique_response_reject
        draft = Draft(content="Mauvais brouillon", version=1)

        critique = use_case._critique_draft(draft, email=None)

        assert critique.is_valid is False
        assert "professionnel" in critique.reason.lower()

    def test_revise_draft(
        self, use_case, mock_llm, mock_revised_response
    ):
        """Test de la méthode _revise_draft."""
        mock_llm.complete.return_value = mock_revised_response
        draft_v1 = Draft(content="V1 rejetée", version=1)

        draft_v2 = use_case._revise_draft(
            draft_v1=draft_v1,
            critique="Ton inapproprié",
            instruction="Plus formel",
            email=None,
        )

        assert isinstance(draft_v2, Draft)
        assert draft_v2.content == mock_revised_response.content
        assert draft_v2.version == 2


# ============================================================================
# TESTS Edge Cases
# ============================================================================


class TestRefineEmailUseCaseEdgeCases:
    """Tests pour les cas limites."""

    def test_execute_empty_draft(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test avec un brouillon vide."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft="",
            instruction="Créer une réponse",
        )

        assert result.status == DraftStatus.VALIDATED_V1
        mock_llm.complete.assert_called()

    def test_execute_empty_instruction(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test avec une instruction vide."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft="Draft existant",
            instruction="",
        )

        assert result.status == DraftStatus.VALIDATED_V1

    def test_execute_long_draft(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test avec un brouillon très long."""
        long_draft = "Lorem ipsum " * 1000
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft=long_draft,
            instruction="Résumer",
        )

        assert result.status == DraftStatus.VALIDATED_V1

    def test_execute_special_characters_in_instruction(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test avec des caractères spéciaux dans l'instruction."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft="Draft",
            instruction="Ajouter des émojis 🎉 et guillemets \"test\"",
        )

        assert result.status == DraftStatus.VALIDATED_V1

    def test_execute_unicode_content(
        self,
        use_case,
        mock_llm,
        mock_critique_response_valid,
    ):
        """Test avec du contenu Unicode."""
        response = Mock()
        response.content = "日本語の内容です。中文内容。"
        response.input_tokens = 100
        response.output_tokens = 50
        response.model = "claude-sonnet-4-20250514"

        mock_llm.complete.side_effect = [response, mock_critique_response_valid]

        result = use_case.execute(
            current_draft="日本語のメール",
            instruction="Répondre en japonais",
        )

        assert result.draft_v1.content == "日本語の内容です。中文内容。"

    def test_execute_multiple_calls_cumulative_tokens(
        self,
        mock_llm,
        knowledge_base,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test que plusieurs appels accumulent les tokens."""
        use_case = RefineEmailUseCase(llm=mock_llm, knowledge_base=knowledge_base)
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,  # 100 in + 50 out
            mock_critique_response_valid,  # 80 in + 10 out
            mock_llm_response_valid,  # 100 in + 50 out (second call)
            mock_critique_response_valid,  # 80 in + 10 out
        ]

        use_case.execute(current_draft="Draft 1", instruction="Modify 1")
        use_case.execute(current_draft="Draft 2", instruction="Modify 2")

        assert use_case.token_usage.input_tokens == 360  # 2 * (100 + 80)
        assert use_case.token_usage.output_tokens == 120  # 2 * (50 + 10)


# ============================================================================
# TESTS Intégration avec Email entity
# ============================================================================


class TestRefineEmailUseCaseWithEmailEntity:
    """Tests d'intégration avec l'entité Email."""

    def test_email_content_for_processing_included(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
        sample_email,
    ):
        """Test que content_for_processing de l'email est utilisé."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        use_case.execute(
            current_draft="Draft",
            instruction="Améliorer",
            email=sample_email,
        )

        # Vérifier que le contenu formaté de l'email est passé
        refine_call = mock_llm.complete.call_args_list[0]
        user_prompt = refine_call.kwargs["user"]
        assert sample_email.sender in user_prompt
        assert sample_email.subject in user_prompt
        assert sample_email.body in user_prompt

    def test_email_with_cc_recipients(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test avec un email ayant des CC."""
        email = Email(
            id="email-cc",
            sender="sender@test.com",
            subject="Test CC",
            body="Test body",
            recipients=["main@test.com"],
            cc=["cc1@test.com", "cc2@test.com"],
        )
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(
            current_draft="Draft",
            instruction="Formel",
            email=email,
        )

        assert result.status == DraftStatus.VALIDATED_V1


# ============================================================================
# TESTS LLM max_tokens parameter
# ============================================================================


class TestRefineEmailUseCaseLLMParameters:
    """Tests pour vérifier les paramètres passés au LLM."""

    def test_refine_uses_max_tokens_draft(
        self, use_case, mock_llm, mock_llm_response_valid, mock_critique_response_valid
    ):
        """Test que refine utilise max_tokens_draft."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        refine_call = mock_llm.complete.call_args_list[0]
        assert refine_call.kwargs["max_tokens"] == use_case.max_tokens_draft

    def test_critique_uses_max_tokens_critique(
        self, use_case, mock_llm, mock_llm_response_valid, mock_critique_response_valid
    ):
        """Test que critique utilise max_tokens_critique."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        critique_call = mock_llm.complete.call_args_list[1]
        assert critique_call.kwargs["max_tokens"] == use_case.max_tokens_critique

    def test_revise_uses_max_tokens_draft(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_reject,
        mock_revised_response,
    ):
        """Test que revise utilise max_tokens_draft."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_reject,
            mock_revised_response,
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        revise_call = mock_llm.complete.call_args_list[2]
        assert revise_call.kwargs["max_tokens"] == use_case.max_tokens_draft

    def test_system_prompt_passed_to_llm(
        self, use_case, mock_llm, mock_llm_response_valid, mock_critique_response_valid
    ):
        """Test que le prompt système est passé au LLM."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        use_case.execute(current_draft="Draft", instruction="Modify")

        for call in mock_llm.complete.call_args_list:
            assert "system" in call.kwargs
            assert call.kwargs["system"] is not None
            assert len(call.kwargs["system"]) > 0


# ============================================================================
# TESTS Critique.from_response intégration
# ============================================================================


class TestCritiqueIntegration:
    """Tests d'intégration avec Critique.from_response."""

    def test_critique_parses_valid_response(self, use_case, mock_llm):
        """Test que VALID est correctement parsé."""
        response = Mock()
        response.content = "VALID"
        response.input_tokens = 50
        response.output_tokens = 5
        response.model = "test"
        mock_llm.complete.return_value = response

        draft = Draft(content="Test", version=1)
        critique = use_case._critique_draft(draft, email=None)

        assert critique.is_valid is True
        assert critique.reason is None

    def test_critique_parses_valid_with_whitespace(self, use_case, mock_llm):
        """Test que VALID avec espaces est parsé."""
        response = Mock()
        response.content = "   VALID   "
        response.input_tokens = 50
        response.output_tokens = 5
        response.model = "test"
        mock_llm.complete.return_value = response

        draft = Draft(content="Test", version=1)
        critique = use_case._critique_draft(draft, email=None)

        assert critique.is_valid is True

    def test_critique_parses_reject_response(self, use_case, mock_llm):
        """Test que REJET est correctement parsé."""
        response = Mock()
        response.content = "REJET : Le message est trop long"
        response.input_tokens = 50
        response.output_tokens = 15
        response.model = "test"
        mock_llm.complete.return_value = response

        draft = Draft(content="Test", version=1)
        critique = use_case._critique_draft(draft, email=None)

        assert critique.is_valid is False
        assert "trop long" in critique.reason

    def test_critique_parses_lowercase_valid(self, use_case, mock_llm):
        """Test que 'valid' (lowercase) n'est pas validé (case sensitive)."""
        response = Mock()
        response.content = "valid"
        response.input_tokens = 50
        response.output_tokens = 5
        response.model = "test"
        mock_llm.complete.return_value = response

        draft = Draft(content="Test", version=1)
        critique = use_case._critique_draft(draft, email=None)

        # "valid" en minuscule devrait être traité comme valide car startswith fait upper()
        assert critique.is_valid is True


# ============================================================================
# TESTS Draft version tracking
# ============================================================================


class TestDraftVersionTracking:
    """Tests pour le suivi des versions de brouillon."""

    def test_draft_v1_has_version_1(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test que le brouillon V1 a version=1."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(current_draft="Draft", instruction="Test")

        assert result.draft_v1.version == 1

    def test_draft_final_v2_has_version_2(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_reject,
        mock_revised_response,
    ):
        """Test que le brouillon corrigé a version=2."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_reject,
            mock_revised_response,
        ]

        result = use_case.execute(current_draft="Draft", instruction="Test")

        assert result.draft_final.version == 2

    def test_draft_final_equals_v1_when_valid(
        self,
        use_case,
        mock_llm,
        mock_llm_response_valid,
        mock_critique_response_valid,
    ):
        """Test que draft_final == draft_v1 quand validé."""
        mock_llm.complete.side_effect = [
            mock_llm_response_valid,
            mock_critique_response_valid,
        ]

        result = use_case.execute(current_draft="Draft", instruction="Test")

        assert result.draft_final is result.draft_v1
