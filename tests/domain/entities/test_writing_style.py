# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour l'entité WritingStyleProfile."""

from datetime import datetime

import pytest

from app.domain.entities.writing_style import (
    ContactStyleProfile,
    FormalityLevel,
    ReferenceExample,
    WritingStyleProfile,
)


class TestFormalityLevel:
    """Tests pour l'enum FormalityLevel."""

    def test_formal_value(self):
        assert FormalityLevel.FORMAL.value == "formal"

    def test_casual_value(self):
        assert FormalityLevel.CASUAL.value == "casual"

    def test_mixed_value(self):
        assert FormalityLevel.MIXED.value == "mixed"

    def test_from_string(self):
        assert FormalityLevel("formal") == FormalityLevel.FORMAL
        assert FormalityLevel("casual") == FormalityLevel.CASUAL
        assert FormalityLevel("mixed") == FormalityLevel.MIXED


class TestWritingStyleProfile:
    """Tests pour WritingStyleProfile."""

    def test_create_basic_profile(self):
        """Test création d'un profil basique."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime(2024, 1, 1, 12, 0, 0),
            email_count=10,
        )
        assert profile.account_id == 1
        assert profile.email_count == 10
        assert profile.formality_level == FormalityLevel.MIXED
        assert profile.common_words == []
        assert profile.preferred_greetings == []
        assert profile.preferred_closings == []

    def test_create_full_profile(self):
        """Test création d'un profil complet."""
        profile = WritingStyleProfile(
            account_id=2,
            analyzed_at=datetime(2024, 1, 1, 12, 0, 0),
            email_count=15,
            common_words=["bonjour", "merci", "cordialement"],
            avg_sentence_length=12.5,
            formality_level=FormalityLevel.FORMAL,
            preferred_greetings=["Bonjour", "Cher/Chère"],
            preferred_closings=["Cordialement", "Bien à vous"],
            typical_signature="Jean Dupont",
            avg_email_length=500,
            analysis_duration_ms=1500,
        )
        assert profile.account_id == 2
        assert profile.email_count == 15
        assert len(profile.common_words) == 3
        assert profile.avg_sentence_length == 12.5
        assert profile.formality_level == FormalityLevel.FORMAL
        assert profile.typical_signature == "Jean Dupont"

    def test_validation_account_id_positive(self):
        """Test que account_id doit être positif."""
        with pytest.raises(ValueError, match="account_id must be positive"):
            WritingStyleProfile(
                account_id=0,
                analyzed_at=datetime.now(),
                email_count=5,
            )

    def test_validation_email_count_non_negative(self):
        """Test que email_count ne peut pas être négatif."""
        with pytest.raises(ValueError, match="email_count must be non-negative"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=-1,
            )

    def test_validation_avg_sentence_length_non_negative(self):
        """Test que avg_sentence_length ne peut pas être négatif."""
        with pytest.raises(ValueError, match="avg_sentence_length must be non-negative"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=5,
                avg_sentence_length=-1.0,
            )

    def test_validation_avg_email_length_non_negative(self):
        """Test que avg_email_length ne peut pas être négatif."""
        with pytest.raises(ValueError, match="avg_email_length must be non-negative"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=5,
                avg_email_length=-1,
            )

    def test_validation_analysis_duration_non_negative(self):
        """Test que analysis_duration_ms ne peut pas être négatif."""
        with pytest.raises(ValueError, match="analysis_duration_ms must be non-negative"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=5,
                analysis_duration_ms=-1,
            )

    def test_formality_level_string_conversion(self):
        """Test conversion automatique string -> enum pour formality_level."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=5,
            formality_level="formal",
        )
        assert profile.formality_level == FormalityLevel.FORMAL

    def test_create_empty(self):
        """Test création d'un profil vide."""
        profile = WritingStyleProfile.create_empty(account_id=42)
        assert profile.account_id == 42
        assert profile.email_count == 0
        assert profile.common_words == []
        assert profile.formality_level == FormalityLevel.MIXED

    def test_to_dict(self):
        """Test sérialisation en dictionnaire."""
        analyzed_at = datetime(2024, 6, 15, 10, 30, 0)
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=analyzed_at,
            email_count=10,
            common_words=["merci"],
            avg_sentence_length=15.0,
            formality_level=FormalityLevel.CASUAL,
            preferred_greetings=["Salut"],
            preferred_closings=["A+"],
            typical_signature="Bob",
            avg_email_length=300,
            analysis_duration_ms=500,
        )

        data = profile.to_dict()

        assert data["account_id"] == 1
        assert data["analyzed_at"] == "2024-06-15T10:30:00"
        assert data["email_count"] == 10
        assert data["common_words"] == ["merci"]
        assert data["avg_sentence_length"] == 15.0
        assert data["formality_level"] == "casual"
        assert data["preferred_greetings"] == ["Salut"]
        assert data["preferred_closings"] == ["A+"]
        assert data["typical_signature"] == "Bob"
        assert data["avg_email_length"] == 300
        assert data["analysis_duration_ms"] == 500

    def test_from_dict(self):
        """Test désérialisation depuis dictionnaire."""
        data = {
            "account_id": 5,
            "analyzed_at": "2024-03-20T14:00:00",
            "email_count": 8,
            "common_words": ["test"],
            "avg_sentence_length": 10.0,
            "formality_level": "formal",
            "preferred_greetings": ["Bonjour"],
            "preferred_closings": ["Cordialement"],
            "typical_signature": None,
            "avg_email_length": 400,
            "analysis_duration_ms": 750,
        }

        profile = WritingStyleProfile.from_dict(data)

        assert profile.account_id == 5
        assert profile.analyzed_at == datetime(2024, 3, 20, 14, 0, 0)
        assert profile.email_count == 8
        assert profile.common_words == ["test"]
        assert profile.formality_level == FormalityLevel.FORMAL
        assert profile.typical_signature is None

    def test_roundtrip_serialization(self):
        """Test que to_dict -> from_dict préserve les données."""
        original = WritingStyleProfile(
            account_id=99,
            analyzed_at=datetime(2024, 12, 25, 8, 0, 0),
            email_count=20,
            common_words=["word1", "word2"],
            avg_sentence_length=18.5,
            formality_level=FormalityLevel.MIXED,
            preferred_greetings=["Hello"],
            preferred_closings=["Bye"],
            typical_signature="Test",
            avg_email_length=600,
            analysis_duration_ms=1000,
        )

        data = original.to_dict()
        restored = WritingStyleProfile.from_dict(data)

        assert restored.account_id == original.account_id
        assert restored.email_count == original.email_count
        assert restored.common_words == original.common_words
        assert restored.formality_level == original.formality_level

    def test_is_sufficient_default_threshold(self):
        """Test is_sufficient avec seuil par défaut (3)."""
        profile_empty = WritingStyleProfile.create_empty(1)
        assert profile_empty.is_sufficient() is False

        profile_2 = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=2,
        )
        assert profile_2.is_sufficient() is False

        profile_3 = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=3,
        )
        assert profile_3.is_sufficient() is True

    def test_is_sufficient_custom_threshold(self):
        """Test is_sufficient avec seuil personnalisé."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=5,
        )
        assert profile.is_sufficient(min_emails=10) is False
        assert profile.is_sufficient(min_emails=5) is True
        assert profile.is_sufficient(min_emails=3) is True

    # PR3 follow-up — `to_prompt_context()` removed from the entity. The unified
    # renderer is `app.prompts.style_guidance.build_style_guidance_from_profile`
    # which emits continuous-metric narrative (e.g. "Formalité 0.7 — style
    # formel") instead of categorical (e.g. "- Ton formel (vouvoiement)"). The
    # categorical assertions used to live here have been retired ; see
    # `tests/prompts/test_style_guidance_from_profile.py` for equivalent
    # coverage of the new path. The signature-leak regression guard below has
    # been kept and migrated to the new API.

    def test_unified_path_omits_typical_signature(self):
        """Regression guard (2026-04-14, migrated PR3) — signature MUST NOT
        leak into the LLM context. The unified path
        :func:`build_style_guidance_from_profile` deliberately ignores
        ``typical_signature`` because the frontend already appends it as a
        footer (``useAccountSignature``). Leaking it caused Haiku to repeat
        the signature inside the body, producing a visible doublon."""
        from app.prompts.style_guidance import build_style_guidance_from_profile
        from app.domain.entities.writing_style import ReferenceExample

        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=10,
            typical_signature="Jean Dupont\nDirecteur",
            # Unified renderer needs at least one anonymized example to emit
            # the metrics+fewshot block (see `build_style_guidance_from_profile`).
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Merci.",
                    subject="OK",
                    anonymized=True,
                    word_count=1,
                ),
            ],
        )

        context = build_style_guidance_from_profile(profile)

        assert "Jean Dupont" not in context
        assert "Directeur" not in context
        assert "Signature" not in context


class TestMergeWithNewEmail:
    """Tests pour la mise à jour incrémentale du profil."""

    def test_merge_first_email(self):
        """Test merge quand email_count est 0."""
        profile = WritingStyleProfile.create_empty(1)
        profile.merge_with_new_email(
            new_words=["bonjour", "merci"],
            new_greetings=["Bonjour"],
            new_closings=["Cordialement"],
            new_email_length=200,
            new_sentence_length=15.0,
        )

        assert profile.email_count == 1
        assert profile.avg_email_length == 200
        assert profile.avg_sentence_length == 15.0
        assert "bonjour" in profile.common_words
        assert "merci" in profile.common_words
        assert "Bonjour" in profile.preferred_greetings
        assert "Cordialement" in profile.preferred_closings

    def test_merge_updates_averages(self):
        """Test que merge calcule correctement les moyennes."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=4,
            avg_email_length=100,
            avg_sentence_length=10.0,
        )

        profile.merge_with_new_email(
            new_words=[],
            new_greetings=[],
            new_closings=[],
            new_email_length=200,
            new_sentence_length=20.0,
        )

        # (100*4 + 200) / 5 = 600 / 5 = 120
        assert profile.avg_email_length == 120
        # (10*4 + 20) / 5 = 60 / 5 = 12
        assert profile.avg_sentence_length == 12.0
        assert profile.email_count == 5

    def test_merge_adds_unique_greetings(self):
        """Test que merge n'ajoute pas de doublons de salutations."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=1,
            preferred_greetings=["Bonjour"],
        )

        profile.merge_with_new_email(
            new_words=[],
            new_greetings=["Bonjour", "Salut"],  # Bonjour déjà présent
            new_closings=[],
            new_email_length=100,
            new_sentence_length=10.0,
        )

        assert profile.preferred_greetings == ["Bonjour", "Salut"]

    def test_merge_limits_words_to_20(self):
        """Test que merge limite les common_words à 20."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=1,
            common_words=[f"word{i}" for i in range(18)],
        )

        profile.merge_with_new_email(
            new_words=["new1", "new2", "new3", "new4", "new5"],
            new_greetings=[],
            new_closings=[],
            new_email_length=100,
            new_sentence_length=10.0,
        )

        assert len(profile.common_words) <= 20

    def test_merge_limits_greetings_to_5(self):
        """Test que merge limite les salutations à 5."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime.now(),
            email_count=1,
            preferred_greetings=["G1", "G2", "G3", "G4"],
        )

        profile.merge_with_new_email(
            new_words=[],
            new_greetings=["G5", "G6", "G7"],
            new_closings=[],
            new_email_length=100,
            new_sentence_length=10.0,
        )

        assert len(profile.preferred_greetings) <= 5

    def test_merge_updates_analyzed_at(self):
        """Test que merge met à jour analyzed_at."""
        old_time = datetime(2024, 1, 1)
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=old_time,
            email_count=1,
        )

        profile.merge_with_new_email(
            new_words=[],
            new_greetings=[],
            new_closings=[],
            new_email_length=100,
            new_sentence_length=10.0,
        )

        assert profile.analyzed_at > old_time


# ---------------------------------------------------------------------------
# Issue #187 — Extension pour apprentissage implicite depuis l'outbox
# ---------------------------------------------------------------------------


class TestReferenceExample:
    """Tests pour le nouveau dataclass ReferenceExample (issue #187)."""

    def test_create_short_example(self):
        """Un exemple court peut être créé avec les champs requis."""
        example = ReferenceExample(
            length_bucket="short",
            body_excerpt="Merci, c'est parfait.",
            subject="RE: point budget",
            word_count=4,
        )
        assert example.length_bucket == "short"
        assert example.body_excerpt == "Merci, c'est parfait."
        assert example.subject == "RE: point budget"
        assert example.word_count == 4

    def test_anonymized_defaults_to_false(self):
        """anonymized DOIT défaut à False — flag de sécurité opt-in.

        Un appelant qui oublie de poser le flag après anonymisation NE FUITE PAS :
        `_filter_anonymized_examples` rejette silencieusement l'exemple. C'est le
        contraire d'avant : avant le flip, un default True laissait passer un
        exemple non-traité si l'inférence oubliait de poser False.
        """
        example = ReferenceExample(
            length_bucket="medium",
            body_excerpt="Je reviens vers vous demain avec les chiffres.",
            subject="Budget Q3",
            word_count=9,
        )
        assert example.anonymized is False

    def test_accepts_all_length_buckets(self):
        """Les 3 buckets short/medium/long sont valides."""
        for bucket in ("short", "medium", "long"):
            example = ReferenceExample(
                length_bucket=bucket,
                body_excerpt="text",
                subject="subject",
                word_count=1,
            )
            assert example.length_bucket == bucket

    def test_to_dict_roundtrip(self):
        """Sérialisation/désérialisation préserve les données."""
        original = ReferenceExample(
            length_bucket="long",
            body_excerpt="Paragraphe 1.\n\nParagraphe 2.",
            subject="RE: dossier",
            anonymized=True,
            word_count=42,
            collected_at="2026-05-15T12:00:00",
            source_email_id="msg-123",
        )
        data = original.to_dict()
        restored = ReferenceExample.from_dict(data)
        assert restored.length_bucket == original.length_bucket
        assert restored.body_excerpt == original.body_excerpt
        assert restored.subject == original.subject
        assert restored.anonymized == original.anonymized
        assert restored.word_count == original.word_count
        assert restored.collected_at == "2026-05-15T12:00:00"
        assert restored.source_email_id == "msg-123"

    def test_from_dict_missing_collection_metadata_stays_undated(self):
        """Les anciens exemples JSON restent explicitement sans timestamp."""
        restored = ReferenceExample.from_dict({
            "length_bucket": "short",
            "body_excerpt": "OK.",
            "subject": "RE:",
            "anonymized": True,
            "word_count": 1,
        })

        assert restored.collected_at is None
        assert restored.source_email_id is None


class TestWritingStyleProfileIssue187Extension:
    """Nouvelles dimensions enrichies (issue #187)."""

    def test_new_fields_have_safe_defaults(self):
        """Un profil fraîchement créé expose les nouveaux champs avec sentinel None.

        PR2 (sentinel migration) : default = None signifie "jamais mesuré". Les
        consumers (`style_guidance.py:_build_metrics_narrative`) skip la ligne
        correspondante au lieu d'inventer une affirmation par défaut.
        """
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime(2026, 4, 17, 12, 0, 0),
            email_count=0,
        )
        assert profile.sentence_length_variance is None
        assert profile.vocabulary_density is None
        assert profile.formality_score is None  # "Jamais mesuré", pas 0.5
        assert profile.exclamation_rate is None
        assert profile.reference_examples == []

    def test_formality_score_range_validation(self):
        """formality_score doit être entre 0.0 et 1.0."""
        with pytest.raises(ValueError, match="formality_score"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=0,
                formality_score=1.5,
            )
        with pytest.raises(ValueError, match="formality_score"):
            WritingStyleProfile(
                account_id=1,
                analyzed_at=datetime.now(),
                email_count=0,
                formality_score=-0.1,
            )

    def test_to_dict_includes_new_fields(self):
        """La sérialisation expose les nouveaux champs."""
        profile = WritingStyleProfile(
            account_id=1,
            analyzed_at=datetime(2026, 4, 17, 12, 0, 0),
            email_count=5,
            sentence_length_variance=3.2,
            vocabulary_density=0.42,
            formality_score=0.75,
            exclamation_rate=0.1,
            reference_examples=[
                ReferenceExample(
                    length_bucket="short",
                    body_excerpt="Merci.",
                    subject="OK",
                    word_count=1,
                ),
            ],
        )
        data = profile.to_dict()
        assert data["sentence_length_variance"] == 3.2
        assert data["vocabulary_density"] == 0.42
        assert data["formality_score"] == 0.75
        assert data["exclamation_rate"] == 0.1
        assert len(data["reference_examples"]) == 1
        assert data["reference_examples"][0]["length_bucket"] == "short"

    def test_from_dict_handles_legacy_profile_without_new_fields(self):
        """Rétrocompat: un ancien profil sérialisé sans les nouveaux champs charge avec défauts."""
        legacy_data = {
            "account_id": 1,
            "analyzed_at": "2024-01-01T12:00:00",
            "email_count": 10,
            "common_words": [],
            "avg_sentence_length": 15.0,
            "formality_level": "mixed",
            "preferred_greetings": [],
            "preferred_closings": [],
            "typical_signature": None,
            "avg_email_length": 400,
            "analysis_duration_ms": 0,
            # Pas de: sentence_length_variance, vocabulary_density, formality_score,
            #        exclamation_rate, reference_examples
        }
        profile = WritingStyleProfile.from_dict(legacy_data)
        # PR2 (sentinel migration): keys absent from a legacy JSON now load as
        # None — the consumer skips emitting a line for "never measured", which
        # is the correct semantics for an account whose outbox was never run
        # through StyleInferenceService. (See `style_guidance.py`.)
        assert profile.sentence_length_variance is None
        assert profile.vocabulary_density is None
        assert profile.formality_score is None
        assert profile.exclamation_rate is None
        assert profile.reference_examples == []

    def test_from_dict_rehydrates_reference_examples(self):
        """from_dict reconstruit les ReferenceExample depuis leur dict."""
        data = {
            "account_id": 1,
            "analyzed_at": "2026-04-17T12:00:00",
            "email_count": 5,
            "reference_examples": [
                {
                    "length_bucket": "short",
                    "body_excerpt": "OK.",
                    "subject": "RE: tout",
                    "anonymized": True,
                    "word_count": 1,
                },
                {
                    "length_bucket": "medium",
                    "body_excerpt": "Je confirme pour demain.",
                    "subject": "Point hebdo",
                    "anonymized": True,
                    "word_count": 5,
                },
            ],
        }
        profile = WritingStyleProfile.from_dict(data)
        assert len(profile.reference_examples) == 2
        assert isinstance(profile.reference_examples[0], ReferenceExample)
        assert profile.reference_examples[0].length_bucket == "short"
        assert profile.reference_examples[1].length_bucket == "medium"

    def test_roundtrip_with_new_fields(self):
        """to_dict → from_dict préserve les nouveaux champs et exemples."""
        original = WritingStyleProfile(
            account_id=42,
            analyzed_at=datetime(2026, 4, 17, 12, 0, 0),
            email_count=100,
            sentence_length_variance=5.4,
            vocabulary_density=0.38,
            formality_score=0.62,
            exclamation_rate=0.25,
            reference_examples=[
                ReferenceExample(
                    length_bucket="long",
                    body_excerpt="Paragraphe détaillé de réponse.",
                    subject="RE: proposition complète",
                    word_count=150,
                ),
            ],
        )
        restored = WritingStyleProfile.from_dict(original.to_dict())
        assert restored.sentence_length_variance == original.sentence_length_variance
        assert restored.vocabulary_density == original.vocabulary_density
        assert restored.formality_score == original.formality_score
        assert restored.exclamation_rate == original.exclamation_rate
        assert len(restored.reference_examples) == 1
        assert restored.reference_examples[0].length_bucket == "long"
        assert restored.reference_examples[0].word_count == 150


