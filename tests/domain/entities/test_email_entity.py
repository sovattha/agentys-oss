# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour l'entité Email."""

import pytest
from datetime import datetime

from app.domain.entities.email import Email, _validate_email_format
from app.domain.exceptions import EmptyValueError, InvalidFormatError


# =============================================================================
# Tests de validation du format email
# =============================================================================


class TestValidateEmailFormat:
    """Tests pour la fonction _validate_email_format."""

    def test_valid_email_format(self):
        """Doit accepter un email valide."""
        _validate_email_format("user@example.com", "sender")
        # Si pas d'exception, c'est un succès

    def test_valid_email_with_subdomain(self):
        """Doit accepter un email avec sous-domaine."""
        _validate_email_format("user@mail.example.com", "sender")

    def test_valid_email_with_numbers(self):
        """Doit accepter un email avec chiffres."""
        _validate_email_format("user123@example456.com", "sender")

    def test_valid_email_with_dots_in_local_part(self):
        """Doit accepter un email avec points dans la partie locale."""
        _validate_email_format("user.name@example.com", "sender")

    def test_valid_email_with_hyphen_in_domain(self):
        """Doit accepter un email avec tiret dans le domaine."""
        _validate_email_format("user@my-example.com", "sender")

    def test_invalid_email_missing_at_sign(self):
        """Doit rejeter un email sans @."""
        with pytest.raises(InvalidFormatError) as exc_info:
            _validate_email_format("userexample.com", "sender")
        assert exc_info.value.field == "sender"
        assert exc_info.value.code == "INVALID_FORMAT"

    def test_invalid_email_missing_domain(self):
        """Doit rejeter un email sans domaine."""
        with pytest.raises(InvalidFormatError) as exc_info:
            _validate_email_format("user@", "sender")
        assert exc_info.value.field == "sender"

    def test_invalid_email_missing_tld(self):
        """Doit rejeter un email sans TLD."""
        with pytest.raises(InvalidFormatError) as exc_info:
            _validate_email_format("user@example", "sender")
        assert exc_info.value.field == "sender"

    def test_invalid_email_with_space(self):
        """Doit rejeter un email contenant un espace."""
        with pytest.raises(InvalidFormatError):
            _validate_email_format("user name@example.com", "sender")

    def test_invalid_email_multiple_at_signs(self):
        """Doit rejeter un email avec plusieurs @."""
        with pytest.raises(InvalidFormatError):
            _validate_email_format("user@@example.com", "sender")

    def test_invalid_email_at_start(self):
        """Doit rejeter un email commençant par @."""
        with pytest.raises(InvalidFormatError):
            _validate_email_format("@example.com", "sender")

    def test_empty_email_string(self):
        """Doit rejeter une chaîne email vide."""
        with pytest.raises(InvalidFormatError):
            _validate_email_format("", "sender")


# =============================================================================
# Tests construction Email
# =============================================================================


class TestEmailConstruction:
    """Tests pour la construction de l'entité Email."""

    def test_construct_email_with_required_fields_only(self):
        """Doit construire un email avec les champs obligatoires."""
        email = Email(
            id="email-123",
            subject="Test Subject",
            body="Test body content",
            sender="sender@example.com"
        )
        assert email.id == "email-123"
        assert email.subject == "Test Subject"
        assert email.body == "Test body content"
        assert email.sender == "sender@example.com"

    def test_construct_email_with_all_fields(self):
        """Doit construire un email avec tous les champs."""
        now = datetime.now()
        email = Email(
            id="email-123",
            subject="Test Subject",
            body="Test body",
            sender="sender@example.com",
            recipients=["recipient1@example.com", "recipient2@example.com"],
            cc=["cc@example.com"],
            received_at=now,
            thread_id="thread-456",
            is_read=True
        )
        assert email.id == "email-123"
        assert email.subject == "Test Subject"
        assert email.body == "Test body"
        assert email.sender == "sender@example.com"
        assert email.recipients == ["recipient1@example.com", "recipient2@example.com"]
        assert email.cc == ["cc@example.com"]
        assert email.received_at == now
        assert email.thread_id == "thread-456"
        assert email.is_read is True

    def test_default_recipients_is_empty_list(self):
        """Doit initialiser recipients à une liste vide par défaut."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.recipients == []

    def test_default_cc_is_empty_list(self):
        """Doit initialiser cc à une liste vide par défaut."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.cc == []

    def test_default_received_at_is_none(self):
        """Doit initialiser received_at à None par défaut."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.received_at is None

    def test_default_thread_id_is_none(self):
        """Doit initialiser thread_id à None par défaut."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.thread_id is None

    def test_default_is_read_is_false(self):
        """Doit initialiser is_read à False par défaut."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.is_read is False

    def test_subject_can_be_empty_string(self):
        """Doit accepter un sujet vide."""
        email = Email(
            id="email-123",
            subject="",
            body="Body",
            sender="sender@example.com"
        )
        assert email.subject == ""

    def test_body_can_be_empty_string(self):
        """Doit accepter un corps vide."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="",
            sender="sender@example.com"
        )
        assert email.body == ""


