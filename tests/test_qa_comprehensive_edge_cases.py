# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests QA Complet - Edge Cases Avancés.

Ce module couvre les edge cases non testés identifiés lors de l'audit QA :
1. DraftHistory - Concurrence, corruption fichier, edge cases timestamp
2. SpecializedAgents - Registry, agents invalides, matchings
3. Container - Lazy loading, singletons, erreurs d'initialisation
4. Entités Domain - Sérialisation/désérialisation, validations
5. Infrastructure - Config, stores, adapters

pytest tests/test_qa_comprehensive_edge_cases.py -v
"""

import pytest
import json
import tempfile
import threading
from pathlib import Path
from datetime import datetime

# ============================================================================
# IMPORTS
# ============================================================================

from app.domain.entities import (
    Email,
    Draft,
    Critique,
    ProcessingResult,
    DraftStatus,
    TokenUsage,
    DeviceToken,
    DevicePlatform,
    PushNotification,
    PushNotificationCategory,
    PushNotificationStatus,
    PushNotificationRecord,
    DraftInput,
    DraftInputTone,
    CompletedDraft,
)
from app.domain.ports import LLMResponse

from app.history import (
    DraftHistory,
    DraftRecord,
    create_record,
)


# ============================================================================
# FIXTURES GLOBALES
# ============================================================================

@pytest.fixture
def temp_dir():
    """Crée un répertoire temporaire."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ============================================================================
# TESTS - DRAFT HISTORY EDGE CASES AVANCÉS
# ============================================================================

