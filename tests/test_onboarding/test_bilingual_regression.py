# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression tests for the bilingual onboarding pipeline.

These tests lock in the behaviour of the FR/EN onboarding split:
- Prompt loader variant resolution (fr/en) with fallback.
- IndexedEmails.primary_language detection on EN vs FR corpora.
- OnboardingProgress carrying i18n keys alongside legacy FR strings.
- _detect_language fallback_language parameter (used downstream by
  smart_routing to bias ambiguous replies toward the user's primary
  language).
- load_primary_language_for_account safe defaults on missing data.
"""

from datetime import datetime

import pytest

from app.onboarding.agents.prompts import load_prompt
from app.onboarding.indexer import EmailIndexer
from app.onboarding.loader import OnboardingEmail
from app.onboarding.orchestrator import (
    OnboardingDiscovery,
    OnboardingProgress,
    OnboardingResult,
    _anon_contact_name,
    _extract_discoveries,
)
from app.onboarding.schemas import EmailDirection, Language
from app.prompts import _detect_language, load_primary_language_for_account


class TestPromptLoaderLanguageAware:
    """load_prompt(name, lang=...) must resolve FR by default, EN variant on demand."""

    def test_default_loads_french_variant(self):
        prompt = load_prompt("profile")
        assert "LANGUE DE SORTIE" in prompt
        assert "Bonjour {first_name}" in prompt

    def test_explicit_fr_same_as_default(self):
        assert load_prompt("profile", lang="fr") == load_prompt("profile")

    def test_en_variant_loaded(self):
        prompt = load_prompt("profile", lang="en")
        assert "OUTPUT LANGUAGE" in prompt
        assert "Hey {first_name}" in prompt

    def test_all_four_agents_have_en_variant(self):
        for name in ("profile", "knowledge", "style", "label"):
            en_prompt = load_prompt(name, lang="en")
            assert len(en_prompt) > 400, f"{name}_en.txt looks truncated"

    def test_unknown_lang_falls_back_to_english(self):
        # OB-03 (audit 2026-04-24): unsupported languages fall back to EN, not
        # FR — feeding a French system prompt to a Spanish/Italian inbox is
        # actively worse than English. ``"mixed"`` is treated the same way at
        # the loader level (the orchestrator separately decides not to flag it
        # as ``unsupported_language``, but the prompt selection is symmetric).
        assert load_prompt("profile", lang="zz") == load_prompt("profile", lang="en")
        assert load_prompt("profile", lang="mixed") == load_prompt("profile", lang="en")


class TestPrimaryLanguageDetection:
    """IndexedEmails.primary_language must aggregate word markers from the sent corpus."""

    @staticmethod
    def _sent(body: str) -> OnboardingEmail:
        return OnboardingEmail(
            id="x", sender_email="u@example.com", sender_name="U",
            recipients=["c@other.com"], cc=[],
            subject="s", body=body, date=datetime(2026, 1, 1),
            direction=EmailDirection.SENT,
        )

    def test_english_corpus_detected_as_en(self):
        body = (
            "Hi Alice, thanks for the quick response on the project plans. "
            "I am sending the next steps for you to review. Please let me know "
            "if you need anything from our team. Best regards."
        ) * 2
        indexer = EmailIndexer("u@example.com")
        indexed = indexer.index([self._sent(body) for _ in range(5)])
        assert indexed.primary_language == Language.EN

    def test_french_corpus_detected_as_fr(self):
        body = (
            "Bonjour Alice, merci pour votre retour rapide sur les plans du "
            "projet. Je vous envoie les prochaines etapes pour que vous les "
            "validiez. N'hesitez pas a nous contacter. Cordialement."
        ) * 2
        indexer = EmailIndexer("u@example.com")
        indexed = indexer.index([self._sent(body) for _ in range(5)])
        assert indexed.primary_language == Language.FR

    def test_empty_corpus_defaults_to_fr(self):
        indexer = EmailIndexer("u@example.com")
        indexed = indexer.index([])
        assert indexed.primary_language == Language.FR


class TestDetectLanguageFallback:
    """_detect_language(text, fallback_language=...) should honour the fallback
    when marker counts tie or the text is empty."""

    def test_empty_text_uses_default_fallback(self):
        assert _detect_language("") == "FRENCH"

    def test_empty_text_honours_english_fallback(self):
        assert _detect_language("", fallback_language="ENGLISH") == "ENGLISH"

    def test_clear_english_beats_fallback(self):
        assert _detect_language(
            "Hi John, thanks for the quick follow-up. Best regards.",
            fallback_language="FRENCH",
        ) == "ENGLISH"

    def test_clear_french_beats_fallback(self):
        assert _detect_language(
            "Bonjour Jean, merci pour votre retour rapide. Cordialement.",
            fallback_language="ENGLISH",
        ) == "FRENCH"

    def test_tie_resolved_by_fallback(self):
        # 'bonjour' (FR marker) + 'hi ' (EN marker) is 1 vs 1.
        assert _detect_language(
            "bonjour hi ", fallback_language="ENGLISH"
        ) == "ENGLISH"
        assert _detect_language(
            "bonjour hi ", fallback_language="FRENCH"
        ) == "FRENCH"


class TestLoadPrimaryLanguageForAccount:
    """load_primary_language_for_account must never raise; returns 'FRENCH'
    as a safe default when the account is missing or the DB can't be read."""

    def test_none_account_returns_french(self):
        assert load_primary_language_for_account(None) == "FRENCH"

    def test_zero_account_returns_french(self):
        assert load_primary_language_for_account(0) == "FRENCH"

    def test_nonexistent_account_returns_french(self):
        # This only hits the DB if the connection is initialised; either way
        # the helper must swallow the exception and return FRENCH.
        assert load_primary_language_for_account(999_999_999) == "FRENCH"


