# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les use cases LabelEmail et LearnLabelingRule.

pytest tests/application/test_label_email.py -v
"""

import pytest
from unittest.mock import Mock, patch

from app.application.label_email import LabelEmailUseCase, LearnLabelingRuleUseCase
from app.domain.entities import TokenUsage
from app.domain.entities.email_labels import (
    EmailLabel,
    LabelAssignment,
    LabelingRule,
    get_default_labels,
)
from app.domain.ports import LLMPort


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_llm():
    """Mock du LLM."""
    return Mock(spec=LLMPort)


@pytest.fixture
def mock_llm_response():
    """Mock d'une réponse LLM."""
    response = Mock()
    response.content = '{"labels": [{"name": "Action", "confidence": 0.9, "reason": "Demande explicite"}]}'
    response.input_tokens = 100
    response.output_tokens = 50
    response.model = "test-model"
    return response


@pytest.fixture
def default_labels():
    """Labels par défaut."""
    return get_default_labels()


def _stub_optional_email_attrs(email):
    """Mock() auto-crée tout attribut en Mock truthy : `getattr(m, 'x', default)`
    ne retourne jamais le default. On force des valeurs sûres pour les attributs
    optionnels que `LabelEmailUseCase.execute` lit via `getattr` puis concatène
    en chaîne (`body_html`, `attachments_meta`) ou itère (`bcc`, `headers`)."""
    email.body_html = ""
    email.attachments_meta = None
    email.headers = {}
    email.bcc = []
    email.thread_id = None
    email.conversation_id = None
    email.received_at = None


@pytest.fixture
def sample_email():
    """Email de test."""
    email = Mock()
    email.id = "email-123"
    email.sender = "client@example.com"
    email.subject = "Projet en cours"
    email.body = "Bonjour, votre dossier a bien été traité conformément aux instructions données. Cordialement."
    email.to = "user@agentys.com"
    email.cc = ""
    email.recipients = ["user@agentys.com"]
    _stub_optional_email_attrs(email)
    return email


@pytest.fixture
def sample_email_cc():
    """Email où l'utilisateur est en CC."""
    email = Mock()
    email.id = "email-cc-456"
    email.sender = "boss@company.com"
    email.subject = "FYI: Mise à jour projet"
    email.body = "Juste pour info."
    email.to = "team@company.com"
    email.cc = "user@agentys.com"
    email.recipients = ["team@company.com", "user@agentys.com"]
    _stub_optional_email_attrs(email)
    return email


@pytest.fixture
def sample_rules():
    """Règles de labellisation de test."""
    return [
        LabelingRule(
            rule_id="rule-1",
            label_name="Action",
            condition_type="subject",
            condition_value="projet en cours",
            priority=100,
            confidence=0.95,
        ),
        LabelingRule(
            rule_id="rule-2",
            label_name="Agentys",
            condition_type="sender",
            condition_value="@agentys.com",
            priority=80,
            confidence=0.9,
        ),
        LabelingRule(
            rule_id="rule-3",
            label_name="Read",
            condition_type="cc",
            condition_value="",
            priority=60,
            confidence=1.0,
        ),
    ]


# ============================================================================
# TESTS LabelEmailUseCase - INITIALIZATION
# ============================================================================


