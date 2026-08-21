# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests for OnboardingManager._persist_contact_profiles.

After the onboarding scan, all 6 per-contact style fields must be persisted
into WritingStyleProfile.contact_profiles so the DrafterAgent can call
to_prompt_hint() and produce the right tone for each contact.

Fields under test:
  formality_override  — FormalityLevel: FORMAL / MIXED / CASUAL
  preferred_greeting  — primary greeting (before " / " separator)
  preferred_closing   — primary closing   (before " / " separator)
  langue              — "français" | "anglais"   (None = auto)
  langue_variante     — ISO code: "fr-CA", "fr-CH", "en-US", …
  nickname            — first name extracted from full name (capitalized)

The agent outputs used here are synthetic but follow the exact schemas
produced by KnowledgeAgent (contacts[]) and StyleAgent (contact_rules[]).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.prompts.style_guidance import (
    build_contact_hint_block,
    build_style_guidance_from_profile,
)
from app.domain.entities.writing_style import (
    ContactStyleProfile,
    WritingStyleProfile,
)
from app.infrastructure.writing_style_store import FileWritingStyleStore
from app.onboarding.manager import OnboardingManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 99001  # isolated fake account — won't collide with real data


# ---------------------------------------------------------------------------
# Shared agent-output fixtures
# (mirrors what KnowledgeAgent + StyleAgent return in production)
# ---------------------------------------------------------------------------

#: Five contacts covering every field combination we care about.
KNOWLEDGE: dict = {
    "contacts": [
        # 1. Swiss francophone colleague — casual, fr-CH variant, first name extractable
        {
            "email": "alice.tremblay@corp.example",
            "name": "Alice Tremblay",
            "type": "colleague",
            "company": "Avasad SA",
            "title": "Chef de projet",
            "preferred_language": "fr",
            "preferred_tone": "casual",
            "interaction_count": 34,
            "topics": ["design", "planning"],
            "language_variant": "fr-CH",
        },
        # 2. French lawyer — formal, fr-FR, first name extractable
        {
            "email": "r.dupont@cabinet-legal.fr",
            "name": "Robert Dupont",
            "type": "client",
            "company": "Cabinet Dupont & Associés",
            "title": "Avocat associé",
            "preferred_language": "fr",
            "preferred_tone": "formal",
            "interaction_count": 8,
            "topics": ["contrats"],
            "language_variant": "fr-FR",
        },
        # 3. US anglophone partner — casual, en-US, multiple greeting/closing variants
        {
            "email": "sarah.johnson@techstartup.io",
            "name": "Sarah Johnson",
            "type": "partner",
            "company": "TechStartup Inc",
            "title": "CTO",
            "preferred_language": "en",
            "preferred_tone": "casual",
            "interaction_count": 19,
            "topics": ["API", "roadmap"],
            "language_variant": "en-US",
        },
        # 4. Québécoise personal contact — casual, fr-CA, placeholder closing
        {
            "email": "karine.morel@gmail.com",
            "name": "Karine Morel",
            "type": "personal",
            "company": None,
            "title": None,
            "preferred_language": "fr",
            "preferred_tone": "casual",
            "interaction_count": 22,
            "topics": ["personnel"],
            "language_variant": "fr-CA",
        },
        # 5. AI contact — name equals email prefix → nickname must NOT be set
        {
            "email": "fatima@okara.ai",
            "name": "fatima",           # lowercase, same as prefix
            "type": "client",
            "company": "Okara.ai",
            "title": "Head of AI",
            "preferred_language": "en",
            "preferred_tone": "semi-formal",
            "interaction_count": 11,
            "topics": ["IA"],
            "language_variant": "en-US",
        },
    ],
    "faq": [],
}