class TestContactStyleProfilePromptHint:
    """PR3 follow-up — these tests target
    :func:`app.prompts.style_guidance.build_contact_hint_block`, the localized
    fr/en port of the (now removed) `ContactStyleProfile.to_prompt_hint()`
    method. The behaviour is identical : `{first_name}` templates are
    expanded with the contact's nickname so Haiku receives the literal
    greeting to reproduce ; literal greetings (legacy data) pass through
    unchanged."""

    def test_literal_greeting_passes_through(self):
        from app.prompts.style_guidance import build_contact_hint_block
        # Legacy data: greeting stored as literal "Bonjour Alexandra,"
        contact = ContactStyleProfile(
            email="alex@example.com",
            preferred_greeting="Bonjour Alexandra,",
            nickname="Alexandra",
        )
        hint = build_contact_hint_block(contact, "fr")
        assert "Salutation habituelle: Bonjour Alexandra," in hint

    def test_template_expanded_with_nickname(self):
        from app.prompts.style_guidance import build_contact_hint_block
        # New data: greeting stored as template "Bonjour {first_name},"
        contact = ContactStyleProfile(
            email="alex@example.com",
            preferred_greeting="Bonjour {first_name},",
            nickname="Alexandra",
        )
        hint = build_contact_hint_block(contact, "fr")
        assert "Salutation habituelle: Bonjour Alexandra," in hint

    def test_template_english_contact(self):
        from app.prompts.style_guidance import build_contact_hint_block
        contact = ContactStyleProfile(
            email="sarah@example.com",
            preferred_greeting="Hi {first_name},",
            nickname="Sarah",
            langue="anglais",
        )
        # FR locale → "Salutation habituelle:" header, but the greeting itself
        # is expanded against the spoken language (`anglais` → ENGLISH template).
        hint = build_contact_hint_block(contact, "fr")
        assert "Salutation habituelle: Hi Sarah," in hint

    def test_template_without_nickname_degrades_gracefully(self):
        from app.prompts.style_guidance import build_contact_hint_block
        # Template but no nickname → expander collapses to stripped form
        contact = ContactStyleProfile(
            email="x@example.com",
            preferred_greeting="Bonjour {first_name},",
            nickname=None,
        )
        hint = build_contact_hint_block(contact, "fr")
        # Empty first_name leaves "Bonjour ," which the expander normalizes
        assert "Salutation habituelle: Bonjour," in hint

    def test_no_greeting_no_hint_line(self):
        from app.prompts.style_guidance import build_contact_hint_block
        contact = ContactStyleProfile(
            email="x@example.com",
            nickname="Alice",
        )
        hint = build_contact_hint_block(contact, "fr")
        assert "Salutation habituelle" not in hint

    def test_closing_unchanged_no_tokenization(self):
        from app.prompts.style_guidance import build_contact_hint_block
        # Closings contain the user's name, not the recipient's — don't touch
        contact = ContactStyleProfile(
            email="x@example.com",
            preferred_closing="Sincèrement,",
            nickname="Alexandra",
        )
        hint = build_contact_hint_block(contact, "fr")
        assert "Clôture habituelle: Sincèrement," in hint