class TestLabelEmailUseCaseInit:
    """Tests pour l'initialisation de LabelEmailUseCase."""

    def test_init_stores_llm(self, mock_llm, default_labels):
        """L'initialisation stocke le LLM."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        assert use_case.llm == mock_llm

    def test_init_stores_labels(self, mock_llm, default_labels):
        """L'initialisation stocke les labels."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        assert use_case.labels == default_labels

    def test_init_stores_rules(self, mock_llm, default_labels, sample_rules):
        """L'initialisation stocke les règles."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=sample_rules)
        assert len(use_case.rules) == 3

    def test_init_sorts_rules_by_priority_descending(self, mock_llm, default_labels, sample_rules):
        """Les règles sont triées par priorité décroissante."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=sample_rules)
        priorities = [r.priority for r in use_case.rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_init_default_max_tokens(self, mock_llm, default_labels):
        """max_tokens par défaut est 512."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        assert use_case.max_tokens == 512

    def test_init_custom_max_tokens(self, mock_llm, default_labels):
        """max_tokens peut être personnalisé."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[], max_tokens=1024)
        assert use_case.max_tokens == 1024

    def test_init_creates_token_usage_if_none(self, mock_llm, default_labels):
        """TokenUsage est créé si non fourni."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[], token_usage=None)
        assert use_case.token_usage is not None
        assert isinstance(use_case.token_usage, TokenUsage)

    def test_init_uses_provided_token_usage(self, mock_llm, default_labels):
        """TokenUsage fourni est utilisé."""
        token_usage = TokenUsage()
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[], token_usage=token_usage)
        assert use_case.token_usage is token_usage

    def test_init_empty_user_email(self, mock_llm, default_labels):
        """user_email par défaut est vide."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        assert use_case.user_email == ""

    def test_init_custom_user_email(self, mock_llm, default_labels):
        """user_email peut être personnalisé."""
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="me@example.com"
        )
        assert use_case.user_email == "me@example.com"


# ============================================================================
# TESTS LabelEmailUseCase - EXECUTE
# ============================================================================


class TestLabelEmailUseCaseExecute:
    """Tests pour LabelEmailUseCase.execute()."""

    def test_execute_returns_label_assignment(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """Execute retourne un LabelAssignment."""
        mock_llm.complete.return_value = mock_llm_response
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email)
        assert isinstance(result, LabelAssignment)

    def test_execute_assignment_has_email_id(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """L'assignation contient l'ID email."""
        mock_llm.complete.return_value = mock_llm_response
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email)
        assert result.email_id == "email-123"

    def test_execute_with_explicit_is_cc_true(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """is_cc=True force le label FYI."""
        mock_llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email, is_cc=True)
        assert "FYI" in result.labels
        assert result.is_cc is True

    def test_execute_with_explicit_is_cc_false(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """is_cc=False ne force pas le label Read."""
        mock_llm.complete.return_value = mock_llm_response
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email, is_cc=False)
        assert result.is_cc is False

    def test_execute_applies_rules_before_ai(self, mock_llm, default_labels, sample_email, sample_rules):
        """Les règles sont appliquées avant l'IA."""
        mock_llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=sample_rules)
        result = use_case.execute(sample_email)
        # "projet en cours" est dans le sujet, donc Action devrait être assigné par règle
        assert "Action" in result.labels

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_execute_ai_labels_added_if_not_exists(self, mock_rep_store, mock_llm, default_labels, sample_email):
        """Les labels IA sont ajoutés s'ils n'existent pas déjà."""
        mock_rep_store.return_value.get_sender_reputation.return_value = None
        mock_rep_store.return_value.get_domain_reputation.return_value = None
        mock_llm.complete.return_value = Mock(
            content='{"labels": [{"name": "FYI", "confidence": 0.8, "reason": "Information"}]}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email)
        assert "FYI" in result.labels

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_execute_default_label_if_no_labels(self, mock_rep_store, mock_llm, default_labels, sample_email):
        """Label FYI par défaut si aucun label n'est assigné.

        Audit 2026-06-13: the terminal "nothing matched" default flipped
        Noise → FYI. Reaching this branch means NO rule fired (so no noise/bulk
        signal matched) and the LLM returned nothing — the email is
        unclassifiable, not clearly bulk, so we surface it as FYI instead of
        burying it in Noise (a structural cause of FYI starvation).
        """
        mock_rep_store.return_value.get_sender_reputation.return_value = None
        mock_rep_store.return_value.get_domain_reputation.return_value = None
        mock_llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case.execute(sample_email)
        assert "FYI" in result.labels
        assert result.confidences["FYI"] == 0.5

    @patch("app.infrastructure.sender_reputation_store.get_reputation_store")
    def test_execute_updates_token_usage(self, mock_rep_store, mock_llm, default_labels, sample_email, mock_llm_response):
        """L'usage de tokens est enregistré."""
        mock_rep_store.return_value.get_sender_reputation.return_value = None
        mock_rep_store.return_value.get_domain_reputation.return_value = None
        mock_llm.complete.return_value = mock_llm_response
        token_usage = TokenUsage()
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], token_usage=token_usage
        )
        use_case.execute(sample_email)
        assert token_usage.input_tokens > 0