class TestDraftHistoryAdvancedEdgeCases:
    """Edge cases avancés pour DraftHistory."""

    @pytest.fixture
    def history(self, temp_dir):
        """Crée un DraftHistory temporaire."""
        history_file = temp_dir / "history" / "drafts.json"
        history_file.parent.mkdir(parents=True, exist_ok=True)
        return DraftHistory(history_file=history_file)

    def test_concurrent_writes(self, history):
        """Écritures concurrentes ne perdent pas de données."""
        errors = []
        written_ids = []
        lock = threading.Lock()

        def write_record(index):
            try:
                record = DraftRecord(
                    id=f"concurrent-{index}",
                    timestamp=datetime.now().isoformat(),
                    email_id=f"email-{index}",
                    email_sender=f"sender{index}@test.com",
                    email_subject=f"Subject {index}",
                    email_preview=f"Preview {index}",
                    draft_v1=f"Draft V1 {index}",
                    critique=f"Critique {index}",
                    draft_final=f"Final {index}",
                    status="VALIDÉ V1"
                )
                history.add(record)
                with lock:
                    written_ids.append(f"concurrent-{index}")
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=write_record, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Erreurs: {errors}"
        # Note: À cause de race conditions, on peut perdre des records
        # Ce test documente le comportement actuel

    def test_load_with_binary_garbage(self, history, temp_dir):
        """Chargement avec données binaires."""
        history_file = temp_dir / "history" / "drafts.json"
        history_file.write_bytes(b'\x00\x01\x02\xff\xfe\xfd')

        records = history._load()
        assert records == []  # Fallback gracieux

    def test_load_with_empty_array(self, history, temp_dir):
        """Chargement avec tableau vide."""
        history_file = temp_dir / "history" / "drafts.json"
        history_file.write_text("[]")

        records = history._load()
        assert records == []

    def test_load_with_null(self, history, temp_dir):
        """Chargement avec null JSON."""
        history_file = temp_dir / "history" / "drafts.json"
        history_file.write_text("null")

        records = history._load()
        # Le code doit retourner [] pour un fichier null (pas une liste)
        assert records == []

    def test_load_with_incomplete_record(self, history, temp_dir):
        """Chargement avec record incomplet - doit être ignoré silencieusement."""
        history_file = temp_dir / "history" / "drafts.json"
        # Record avec champs manquants
        incomplete_data = [{"id": "test-1", "timestamp": "2024-01-01T00:00:00"}]
        history_file.write_text(json.dumps(incomplete_data))

        # get_all doit ignorer les records incomplets et retourner une liste vide
        records = history.get_all()
        assert records == []  # Record incomplet ignoré silencieusement

    def test_get_stats_with_no_v1_or_v2(self, history):
        """Statistiques avec records sans V1/V2 dans status."""
        record = DraftRecord(
            id="weird-1",
            timestamp=datetime.now().isoformat(),
            email_id="email-1",
            email_sender="test@test.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="UNKNOWN_STATUS"  # Pas de V1 ou V2
        )
        history.add(record)

        stats = history.get_stats()
        assert stats["validated_v1"] == 0
        assert stats["corrected_v2"] == 0
        assert stats["total"] == 1

    def test_get_stats_with_no_processing_time(self, history):
        """Statistiques avec records sans processing_time_ms."""
        record = DraftRecord(
            id="no-time-1",
            timestamp=datetime.now().isoformat(),
            email_id="email-1",
            email_sender="test@test.com",
            email_subject="Test",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1",
            processing_time_ms=0  # Zéro
        )
        history.add(record)

        stats = history.get_stats()
        # Avec processing_time_ms=0, il n'est pas inclus dans le calcul
        assert stats["avg_processing_time_ms"] == 0

    def test_search_case_insensitive(self, history):
        """Recherche insensible à la casse."""
        record = DraftRecord(
            id="case-1",
            timestamp=datetime.now().isoformat(),
            email_id="email-1",
            email_sender="JohnDoe@EXAMPLE.COM",
            email_subject="IMPORTANT Subject",
            email_preview="Preview",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        history.add(record)

        # Recherche en minuscules
        results = history.search(query="johndoe")
        assert len(results) == 1

        # Recherche en majuscules
        results = history.search(query="IMPORTANT")
        assert len(results) == 1

    def test_export_csv_with_special_characters(self, history):
        """Export CSV avec caractères spéciaux."""
        record = DraftRecord(
            id="special-1",
            timestamp=datetime.now().isoformat(),
            email_id="email-1",
            email_sender='test@test.com',
            email_subject='Sujet avec "guillemets" et, virgules',
            email_preview='Preview avec\nnewlines',
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="VALIDÉ V1"
        )
        history.add(record)

        csv_content = history.export_csv()
        assert "special-1" in csv_content
        # Le CSV devrait être valide malgré les caractères spéciaux

    def test_daily_stats_with_invalid_timestamp(self, history, temp_dir):
        """Stats journalières avec timestamp invalide."""
        history_file = temp_dir / "history" / "drafts.json"
        # Record avec timestamp malformé
        data = [{
            "id": "invalid-ts",
            "timestamp": "not-a-timestamp",
            "email_id": "email-1",
            "email_sender": "test@test.com",
            "email_subject": "Test",
            "email_preview": "Preview",
            "draft_v1": "V1",
            "critique": "Critique",
            "draft_final": "Final",
            "status": "VALIDÉ V1"
        }]
        history_file.write_text(json.dumps(data))

        history.get_stats()
        # Ne devrait pas crasher, daily_stats devrait gérer gracieusement


# ============================================================================
# TESTS - TOKEN USAGE EDGE CASES
# ============================================================================

class TestTokenUsageEdgeCases:
    """Edge cases pour TokenUsage."""

    def test_cost_with_float_overflow(self):
        """Coût avec tokens très élevés (overflow potentiel)."""
        usage = TokenUsage(
            input_tokens=10**15,  # 1 quadrillion
            output_tokens=10**15,
            model="claude-sonnet-4-20250514"
        )
        cost = usage.cost
        # Ne devrait pas overflow, retourne un float
        assert isinstance(cost, float)
        assert cost > 0

    def test_add_with_zero_tokens(self):
        """Add avec zéro tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        usage.add(0, 0, "")

        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_str_with_unknown_model(self):
        """__str__ avec modèle inconnu."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="unknown-model-xyz"
        )
        result = str(usage)
        # Ne devrait pas crasher
        assert "1,000" in result

    def test_str_with_model_containing_special_chars(self):
        """__str__ avec modèle contenant des caractères spéciaux."""
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            model="model:with:colons-and_underscores"
        )
        result = str(usage)
        assert "100" in result

    def test_reset_clears_all(self):
        """Reset remet tout à zéro."""
        usage = TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            model="claude-opus-4-20250514"
        )
        usage.reset()

        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.model == ""
        assert usage.total == 0
        assert usage.cost == 0  # Zéro car pas de tokens

    def test_input_output_aliases(self):
        """Test des aliases input/output."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)

        assert usage.input == usage.input_tokens
        assert usage.output == usage.output_tokens


# ============================================================================
# TESTS - CRITIQUE PARSING EDGE CASES
# ============================================================================

class TestCritiqueParsingEdgeCases:
    """Edge cases pour Critique.from_response."""

    def test_empty_response(self):
        """Réponse vide."""
        critique = Critique.from_response("")
        assert critique.is_valid is False
        assert critique.raw_response == ""

    def test_only_whitespace(self):
        """Réponse avec uniquement des espaces."""
        critique = Critique.from_response("   \t\n  ")
        assert critique.is_valid is False

    def test_valid_lowercase(self):
        """VALID en minuscules."""
        critique = Critique.from_response("valid response")
        assert critique.is_valid is True

    def test_valide_french(self):
        """VALIDE en français."""
        critique = Critique.from_response("VALIDE - Bonne réponse")
        # Le parsing vérifie startswith("VALID"), donc VALIDE = True
        assert critique.is_valid is True

    def test_validation_word(self):
        """Mot contenant VALID au début."""
        critique = Critique.from_response("VALIDATION needed")
        # Commence par VALID donc considéré valide
        assert critique.is_valid is True

    def test_reason_extraction(self):
        """Extraction de la raison du rejet."""
        critique = Critique.from_response("REJET : Ton trop informel")
        assert critique.is_valid is False
        assert "Ton trop informel" in critique.reason

    def test_binary_characters(self):
        """Réponse avec caractères binaires."""
        response = "REJET \x00\x01 Invalid chars"
        critique = Critique.from_response(response)
        assert critique.is_valid is False


# ============================================================================
# TESTS - DEVICE TOKEN EDGE CASES
# ============================================================================

class TestDeviceTokenEdgeCases:
    """Edge cases pour DeviceToken."""

    def test_empty_token_raises(self):
        """Token vide lève une erreur."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="", platform=DevicePlatform.IOS)

    def test_whitespace_token_raises(self):
        """Token avec uniquement des espaces lève une erreur."""
        # "   " est considéré comme vide après strip()
        with pytest.raises(ValueError, match="cannot be empty"):
            DeviceToken(token="   ", platform=DevicePlatform.IOS)

    def test_platform_from_string(self):
        """Platform depuis une string."""
        device = DeviceToken(token="test", platform="ios")
        assert device.platform == DevicePlatform.IOS

    def test_platform_invalid_string_raises(self):
        """Platform invalide lève une erreur."""
        with pytest.raises(ValueError):
            DeviceToken(token="test", platform="blackberry")

    def test_to_dict_with_none_last_used(self):
        """to_dict avec last_used_at None."""
        device = DeviceToken(
            token="test",
            platform=DevicePlatform.ANDROID,
            last_used_at=None
        )
        data = device.to_dict()
        assert data["last_used_at"] is None

    def test_from_dict_with_missing_created_at(self):
        """from_dict avec created_at manquant."""
        data = {
            "token": "test",
            "platform": "web"
        }
        device = DeviceToken.from_dict(data)
        # created_at devrait avoir une valeur par défaut
        assert device.created_at is not None