class TestResolveReplyLanguage:
    """Regression coverage for the reply-language resolution in
    ``_resolve_reply_language`` (used by every standard draft prompt).

    Before the fix at builders.py:865, the user's KB preference
    (`**Langue**: Français`) was treated as a hard override — replying in
    French to an English newsletter was the symptom. The contract is now:

      explicit instruction > content detection > user preference (fallback) >
      onboarding primary language > "FRENCH"

    Locking this hierarchy in tests avoids accidental regressions if anyone
    re-introduces the override pattern."""

    def _patch_prefs(self, monkeypatch, kb_pref: str, primary: str):
        """Force both user-preference sources to specific values."""
        from app.prompts import builders as _b
        monkeypatch.setattr(_b, "_extract_preferred_language", lambda _aid=None: kb_pref)
        monkeypatch.setattr(_b, "load_primary_language_for_account", lambda _aid=None: primary)

    def test_english_email_with_french_kb_pref_replies_in_english(self, monkeypatch):
        # The original bug: KB says Langue=Français, but the email is clearly
        # English. We must mirror the sender, not force French.
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="FRENCH", primary="FRENCH")
        result = _resolve_reply_language(
            subject="The Daily Degen - April 23rd, 2026",
            body="Hi readers, today we cover the latest market moves. Click to read more.",
            account_id=42,
        )
        assert result == "ENGLISH"

    def test_french_email_with_french_kb_pref_replies_in_french(self, monkeypatch):
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="FRENCH", primary="FRENCH")
        result = _resolve_reply_language(
            subject="Confirmation de réunion",
            body="Bonjour Jean, merci pour votre retour. À demain. Cordialement.",
            account_id=42,
        )
        assert result == "FRENCH"

    def test_english_email_with_english_kb_pref_replies_in_english(self, monkeypatch):
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="ENGLISH", primary="ENGLISH")
        result = _resolve_reply_language(
            subject="Quick question",
            body="Hi, can you confirm tomorrows meeting? Thanks.",
            account_id=42,
        )
        assert result == "ENGLISH"

    def test_ambiguous_email_falls_back_to_kb_pref(self, monkeypatch):
        # Tied / sparse markers → KB preference is the fallback, not an override.
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="ENGLISH", primary="FRENCH")
        result = _resolve_reply_language(
            subject="OK",
            body="",
            account_id=42,
        )
        assert result == "ENGLISH"

    def test_ambiguous_email_falls_back_to_primary_when_no_kb_pref(self, monkeypatch):
        # No KB preference → next fallback is onboarding primary_language.
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="", primary="ENGLISH")
        result = _resolve_reply_language(
            subject="",
            body="",
            account_id=42,
        )
        assert result == "ENGLISH"

    def test_explicit_instruction_overrides_everything(self, monkeypatch):
        # User typed "translate to English" — this beats both detection and
        # KB preference, because it's a direct, contextual command.
        from app.prompts.builders import _resolve_reply_language
        self._patch_prefs(monkeypatch, kb_pref="FRENCH", primary="FRENCH")
        result = _resolve_reply_language(
            subject="Bonjour Jean",
            body="Bonjour, pouvez-vous confirmer la réunion ? Cordialement.",
            account_id=42,
            instructions="translate the reply to English",
        )
        assert result == "ENGLISH"

    def test_no_account_safe_default(self, monkeypatch):
        # account_id=None is the daemon path before account resolution —
        # must not raise and must still mirror an unambiguous English email.
        from app.prompts.builders import _resolve_reply_language
        result = _resolve_reply_language(
            subject="Quick update",
            body="Hi, just checking in. Talk soon. Best regards.",
            account_id=None,
        )
        assert result == "ENGLISH"