# =============================================================================
# Tests validation id
# =============================================================================


class TestEmailIdValidation:
    """Tests pour la validation du champ id."""

    def test_id_none_raises_empty_value_error(self):
        """Doit lever EmptyValueError si id est None."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id=None,
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )
        assert exc_info.value.field == "id"
        assert exc_info.value.code == "EMPTY_VALUE"

    def test_id_empty_string_raises_empty_value_error(self):
        """Doit lever EmptyValueError si id est une chaîne vide."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id="",
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )
        assert exc_info.value.field == "id"

    def test_id_only_whitespace_raises_empty_value_error(self):
        """Doit lever EmptyValueError si id ne contient que des espaces."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id="   ",
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )
        assert exc_info.value.field == "id"

    def test_id_non_string_raises_type_error(self):
        """Doit lever TypeError si id n'est pas une chaîne."""
        with pytest.raises(TypeError) as exc_info:
            Email(
                id=123,
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )
        assert "id must be a string" in str(exc_info.value)

    def test_id_non_string_list_raises_type_error(self):
        """Doit lever TypeError si id est une liste."""
        with pytest.raises(TypeError):
            Email(
                id=["email-123"],
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )

    def test_id_non_string_dict_raises_type_error(self):
        """Doit lever TypeError si id est un dictionnaire."""
        with pytest.raises(TypeError):
            Email(
                id={"id": "email-123"},
                subject="Subject",
                body="Body",
                sender="sender@example.com"
            )

    def test_valid_id_with_alphanumeric(self):
        """Doit accepter un id alphanumeric."""
        email = Email(
            id="email_123_abc",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.id == "email_123_abc"

    def test_valid_id_with_uuid_format(self):
        """Doit accepter un id au format UUID."""
        uuid_string = "550e8400-e29b-41d4-a716-446655440000"
        email = Email(
            id=uuid_string,
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.id == uuid_string

    def test_valid_id_with_single_character(self):
        """Doit accepter un id à un seul caractère."""
        email = Email(
            id="a",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.id == "a"


# =============================================================================
# Tests validation sender
# =============================================================================


class TestEmailSenderValidation:
    """Tests pour la validation du champ sender."""

    def test_sender_empty_string_raises_empty_value_error(self):
        """Doit lever EmptyValueError si sender est une chaîne vide."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id="email-123",
                subject="Subject",
                body="Body",
                sender=""
            )
        assert exc_info.value.field == "sender"
        assert exc_info.value.code == "EMPTY_VALUE"

    def test_sender_only_whitespace_raises_empty_value_error(self):
        """Doit lever EmptyValueError si sender ne contient que des espaces."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id="email-123",
                subject="Subject",
                body="Body",
                sender="   "
            )
        assert exc_info.value.field == "sender"

    def test_sender_invalid_format_raises_invalid_format_error(self):
        """Doit lever InvalidFormatError si sender n'est pas au format email."""
        with pytest.raises(InvalidFormatError) as exc_info:
            Email(
                id="email-123",
                subject="Subject",
                body="Body",
                sender="invalid-sender"
            )
        assert exc_info.value.field == "sender"
        assert exc_info.value.code == "INVALID_FORMAT"

    def test_sender_missing_at_sign_raises_invalid_format_error(self):
        """Doit lever InvalidFormatError si sender n'a pas de @."""
        with pytest.raises(InvalidFormatError):
            Email(
                id="email-123",
                subject="Subject",
                body="Body",
                sender="senderexample.com"
            )

    def test_sender_missing_domain_raises_invalid_format_error(self):
        """Doit lever InvalidFormatError si sender n'a pas de domaine."""
        with pytest.raises(InvalidFormatError):
            Email(
                id="email-123",
                subject="Subject",
                body="Body",
                sender="sender@"
            )

    def test_valid_sender_simple_format(self):
        """Doit accepter un sender au format simple."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="user@example.com"
        )
        assert email.sender == "user@example.com"

    def test_valid_sender_with_subdomain(self):
        """Doit accepter un sender avec sous-domaine."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="user@mail.example.com"
        )
        assert email.sender == "user@mail.example.com"

    def test_validation_order_id_before_sender(self):
        """Doit valider id avant sender."""
        with pytest.raises(EmptyValueError) as exc_info:
            Email(
                id="",
                subject="Subject",
                body="Body",
                sender="invalid"
            )
        # Doit échouer sur id, pas sur sender
        assert exc_info.value.field == "id"


# =============================================================================
# Tests propriétés
# =============================================================================


class TestEmailProperties:
    """Tests pour les propriétés de l'entité Email."""

    def test_is_cc_only_true_when_recipients_empty_and_cc_not_empty(self):
        """Doit retourner True quand recipients est vide et cc a des entrées."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=[],
            cc=["cc@example.com"]
        )
        assert email.is_cc_only is True

    def test_is_cc_only_true_when_multiple_cc_recipients(self):
        """Doit retourner True avec plusieurs cc et pas de destinataires."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=[],
            cc=["cc1@example.com", "cc2@example.com"]
        )
        assert email.is_cc_only is True

    def test_is_cc_only_false_when_recipients_not_empty(self):
        """Doit retourner False quand recipients n'est pas vide."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=["recipient@example.com"],
            cc=["cc@example.com"]
        )
        assert email.is_cc_only is False

    def test_is_cc_only_false_when_both_empty(self):
        """Doit retourner False quand recipients et cc sont tous deux vides."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=[],
            cc=[]
        )
        assert email.is_cc_only is False

    def test_is_cc_only_false_when_no_cc_but_recipients(self):
        """Doit retourner False quand pas de cc mais des recipients."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=["recipient@example.com"],
            cc=[]
        )
        assert email.is_cc_only is False

    def test_content_for_processing_format(self):
        """Doit retourner le contenu formaté correctement."""
        email = Email(
            id="email-123",
            subject="Test Subject",
            body="Test body content",
            sender="sender@example.com"
        )
        expected = "De: sender@example.com\nSujet: Test Subject\n\nTest body content"
        assert email.content_for_processing == expected

    def test_content_for_processing_with_empty_subject(self):
        """Doit inclure un sujet vide dans le contenu formaté."""
        email = Email(
            id="email-123",
            subject="",
            body="Body content",
            sender="sender@example.com"
        )
        expected = "De: sender@example.com\nSujet: \n\nBody content"
        assert email.content_for_processing == expected

    def test_content_for_processing_with_empty_body(self):
        """Doit inclure un corps vide dans le contenu formaté."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="",
            sender="sender@example.com"
        )
        expected = "De: sender@example.com\nSujet: Subject\n\n"
        assert email.content_for_processing == expected

    def test_content_for_processing_with_multiline_body(self):
        """Doit inclure les sauts de ligne du corps."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Line 1\nLine 2\nLine 3",
            sender="sender@example.com"
        )
        expected = "De: sender@example.com\nSujet: Subject\n\nLine 1\nLine 2\nLine 3"
        assert email.content_for_processing == expected

    def test_content_for_processing_with_special_characters(self):
        """Doit préserver les caractères spéciaux dans le contenu."""
        email = Email(
            id="email-123",
            subject="Sujet avec accents: é è ê à",
            body="Contenu avec émojis 🎉 et caractères spéciaux @#$%",
            sender="sender@example.com"
        )
        expected = "De: sender@example.com\nSujet: Sujet avec accents: é è ê à\n\nContenu avec émojis 🎉 et caractères spéciaux @#$%"
        assert email.content_for_processing == expected

    def test_content_for_processing_multiple_calls_consistent(self):
        """Doit retourner la même valeur à chaque appel."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        first_call = email.content_for_processing
        second_call = email.content_for_processing
        assert first_call == second_call