# ============================================================================
# TESTS LabelEmailUseCase - DETECT CC
# ============================================================================


class TestLabelEmailUseCaseDetectCC:
    """Tests pour la détection CC."""

    def test_detect_cc_returns_false_if_no_user_email(self, mock_llm, default_labels, sample_email_cc):
        """Retourne False si user_email est vide."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case._detect_cc(sample_email_cc)
        assert result is False

    def test_detect_cc_returns_true_if_user_in_cc_only(self, mock_llm, default_labels, sample_email_cc):
        """Retourne True si utilisateur en CC mais pas en TO."""
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="user@agentys.com"
        )
        result = use_case._detect_cc(sample_email_cc)
        assert result is True

    def test_detect_cc_returns_false_if_user_in_to(self, mock_llm, default_labels, sample_email):
        """Retourne False si utilisateur en TO."""
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="user@agentys.com"
        )
        result = use_case._detect_cc(sample_email)
        assert result is False

    def test_detect_cc_case_insensitive(self, mock_llm, default_labels, sample_email_cc):
        """La détection est insensible à la casse."""
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="USER@AGENTYS.COM"
        )
        result = use_case._detect_cc(sample_email_cc)
        assert result is True

    def test_detect_cc_handles_missing_to_field(self, mock_llm, default_labels):
        """Gère l'absence du champ TO."""
        email = Mock()
        email.cc = "user@test.com"
        email.to = None
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="user@test.com"
        )
        result = use_case._detect_cc(email)
        assert result is True

    def test_detect_cc_handles_missing_cc_field(self, mock_llm, default_labels):
        """Gère l'absence du champ CC."""
        email = Mock()
        email.cc = None
        email.to = "user@test.com"
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[], user_email="user@test.com"
        )
        result = use_case._detect_cc(email)
        assert result is False


# ============================================================================
# TESTS LabelEmailUseCase - APPLY RULES
# ============================================================================


