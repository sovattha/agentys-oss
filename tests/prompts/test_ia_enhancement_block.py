"""Tests d'intégration pour _build_ia_enhancement_block (#190 + #197 + #198).

Vérifie que les extensions IA optionnelles se composent correctement :
- Chacune se tait quand inactive (pas de pollution du prompt)
- Toutes présentes = les 3 blocs dans la sortie
- Une extension qui crashe n'empêche pas les autres de produire leur bloc
"""

import pytest

from app.domain.entities.classification import IntentCategory
from app.domain.entities.recipient_profile import (
    DISCScores,
    DISCType,
    RecipientProfile,
)
from app.prompts.builders import _build_ia_enhancement_block
from app.prompts.frameworks import FrameworkKey
from app.prompts.triggers import TriggerKey


@pytest.fixture
def reliable_profile():
    return RecipientProfile(
        email="bob@example.com",
        disc=DISCType.CONSCIENTIOUSNESS,
        disc_scores=DISCScores(0.2, 0.2, 0.2, 0.6),
        confidence=0.3,
        sample_size=5,
    )


class TestNothingActive:
    def test_all_none_returns_empty(self):
        assert _build_ia_enhancement_block() == ""

    def test_triggers_enabled_without_intent_returns_empty(self):
        # Sans intent, aucun trigger ne peut être sélectionné.
        assert _build_ia_enhancement_block(triggers_enabled=True) == ""


class TestRecipientProfileOnly:
    def test_reliable_profile_injects_single_block(self, reliable_profile):
        out = _build_ia_enhancement_block(recipient_profile=reliable_profile)
        assert "<PROFIL_DESTINATAIRE>" in out
        assert "<FRAMEWORK_REPONSE>" not in out
        assert "<TRIGGER_COMPORTEMENTAL>" not in out

    def test_unreliable_profile_produces_no_block(self):
        weak = RecipientProfile(
            email="x@example.com",
            disc=DISCType.UNKNOWN,
            confidence=0.0,
            sample_size=0,
        )
        assert _build_ia_enhancement_block(recipient_profile=weak) == ""


class TestIntentOnly:
    def test_intent_injects_framework_block(self):
        out = _build_ia_enhancement_block(intent=IntentCategory.NEGOTIATION)
        assert "<FRAMEWORK_REPONSE>" in out
        assert "PAS" in out
        assert "<TRIGGER_COMPORTEMENTAL>" not in out

    def test_escalation_intent_skips_framework_block(self):
        out = _build_ia_enhancement_block(intent=IntentCategory.ESCALATION)
        # ESCALATION → framework NONE → bloc vide.
        assert out == ""

    def test_framework_override_respected(self):
        out = _build_ia_enhancement_block(
            intent=IntentCategory.INQUIRY,
            framework_override=FrameworkKey.BAB,
        )
        assert "BAB" in out


class TestTriggerIntegration:
    def test_triggers_disabled_no_trigger_block(self):
        out = _build_ia_enhancement_block(
            intent=IntentCategory.INQUIRY,
            triggers_enabled=False,
        )
        assert "<TRIGGER_COMPORTEMENTAL>" not in out

    def test_triggers_enabled_injects_trigger_block(self):
        out = _build_ia_enhancement_block(
            intent=IntentCategory.INQUIRY,
            triggers_enabled=True,
        )
        assert "<TRIGGER_COMPORTEMENTAL>" in out
        assert "Curiosité" in out or "CURIOSITY" in out.upper()

    def test_trigger_override_respected(self):
        out = _build_ia_enhancement_block(
            intent=IntentCategory.INQUIRY,
            triggers_enabled=True,
            trigger_override=TriggerKey.SOCIAL_PROOF,
        )
        assert "sociale" in out.lower() or "social" in out.lower()

    def test_objection_bans_urgency_override(self):
        # Guardrail : même avec override URGENCY, bannie sur OBJECTION.
        out = _build_ia_enhancement_block(
            intent=IntentCategory.OBJECTION,
            triggers_enabled=True,
            trigger_override=TriggerKey.URGENCY,
        )
        # Le framework PAS s'injecte, mais pas de bloc trigger.
        assert "<FRAMEWORK_REPONSE>" in out
        assert "<TRIGGER_COMPORTEMENTAL>" not in out


class TestFullComposition:
    def test_all_extensions_compose(self, reliable_profile):
        out = _build_ia_enhancement_block(
            recipient_profile=reliable_profile,
            intent=IntentCategory.NEGOTIATION,
            triggers_enabled=True,
        )
        # Les 3 blocs doivent être présents et distincts.
        assert "<PROFIL_DESTINATAIRE>" in out
        assert "<FRAMEWORK_REPONSE>" in out
        assert "<TRIGGER_COMPORTEMENTAL>" in out

    def test_blocks_separated_by_double_newline(self, reliable_profile):
        out = _build_ia_enhancement_block(
            recipient_profile=reliable_profile,
            intent=IntentCategory.NEGOTIATION,
            triggers_enabled=True,
        )
        # Double newline entre chaque pour une lecture claire par le LLM.
        assert out.count("\n\n") >= 2


class TestFailOpen:
    def test_broken_profile_doesnt_crash_other_blocks(self):
        # Un profile qui lève une exception ne doit pas empêcher le framework
        # de s'injecter. On simule en passant un mock qui lève.
        class BrokenProfile:
            def to_prompt_block(self):
                raise RuntimeError("broken")

        out = _build_ia_enhancement_block(
            recipient_profile=BrokenProfile(),  # type: ignore[arg-type]
            intent=IntentCategory.INQUIRY,
        )
        # Le profile a crashé silencieusement, mais le framework est là.
        assert "<FRAMEWORK_REPONSE>" in out