class TestOnboardingProgressI18n:
    """OnboardingProgress must carry i18n keys + params in addition to the
    legacy ``message`` string so the frontend can translate."""

    def test_message_key_defaults_to_empty(self):
        p = OnboardingProgress(step="profile", status="running", progress=10)
        assert p.message_key == ""
        assert p.message_params == {}

    def test_message_key_and_params_roundtrip(self):
        p = OnboardingProgress(
            step="error", status="failed", progress=0,
            message="Analyse partielle : profile en echec.",
            message_key="onboarding.scan_error_partial",
            message_params={"agents": "profile"},
        )
        assert p.message_key == "onboarding.scan_error_partial"
        assert p.message_params == {"agents": "profile"}

    def test_legacy_message_still_populated(self):
        p = OnboardingProgress(
            step="profile", status="completed", progress=25,
            message="Profil terminé.",
            message_key="onboarding.scan_done_profile",
        )
        assert p.message == "Profil terminé."


class TestOnboardingResultPrimaryLanguage:
    """OnboardingResult must expose primary_language and the orchestrator
    must inject it into the profile dict so the drafter can read it."""

    def test_default_primary_language_is_fr(self):
        r = OnboardingResult()
        assert r.primary_language == "fr"

    def test_primary_language_persists_on_construct(self):
        r = OnboardingResult(primary_language="en")
        assert r.primary_language == "en"

    def test_profile_setdefault_pattern(self):
        """Mirrors the orchestrator's final step: surface primary_language
        on profile without clobbering an LLM-supplied value."""
        r = OnboardingResult(primary_language="en")
        r.profile = {}
        r.profile.setdefault("primary_language", r.primary_language)
        assert r.profile["primary_language"] == "en"

        # Already-set value wins
        r2 = OnboardingResult(primary_language="en")
        r2.profile = {"primary_language": "fr"}
        r2.profile.setdefault("primary_language", r2.primary_language)
        assert r2.profile["primary_language"] == "fr"


class TestDiscoveryAnonymization:
    """Privacy-safe helpers — no raw email address or surname should leak
    into the live feed. These are the last line of defense before a
    discovery reaches the WebSocket."""

    def test_full_name_becomes_first_plus_initial(self):
        assert _anon_contact_name("Alice Dupont") == "Alice D."

    def test_single_name_preserved(self):
        assert _anon_contact_name("Alice") == "Alice"

    def test_email_address_becomes_first_name(self):
        # alice.dupont@example.com -> "Alice"
        assert _anon_contact_name("alice.dupont@example.com") == "Alice"
        # no-dots: local-part title-cased
        assert _anon_contact_name("bob@x.com") == "Bob"

    def test_empty_returns_empty(self):
        assert _anon_contact_name("") == ""
        assert _anon_contact_name(None) == ""

    def test_multiword_last_name_uses_last_initial(self):
        # Keep behaviour simple: initial of the final token.
        assert _anon_contact_name("Jean Paul Belmondo") == "Jean B."

