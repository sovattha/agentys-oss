"""Tests pour IntentCategory et IntentClassification.

Ces entités pilotent le routage du DrafterAgent vers des protocoles de réponse
adaptés (framework copywriting, triggers comportementaux, action d'escalation).
Voir issue #191.
"""

import pytest

from app.domain.entities.classification import (
    IntentCategory,
    IntentClassification,
)
from app.domain.exceptions import InvalidBoundsError


class TestIntentCategory:
    def test_all_intents_exist(self):
        expected = {
            "INQUIRY",
            "NEGOTIATION",
            "FOLLOW_UP",
            "OBJECTION",
            "ESCALATION",
            "INFORMATIONAL",
            "OTHER",
        }
        actual = {i.name for i in IntentCategory}
        assert actual == expected

    def test_intent_values_match_names(self):
        # Les valeurs sérialisées doivent matcher les noms pour stabilité DB.
        for intent in IntentCategory:
            assert intent.value == intent.name


class TestIntentClassification:
    def test_valid_instance(self):
        ic = IntentClassification(
            intent=IntentCategory.NEGOTIATION,
            confidence=0.87,
            reasoning="mentionne budget et deadline",
        )
        assert ic.intent == IntentCategory.NEGOTIATION
        assert ic.confidence == 0.87

    @pytest.mark.parametrize("bad_conf", [-0.1, 1.01, 2.0])
    def test_confidence_out_of_bounds_raises(self, bad_conf):
        with pytest.raises(InvalidBoundsError):
            IntentClassification(
                intent=IntentCategory.INQUIRY,
                confidence=bad_conf,
                reasoning="x",
            )

    def test_reasoning_none_raises_type_error(self):
        with pytest.raises(TypeError):
            IntentClassification(
                intent=IntentCategory.INQUIRY,
                confidence=0.5,
                reasoning=None,  # type: ignore[arg-type]
            )

    def test_default_is_safe_fallback(self):
        ic = IntentClassification.default()
        assert ic.intent == IntentCategory.OTHER
        assert 0.0 <= ic.confidence <= 1.0
        assert ic.reasoning  # non-empty

    def test_escalation_requires_human(self):
        ic = IntentClassification(
            intent=IntentCategory.ESCALATION,
            confidence=0.9,
            reasoning="demande RGPD avec menace juridique",
        )
        assert ic.requires_human_escalation()

    def test_low_confidence_escalation_does_not_trigger(self):
        # Protection contre les faux positifs d'escalation.
        ic = IntentClassification(
            intent=IntentCategory.ESCALATION,
            confidence=0.4,
            reasoning="ambigu",
        )
        assert not ic.requires_human_escalation()

    def test_non_escalation_never_triggers(self):
        for intent in IntentCategory:
            if intent == IntentCategory.ESCALATION:
                continue
            ic = IntentClassification(intent=intent, confidence=0.99, reasoning="")
            assert not ic.requires_human_escalation()

    def test_to_dict_roundtrip(self):
        ic = IntentClassification(
            intent=IntentCategory.FOLLOW_UP,
            confidence=0.75,
            reasoning="3e relance",
        )
        d = ic.to_dict()
        assert d == {
            "intent": "FOLLOW_UP",
            "confidence": 0.75,
            "reasoning": "3e relance",
        }
        restored = IntentClassification.from_dict(d)
        assert restored == ic

    def test_from_dict_unknown_intent_falls_back_to_other(self):
        ic = IntentClassification.from_dict(
            {"intent": "NOT_A_REAL_INTENT", "confidence": 0.9, "reasoning": "llm drifted"}
        )
        assert ic.intent == IntentCategory.OTHER
        assert ic.confidence == 0.9

    def test_from_dict_clamps_confidence(self):
        ic = IntentClassification.from_dict(
            {"intent": "INQUIRY", "confidence": 1.5, "reasoning": ""}
        )
        assert ic.confidence == 1.0

    def test_from_dict_null_reasoning_becomes_empty_string(self):
        ic = IntentClassification.from_dict(
            {"intent": "INQUIRY", "confidence": 0.5, "reasoning": None}
        )
        assert ic.reasoning == ""