class TestLabelEmailUseCaseApplyRules:
    """Tests pour l'application des règles."""

    def test_apply_rules_matches_sender(self, mock_llm, default_labels):
        """Règle sender correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="VIP", condition_type="sender",
                condition_value="boss@company.com", priority=100, confidence=1.0
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "boss@company.com", "subject": "Hi", "body": "Hello"}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][0] == "VIP"

    def test_apply_rules_matches_subject_regex(self, mock_llm, default_labels):
        """Règle subject_regex avec alternance correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Urgent", condition_type="subject_regex",
                condition_value="urgent|asap", priority=100, confidence=0.9
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "This is ASAP!", "body": ""}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][0] == "Urgent"

    def test_apply_rules_subject_literal_not_regex(self, mock_llm, default_labels):
        """condition_type='subject' is LITERAL substring. '[Newsletter]' must
        not be interpreted as a regex character class matching N/e/w/s/l/t/r."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Noise", condition_type="subject",
                condition_value="[Newsletter]", priority=100, confidence=0.9
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        # Subject has the letters N/e/w/s/l/t/r but not literal '[Newsletter]'
        bad = {"sender": "alex@x.com", "subject": "Invitation: Rencontre Alexandre", "body": ""}
        assert use_case._apply_rules(bad) == []
        # Literal match still works
        good = {"sender": "alex@x.com", "subject": "[Newsletter] weekly digest", "body": ""}
        result = use_case._apply_rules(good)
        assert len(result) == 1
        assert result[0][0] == "Noise"

    def test_apply_rules_matches_body(self, mock_llm, default_labels):
        """Règle body correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Invoice", condition_type="body",
                condition_value="facture", priority=100, confidence=0.85
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "Doc", "body": "Voici la facture"}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][0] == "Invoice"

    def test_apply_rules_matches_cc(self, mock_llm, default_labels):
        """Règle CC correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="FYI", condition_type="cc",
                condition_value="", priority=100, confidence=1.0
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "Info", "body": "", "is_cc": True}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][0] == "FYI"

    def test_apply_rules_matches_recipient(self, mock_llm, default_labels):
        """Règle recipient correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Team", condition_type="recipient",
                condition_value="team@company.com", priority=100, confidence=0.9
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "Hi", "body": "", "recipients": ["team@company.com"]}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][0] == "Team"

    def test_apply_rules_skips_already_matched_label(self, mock_llm, default_labels):
        """Skip les labels déjà matchés par une règle de priorité supérieure."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Action", condition_type="subject",
                condition_value="urgent", priority=100, confidence=1.0
            ),
            LabelingRule(
                rule_id="r2", label_name="Action", condition_type="body",
                condition_value="important", priority=50, confidence=0.8
            ),
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "Urgent", "body": "Important"}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1
        assert result[0][2] == "Règle: subject = 'urgent'"

    def test_apply_rules_records_use(self, mock_llm, default_labels):
        """L'utilisation de la règle est enregistrée."""
        rule = LabelingRule(
            rule_id="r1", label_name="Test", condition_type="sender",
            condition_value="test@test.com", priority=100, confidence=1.0
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[rule])
        email_data = {"sender": "test@test.com", "subject": "Hi", "body": ""}
        use_case._apply_rules(email_data)
        assert rule.use_count == 1

    def test_apply_rules_handles_invalid_regex(self, mock_llm, default_labels):
        """Gère les regex invalides en fallback sur string match."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="Test", condition_type="subject",
                condition_value="[invalid", priority=100, confidence=1.0
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "test@test.com", "subject": "[invalid", "body": ""}
        result = use_case._apply_rules(email_data)
        assert len(result) == 1  # Fallback to string matching

    def test_apply_rules_no_match(self, mock_llm, default_labels):
        """Retourne liste vide si aucune règle ne correspond."""
        rules = [
            LabelingRule(
                rule_id="r1", label_name="VIP", condition_type="sender",
                condition_value="vip@company.com", priority=100, confidence=1.0
            )
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=rules)
        email_data = {"sender": "nobody@test.com", "subject": "Hi", "body": ""}
        result = use_case._apply_rules(email_data)
        assert len(result) == 0


# ============================================================================
# TESTS LabelEmailUseCase - CLASSIFY WITH AI
# ============================================================================


class TestLabelEmailUseCaseClassifyWithAI:
    """Tests pour la classification IA."""

    def test_classify_with_ai_calls_llm(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """L'IA est appelée via LLM."""
        mock_llm.complete.return_value = mock_llm_response
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        use_case._classify_with_ai(sample_email, [])
        mock_llm.complete.assert_called_once()

    def test_classify_with_ai_excludes_existing_in_prompt(self, mock_llm, default_labels, sample_email, mock_llm_response):
        """Les labels existants sont exclus des labels disponibles pour l'IA."""
        mock_llm.complete.return_value = mock_llm_response
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        # When Action is already assigned, it should not be in the available labels for AI
        use_case._classify_with_ai(sample_email, ["Action"])
        # Check that the system prompt doesn't include Action as an available label
        call_args = mock_llm.complete.call_args
        system_prompt = call_args.kwargs.get("system", "")
        # Action should not be in the available labels since it's already assigned
        assert "Action:" not in system_prompt

    def test_classify_with_ai_returns_empty_if_all_labels_exist(self, mock_llm, default_labels, sample_email):
        """Retourne vide si tous les labels sont déjà assignés."""
        all_label_names = [lbl.name for lbl in default_labels]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case._classify_with_ai(sample_email, all_label_names)
        assert result == []
        mock_llm.complete.assert_not_called()

    def test_classify_with_ai_parses_response(self, mock_llm, default_labels, sample_email):
        """La réponse IA est parsée correctement."""
        mock_llm.complete.return_value = Mock(
            content='{"labels": [{"name": "FYI", "confidence": 0.85, "reason": "Test"}]}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        result = use_case._classify_with_ai(sample_email, [])
        assert len(result) == 1
        assert result[0][0] == "FYI"
        assert result[0][1] == 0.85


# ============================================================================
# TESTS LabelEmailUseCase - PROMPTS
# ============================================================================


class TestLabelEmailUseCasePrompts:
    """Tests pour la construction des prompts."""

    def test_build_system_prompt_contains_labels(self, mock_llm, default_labels):
        """Le prompt système contient les labels disponibles."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        available = [f"- {lbl.name}: {lbl.description}" for lbl in default_labels]
        prompt = use_case._build_system_prompt(available)
        assert "Action" in prompt
        assert "FYI" in prompt

    def test_build_system_prompt_contains_json_format(self, mock_llm, default_labels):
        """Le prompt système spécifie le format JSON."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        prompt = use_case._build_system_prompt([])
        assert "JSON" in prompt

    def test_build_user_prompt_contains_email_info(self, mock_llm, default_labels, sample_email):
        """Le prompt utilisateur contient les infos email."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        prompt = use_case._build_user_prompt(sample_email, [])
        assert sample_email.sender in prompt
        assert sample_email.subject in prompt

    def test_build_user_prompt_truncates_body(self, mock_llm, default_labels):
        """Le corps est tronqué à 1500 caractères."""
        email = Mock()
        email.sender = "test@test.com"
        email.subject = "Test"
        email.body = "A" * 3000
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        prompt = use_case._build_user_prompt(email, [])
        # Body tronqué à 1500
        assert len(prompt) < 3000


# ============================================================================
# TESTS LabelEmailUseCase - PARSE AI RESPONSE
# ============================================================================


class TestLabelEmailUseCaseParseAIResponse:
    """Tests pour le parsing des réponses IA."""

    def test_parse_ai_response_valid_json(self, mock_llm, default_labels):
        """Parse une réponse JSON valide."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": [{"name": "Action", "confidence": 0.9, "reason": "Test"}]}'
        result = use_case._parse_ai_response(response)
        assert len(result) == 1
        assert result[0][0] == "Action"

    def test_parse_ai_response_with_markdown_wrapper(self, mock_llm, default_labels):
        """Parse une réponse avec wrapper markdown."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '```json\n{"labels": [{"name": "FYI", "confidence": 0.8}]}\n```'
        result = use_case._parse_ai_response(response)
        assert len(result) == 1
        assert result[0][0] == "FYI"

    def test_parse_ai_response_invalid_json(self, mock_llm, default_labels):
        """Retourne liste vide pour JSON invalide."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = "This is not JSON"
        result = use_case._parse_ai_response(response)
        assert result == []

    def test_parse_ai_response_empty_labels(self, mock_llm, default_labels):
        """Gère une liste de labels vide."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": []}'
        result = use_case._parse_ai_response(response)
        assert result == []

    def test_parse_ai_response_filters_invalid_labels(self, mock_llm, default_labels):
        """Filtre les labels invalides."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": [{"name": "InvalidLabel", "confidence": 0.9}]}'
        result = use_case._parse_ai_response(response)
        assert result == []

    def test_parse_ai_response_default_confidence(self, mock_llm, default_labels):
        """Utilise confidence par défaut si non spécifié."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": [{"name": "Action"}]}'
        result = use_case._parse_ai_response(response)
        assert result[0][1] == 0.8

    def test_parse_ai_response_default_reason(self, mock_llm, default_labels):
        """Utilise reason par défaut si non spécifié."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": [{"name": "Action", "confidence": 0.9}]}'
        result = use_case._parse_ai_response(response)
        assert result[0][2] == "Classification IA"

    def test_parse_ai_response_multiple_labels(self, mock_llm, default_labels):
        """Parse plusieurs labels."""
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=[])
        response = '{"labels": [{"name": "Action", "confidence": 0.9}, {"name": "FYI", "confidence": 0.7}]}'
        result = use_case._parse_ai_response(response)
        assert len(result) == 2


