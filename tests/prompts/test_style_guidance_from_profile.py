# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour build_style_guidance_from_profile (issue #187 / S4).

Ce bloc remplace les labels explicites ton=formel / emotion=chaleureux par :
- Un bloc few-shot <STYLE_EXAMPLES> avec les 3 exemples anonymisés du profil
- Un bloc narratif de métriques observées ("Phrases ~15 mots, 0.2 emoji/email")
"""

from datetime import datetime


from app.domain.entities.writing_style import (
    ReferenceExample,
    WritingStyleProfile,
)
from app.prompts.style_guidance import build_style_guidance_from_profile


def _make_profile(**overrides) -> WritingStyleProfile:
    defaults = {
        "account_id": 1,
        "analyzed_at": datetime(2026, 4, 17),
        "email_count": 10,
        "avg_sentence_length": 14.0,
        "formality_score": 0.7,
        "emoji_frequency": 0.1,
        "exclamation_rate": 0.2,
        "vocabulary_density": 0.45,
        "sentence_length_variance": 3.0,
        "reference_examples": [
            ReferenceExample(
                length_bucket="short",
                body_excerpt="Merci, c'est noté.",
                subject="RE: point",
                anonymized=True,
                word_count=4,
            ),
            ReferenceExample(
                length_bucket="medium",
                body_excerpt="Je confirme la réunion demain à 10h.",
                subject="Réunion",
                anonymized=True,
                word_count=8,
            ),
            ReferenceExample(
                length_bucket="long",
                body_excerpt="Paragraphe 1.\n\nParagraphe 2.",
                subject="RE: dossier complet",
                anonymized=True,
                word_count=50,
            ),
        ],
    }
    defaults.update(overrides)
    return WritingStyleProfile(**defaults)


class TestBuildStyleGuidance:
    def test_returns_empty_when_profile_is_none(self):
        assert build_style_guidance_from_profile(None) == ""

    def test_emits_metrics_but_no_fewshot_when_no_reference_examples(self):
        """Fix #4a : les métriques agrégées (formalité, longueur, etc.) sont
        émises même sans exemples anonymisés — un profil peut perdre ses
        exemples après purge de rétention tout en gardant ses statistiques.
        Seul le bloc few-shot reste gated sur les exemples. Avant le fix, tout
        était gated → un profil stats-only n'injectait aucune guidance."""
        profile = _make_profile(reference_examples=[])
        result = build_style_guidance_from_profile(profile)
        assert "<STYLE_EXAMPLES>" not in result  # pas de few-shot sans exemples
        assert "STYLE OBSERVÉ" in result  # mais le bloc métriques est là
        assert "14" in result  # avg_sentence_length émis

    def test_includes_style_examples_block(self):
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile)
        assert "<STYLE_EXAMPLES>" in result
        assert "</STYLE_EXAMPLES>" in result

    def test_includes_all_three_examples(self):
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile)
        assert "Merci, c'est noté." in result
        assert "Je confirme la réunion demain à 10h." in result
        assert "Paragraphe 1." in result

    def test_includes_metrics_narrative(self):
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile)
        # Attendu : mentionne avg_sentence_length, formality_score, emoji_rate
        assert "14" in result  # avg_sentence_length
        assert "0.7" in result or "70" in result  # formality_score
        # emoji_frequency 0.1 → "rare" ou "0.1"
        assert "emoji" in result.lower() or "0.1" in result

    def test_skips_non_anonymized_examples(self):
        """Sécurité: un exemple avec anonymized=False ne doit JAMAIS être injecté."""
        profile = _make_profile(reference_examples=[
            ReferenceExample(
                length_bucket="short",
                body_excerpt="Bonjour Marie, contact alice@test.com",
                subject="Test",
                anonymized=False,  # ← non anonymisé
                word_count=5,
            ),
            ReferenceExample(
                length_bucket="medium",
                body_excerpt="Exemple propre anonymisé.",
                subject="Propre",
                anonymized=True,
                word_count=4,
            ),
        ])
        result = build_style_guidance_from_profile(profile)
        # L'exemple non anonymisé est absent
        assert "Marie" not in result
        assert "alice@test.com" not in result
        # L'exemple propre est présent
        assert "Exemple propre anonymisé." in result

    def test_no_fewshot_leak_when_all_examples_non_anonymized(self):
        """Sécurité : si TOUS les exemples sont non anonymisés, le bloc few-shot
        est vide — AUCUN corps d'email ne fuite. Les métriques agrégées (qui ne
        contiennent aucun corps d'exemple) restent émises depuis le fix #4a."""
        profile = _make_profile(reference_examples=[
            ReferenceExample(
                length_bucket="short",
                body_excerpt="Hi Bob, check bob@test.com",
                subject="fuite",
                anonymized=False,
                word_count=5,
            ),
        ])
        result = build_style_guidance_from_profile(profile)
        # Le corps non anonymisé ne fuite jamais (few-shot toujours gated)
        assert "<STYLE_EXAMPLES>" not in result
        assert "Bob" not in result
        assert "bob@test.com" not in result

    def test_metrics_describe_low_formality(self):
        """formality_score bas → narratif mentionne un style décontracté."""
        profile = _make_profile(formality_score=0.2, emoji_frequency=2.0)
        result = build_style_guidance_from_profile(profile).lower()
        assert "décontract" in result or "casual" in result or "0.2" in result

    def test_metrics_describe_high_formality(self):
        profile = _make_profile(formality_score=0.9, emoji_frequency=0.0)
        result = build_style_guidance_from_profile(profile).lower()
        assert "formel" in result or "formal" in result or "0.9" in result

    def test_english_locale_produces_english_narrative(self):
        """F16 — language='en' produit un bloc entièrement en anglais."""
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile, language="en")
        # Heading en anglais
        assert "OBSERVED FROM OUTBOX" in result
        # Pas de texte français caractéristique
        assert "Voici" not in result
        assert "Phrases de" not in result
        assert "STYLE OBSERVÉ" not in result
        # Quelques marqueurs EN
        assert "Sentences" in result or "words" in result
        assert "anonymized examples" in result or "SAME STYLE" in result

    def test_french_locale_is_default(self):
        """La langue FR est utilisée par défaut (rétrocompat)."""
        profile = _make_profile()
        result_default = build_style_guidance_from_profile(profile)
        result_fr = build_style_guidance_from_profile(profile, language="fr")
        assert result_default == result_fr

    def test_unknown_locale_falls_back_to_french(self):
        """Une langue inconnue retombe sur FR (safe default)."""
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile, language="zz")
        assert "STYLE OBSERVÉ" in result

    def test_no_tone_label_caricature(self):
        """Le bloc ne doit PAS contenir les anciens labels de slider.

        Les sliders étaient le pattern à supprimer (issue #187).
        """
        profile = _make_profile()
        result = build_style_guidance_from_profile(profile).lower()
        # Ne doit pas hardcoder les labels slider legacy
        assert "ton=formel" not in result
        assert "emotion_level" not in result
        assert "chaleureux" not in result  # label slider


