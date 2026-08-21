"""Tests pour les triggers comportementaux (#198).

Couvre :
- Opt-in par défaut (aucun trigger si enabled=False)
- Mapping intent → trigger
- Guardrails : triggers bannis par intent
- Override utilisateur soumis aux guardrails
- Rendu prompt + clauses anti-abus
"""

import pytest

from app.domain.entities.classification import IntentCategory
from app.prompts.triggers import (
    TriggerKey,
    build_trigger_prompt_block,
    get_trigger,
    select_trigger,
)


class TestOptIn:
    def test_disabled_returns_none_regardless_of_intent(self):
        for intent in IntentCategory:
            t = select_trigger(intent, enabled=False)
            assert t.key == TriggerKey.NONE

    def test_disabled_ignores_override(self):
        t = select_trigger(IntentCategory.INQUIRY, enabled=False, override=TriggerKey.URGENCY)
        assert t.key == TriggerKey.NONE


class TestDefaultMapping:
    @pytest.mark.parametrize(
        "intent,expected",
        [
            (IntentCategory.INQUIRY, TriggerKey.CURIOSITY),
            (IntentCategory.NEGOTIATION, TriggerKey.RECIPROCITY),
            (IntentCategory.FOLLOW_UP, TriggerKey.URGENCY),
            (IntentCategory.OBJECTION, TriggerKey.SOCIAL_PROOF),
            (IntentCategory.ESCALATION, TriggerKey.NONE),
            (IntentCategory.INFORMATIONAL, TriggerKey.NONE),
            (IntentCategory.OTHER, TriggerKey.NONE),
        ],
    )
    def test_intent_maps_to_expected_trigger(self, intent, expected):
        t = select_trigger(intent, enabled=True)
        assert t.key == expected


class TestGuardrails:
    def test_urgency_banned_on_objection(self):
        # Même avec enabled + override, l'urgence est bannie sur objection.
        t = select_trigger(
            IntentCategory.OBJECTION,
            enabled=True,
            override=TriggerKey.URGENCY,
        )
        assert t.key == TriggerKey.NONE

    def test_all_triggers_banned_on_escalation(self):
        for tk in [TriggerKey.URGENCY, TriggerKey.CURIOSITY,
                   TriggerKey.SOCIAL_PROOF, TriggerKey.RECIPROCITY]:
            t = select_trigger(
                IntentCategory.ESCALATION,
                enabled=True,
                override=tk,
            )
            assert t.key == TriggerKey.NONE

    def test_informational_bans_urgency_and_curiosity(self):
        for tk in [TriggerKey.URGENCY, TriggerKey.CURIOSITY]:
            t = select_trigger(
                IntentCategory.INFORMATIONAL,
                enabled=True,
                override=tk,
            )
            assert t.key == TriggerKey.NONE

    def test_informational_allows_reciprocity_via_override(self):
        t = select_trigger(
            IntentCategory.INFORMATIONAL,
            enabled=True,
            override=TriggerKey.RECIPROCITY,
        )
        assert t.key == TriggerKey.RECIPROCITY


class TestPromptBlock:
    def test_disabled_produces_empty_block(self):
        assert build_trigger_prompt_block(IntentCategory.INQUIRY, enabled=False) == ""

    def test_none_trigger_produces_empty_block(self):
        assert build_trigger_prompt_block(IntentCategory.INFORMATIONAL, enabled=True) == ""

    def test_block_contains_trigger_name(self):
        block = build_trigger_prompt_block(IntentCategory.NEGOTIATION, enabled=True)
        assert "Réciprocité" in block
        assert "<TRIGGER_COMPORTEMENTAL>" in block

    def test_block_contains_anti_abuse_clause(self):
        block = build_trigger_prompt_block(IntentCategory.FOLLOW_UP, enabled=True)
        # URGENCY trigger doit contenir la clause d'interdiction de faux urgency.
        assert "IMPÉRATIF" in block
        assert "inventé" in block.lower() or "invente" in block.lower()

    def test_block_enforces_single_trigger_rule(self):
        block = build_trigger_prompt_block(IntentCategory.INQUIRY, enabled=True)
        assert "UN SEUL" in block or "empilement" in block.lower()


class TestLookup:
    def test_get_all_triggers(self):
        for key in TriggerKey:
            t = get_trigger(key)
            assert t.key == key

    def test_non_none_triggers_have_snippet_and_anti_abuse(self):
        for key in TriggerKey:
            if key == TriggerKey.NONE:
                continue
            t = get_trigger(key)
            assert t.snippet
            assert t.anti_abuse_clause