# ============================================================================
# TESTS LearnLabelingRuleUseCase - INITIALIZATION
# ============================================================================


class TestLearnLabelingRuleUseCaseInit:
    """Tests pour l'initialisation de LearnLabelingRuleUseCase."""

    def test_init_stores_llm(self, mock_llm):
        """L'initialisation stocke le LLM."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        assert use_case.llm == mock_llm

    def test_init_default_max_tokens(self, mock_llm):
        """max_tokens par défaut est 256."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        assert use_case.max_tokens == 256

    def test_init_creates_token_usage_if_none(self, mock_llm):
        """TokenUsage est créé si non fourni."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=None)
        assert use_case.token_usage is not None

    def test_init_uses_provided_token_usage(self, mock_llm):
        """TokenUsage fourni est utilisé."""
        token_usage = TokenUsage()
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=token_usage)
        assert use_case.token_usage is token_usage


# ============================================================================
# TESTS LearnLabelingRuleUseCase - EXECUTE
# ============================================================================


class TestLearnLabelingRuleUseCaseExecute:
    """Tests pour LearnLabelingRuleUseCase.execute()."""

    def test_execute_returns_list(self, mock_llm, sample_email):
        """Execute retourne une liste."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.9}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, ["Read"], ["Action"])
        assert isinstance(result, list)

    def test_execute_returns_empty_if_no_changes(self, mock_llm, sample_email):
        """Retourne liste vide si pas de changements."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, ["Read"], ["Read"])
        assert result == []
        mock_llm.complete.assert_not_called()

    def test_execute_learns_from_added_labels(self, mock_llm, sample_email):
        """Apprend des labels ajoutés."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "subject", "condition_value": "demande urgente", "confidence": 0.85}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, [], ["Action"])
        assert len(result) == 1
        assert result[0].label_name == "Action"

    def test_execute_learns_from_multiple_added_labels(self, mock_llm, sample_email):
        """Apprend de plusieurs labels ajoutés."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "subject", "condition_value": "projet en cours", "confidence": 0.9}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, [], ["Action", "Waiting"])
        assert len(result) == 2

    def test_execute_ignores_removed_labels(self, mock_llm, sample_email):
        """Les labels retirés ne génèrent pas de règles."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": null}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, ["Action"], [])
        # Aucune règle générée pour les labels retirés
        assert result == []