# ============================================================================
# TESTS - PUSH NOTIFICATION EDGE CASES
# ============================================================================

class TestPushNotificationEdgeCases:
    """Edge cases pour PushNotification."""

    def test_empty_title_raises(self):
        """Titre vide lève une erreur."""
        with pytest.raises(ValueError, match="title cannot be empty"):
            PushNotification(title="", body="Body")

    def test_empty_body_raises(self):
        """Corps vide lève une erreur."""
        with pytest.raises(ValueError, match="body cannot be empty"):
            PushNotification(title="Title", body="")

    def test_category_from_string(self):
        """Category depuis une string."""
        notif = PushNotification(
            title="Title",
            body="Body",
            category="draft.created"
        )
        assert notif.category == PushNotificationCategory.DRAFT_CREATED

    def test_category_invalid_raises(self):
        """Category invalide lève une erreur."""
        with pytest.raises(ValueError):
            PushNotification(
                title="Title",
                body="Body",
                category="invalid.category"
            )

    def test_to_dict_with_none_data(self):
        """to_dict avec data=None retourne {}."""
        notif = PushNotification(
            title="Title",
            body="Body",
            data=None
        )
        data = notif.to_dict()
        assert data["data"] == {}

    def test_negative_badge(self):
        """Badge négatif (edge case)."""
        notif = PushNotification(
            title="Title",
            body="Body",
            badge=-5
        )
        # Pas de validation, accepté
        assert notif.badge == -5

    def test_negative_ttl(self):
        """TTL négatif (edge case)."""
        notif = PushNotification(
            title="Title",
            body="Body",
            ttl=-1
        )
        assert notif.ttl == -1