class TestSentinelNotMeasured:
    """PR2 (sentinel migration) — Optional[float] = None signifie "jamais mesuré".

    Le consumer doit OMETTRE la ligne correspondante au lieu d'inventer une
    affirmation par défaut. C'est la différence entre "0 emoji observé sur 250
    emails" (mesure réelle, le LLM doit le savoir) et "on ne sait pas" (le LLM
    ne doit PAS recevoir d'info inventée).
    """

    def test_skips_formality_line_when_score_is_none(self):
        profile = _make_profile(formality_score=None)
        result = build_style_guidance_from_profile(profile)
        assert "Formalité" not in result

    def test_emits_formality_line_when_score_is_zero(self):
        """0.0 = mesure réelle (très casual), distincte de None (non mesuré)."""
        profile = _make_profile(formality_score=0.0)
        result = build_style_guidance_from_profile(profile)
        assert "Formalité" in result
        assert "décontract" in result.lower() or "casual" in result.lower()

    def test_skips_vocabulary_line_when_density_is_none(self):
        profile = _make_profile(vocabulary_density=None)
        result = build_style_guidance_from_profile(profile)
        assert "Densité lexicale" not in result

    def test_skips_emoji_line_when_frequency_is_none(self):
        """None = jamais mesuré → ne PAS dire "Aucun emoji" (affirmation indue)."""
        profile = _make_profile(emoji_frequency=None)
        result = build_style_guidance_from_profile(profile)
        # Ni "fréquemment", ni "occasionnels", ni "Aucun"
        assert "Emojis" not in result
        assert "emoji" not in result.lower()

    def test_emits_no_emoji_line_when_frequency_is_zero(self):
        """0.0 = mesure (l'utilisateur n'utilise pas d'emoji) → l'info est utile."""
        profile = _make_profile(emoji_frequency=0.0)
        result = build_style_guidance_from_profile(profile)
        assert "Aucun emoji" in result

    def test_skips_exclamation_line_when_rate_is_none(self):
        profile = _make_profile(exclamation_rate=None)
        result = build_style_guidance_from_profile(profile)
        assert "exclamation" not in result.lower()

    def test_omits_variance_when_none_but_keeps_avg(self):
        """sentence_length_variance None : la note d'écart-type est omise mais
        la moyenne reste émise (avg_sentence_length n'est pas Optional)."""
        profile = _make_profile(sentence_length_variance=None, avg_sentence_length=14.0)
        result = build_style_guidance_from_profile(profile)
        assert "14" in result  # moyenne présente
        assert "écart-type" not in result and "std dev" not in result