# ============================================================================
# TESTS LearnLabelingRuleUseCase - EXTRACT PATTERN
# ============================================================================


class TestLearnLabelingRuleUseCaseExtractPattern:
    """Tests pour l'extraction de patterns."""

    def test_extract_pattern_returns_rule(self, mock_llm, sample_email):
        """Retourne une règle pour un pattern valide."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.9}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "VIP", "add")
        assert result is not None
        assert isinstance(result, LabelingRule)

    def test_extract_pattern_rule_has_correct_label(self, mock_llm, sample_email):
        """La règle a le bon label."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.8}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Custom", "add")
        assert result.label_name == "Custom"

    def test_extract_pattern_rule_has_learned_from(self, mock_llm, sample_email):
        """La règle a la source d'apprentissage."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "subject", "condition_value": "demande urgente", "confidence": 0.8}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result.learned_from == "email-123"

    def test_extract_pattern_rule_has_medium_priority(self, mock_llm, sample_email):
        """Les règles apprises ont une priorité moyenne (40)."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "body", "condition_value": "répondre rapidement", "confidence": 0.8}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result.priority == 40

    def test_extract_pattern_returns_none_for_null_type(self, mock_llm, sample_email):
        """Retourne None si condition_type est null."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": null}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result is None

    def test_extract_pattern_returns_none_for_invalid_json(self, mock_llm, sample_email):
        """Retourne None pour JSON invalide."""
        mock_llm.complete.return_value = Mock(
            content='invalid json',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result is None

    def test_extract_pattern_handles_markdown_wrapper(self, mock_llm, sample_email):
        """Gère le wrapper markdown."""
        mock_llm.complete.return_value = Mock(
            content='```json\n{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.85}\n```',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result is not None
        assert result.confidence == 0.85

    def test_extract_pattern_uses_default_confidence(self, mock_llm, sample_email):
        """Utilise confidence par défaut si non spécifié."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com"}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "Test", "add")
        assert result.confidence == 0.8

    def test_extract_pattern_updates_token_usage(self, mock_llm, sample_email):
        """L'usage de tokens est enregistré."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "test", "confidence": 0.9}',
            input_tokens=100, output_tokens=50, model="test"
        )
        token_usage = TokenUsage()
        use_case = LearnLabelingRuleUseCase(llm=mock_llm, token_usage=token_usage)
        use_case._extract_pattern(sample_email, "Test", "add")
        assert token_usage.input_tokens == 100
        assert token_usage.output_tokens == 50

    def test_extract_pattern_generates_unique_id(self, mock_llm, sample_email):
        """Génère un ID unique pour la règle."""
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.9}',
            input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result1 = use_case._extract_pattern(sample_email, "Test1", "add")
        result2 = use_case._extract_pattern(sample_email, "Test2", "add")
        assert result1.rule_id != result2.rule_id


# ============================================================================
# TESTS LearnLabelingRuleUseCase - ERROR HANDLING & FALLBACK
# ============================================================================


class TestLearnLabelingRuleUseCaseErrorHandling:
    """Tests pour la gestion d'erreurs et les règles fallback."""

    def test_extract_pattern_catches_llm_error(self, mock_llm, sample_email):
        """_extract_pattern retourne None si le LLM lève une exception."""
        from app.domain.exceptions import LLMConnectionError
        mock_llm.complete.side_effect = LLMConnectionError(
            provider="test", url="test", message="connection refused"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "FYI", "Action")
        assert result is None

    def test_execute_fallback_on_llm_failure(self, mock_llm, sample_email):
        """Fallback sender rule is created when LLM fails."""
        from app.domain.exceptions import LLMConnectionError
        mock_llm.complete.side_effect = LLMConnectionError(
            provider="test", url="test", message="connection refused"
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case.execute(sample_email, ["Action"], ["FYI"])
        assert len(result) == 1
        assert result[0].condition_type == "sender"
        assert result[0].label_name == "FYI"
        assert result[0].learned_from == "email-123"

    def test_fallback_noise_uses_domain(self, mock_llm, sample_email):
        """Noise fallback uses @domain."""
        sample_email.sender = "news@company.com"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Noise")
        assert result is not None
        assert result.condition_value == "@company.com"
        assert result.label_name == "Noise"

    def test_fallback_fyi_uses_full_email(self, mock_llm, sample_email):
        """FYI fallback uses full email address."""
        sample_email.sender = "John Doe <john@example.com>"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "FYI")
        assert result is not None
        assert result.condition_value == "john@example.com"
        assert result.label_name == "FYI"

    def test_fallback_waiting_uses_full_email(self, mock_llm, sample_email):
        """Waiting fallback uses full email address."""
        sample_email.sender = "alice@corp.com"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Waiting")
        assert result is not None
        assert result.condition_value == "alice@corp.com"

    def test_fallback_action_creates_subject_rule(self, mock_llm, sample_email):
        """Action fallback creates a subject-based rule (sender->Action blocked)."""
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Action")
        assert result is not None
        assert result.condition_type == "subject"
        assert result.label_name == "Action"
        assert result.confidence == 0.65

    def test_fallback_personal_domain_noise_uses_full_email(self, mock_llm, sample_email):
        """Noise + personal domain uses full email instead of domain."""
        sample_email.sender = "spam@gmail.com"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Noise")
        assert result is not None
        assert result.condition_value == "spam@gmail.com"

    def test_fallback_has_learned_from(self, mock_llm, sample_email):
        """Fallback rule has learned_from set to email ID."""
        sample_email.sender = "info@newsletter.com"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Noise")
        assert result is not None
        assert result.learned_from == "email-123"
        assert result.priority == 35
        assert result.confidence == 0.75

    def test_fallback_no_at_sign_returns_none(self, mock_llm, sample_email):
        """Fallback returns None if sender has no @ sign."""
        sample_email.sender = "invalid-sender"
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._create_fallback_rule(sample_email, "Noise")
        assert result is None

    def test_extract_pattern_catches_timeout_error(self, mock_llm, sample_email):
        """_extract_pattern retourne None si le LLM timeout."""
        from app.domain.exceptions import LLMTimeoutError
        mock_llm.complete.side_effect = LLMTimeoutError(
            provider="test", timeout_seconds=30
        )
        use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        result = use_case._extract_pattern(sample_email, "FYI", "Action")
        assert result is None