# =============================================================================
# Tests cas limites et intégration
# =============================================================================


class TestEmailEdgeCases:
    """Tests pour les cas limites et comportements spéciaux."""

    def test_email_with_very_long_id(self):
        """Doit accepter un id très long."""
        long_id = "a" * 10000
        email = Email(
            id=long_id,
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email.id == long_id

    def test_email_with_very_long_body(self):
        """Doit accepter un corps très long."""
        long_body = "a" * 100000
        email = Email(
            id="email-123",
            subject="Subject",
            body=long_body,
            sender="sender@example.com"
        )
        assert email.body == long_body

    def test_email_with_unicode_in_all_fields(self):
        """Doit accepter des caractères Unicode dans tous les champs."""
        email = Email(
            id="email-123-français",
            subject="Sujet avec accents: café, résumé",
            body="Contenu avec caractères spéciaux: ñ, ü, ö, 中文, 日本語",
            sender="utilisateur@exemple.fr"
        )
        assert "café" in email.subject
        assert "中文" in email.body

    def test_email_immutability_after_construction(self):
        """Doit permettre la modification des champs après construction."""
        email = Email(
            id="email-123",
            subject="Original Subject",
            body="Original Body",
            sender="sender@example.com"
        )
        # Les dataclasses sont mutables par défaut
        email.subject = "Modified Subject"
        assert email.subject == "Modified Subject"

    def test_email_with_none_received_at_and_thread_id(self):
        """Doit gérer les champs optionnels None correctement."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            received_at=None,
            thread_id=None
        )
        assert email.received_at is None
        assert email.thread_id is None

    def test_email_with_past_received_at(self):
        """Doit accepter une date reçue dans le passé."""
        past_date = datetime(2020, 1, 1, 12, 0, 0)
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            received_at=past_date
        )
        assert email.received_at == past_date

    def test_email_with_future_received_at(self):
        """Doit accepter une date reçue dans le futur."""
        future_date = datetime(2099, 12, 31, 23, 59, 59)
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            received_at=future_date
        )
        assert email.received_at == future_date

    def test_email_with_many_recipients(self):
        """Doit gérer une grande liste de destinataires."""
        recipients = [f"recipient{i}@example.com" for i in range(100)]
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=recipients
        )
        assert len(email.recipients) == 100

    def test_email_with_duplicate_recipients(self):
        """Doit accepter des adresses dupliquées dans recipients."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com",
            recipients=["user@example.com", "user@example.com"]
        )
        assert len(email.recipients) == 2

    def test_email_with_mixed_case_sender(self):
        """Doit accepter un sender en majuscules."""
        email = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="SENDER@EXAMPLE.COM"
        )
        assert email.sender == "SENDER@EXAMPLE.COM"

    def test_email_dataclass_equality(self):
        """Doit pouvoir comparer deux emails."""
        email1 = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        email2 = Email(
            id="email-123",
            subject="Subject",
            body="Body",
            sender="sender@example.com"
        )
        assert email1 == email2

    def test_email_dataclass_inequality(self):
        """Doit détecter les différences entre emails."""
        email1 = Email(
            id="email-123",
            subject="Subject 1",
            body="Body",
            sender="sender@example.com"
        )
        email2 = Email(
            id="email-123",
            subject="Subject 2",
            body="Body",
            sender="sender@example.com"
        )
        assert email1 != email2

    def test_email_with_newlines_in_subject(self):
        """Doit accepter des sauts de ligne dans le sujet."""
        email = Email(
            id="email-123",
            subject="Subject\nLine 2",
            body="Body",
            sender="sender@example.com"
        )
        assert "Line 2" in email.subject