class TestRecipientEmailContactHint:
    """PR3 — extension `recipient_email` : émet un bloc per-contact en bout
    de chaîne quand le profile contient un ContactStyleProfile matché."""

    def _make_profile_with_contact(self, contact_email: str, **contact_overrides):
        from app.domain.entities.writing_style import (
            ContactStyleProfile,
            FormalityLevel,
        )
        contact = ContactStyleProfile(
            email=contact_email,
            nickname=contact_overrides.get("nickname", "Nat"),
            formality_override=contact_overrides.get("formality_override", FormalityLevel.CASUAL),
            preferred_greeting=contact_overrides.get("preferred_greeting", "Salut {first_name},"),
            preferred_closing=contact_overrides.get("preferred_closing", "À bientôt,"),
            langue=contact_overrides.get("langue", "français"),
            langue_variante=contact_overrides.get("langue_variante", "fr-CH"),
        )
        profile = _make_profile()
        profile.contact_profiles[contact_email.lower()] = contact.to_dict()
        return profile

    def test_recipient_match_emits_contact_hint(self):
        profile = self._make_profile_with_contact("nat@example.com")
        result = build_style_guidance_from_profile(
            profile, recipient_email="nat@example.com"
        )
        assert "SURNOM" in result
        assert "Nat" in result
        assert "Salut Nat," in result  # template expansion
        assert "À bientôt," in result
        assert "fr-CH" in result

    def test_recipient_match_is_case_insensitive(self):
        profile = self._make_profile_with_contact("nat@example.com")
        result = build_style_guidance_from_profile(
            profile, recipient_email="NAT@EXAMPLE.COM"
        )
        assert "Nat" in result

    def test_no_recipient_emits_no_contact_hint(self):
        profile = self._make_profile_with_contact("nat@example.com")
        result = build_style_guidance_from_profile(profile)
        assert "SURNOM" not in result

    def test_recipient_no_match_emits_no_contact_hint(self):
        profile = self._make_profile_with_contact("nat@example.com")
        result = build_style_guidance_from_profile(
            profile, recipient_email="unknown@example.com"
        )
        assert "SURNOM" not in result
        # Pas de mention parasite du destinataire
        assert "unknown@example.com" not in result

    def test_english_locale_emits_english_contact_hint(self):
        profile = self._make_profile_with_contact(
            "nat@example.com", langue="anglais", preferred_greeting="Hi {first_name},"
        )
        result = build_style_guidance_from_profile(
            profile, recipient_email="nat@example.com", language="en"
        )
        assert "NICKNAME" in result
        assert "Hi Nat," in result
        # No French markers
        assert "SURNOM" not in result
        assert "VARIANTE RÉGIONALE" not in result

    def test_contact_hint_emitted_even_without_examples(self):
        """Un contact match a de la valeur même quand le profile n'a pas
        encore d'examples — la migration PR1 peut prendre un onboarding
        complet, mais l'éditeur per-contact UI peut populer un contact
        avant ça."""
        from app.domain.entities.writing_style import (
            ContactStyleProfile,
            FormalityLevel,
        )
        # Profile vide (no examples) avec un contact populé manuellement.
        profile = _make_profile(reference_examples=[])
        contact = ContactStyleProfile(
            email="alice@example.com",
            nickname="Alice",
            formality_override=FormalityLevel.FORMAL,
        )
        profile.contact_profiles["alice@example.com"] = contact.to_dict()

        result = build_style_guidance_from_profile(
            profile, recipient_email="alice@example.com"
        )
        # Pas de bloc <STYLE_EXAMPLES> mais le hint contact est là.
        assert "<STYLE_EXAMPLES>" not in result
        assert "Alice" in result
        assert "Formalité spécifique: formal" in result

    def test_partial_contact_emits_only_filled_fields(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        contact = ContactStyleProfile(
            email="bob@example.com",
            nickname=None,
            formality_override=None,
            preferred_greeting=None,
            preferred_closing="Cdt,",
            langue=None,
            langue_variante=None,
        )
        profile = _make_profile()
        profile.contact_profiles["bob@example.com"] = contact.to_dict()
        result = build_style_guidance_from_profile(
            profile, recipient_email="bob@example.com"
        )
        # Seul le closing apparaît
        assert "Cdt," in result
        assert "SURNOM" not in result
        assert "Formalité spécifique" not in result


class TestBuildContactHintBlock:
    """PR3 — fonction libre `build_contact_hint_block` (port localisé de
    ContactStyleProfile.to_prompt_hint)."""

    def test_empty_contact_returns_empty_string(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        from app.prompts.style_guidance import build_contact_hint_block
        contact = ContactStyleProfile(email="x@example.com")
        assert build_contact_hint_block(contact, "fr") == ""
        assert build_contact_hint_block(contact, "en") == ""

    def test_template_greeting_expanded_with_nickname(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        from app.prompts.style_guidance import build_contact_hint_block
        contact = ContactStyleProfile(
            email="x@example.com",
            nickname="Alice",
            preferred_greeting="Bonjour {first_name},",
            langue="français",
        )
        out = build_contact_hint_block(contact, "fr")
        assert "Bonjour Alice," in out

    def test_literal_greeting_passes_through(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        from app.prompts.style_guidance import build_contact_hint_block
        contact = ContactStyleProfile(
            email="x@example.com",
            preferred_greeting="Bonjour Maître,",
        )
        out = build_contact_hint_block(contact, "fr")
        assert "Bonjour Maître," in out