class TestDiscoveryExtractionProfile:
    """ProfileAgent result → narrative discoveries."""

    def test_signature_with_name_and_company_emits_finding(self):
        result = {
            "user_name": "Sophie Martin",
            "signature": {
                "name": "Sophie Martin",
                "title": "Product Manager",
                "company": "TechCorp",
            },
            "tone": {"default_tone": "semi-formal"},
            "language_variant": "fr-FR",
            "languages": ["fr", "en"],
        }
        discs = _extract_discoveries("profile", result)
        keys = [d.message_key for d in discs]
        assert "onboarding.discovery_signature_found" in keys
        assert "onboarding.discovery_signature_title" in keys
        assert "onboarding.discovery_tone_semi_formal" in keys
        assert "onboarding.discovery_language_variant" in keys
        assert "onboarding.discovery_languages_multi" in keys

    def test_preferred_name_different_from_full_name_emits_insight(self):
        """Nickname divergent from the legal full name is a useful
        discovery — the ProfileAgent now extracts it and the UI displays
        it alongside user_name."""
        result = {
            "user_name": "Alexandre Dupont",
            "preferred_name": "Alex",
            "tone": {},
        }
        discs = _extract_discoveries("profile", result)
        keys = [d.message_key for d in discs]
        assert "onboarding.discovery_preferred_name" in keys

    def test_preferred_name_equal_to_user_name_does_not_repeat(self):
        """No point emitting a discovery that says the same thing as
        the signature finding. Avoids spam in the feed."""
        result = {
            "user_name": "Alex",
            "preferred_name": "Alex",
            "tone": {},
        }
        discs = _extract_discoveries("profile", result)
        assert not any(
            d.message_key == "onboarding.discovery_preferred_name"
            for d in discs
        )

    def test_addressing_tu_emits_insight(self):
        result = {"tone": {"default_tone": "casual", "addressing": "tu"}}
        discs = _extract_discoveries("profile", result)
        keys = [d.message_key for d in discs]
        assert "onboarding.discovery_addressing_tu" in keys

    def test_addressing_vous_emits_insight(self):
        result = {"tone": {"default_tone": "formal", "addressing": "vous"}}
        discs = _extract_discoveries("profile", result)
        keys = [d.message_key for d in discs]
        assert "onboarding.discovery_addressing_vous" in keys

    def test_addressing_null_skips_emission(self):
        """English-only corpora return addressing=null — we must NOT
        emit a discovery claiming a tu/vous pattern for them."""
        result = {"tone": {"default_tone": "casual", "addressing": None}}
        discs = _extract_discoveries("profile", result)
        assert not any(
            d.message_key.startswith("onboarding.discovery_addressing_")
            for d in discs
        )

    def test_missing_fields_do_not_emit_empty_discoveries(self):
        result = {"tone": {}, "signature": {}}
        discs = _extract_discoveries("profile", result)
        # Nothing to say about this result — no empty "Title: None" leaks.
        assert all(d.message_params for d in discs) or all(
            "title" not in d.message_params for d in discs
        )

    def test_invalid_tone_skipped(self):
        result = {"tone": {"default_tone": "excited"}}
        discs = _extract_discoveries("profile", result)
        assert not any(d.message_key.startswith("onboarding.discovery_tone_") for d in discs)

    def test_single_language_no_multi_emit(self):
        result = {"languages": ["fr"]}
        discs = _extract_discoveries("profile", result)
        assert not any(d.message_key.endswith("languages_multi") for d in discs)