RULES: dict = {
    "contact_rules": [
        {
            "contact_email": "alice.tremblay@corp.example",
            "tone": "casual",
            "greeting": "Salut Alice, / Alice,",    # two variants → take first
            "closing": "Alex",
            "language": "fr",
        },
        {
            "contact_email": "r.dupont@cabinet-legal.fr",
            "tone": "formal",
            "greeting": "Bonjour Maître Dupont,",
            "closing": "Cordialement, / Bien cordialement,",  # two variants → take first
            "language": "fr",
        },
        {
            "contact_email": "sarah.johnson@techstartup.io",
            "tone": "casual",
            "greeting": "Hey Sarah / Hi Sarah,",    # two variants → take first
            "closing": "Cheers",
            "language": "en",
        },
        {
            "contact_email": "karine.morel@gmail.com",
            "tone": "casual",
            "greeting": "Salut Karine,",
            "closing": "(none)",                    # LLM placeholder → must NOT be stored
            "language": "fr",
        },
        {
            "contact_email": "fatima@okara.ai",
            "tone": "semi-formal",
            "greeting": "Hi Fatima,",
            "closing": "Best,",
            "language": "en",
        },
    ],
    "general_rules": [],
    "forbidden_phrases": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path, contact_profiles: dict | None = None) -> FileWritingStyleStore:
    """Return an isolated FileWritingStyleStore pre-seeded with ACCOUNT_ID profile."""
    data_dir = tmp_path / "learning"
    data_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "account_id": ACCOUNT_ID,
        "analyzed_at": "2026-04-16T00:00:00",
        "email_count": 25,
        "common_words": [],
        "avg_sentence_length": 12.5,
        "formality_level": "mixed",
        "preferred_greetings": ["Bonjour"],
        "preferred_closings": ["Cordialement"],
        "typical_signature": None,
        "avg_email_length": 120,
        "analysis_duration_ms": 0,
        "emoji_frequency": 0.0,
        "contact_profiles": contact_profiles or {},
    }
    (data_dir / f"style_profile_{ACCOUNT_ID}.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return FileWritingStyleStore(data_dir=data_dir)


def _run(
    store: FileWritingStyleStore,
    knowledge: dict,
    rules: dict,
) -> WritingStyleProfile:
    """Inject store, call _persist_contact_profiles, return reloaded profile."""
    from app.infrastructure.container import get_container

    manager = OnboardingManager(session_factory=lambda: None)
    container = get_container()
    with patch.object(container, "get_writing_style_store", return_value=store):
        manager._persist_contact_profiles(knowledge, rules, ACCOUNT_ID)

    profile = store.load(ACCOUNT_ID)
    assert profile is not None, "Profile vanished after persist"
    return profile


def _c(profile: WritingStyleProfile, email: str) -> Dict[str, Any]:
    """Return raw contact_profiles dict for email (asserts presence)."""
    key = email.lower()
    assert key in profile.contact_profiles, (
        f"Contact {email!r} missing from contact_profiles.\n"
        f"Present keys: {sorted(profile.contact_profiles)}"
    )
    return profile.contact_profiles[key]


# ---------------------------------------------------------------------------
# Core field tests — 5 contacts × 6 fields
# ---------------------------------------------------------------------------

class TestAllFieldsExtracted:
    """Each contact gets all 6 fields populated from agent outputs."""

    @pytest.fixture(autouse=True)
    def _profile(self, tmp_path):
        store = _make_store(tmp_path)
        self.profile = _run(store, KNOWLEDGE, RULES)

    # ── Contact 1: Alice (Swiss, casual, fr) ────────────────────────────────

    def test_alice_formality_casual(self):
        assert _c(self.profile, "alice.tremblay@corp.example")["formality_override"] == "casual"

    def test_alice_greeting_primary_variant(self):
        # "Salut Alice, / Alice," → takes part before " / ", then tokenizes the
        # recipient's first name → template form. Expansion happens at prompt time.
        assert _c(self.profile, "alice.tremblay@corp.example")["preferred_greeting"] == "Salut {first_name},"

    def test_alice_closing(self):
        assert _c(self.profile, "alice.tremblay@corp.example")["preferred_closing"] == "Alex"

    def test_alice_langue_francais(self):
        assert _c(self.profile, "alice.tremblay@corp.example")["langue"] == "français"

    def test_alice_variante_fr_ch(self):
        assert _c(self.profile, "alice.tremblay@corp.example")["langue_variante"] == "fr-CH"

    def test_alice_nickname_first_name(self):
        # "Alice Tremblay" → first capitalized word
        assert _c(self.profile, "alice.tremblay@corp.example")["nickname"] == "Alice"

    # ── Contact 2: Robert (French lawyer, formal) ────────────────────────────

    def test_robert_formality_formal(self):
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["formality_override"] == "formal"

    def test_robert_greeting(self):
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["preferred_greeting"] == "Bonjour Maître Dupont,"

    def test_robert_closing_primary_variant(self):
        # "Cordialement, / Bien cordialement," → takes part before " / "
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["preferred_closing"] == "Cordialement,"

    def test_robert_langue_francais(self):
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["langue"] == "français"

    def test_robert_variante_fr_fr(self):
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["langue_variante"] == "fr-FR"

    def test_robert_nickname(self):
        assert _c(self.profile, "r.dupont@cabinet-legal.fr")["nickname"] == "Robert"

    # ── Contact 3: Sarah (US, casual, en) ────────────────────────────────────

    def test_sarah_formality_casual(self):
        assert _c(self.profile, "sarah.johnson@techstartup.io")["formality_override"] == "casual"

    def test_sarah_greeting_primary_variant(self):
        # "Hey Sarah / Hi Sarah," → takes part before " / ", then tokenized.
        assert _c(self.profile, "sarah.johnson@techstartup.io")["preferred_greeting"] == "Hey {first_name}"

    def test_sarah_closing(self):
        assert _c(self.profile, "sarah.johnson@techstartup.io")["preferred_closing"] == "Cheers"

    def test_sarah_langue_anglais(self):
        assert _c(self.profile, "sarah.johnson@techstartup.io")["langue"] == "anglais"

    def test_sarah_variante_en_us(self):
        assert _c(self.profile, "sarah.johnson@techstartup.io")["langue_variante"] == "en-US"

    def test_sarah_nickname(self):
        assert _c(self.profile, "sarah.johnson@techstartup.io")["nickname"] == "Sarah"

    # ── Contact 4: Karine (Québec, closing is placeholder) ───────────────────

    def test_karine_formality_casual(self):
        assert _c(self.profile, "karine.morel@gmail.com")["formality_override"] == "casual"

    def test_karine_greeting(self):
        assert _c(self.profile, "karine.morel@gmail.com")["preferred_greeting"] == "Salut {first_name},"

    def test_karine_closing_placeholder_not_stored(self):
        # "(none)" must be silently dropped — the DrafterAgent must not see it
        assert _c(self.profile, "karine.morel@gmail.com")["preferred_closing"] is None

    def test_karine_langue_francais(self):
        assert _c(self.profile, "karine.morel@gmail.com")["langue"] == "français"

    def test_karine_variante_fr_ca(self):
        assert _c(self.profile, "karine.morel@gmail.com")["langue_variante"] == "fr-CA"

    def test_karine_nickname(self):
        assert _c(self.profile, "karine.morel@gmail.com")["nickname"] == "Karine"

    # ── Contact 5: Fatima (name == email prefix → no nickname) ───────────────

    def test_fatima_formality_semi_formal(self):
        # "semi-formal" → FormalityLevel.MIXED.value
        assert _c(self.profile, "fatima@okara.ai")["formality_override"] == "mixed"

    def test_fatima_greeting(self):
        assert _c(self.profile, "fatima@okara.ai")["preferred_greeting"] == "Hi {first_name},"

    def test_fatima_closing(self):
        assert _c(self.profile, "fatima@okara.ai")["preferred_closing"] == "Best,"

    def test_fatima_langue_anglais(self):
        assert _c(self.profile, "fatima@okara.ai")["langue"] == "anglais"

    def test_fatima_variante_en_us(self):
        assert _c(self.profile, "fatima@okara.ai")["langue_variante"] == "en-US"

    def test_fatima_nickname_from_greeting_overrides_email_prefix_suppression(self):
        # KnowledgeAgent name "fatima" == email prefix → would be suppressed.
        # BUT StyleAgent greeting "Hi Fatima," contains a capitalized first name →
        # greeting-extraction wins and produces a proper nickname.
        assert _c(self.profile, "fatima@okara.ai")["nickname"] == "Fatima"


# ---------------------------------------------------------------------------
# Precision / edge-case tests
# ---------------------------------------------------------------------------

class TestPrecisionEdgeCases:

    def test_language_mixed_maps_to_none(self, tmp_path):
        """'mixed' language in StyleAgent → langue should be None (auto-detect)."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "mixed@example.com", "name": "Mixed User", "type": "colleague",
             "preferred_language": "mixed", "preferred_tone": "semi-formal",
             "interaction_count": 5, "topics": [], "language_variant": None},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": "mixed@example.com", "tone": "semi-formal",
             "greeting": "Hello Mixed,", "closing": "Thanks,", "language": "mixed"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, knowledge, rules)
        assert _c(profile, "mixed@example.com")["langue"] is None

    def test_no_language_variant_in_knowledge(self, tmp_path):
        """language_variant: null in knowledge on a neutral TLD (.com) stays None."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "novariant@example.com", "name": "No Variant", "type": "colleague",
             "preferred_language": "fr", "preferred_tone": "casual",
             "interaction_count": 3, "topics": [], "language_variant": None},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": "novariant@example.com", "tone": "casual",
             "greeting": "Salut,", "closing": "À bientôt,", "language": "fr"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, knowledge, rules)
        assert _c(profile, "novariant@example.com")["langue_variante"] is None

    def test_tld_fallback_fills_variant_when_llm_returns_none(self, tmp_path):
        """RECV-only contact on a .ch TLD: LLM couldn't infer variant, TLD fallback does."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "contact@naef.ch", "name": None, "type": "partner",
             "preferred_language": None, "preferred_tone": None,
             "interaction_count": 1, "topics": [], "language_variant": None},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        contact = _c(profile, "contact@naef.ch")
        assert contact["langue_variante"] == "fr-CH"
        # Spoken language is inferred from the fr-* variant prefix.
        assert contact["langue"] == "français"

    def test_tld_fallback_does_not_override_llm_variant(self, tmp_path):
        """If KnowledgeAgent already produced a variant, TLD heuristic stays silent."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "contact@naef.ch", "name": "Some One", "type": "colleague",
             "preferred_language": "en", "preferred_tone": "casual",
             "interaction_count": 2, "topics": [], "language_variant": "en-US"},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        contact = _c(profile, "contact@naef.ch")
        assert contact["langue_variante"] == "en-US"
        assert contact["langue"] == "anglais"

    def test_placeholder_greeting_not_stored(self, tmp_path):
        """'(name only or none)' greeting from style.txt — must be dropped."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "ph@example.com", "name": "Placeholder User", "type": "colleague",
             "preferred_language": "fr", "preferred_tone": "casual",
             "interaction_count": 2, "topics": [], "language_variant": "fr-FR"},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": "ph@example.com", "tone": "casual",
             "greeting": "(name only or none)", "closing": "(none)", "language": "fr"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, knowledge, rules)
        contact = _c(profile, "ph@example.com")
        assert contact["preferred_greeting"] is None
        assert contact["preferred_closing"] is None

    def test_nickname_lowercase_first_word_suppressed(self, tmp_path):
        """First word of name that starts lowercase must NOT become a nickname."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "user@corp.com", "name": "john doe", "type": "colleague",
             "preferred_language": "en", "preferred_tone": "casual",
             "interaction_count": 5, "topics": [], "language_variant": "en-US"},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        assert _c(profile, "user@corp.com")["nickname"] is None

    def test_knowledge_only_contact_gets_partial_fields(self, tmp_path):
        """Contact in knowledge but absent from contact_rules still gets variant + nickname."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "only_knowledge@swiss.ch", "name": "Jean-Pierre Mueller",
             "type": "colleague", "preferred_language": "fr", "preferred_tone": "semi-formal",
             "interaction_count": 7, "topics": [], "language_variant": "fr-CH"},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        contact = _c(profile, "only_knowledge@swiss.ch")
        assert contact["langue_variante"] == "fr-CH"
        assert contact["nickname"] == "Jean-Pierre"         # hyphenated first name
        assert contact["formality_override"] == "mixed"     # semi-formal fallback
        assert contact["preferred_greeting"] is None        # no style data
        assert contact["preferred_closing"] is None

    def test_rules_only_contact_gets_style_fields(self, tmp_path):
        """Contact in contact_rules but absent from knowledge still gets greeting/closing/formality."""
        store = _make_store(tmp_path)
        rules = {"contact_rules": [
            {"contact_email": "only_rules@example.com", "tone": "formal",
             "greeting": "Cher Monsieur,", "closing": "Veuillez agréer,", "language": "fr"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, {}, rules)
        contact = _c(profile, "only_rules@example.com")
        assert contact["formality_override"] == "formal"
        assert contact["preferred_greeting"] == "Cher Monsieur,"
        assert contact["preferred_closing"] == "Veuillez agréer,"
        assert contact["langue"] == "français"
        assert contact["langue_variante"] is None   # no knowledge → no variant
        assert contact["nickname"] is None

    def test_style_tone_takes_precedence_over_knowledge_tone(self, tmp_path):
        """When StyleAgent says formal but KnowledgeAgent says casual → formal wins."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "conflict@example.com", "name": "Conflicting User", "type": "client",
             "preferred_language": "fr", "preferred_tone": "casual",   # ← knowledge says casual
             "interaction_count": 4, "topics": [], "language_variant": "fr-FR"},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": "conflict@example.com", "tone": "formal",  # ← style says formal
             "greeting": "Bonjour Monsieur,", "closing": "Cordialement,", "language": "fr"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, knowledge, rules)
        # StyleAgent is based on actual sent emails → higher fidelity → wins
        assert _c(profile, "conflict@example.com")["formality_override"] == "formal"

    def test_case_insensitive_email_matching(self, tmp_path):
        """Contact emails are case-insensitive throughout the pipeline."""
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": "Alice@COMPANY.COM", "name": "Alice Smith", "type": "colleague",
             "preferred_language": "en", "preferred_tone": "casual",
             "interaction_count": 10, "topics": [], "language_variant": "en-GB"},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": "alice@company.com",  # different casing
             "tone": "casual", "greeting": "Hey Alice,", "closing": "Cheers",
             "language": "en"},
        ], "general_rules": [], "forbidden_phrases": []}

        profile = _run(store, knowledge, rules)
        contact = _c(profile, "alice@company.com")
        # Both knowledge and rules should have merged into one entry
        assert contact["nickname"] == "Alice"
        assert contact["preferred_greeting"] == "Hey {first_name},"
        assert contact["langue_variante"] == "en-GB"