# ============================================================================
# TESTS INTEGRATION
# ============================================================================


class TestLabelEmailIntegration:
    """Tests d'intégration pour le workflow complet."""

    def test_full_workflow_with_rules_and_ai(self, mock_llm, default_labels, sample_email):
        """Workflow complet avec règles (custom label) et IA (default label)."""
        mock_llm.complete.return_value = Mock(
            content='{"labels": [{"name": "Action", "confidence": 0.8, "reason": "Demande"}]}',
            input_tokens=10, output_tokens=5, model="test"
        )
        # Use a rule that sets a CUSTOM label (not default), so AI is still called for default
        custom_rules = [
            LabelingRule(
                rule_id="rule-custom", label_name="Agentys",
                condition_type="subject", condition_value="projet",
                priority=100, confidence=0.9,
            ),
        ]
        use_case = LabelEmailUseCase(llm=mock_llm, labels=default_labels, rules=custom_rules)
        result = use_case.execute(sample_email)

        # Agentys est assigné par règle (subject contient "projet")
        assert "Agentys" in result.labels
        # Action est assigné par IA
        assert "Action" in result.labels

    def test_cc_email_always_gets_fyi_label(self, mock_llm, default_labels, sample_email_cc):
        """Un email en CC reçoit toujours le label FYI."""
        mock_llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=10, output_tokens=5, model="test"
        )
        use_case = LabelEmailUseCase(
            llm=mock_llm, labels=default_labels, rules=[],
            user_email="user@agentys.com"
        )
        result = use_case.execute(sample_email_cc)
        assert "FYI" in result.labels
        assert result.is_cc is True
        assert result.confidences["FYI"] == 1.0

    def test_learn_and_apply_rule(self, mock_llm, default_labels, sample_email):
        """Apprendre une règle puis l'appliquer."""
        # Apprendre une règle
        mock_llm.complete.return_value = Mock(
            content='{"condition_type": "sender", "condition_value": "client@example.com", "confidence": 0.95}',
            input_tokens=10, output_tokens=5, model="test"
        )
        learn_use_case = LearnLabelingRuleUseCase(llm=mock_llm)
        rules = learn_use_case.execute(sample_email, [], ["VIP"])

        # Créer un label VIP
        vip_label = EmailLabel(name="VIP", color="#ff0000", description="Important")
        labels = default_labels + [vip_label]

        # Appliquer la règle apprise
        mock_llm.complete.return_value = Mock(
            content='{"labels": []}', input_tokens=10, output_tokens=5, model="test"
        )
        label_use_case = LabelEmailUseCase(llm=mock_llm, labels=labels, rules=rules)
        result = label_use_case.execute(sample_email)

        assert "VIP" in result.labels