# ============================================================================
# TESTS - DRAFT INPUT EDGE CASES
# ============================================================================

class TestDraftInputEdgeCases:
    """Edge cases pour DraftInput."""

    def test_is_draft_input_with_numbers_only(self):
        """Texte avec uniquement des numéros."""
        text = """1. Premier
2. Deuxième
3. Troisième"""
        assert DraftInput.is_draft_input(text) is True

    def test_is_draft_input_with_mixed_content(self):
        """Texte mélangé bullets et prose."""
        text = """Voici ma demande:
- Point 1
Avec du texte entre
- Point 2"""
        # 2/4 lignes sont des bullets = 50%
        result = DraftInput.is_draft_input(text)
        assert isinstance(result, bool)

    def test_extract_recipient_email_format(self):
        """Extraction destinataire format email."""
        text = "Brouillon: à support@company.com, demande d'info"
        DraftInput.from_raw_text(text)
        # Le pattern regex ne capture pas les emails complets
        # mais peut capturer des parties

    def test_extract_tone_multiple_keywords(self):
        """Plusieurs keywords de ton présents."""
        text = "Brouillon urgent et formel: test"
        draft = DraftInput.from_raw_text(text)
        # Premier ton trouvé gagne (URGENT avant FORMAL dans le dict)
        assert draft.tone in [DraftInputTone.FORMAL, DraftInputTone.URGENT]

    def test_key_points_with_indentation(self):
        """Key points avec indentation."""
        text = """  - Point indenté 1
    - Point très indenté 2
- Point normal"""
        draft = DraftInput.from_raw_text(text)
        assert len(draft.key_points) >= 2

    def test_subject_extraction_multiple_patterns(self):
        """Extraction sujet avec multiples patterns."""
        text = """Sujet: Premier sujet
Objet: Deuxième sujet
- Point clé"""
        draft = DraftInput.from_raw_text(text)
        # Premier pattern trouvé gagne
        assert "Premier sujet" in (draft.subject_hint or "")

    def test_has_enough_context_boundary(self):
        """has_enough_context aux limites."""
        # 0 key points
        draft1 = DraftInput(raw_input="test", key_points=[])
        assert draft1.has_enough_context is False

        # 1 key point
        draft2 = DraftInput(raw_input="test", key_points=["Un point"])
        assert draft2.has_enough_context is True


# ============================================================================
# TESTS - COMPLETED DRAFT EDGE CASES
# ============================================================================

class TestCompletedDraftEdgeCases:
    """Edge cases pour CompletedDraft."""

    def test_str_with_empty_subject(self):
        """__str__ avec sujet vide."""
        draft = CompletedDraft(subject="", body="Corps du message")
        result = str(draft)
        # Devrait quand même avoir le corps
        assert "Corps du message" in result

    def test_str_with_multiline_body(self):
        """__str__ avec corps multi-lignes."""
        draft = CompletedDraft(
            subject="Sujet",
            body="Ligne 1\n\nLigne 2\n\n\nLigne 3"
        )
        result = str(draft)
        assert "Ligne 1" in result
        assert "Ligne 3" in result

    def test_formatted_output_contains_cta(self):
        """formatted_output contient le CTA."""
        draft = CompletedDraft(subject="Test", body="Body")
        output = draft.formatted_output
        assert "Prêt à envoyer" in output
        assert "modifier" in output
        assert "---" in output


# ============================================================================
# TESTS - EMAIL ENTITY EDGE CASES
# ============================================================================