# ---------------------------------------------------------------------------
# Manual-settings preservation
# ---------------------------------------------------------------------------

class TestManualSettingsPreserved:
    """
    When a user has manually set a field and the scan has no data for it,
    the manual value must not be overwritten.
    """

    def test_manual_nickname_preserved_when_scan_has_no_name(self, tmp_path):
        """User set nickname="Kiki". Scan sees name=email prefix → should not clobber."""
        pre_existing = {
            "kiki@example.com": {
                "email": "kiki@example.com",
                "formality_override": None,
                "preferred_greeting": None,
                "preferred_closing": None,
                "langue_variante": None,
                "langue": None,
                "nickname": "Kiki",     # ← manually set by user
            }
        }
        store = _make_store(tmp_path, contact_profiles=pre_existing)
        # Scan: name = "kiki" (same as email prefix) → scan produces no nickname
        knowledge = {"contacts": [
            {"email": "kiki@example.com", "name": "kiki", "type": "colleague",
             "preferred_language": "fr", "preferred_tone": "casual",
             "interaction_count": 5, "topics": [], "language_variant": "fr-CA"},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        # Scan cannot determine a proper nickname from "kiki", manual "Kiki" must survive
        assert _c(profile, "kiki@example.com")["nickname"] == "Kiki"

    def test_manual_closing_preserved_when_scan_has_none(self, tmp_path):
        """User customised closing. Scan finds no closing for this contact → keep user's."""
        pre_existing = {
            "colleague@corp.com": {
                "email": "colleague@corp.com",
                "formality_override": None,
                "preferred_greeting": None,
                "preferred_closing": "Bonne semaine !",   # ← manually set
                "langue_variante": None,
                "langue": None,
                "nickname": None,
            }
        }
        store = _make_store(tmp_path, contact_profiles=pre_existing)
        # Scan has this contact in knowledge but no contact_rules entry → closing stays
        knowledge = {"contacts": [
            {"email": "colleague@corp.com", "name": "Colleague Name", "type": "colleague",
             "preferred_language": "fr", "preferred_tone": "semi-formal",
             "interaction_count": 6, "topics": [], "language_variant": "fr-BE"},
        ], "faq": []}

        profile = _run(store, knowledge, {})
        assert _c(profile, "colleague@corp.com")["preferred_closing"] == "Bonne semaine !"


# ---------------------------------------------------------------------------
# Robustness / graceful-degradation tests
# ---------------------------------------------------------------------------

class TestRobustness:

    def test_empty_knowledge_and_rules_no_crash(self, tmp_path):
        """Empty inputs → no-op, no exception, profile untouched."""
        store = _make_store(tmp_path)
        profile = _run(store, {}, {})
        assert profile.contact_profiles == {}

    def test_none_knowledge_contacts_key(self, tmp_path):
        """'contacts' key missing from knowledge → handled gracefully."""
        store = _make_store(tmp_path)
        profile = _run(store, {"faq": []}, {"contact_rules": []})
        assert profile.contact_profiles == {}

    def test_profile_not_in_store_lazy_creates_and_persists(self, tmp_path):
        """No WritingStyleProfile for this account → profile is lazy-created so
        per-contact enrichment is never silently dropped.
        Protects against the regression where the per-contact editor stayed
        empty when the outbox-based base profile hadn't been saved yet.
        """
        data_dir = tmp_path / "empty_learning"
        data_dir.mkdir()
        store = FileWritingStyleStore(data_dir=data_dir)  # no profile file
        assert store.load(ACCOUNT_ID) is None

        from app.infrastructure.container import get_container
        manager = OnboardingManager(session_factory=lambda: None)
        container = get_container()
        with patch.object(container, "get_writing_style_store", return_value=store):
            manager._persist_contact_profiles(KNOWLEDGE, RULES, ACCOUNT_ID)

        profile = store.load(ACCOUNT_ID)
        assert profile is not None, "Profile must be lazy-created when missing"
        # All 5 test contacts from KNOWLEDGE+RULES must now be persisted.
        assert len(profile.contact_profiles) == 5
        # Spot-check one: formality_override should be mapped from preferred_tone.
        alice = profile.contact_profiles["alice.tremblay@corp.example"]
        assert alice["formality_override"] == "casual"
        assert alice["langue_variante"] == "fr-CH"
        assert alice["nickname"] == "Alice"

    def test_malformed_contact_entry_skipped(self, tmp_path):
        """Contacts missing 'email' key are silently skipped."""
        store = _make_store(tmp_path)
        bad_knowledge = {"contacts": [
            {"name": "No Email Here", "type": "colleague"},  # missing email
            {"email": "", "name": "Empty Email", "type": "colleague"},  # empty email
            {"email": "good@example.com", "name": "Good Contact", "type": "colleague",
             "preferred_language": "en", "preferred_tone": "casual",
             "interaction_count": 1, "topics": [], "language_variant": "en-US"},
        ], "faq": []}

        profile = _run(store, bad_knowledge, {})
        # Only the valid contact should appear
        assert len(profile.contact_profiles) == 1
        assert "good@example.com" in profile.contact_profiles


# ---------------------------------------------------------------------------
# End-to-end prompt integration test
# ---------------------------------------------------------------------------

class TestDrafterAgentPromptIntegration:
    """
    Verify the full pipeline: scan → persist → to_prompt_hint().

    This is what actually matters for quality: the DrafterAgent must receive
    per-contact tone instructions derived from real email analysis.
    """

    @pytest.fixture(autouse=True)
    def _run_scan(self, tmp_path):
        store = _make_store(tmp_path)
        self.profile = _run(store, KNOWLEDGE, RULES)

    def test_alice_prompt_hint_contains_all_signals(self):
        contact_data = _c(self.profile, "alice.tremblay@corp.example")
        contact = ContactStyleProfile.from_dict(contact_data)
        hint = build_contact_hint_block(contact, "fr")

        assert "Alice" in hint                   # nickname used in hint
        assert "Salut Alice," in hint            # specific greeting
        assert "fr-CH" in hint                   # regional vocabulary signal
        assert "français" in hint                # langue signal for French reply

    def test_robert_prompt_hint_formal_signals(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        contact = ContactStyleProfile.from_dict(_c(self.profile, "r.dupont@cabinet-legal.fr"))
        hint = build_contact_hint_block(contact, "fr")

        assert "formal" in hint.lower()
        assert "Bonjour Maître Dupont," in hint
        assert "Cordialement," in hint
        assert "fr-FR" in hint

    def test_sarah_prompt_hint_english_us(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        contact = ContactStyleProfile.from_dict(_c(self.profile, "sarah.johnson@techstartup.io"))
        hint = build_contact_hint_block(contact, "fr")

        assert "anglais" in hint                  # langue signal for English reply
        assert "en-US" in hint
        assert "Hey Sarah" in hint
        assert "Cheers" in hint

    def test_karine_prompt_hint_no_closing_signal(self):
        from app.domain.entities.writing_style import ContactStyleProfile
        contact = ContactStyleProfile.from_dict(_c(self.profile, "karine.morel@gmail.com"))
        hint = build_contact_hint_block(contact, "fr")

        # "(none)" placeholder was dropped → closing must be absent from hint
        assert "Clôture habituelle" not in hint
        assert "(none)" not in hint
        # But variant and greeting are still there
        assert "fr-CA" in hint
        assert "Salut Karine," in hint

    def test_writing_style_profile_unified_path_includes_contact_adaptation(self):
        """PR3 follow-up — `build_style_guidance_from_profile(recipient_email=...)`
        appends the per-contact directive block. The legacy categorical
        "Adaptation pour {email}:" header has been retired with the migration.
        """
        ctx = build_style_guidance_from_profile(
            self.profile, language="fr", recipient_email="sarah.johnson@techstartup.io"
        )

        assert "anglais" in ctx                # reply in English signal
        assert "en-US" in ctx
        assert "Hey Sarah" in ctx
        assert "Sarah" in ctx                  # nickname in the context


# ---------------------------------------------------------------------------
# True end-to-end: emails → real agents (mocked LLM) → persist → profile
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """
    Runs the actual KnowledgeAgent and StyleAgent classes on real IndexedEmails,
    feeding them a mocked LLM that returns realistic JSON (as the real Claude
    would in production). Then calls _persist_contact_profiles and verifies
    that all 6 fields land in the profile.

    This confirms the full chain:
      OnboardingEmail[] → EmailIndexer → KnowledgeAgent/StyleAgent → _persist → profile

    Any serialization layer that would strip fields (e.g. if agents accidentally
    routed through dataclasses) would cause failures here.
    """

    # ── Mocked LLM payloads — what Claude would return in production ─────────

    _KNOWLEDGE_JSON = json.dumps({
        "contacts": [
            {
                "email": "marie.chen@suisse-tech.ch",
                "name": "Marie Chen",
                "type": "colleague",
                "company": "Suisse Tech SA",
                "title": None,
                "preferred_language": "fr",
                "preferred_tone": "casual",
                "interaction_count": 8,
                "topics": ["projet Alpha", "code review"],
                "language_variant": "fr-CH",
            },
            {
                "email": "james.parker@lawfirm.com",
                "name": "James Parker",
                "type": "client",
                "company": "Parker & Associates",
                "title": "Attorney",
                "preferred_language": "en",
                "preferred_tone": "formal",
                "interaction_count": 5,
                "topics": ["contracts", "compliance"],
                "language_variant": "en-US",
            },
            {
                "email": "sophie.martin@design.fr",
                "name": "Sophie Martin",
                "type": "colleague",
                "company": "Design Studio",
                "title": "Lead Designer",
                "preferred_language": "fr",
                "preferred_tone": "semi-formal",
                "interaction_count": 12,
                "topics": ["UI", "maquettes"],
                "language_variant": "fr-FR",
            },
        ],
        "faq": [
            {
                "question": "Quel est le délai de livraison ?",
                "answer": "3 semaines après validation.",
                "category": "FAQ",
                "context": "délai, livraison",
            }
        ],
    }, ensure_ascii=False)

    _STYLE_JSON = json.dumps({
        "contact_rules": [
            {
                "contact_email": "marie.chen@suisse-tech.ch",
                "tone": "casual",
                "greeting": "Salut Marie,",
                "closing": "Alex",
                "language": "fr",
            },
            {
                "contact_email": "james.parker@lawfirm.com",
                "tone": "formal",
                "greeting": "Dear James,",
                "closing": "Best regards,",
                "language": "en",
            },
            {
                "contact_email": "sophie.martin@design.fr",
                "tone": "semi-formal",
                "greeting": "Bonjour Sophie,",
                "closing": "Cordialement,",
                "language": "fr",
            },
        ],
        "general_rules": [
            {
                "name": "tutoiement_equipe",
                "description": "Tutoiement avec l'équipe interne",
                "trigger": "Email interne",
                "action": "Utiliser tu",
            }
        ],
        "forbidden_phrases": [],
    }, ensure_ascii=False)

    # ── Fake email corpus ─────────────────────────────────────────────────────

    USER = "alex@agentys.io"

    @staticmethod
    def _make_emails(user: str):
        """Create a minimal but realistic corpus: sent + received per contact."""
        from app.onboarding.loader import OnboardingEmail
        from app.onboarding.schemas import EmailDirection

        base = datetime(2026, 3, 1, 9, 0)

        def _dt(offset_days: int, offset_hours: int = 0):
            return base + timedelta(days=offset_days, hours=offset_hours)

        return [
            # ── Marie Chen (fr-CH, casual) ───────────────────────────────────
            OnboardingEmail(
                id="r1", sender_email="marie.chen@suisse-tech.ch",
                sender_name="Marie Chen",
                recipients=[user], cc=[],
                subject="Point projet Alpha",
                body="Salut Alex, as-tu avancé sur le projet Alpha ? Merci",
                date=_dt(0), direction=EmailDirection.RECEIVED, thread_id="t1",
            ),
            OnboardingEmail(
                id="s1", sender_email=user,
                sender_name="Alex",
                recipients=["marie.chen@suisse-tech.ch"], cc=[],
                subject="Re: Point projet Alpha",
                body="Salut Marie,\n\nOui, j'ai terminé la revue de code. Je t'envoie le rapport d'ici demain.\n\nAlex",
                date=_dt(0, 2), direction=EmailDirection.SENT, thread_id="t1",
            ),
            OnboardingEmail(
                id="s2", sender_email=user,
                sender_name="Alex",
                recipients=["marie.chen@suisse-tech.ch"], cc=[],
                subject="Suivi semaine 12",
                body="Salut Marie,\n\nVoici le point de la semaine. RAS de mon côté.\n\nAlex",
                date=_dt(7), direction=EmailDirection.SENT, thread_id="t2",
            ),
            # ── James Parker (en-US, formal) ─────────────────────────────────
            OnboardingEmail(
                id="r2", sender_email="james.parker@lawfirm.com",
                sender_name="James Parker",
                recipients=[user], cc=[],
                subject="Contract review needed",
                body="Hi Alex, please review the attached contract terms. Thanks, James Parker, Attorney",
                date=_dt(1), direction=EmailDirection.RECEIVED, thread_id="t3",
            ),
            OnboardingEmail(
                id="s3", sender_email=user,
                sender_name="Alex",
                recipients=["james.parker@lawfirm.com"], cc=[],
                subject="Re: Contract review needed",
                body="Dear James,\n\nThank you for sending the contract. I have reviewed all sections and will provide feedback by end of week.\n\nBest regards,\nAlex",
                date=_dt(1, 3), direction=EmailDirection.SENT, thread_id="t3",
            ),
            OnboardingEmail(
                id="s4", sender_email=user,
                sender_name="Alex",
                recipients=["james.parker@lawfirm.com"], cc=[],
                subject="NDA follow-up",
                body="Dear James,\n\nI wanted to follow up on the NDA we discussed. Please let me know when you are available.\n\nBest regards,\nAlex",
                date=_dt(5), direction=EmailDirection.SENT, thread_id="t4",
            ),
            # ── Sophie Martin (fr-FR, semi-formal) ───────────────────────────
            OnboardingEmail(
                id="r3", sender_email="sophie.martin@design.fr",
                sender_name="Sophie Martin",
                recipients=[user], cc=[],
                subject="Maquettes V2",
                body="Bonjour Alex, je t'envoie les maquettes V2. Cordialement, Sophie Martin",
                date=_dt(2), direction=EmailDirection.RECEIVED, thread_id="t5",
            ),
            OnboardingEmail(
                id="s5", sender_email=user,
                sender_name="Alex",
                recipients=["sophie.martin@design.fr"], cc=[],
                subject="Re: Maquettes V2",
                body="Bonjour Sophie,\n\nMerci pour les maquettes. Quelques retours :\n- Le header me convient\n- Ajuster les couleurs du bouton CTA\n\nCordialement,\nAlex",
                date=_dt(2, 1), direction=EmailDirection.SENT, thread_id="t5",
            ),
        ]

    @pytest.fixture(autouse=True)
    def _run_full_pipeline(self, tmp_path):
        """
        Full pipeline:
        1. Index emails with EmailIndexer
        2. Run KnowledgeAgent (mocked LLM → _KNOWLEDGE_JSON)
        3. Run StyleAgent      (mocked LLM → _STYLE_JSON)
        4. Call _persist_contact_profiles
        5. Store reloaded profile in self.profile
        """
        from app.domain.ports.llm_port import LLMResponse
        from app.onboarding.agents.knowledge_agent import KnowledgeAgent
        from app.onboarding.agents.style_agent import StyleAgent
        from app.onboarding.indexer import EmailIndexer
        from unittest.mock import MagicMock
        from app.infrastructure.container import get_container

        # Index emails
        emails = self._make_emails(self.USER)
        indexed = EmailIndexer(self.USER).index(emails)

        # Build per-agent mock LLMs
        def _mock_llm(payload: str):
            m = MagicMock()
            m.complete.return_value = LLMResponse(
                content=payload, input_tokens=500, output_tokens=300
            )
            m.is_available.return_value = True
            return m

        # Run the real agents (mocked LLM provides deterministic JSON)
        knowledge_output = KnowledgeAgent(_llm=_mock_llm(self._KNOWLEDGE_JSON)).analyse(indexed)
        style_output = StyleAgent(_llm=_mock_llm(self._STYLE_JSON)).analyse(indexed)

        # Persist via manager
        store = _make_store(tmp_path)
        manager = OnboardingManager(session_factory=lambda: None)
        container = get_container()
        with patch.object(container, "get_writing_style_store", return_value=store):
            manager._persist_contact_profiles(knowledge_output, style_output, ACCOUNT_ID)

        self.profile = store.load(ACCOUNT_ID)
        assert self.profile is not None

    # ── Verify agents passed language_variant through (not stripped) ──────────

    def test_knowledge_agent_preserves_language_variant_in_output(self):
        """KnowledgeAgent must NOT strip language_variant from its raw dict output."""
        from app.domain.ports.llm_port import LLMResponse
        from app.onboarding.agents.knowledge_agent import KnowledgeAgent
        from app.onboarding.indexer import EmailIndexer
        from unittest.mock import MagicMock

        emails = self._make_emails(self.USER)
        indexed = EmailIndexer(self.USER).index(emails)
        m = MagicMock()
        m.complete.return_value = LLMResponse(content=self._KNOWLEDGE_JSON)
        output = KnowledgeAgent(_llm=m).analyse(indexed)

        # The raw dict must carry language_variant for each contact
        variants = {c["email"]: c.get("language_variant") for c in output.get("contacts", [])}
        assert variants.get("marie.chen@suisse-tech.ch") == "fr-CH"
        assert variants.get("james.parker@lawfirm.com") == "en-US"
        assert variants.get("sophie.martin@design.fr") == "fr-FR"

    def test_style_agent_preserves_greeting_closing_in_output(self):
        """StyleAgent must NOT strip greeting/closing from its raw dict output."""
        from app.domain.ports.llm_port import LLMResponse
        from app.onboarding.agents.style_agent import StyleAgent
        from app.onboarding.indexer import EmailIndexer
        from unittest.mock import MagicMock

        emails = self._make_emails(self.USER)
        indexed = EmailIndexer(self.USER).index(emails)
        m = MagicMock()
        m.complete.return_value = LLMResponse(content=self._STYLE_JSON)
        output = StyleAgent(_llm=m).analyse(indexed)

        rules = {r["contact_email"]: r for r in output.get("contact_rules", [])}
        assert rules["marie.chen@suisse-tech.ch"]["greeting"] == "Salut Marie,"
        assert rules["james.parker@lawfirm.com"]["closing"] == "Best regards,"
        assert rules["sophie.martin@design.fr"]["tone"] == "semi-formal"

    # ── Per-contact field assertions ──────────────────────────────────────────

    def test_marie_all_fields(self):
        contact = _c(self.profile, "marie.chen@suisse-tech.ch")
        assert contact["formality_override"] == "casual"
        assert contact["preferred_greeting"] == "Salut {first_name},"
        assert contact["preferred_closing"] == "Alex"
        assert contact["langue"] == "français"
        assert contact["langue_variante"] == "fr-CH"
        assert contact["nickname"] == "Marie"

    def test_james_all_fields(self):
        contact = _c(self.profile, "james.parker@lawfirm.com")
        assert contact["formality_override"] == "formal"
        assert contact["preferred_greeting"] == "Dear {first_name},"
        assert contact["preferred_closing"] == "Best regards,"
        assert contact["langue"] == "anglais"
        assert contact["langue_variante"] == "en-US"
        assert contact["nickname"] == "James"

    def test_sophie_all_fields(self):
        contact = _c(self.profile, "sophie.martin@design.fr")
        assert contact["formality_override"] == "mixed"      # semi-formal → MIXED
        assert contact["preferred_greeting"] == "Bonjour {first_name},"
        assert contact["preferred_closing"] == "Cordialement,"
        assert contact["langue"] == "français"
        assert contact["langue_variante"] == "fr-FR"
        assert contact["nickname"] == "Sophie"

    def test_all_three_contacts_present(self):
        """Exactly 3 contacts should be in the profile — no leakage of noise senders."""
        assert len(self.profile.contact_profiles) == 3

    def test_faq_does_not_affect_contact_profiles(self):
        """FAQ entries in knowledge output must not create spurious contact entries."""
        # "délai de livraison" FAQ entry is not an email → should not appear
        for key in self.profile.contact_profiles:
            assert "faq" not in key
            assert "délai" not in key

    def test_drafter_agent_context_built_correctly_for_each_contact(self):
        """
        The final DrafterAgent call — to_prompt_context(recipient_email=...) —
        must include per-contact adaptation for all 3 contacts.
        """
        for email, expected_signals in [
            ("marie.chen@suisse-tech.ch", ["fr-CH", "Salut Marie,", "Marie", "français"]),
            ("james.parker@lawfirm.com",  ["en-US", "Dear James,", "James", "anglais"]),
            ("sophie.martin@design.fr",   ["fr-FR", "Bonjour Sophie,", "Sophie"]),
        ]:
            ctx = build_style_guidance_from_profile(
                self.profile, language="fr", recipient_email=email
            )
            for signal in expected_signals:
                assert signal in ctx, (
                    f"Signal {signal!r} missing from DrafterAgent context for {email}.\n"
                    f"Context:\n{ctx}"
                )


# ---------------------------------------------------------------------------
# Nickname extraction — greeting takes precedence over full name
# ---------------------------------------------------------------------------

class TestNicknameExtraction:
    """
    The first name actually used in the greeting (StyleAgent) takes
    priority over the first word of the KnowledgeAgent full name.
    This ensures nicknames like "Ali" (used in practice) are preferred
    over "Alice" (from the formal full name in the signature).
    """

    def _run_single(self, tmp_path, greeting: str, full_name: str, email: str = "contact@example.com") -> dict:
        store = _make_store(tmp_path)
        knowledge = {"contacts": [
            {"email": email, "name": full_name, "type": "colleague",
             "preferred_language": "fr", "preferred_tone": "casual",
             "interaction_count": 5, "topics": [], "language_variant": None},
        ], "faq": []}
        rules = {"contact_rules": [
            {"contact_email": email, "tone": "casual",
             "greeting": greeting, "closing": "Cdt", "language": "fr"},
        ], "general_rules": [], "forbidden_phrases": []}
        profile = _run(store, knowledge, rules)
        return _c(profile, email)

    def test_greeting_nickname_preferred_over_full_name(self, tmp_path):
        """User writes "Salut Ali," but full name is "Alice Tremblay" → nickname = "Ali"."""
        contact = self._run_single(tmp_path, "Salut Ali,", "Alice Tremblay")
        assert contact["nickname"] == "Ali"

    def test_bonjour_extracts_first_name(self, tmp_path):
        contact = self._run_single(tmp_path, "Bonjour Sophie,", "Sophie Martin")
        assert contact["nickname"] == "Sophie"

    def test_hi_extracts_first_name(self, tmp_path):
        contact = self._run_single(tmp_path, "Hi James,", "James Parker")
        assert contact["nickname"] == "James"

    def test_hey_extracts_first_name(self, tmp_path):
        contact = self._run_single(tmp_path, "Hey Sarah", "Sarah Johnson")
        assert contact["nickname"] == "Sarah"

    def test_dear_extracts_first_name(self, tmp_path):
        contact = self._run_single(tmp_path, "Dear Emma,", "Emma Wilson")
        assert contact["nickname"] == "Emma"

    def test_hyphenated_first_name_extracted(self, tmp_path):
        """"Salut Jean-Pierre," → "Jean-Pierre" (hyphenated names preserved)."""
        contact = self._run_single(tmp_path, "Salut Jean-Pierre,", "Jean-Pierre Dupont")
        assert contact["nickname"] == "Jean-Pierre"

    def test_honorific_greeting_falls_back_to_full_name_first_word(self, tmp_path):
        """
        "Bonjour Monsieur Dupont," → no nickname from greeting (family name after
        honorific). Fallback: first word of KnowledgeAgent name = "Robert".
        """
        contact = self._run_single(tmp_path, "Bonjour Monsieur Dupont,", "Robert Dupont")
        assert contact["nickname"] == "Robert"

    def test_greeting_no_name_falls_back_to_full_name(self, tmp_path):
        """'Bonjour,' alone → no name to extract → fallback to KnowledgeAgent name."""
        contact = self._run_single(tmp_path, "Bonjour,", "Marie Curie")
        assert contact["nickname"] == "Marie"

    def test_placeholder_greeting_falls_back_to_full_name(self, tmp_path):
        """'(none)' placeholder → fallback to KnowledgeAgent name."""
        contact = self._run_single(tmp_path, "(none)", "Karine Morel")
        assert contact["nickname"] == "Karine"

    def test_no_greeting_and_no_usable_name(self, tmp_path):
        """No greeting, name equals email prefix → no nickname at all."""
        contact = self._run_single(tmp_path, "", "fatima", email="fatima@okara.ai")
        assert contact["nickname"] is None

    def test_extract_name_from_greeting_static_method(self):
        """Unit-test the static helper directly."""
        fn = OnboardingManager._extract_name_from_greeting
        assert fn("Salut Alice,") == "Alice"
        assert fn("Bonjour Sophie,") == "Sophie"
        assert fn("Hi James,") == "James"
        assert fn("Hey Sarah") == "Sarah"
        assert fn("Dear Emma,") == "Emma"
        assert fn("Salut Ali,") == "Ali"
        assert fn("Bonjour Monsieur Dupont,") is None   # honorific → skip
        assert fn("Bonjour Madame Martin,") is None     # honorific → skip
        assert fn("Bonjour,") is None                   # no name
        assert fn("(none)") is None                     # placeholder
        assert fn("") is None                           # empty
        assert fn("Salut Alice, / Alice,") == "Alice"   # multi-variant → primary
