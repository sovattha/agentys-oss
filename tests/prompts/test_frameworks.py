"""Tests pour les frameworks de copywriting (#197).

Couvre le mapping intent → framework, l'override utilisateur, et le rendu
du bloc injectable dans le system prompt.
"""

import pytest

from app.domain.entities.classification import IntentCategory
from app.prompts.frameworks import (
    Framework,
    FrameworkKey,
    build_framework_prompt_block,
    get_framework,
    select_framework,
)


class TestDefaultMapping:
    @pytest.mark.parametrize(
        "intent,expected",
        [
            (IntentCategory.INQUIRY, FrameworkKey.AIDA),
            (IntentCategory.NEGOTIATION, FrameworkKey.PAS),
            (IntentCategory.FOLLOW_UP, FrameworkKey.BAB),
            (IntentCategory.OBJECTION, FrameworkKey.PAS),
            (IntentCategory.ESCALATION, FrameworkKey.NONE),
            (IntentCategory.INFORMATIONAL, FrameworkKey.FIVE_CS),
            (IntentCategory.OTHER, FrameworkKey.FIVE_CS),
        ],
    )
    def test_intent_maps_to_expected_framework(self, intent, expected):
        fw = select_framework(intent)
        assert fw.key == expected

    def test_all_intents_have_mapping(self):
        # Jamais de KeyError pour un intent valide.
        for intent in IntentCategory:
            fw = select_framework(intent)
            assert isinstance(fw, Framework)


class TestOverride:
    def test_user_override_supersedes_default(self):
        # User force BAB sur un Inquiry (qui mapperait normalement sur AIDA).
        fw = select_framework(IntentCategory.INQUIRY, override=FrameworkKey.BAB)
        assert fw.key == FrameworkKey.BAB

    def test_override_none_means_no_framework(self):
        fw = select_framework(IntentCategory.INQUIRY, override=FrameworkKey.NONE)
        assert fw.key == FrameworkKey.NONE


class TestPromptBlockRendering:
    def test_none_framework_returns_empty_block(self):
        # ESCALATION → pas de framework ni de bloc injecté.
        block = build_framework_prompt_block(IntentCategory.ESCALATION)
        assert block == ""

    def test_framework_block_mentions_structure(self):
        block = build_framework_prompt_block(IntentCategory.NEGOTIATION)
        assert "PAS" in block
        assert "Problem" in block
        assert "Solution" in block

    def test_block_is_tagged_for_parsability(self):
        block = build_framework_prompt_block(IntentCategory.INQUIRY)
        assert block.startswith("<FRAMEWORK_REPONSE>")
        assert block.endswith("</FRAMEWORK_REPONSE>")

    def test_graceful_degradation_clause_present(self):
        # Le snippet doit inclure la clause anti-forçage pour éviter des
        # drafts articulés artificiellement quand l'input ne s'y prête pas.
        block = build_framework_prompt_block(IntentCategory.INQUIRY)
        assert "dégrade" in block.lower() or "degrade" in block.lower()


class TestLookup:
    def test_get_framework_returns_all_keys(self):
        for key in FrameworkKey:
            fw = get_framework(key)
            assert fw.key == key

    def test_frameworks_have_non_empty_snippets_except_none(self):
        for key in FrameworkKey:
            fw = get_framework(key)
            if key == FrameworkKey.NONE:
                assert fw.snippet == ""
            else:
                assert fw.snippet  # Non-empty.
                assert fw.structure  # Non-empty.