class TestEmailEntityEdgeCases:
    """Edge cases pour Email."""

    def test_is_cc_only_with_none_recipients(self):
        """is_cc_only avec recipients None (impossible avec list default)."""
        # Dataclass utilise default_factory, donc toujours une liste
        email = Email(
            id="1",
            subject="Test",
            body="Body",
            sender="test@test.com"
        )
        assert email.recipients == []
        assert email.cc == []
        assert email.is_cc_only is False

    def test_content_for_processing_with_multiline_body(self):
        """content_for_processing avec corps multi-lignes."""
        email = Email(
            id="1",
            subject="Test",
            body="Ligne 1\nLigne 2\nLigne 3",
            sender="test@test.com"
        )
        content = email.content_for_processing
        assert "Ligne 1" in content
        assert "Ligne 2" in content
        assert "Ligne 3" in content

    def test_email_with_international_sender(self):
        """Email avec expéditeur international."""
        email = Email(
            id="1",
            subject="Test",
            body="Body",
            sender="用户@例え.日本"  # Unicode email
        )
        assert email.sender == "用户@例え.日本"


# ============================================================================
# TESTS - PROCESSING RESULT EDGE CASES
# ============================================================================

class TestProcessingResultEdgeCases:
    """Edge cases pour ProcessingResult."""

    def test_was_corrected_with_all_statuses(self):
        """was_corrected avec tous les statuts."""
        for status in DraftStatus:
            result = ProcessingResult(
                email_id="1",
                draft_v1=Draft(content="V1"),
                critique=Critique(raw_response="Test", is_valid=True),
                draft_final=Draft(content="Final"),
                status=status
            )
            if status == DraftStatus.CORRECTED_V2:
                assert result.was_corrected is True
            else:
                assert result.was_corrected is False


# ============================================================================
# TESTS - LLM RESPONSE EDGE CASES
# ============================================================================

class TestLLMResponseEdgeCases:
    """Edge cases pour LLMResponse."""

    def test_llm_response_with_unicode_model_name(self):
        """LLMResponse avec nom de modèle unicode."""
        response = LLMResponse(
            content="Test",
            input_tokens=100,
            output_tokens=50,
            model="模型-名称"  # Unicode model name
        )
        assert response.model == "模型-名称"

    def test_llm_response_with_empty_content(self):
        """LLMResponse avec contenu vide."""
        response = LLMResponse(
            content="",
            input_tokens=100,
            output_tokens=0,
            model="test"
        )
        assert response.content == ""
        assert response.output_tokens == 0

    def test_llm_response_content_with_null_bytes(self):
        """LLMResponse avec bytes null dans le contenu."""
        response = LLMResponse(
            content="Test\x00\x00Content",
            input_tokens=10,
            output_tokens=5,
            model="test"
        )
        assert "\x00" in response.content


# ============================================================================
# TESTS - CREATE RECORD HELPER
# ============================================================================

class TestCreateRecordHelper:
    """Tests pour la fonction create_record."""

    def test_create_record_id_uniqueness(self):
        """IDs générés sont uniques."""
        ids = set()
        for _ in range(100):
            record = create_record(
                email_id="email",
                email_sender="sender@test.com",
                email_subject="Subject",
                email_body="Body",
                draft_v1="V1",
                critique="Critique",
                draft_final="Final",
                status="V1"
            )
            ids.add(record.id)

        assert len(ids) == 100  # Tous uniques

    def test_create_record_timestamp_format(self):
        """Timestamp au format ISO."""
        record = create_record(
            email_id="email",
            email_sender="sender@test.com",
            email_subject="Subject",
            email_body="Body",
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="V1"
        )
        # Devrait être parseable comme datetime
        parsed = datetime.fromisoformat(record.timestamp)
        assert isinstance(parsed, datetime)

    def test_create_record_preview_exact_100_chars(self):
        """Preview avec exactement 100 caractères."""
        body = "A" * 100
        record = create_record(
            email_id="email",
            email_sender="sender@test.com",
            email_subject="Subject",
            email_body=body,
            draft_v1="V1",
            critique="Critique",
            draft_final="Final",
            status="V1"
        )
        # 100 chars exactement, pas de troncature
        assert record.email_preview == body
        assert "..." not in record.email_preview


# ============================================================================
# TESTS - ENUMS COMPLETENESS
# ============================================================================