class TestDiscoveryExtractionKnowledge:
    """KnowledgeAgent result → narrative discoveries."""

    def test_top_contact_anonymized(self):
        result = {
            "contacts": [
                {"name": "Alice Dupont", "email": "alice@x.com", "interaction_count": 47},
                {"name": "Pierre Legrand", "email": "pierre@y.com", "interaction_count": 23},
            ]
        }
        discs = _extract_discoveries("knowledge", result)
        top = next(d for d in discs if d.message_key.endswith("top_contact"))
        assert top.message_params["name"] == "Alice D."
        assert top.message_params["count"] == 47

    def test_contacts_by_language_requires_two_langs(self):
        # Only one preferred_language = no multilingual discovery.
        result = {
            "contacts": [
                {"name": f"c{i}", "email": f"c{i}@x.com", "preferred_language": "fr", "interaction_count": 1}
                for i in range(3)
            ]
        }
        discs = _extract_discoveries("knowledge", result)
        assert not any(d.message_key.endswith("contacts_by_language") for d in discs)

    def test_contacts_by_language_emits_on_multilingual(self):
        result = {
            "contacts": [
                {"name": "Alice", "email": "a@x.com", "preferred_language": "fr", "interaction_count": 5},
                {"name": "Bob", "email": "b@x.com", "preferred_language": "en", "interaction_count": 3},
                {"name": "Carla", "email": "c@x.com", "preferred_language": "fr", "interaction_count": 2},
            ]
        }
        discs = _extract_discoveries("knowledge", result)
        multi = next(d for d in discs if d.message_key.endswith("contacts_by_language"))
        # "2 FR · 1 EN" sorted by count desc
        assert "2 FR" in multi.message_params["distribution"]
        assert "1 EN" in multi.message_params["distribution"]

    def test_contacts_count_emitted(self):
        result = {"contacts": [{"name": "A", "interaction_count": 1}]}
        discs = _extract_discoveries("knowledge", result)
        assert any(d.message_key.endswith("contacts_count") for d in discs)

    def test_empty_contacts_emits_nothing(self):
        discs = _extract_discoveries("knowledge", {"contacts": []})
        assert discs == []


class TestDiscoveryExtractionStyle:
    """StyleAgent result → narrative discoveries."""

    def test_rules_count_and_casual_cluster(self):
        result = {
            "contact_rules": [
                {"contact_email": "a@x.com", "tone": "casual"},
                {"contact_email": "b@x.com", "tone": "casual"},
                {"contact_email": "c@x.com", "tone": "formal"},
            ],
            "general_rules": [
                {"name": "tu_equipe", "description": "Tutoiement avec l'équipe"},
            ],
        }
        discs = _extract_discoveries("style", result)
        keys = [d.message_key for d in discs]
        assert "onboarding.discovery_rules_count" in keys
        assert "onboarding.discovery_first_name_cluster" in keys
        assert "onboarding.discovery_rule_described" in keys
        # Casual cluster counts only the casual-tone contacts.
        cluster = next(d for d in discs if d.message_key.endswith("first_name_cluster"))
        assert cluster.message_params["count"] == 2

    def test_single_casual_not_enough_for_cluster(self):
        result = {
            "contact_rules": [{"contact_email": "a@x.com", "tone": "casual"}],
            "general_rules": [],
        }
        discs = _extract_discoveries("style", result)
        assert not any(d.message_key.endswith("first_name_cluster") for d in discs)


class TestDiscoveryExtractionLabel:
    """LabelAgent result → narrative discoveries."""

    def test_stats_distribution_emitted(self):
        result = {"statistics": {"action": 25, "fyi": 28, "noise": 47}}
        discs = _extract_discoveries("label", result)
        dist = next(d for d in discs if d.message_key.endswith("stats_distribution"))
        assert dist.message_params == {"action": 25, "fyi": 28, "noise": 47}

    def test_zero_stats_no_emit(self):
        # All-zero or missing stats = nothing meaningful to say yet.
        assert _extract_discoveries("label", {"statistics": {}}) == []
        assert _extract_discoveries("label", {"statistics": {"action": 0, "fyi": 0, "noise": 0}}) == []


class TestOnboardingDiscoveryDataclass:
    """Schema contract for the event payload."""

    def test_kind_and_defaults(self):
        d = OnboardingDiscovery(kind="finding", message_key="foo.bar")
        assert d.kind == "finding"
        assert d.message_params == {}
        assert d.agent == ""
        assert d.fallback_message == ""

    def test_params_and_agent(self):
        d = OnboardingDiscovery(
            kind="insight",
            message_key="foo.top_contact",
            message_params={"name": "Alice D.", "count": 47},
            agent="knowledge",
            fallback_message="Top contact: Alice D. (47)",
        )
        assert d.agent == "knowledge"
        assert d.message_params["name"] == "Alice D."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