# =============================================================================
# Tests d'intégration complets
# =============================================================================


class TestEmailIntegration:
    """Tests d'intégration complets."""

    def test_complete_email_workflow(self):
        """Test d'un workflow complet d'email."""
        # Création d'un email complet
        email = Email(
            id="msg-2026-001",
            subject="Important Project Update",
            body="Here is the status report for the project...",
            sender="manager@company.com",
            recipients=["team@company.com"],
            cc=["director@company.com"],
            received_at=datetime(2026, 3, 23, 10, 30, 0),
            thread_id="thread-2026-001",
            is_read=False
        )

        # Vérification de tous les champs
        assert email.id == "msg-2026-001"
        assert email.subject == "Important Project Update"
        assert len(email.recipients) == 1
        assert len(email.cc) == 1
        assert email.is_read is False

        # Vérification des propriétés
        assert email.is_cc_only is False
        assert "manager@company.com" in email.content_for_processing
        assert "Important Project Update" in email.content_for_processing

    def test_email_validation_sequence(self):
        """Test de la séquence de validation complète."""
        # Tous les validateurs doivent passer
        email = Email(
            id="valid-id",
            subject="Valid Subject",
            body="Valid Body",
            sender="valid@example.com",
            recipients=["recipient@example.com"],
            cc=["cc@example.com"],
            thread_id="thread-123",
            is_read=True
        )

        assert email.id is not None
        assert isinstance(email.id, str)
        assert email.sender is not None
        assert "@" in email.sender
        assert "." in email.sender.split("@")[1]

    def test_cc_only_email_properties(self):
        """Test les propriétés spécifiques d'un email CC-only."""
        email = Email(
            id="cc-email",
            subject="CC Only Email",
            body="This email was sent in CC",
            sender="external@external.com",
            recipients=[],
            cc=["me@company.com", "colleague@company.com"]
        )

        assert email.is_cc_only is True
        content = email.content_for_processing
        assert "CC Only Email" in content
        assert "external@external.com" in content

    def test_email_with_no_optional_fields_has_defaults(self):
        """Test que les champs optionnels ont les bonnes valeurs par défaut."""
        email = Email(
            id="minimal",
            subject="Minimal",
            body="Minimal",
            sender="minimal@example.com"
        )

        # Vérification des défauts
        assert email.recipients == []
        assert email.cc == []
        assert email.received_at is None
        assert email.thread_id is None
        assert email.is_read is False

        # L'email doit quand même être valide
        assert email.content_for_processing is not None