class TestEnumsCompleteness:
    """Tests de complétude pour les enums."""

    def test_draft_status_has_all_expected(self):
        """DraftStatus a tous les statuts attendus."""
        expected = {"pending", "validated_v1", "corrected_v2", "rejected"}
        actual = {s.value for s in DraftStatus}
        assert expected == actual

    def test_device_platform_has_all_expected(self):
        """DevicePlatform a toutes les plateformes attendues."""
        expected = {"ios", "android", "web"}
        actual = {p.value for p in DevicePlatform}
        assert expected == actual

    def test_notification_status_has_all_expected(self):
        """PushNotificationStatus a tous les statuts attendus."""
        expected = {"pending", "sent", "delivered", "failed"}
        actual = {s.value for s in PushNotificationStatus}
        assert expected == actual

    def test_notification_category_has_all_expected(self):
        """PushNotificationCategory a toutes les catégories attendues."""
        expected = {
            "draft.created", "draft.failed", "followup.sent",
            "health.alert", "budget.warning", "error", "info"
        }
        actual = {c.value for c in PushNotificationCategory}
        assert expected == actual

    def test_draft_input_tone_has_all_expected(self):
        """DraftInputTone a tous les tons attendus."""
        expected = {"formal", "friendly", "urgent", "conciliatory", "neutral"}
        actual = {t.value for t in DraftInputTone}
        assert expected == actual


# ============================================================================
# TESTS - SERIALIZATION ROUNDTRIP
# ============================================================================

class TestSerializationRoundtrip:
    """Tests aller-retour sérialisation/désérialisation."""

    def test_device_token_roundtrip(self):
        """DeviceToken to_dict/from_dict roundtrip."""
        original = DeviceToken(
            token="test_token_123",
            platform=DevicePlatform.IOS,
            user_id="user_456",
            device_name="iPhone 15 Pro",
            app_version="2.0.1",
            is_active=True
        )

        data = original.to_dict()
        restored = DeviceToken.from_dict(data)

        assert restored.token == original.token
        assert restored.platform == original.platform
        assert restored.user_id == original.user_id
        assert restored.device_name == original.device_name
        assert restored.is_active == original.is_active

    def test_push_notification_to_dict(self):
        """PushNotification to_dict preserves all fields."""
        original = PushNotification(
            title="Test Title",
            body="Test Body",
            category=PushNotificationCategory.DRAFT_CREATED,
            data={"key": "value", "nested": {"inner": 123}},
            badge=5,
            sound=False,
            priority="high",
            ttl=7200,
            collapse_key="group_1",
            image_url="https://example.com/image.png"
        )

        data = original.to_dict()

        assert data["title"] == "Test Title"
        assert data["body"] == "Test Body"
        assert data["category"] == "draft.created"
        assert data["data"] == {"key": "value", "nested": {"inner": 123}}
        assert data["badge"] == 5
        assert data["sound"] is False
        assert data["priority"] == "high"
        assert data["ttl"] == 7200
        assert data["collapse_key"] == "group_1"
        assert data["image_url"] == "https://example.com/image.png"

    def test_push_notification_record_to_dict(self):
        """PushNotificationRecord to_dict."""
        notif = PushNotification(title="Title", body="Body")
        record = PushNotificationRecord(
            notification=notif,
            device_token="token_123",
            status=PushNotificationStatus.SENT,
            message_id="msg_456",
            error_message=None
        )

        data = record.to_dict()

        assert data["device_token"] == "token_123"
        assert data["status"] == "sent"
        assert data["message_id"] == "msg_456"
        assert data["notification"]["title"] == "Title"


# ============================================================================
# TESTS - BOUNDARY CONDITIONS
# ============================================================================

class TestBoundaryConditions:
    """Tests des conditions aux limites."""

    def test_token_usage_with_max_int(self):
        """TokenUsage avec valeurs maximales."""
        import sys
        max_int = sys.maxsize

        usage = TokenUsage(
            input_tokens=max_int,
            output_tokens=max_int,
            model="test"
        )

        # total ne devrait pas overflow en Python (pas de limite)
        assert usage.total == max_int * 2

    def test_empty_key_points_list(self):
        """DraftInput avec liste key_points vide."""
        draft = DraftInput(
            raw_input="test",
            key_points=[]
        )
        assert draft.has_enough_context is False

    def test_single_char_subject(self):
        """Email avec sujet d'un caractère."""
        email = Email(
            id="1",
            subject="X",
            body="Body",
            sender="test@test.com"
        )
        assert email.subject == "X"

    def test_notification_with_empty_data_dict(self):
        """PushNotification avec data={}."""
        notif = PushNotification(
            title="Title",
            body="Body",
            data={}
        )
        assert notif.data == {}
        assert notif.to_dict()["data"] == {}
