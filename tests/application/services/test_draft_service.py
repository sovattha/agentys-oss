"""Tests Phase 2a — DraftService skeleton + DTOs (verrouille les contrats).

Phase 2a livre uniquement la "forme" du service. La logique métier
(generate() qui appelle Drafter → SelfCritique → escalade éventuelle Critic+V2)
arrive en Phase 2b (compose) et 2c (reply).
"""

from __future__ import annotations

import dataclasses
import pytest

from app.application.dto.draft_context import DraftContext
from app.application.dto.draft_result import DraftServiceResult
from app.application.services.draft_service import DraftService


# ---------------------------------------------------------------------------
# DraftContext — frozen dataclass, champs typés
# ---------------------------------------------------------------------------

class TestDraftContext:
    def test_minimal_construction_compose_mode(self):
        # En mode compose, email_in est None — l'utilisateur compose à partir
        # d'un (subject, instructions) sans email préalable.
        ctx = DraftContext(
            recipient_email="alice@example.com",
            subject="Demande de devis",
            instructions="Propose 3 options.",
            knowledge_base="",
            user_email="me@example.com",
        )
        assert ctx.email_in is None
        assert ctx.recipient_email == "alice@example.com"
        assert ctx.conversation_history == ()  # Default tuple, immutable

    def test_full_construction_reply_mode(self):
        ctx = DraftContext(
            email_in={
                "sender": "alice@example.com",
                "body": "Bonjour, pouvez-vous m'envoyer le rapport ?",
                "subject": "Demande rapport",
                "id": "msg-42",
                "thread_id": "thread-1",
            },
            recipient_email="alice@example.com",
            subject="Re: Rapport",
            instructions="",
            cc=("bob@example.com",),
            conversation_history=({"sender": "alice@example.com", "body": "Hello"},),
            knowledge_base="ACME Corp...",
            account_id=42,
            user_email="me@example.com",
            tier_hint="STANDARD",
            language="fr",
        )
        assert ctx.email_in is not None
        assert ctx.email_in["thread_id"] == "thread-1"
        assert ctx.cc == ("bob@example.com",)
        assert ctx.account_id == 42
        assert ctx.tier_hint == "STANDARD"
        assert ctx.language == "fr"

    def test_compose_id_field_supports_streaming(self):
        # Phase 2b/2c brancheront le streaming WebSocket via compose_id —
        # le DTO doit le supporter dès Phase 2a pour éviter le breaking change.
        ctx = DraftContext(
            recipient_email="a@b.com", subject="x", instructions="",
            knowledge_base="", user_email="me@b.com",
            compose_id="compose-session-abc123",
        )
        assert ctx.compose_id == "compose-session-abc123"

    def test_is_frozen(self):
        ctx = DraftContext(
            recipient_email="a@b.com", subject="x", instructions="",
            knowledge_base="", user_email="me@b.com",
        )
        # Frozen dataclass : muter doit raise FrozenInstanceError
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ctx.recipient_email = "evil@b.com"  # type: ignore[misc]

    def test_conversation_history_default_is_immutable(self):
        # Pattern : utiliser tuple par défaut pour éviter le piège du
        # default mutable shared entre instances.
        ctx = DraftContext(
            recipient_email="a@b.com", subject="x", instructions="",
            knowledge_base="", user_email="me@b.com",
        )
        assert isinstance(ctx.conversation_history, tuple)


# ---------------------------------------------------------------------------
# DraftServiceResult — mutable dataclass
# ---------------------------------------------------------------------------

class TestDraftServiceResult:
    def test_minimal_construction(self):
        r = DraftServiceResult(body="Bonjour, c'est noté.")
        assert r.body == "Bonjour, c'est noté."
        assert r.pipeline_info == {}
        assert r.escalated is False
        assert r.version_index == 1
        assert r.self_critique is None
        assert r.critique is None

    def test_is_mutable_for_progressive_construction(self):
        # Phase 2b/2c construira un result en plusieurs étapes :
        # body d'abord, puis self_critique, puis (si escalade) critique + V2.
        r = DraftServiceResult(body="V1")
        r.escalated = True
        r.version_index = 2
        r.body = "V2"
        assert r.body == "V2"
        assert r.escalated is True
        assert r.version_index == 2

    def test_escalated_result_carries_both_verdicts(self):
        # Quand escalated=True, le DTO doit carry à la fois le verdict
        # SelfCritique (qui a déclenché l'escalade) ET le verdict Critic
        # (qui a tranché valid/reject + V2 éventuel)
        from app.domain.entities.self_critique import SelfCritique
        sc = SelfCritique(self_score=60, risks=("placeholder",), a_confirmer_count=1, confidence="med")
        r = DraftServiceResult(
            body="X",
            self_critique=sc,
            critique={"overall_score": 75, "decision": "valid", "was_revised": True},
            escalated=True,
            version_index=2,
        )
        assert r.self_critique is sc  # Reference preserved, no copy
        assert r.critique["was_revised"] is True
        assert r.escalated is True
        assert r.version_index == 2


# ---------------------------------------------------------------------------
# DraftService — skeleton (Phase 2a) — generate() lève NotImplementedError
# ---------------------------------------------------------------------------

class TestDraftServiceSkeleton:
    def test_instantiable_without_dependencies(self):
        # En Phase 2a, on doit pouvoir instancier sans factories — Phase 2b
        # branchera les factories depuis Container côté API endpoints.
        service = DraftService()
        assert service is not None

    def test_instantiable_with_injected_factories(self):
        # Pour les tests Phase 2b/2c, on injecte des fakes — l'API doit
        # supporter ça dès maintenant.
        called = {"drafter": False, "self_critique": False, "critic": False}

        def fake_drafter():
            called["drafter"] = True

        def fake_sc():
            called["self_critique"] = True

        def fake_critic():
            called["critic"] = True

        service = DraftService(
            drafter_factory=fake_drafter,
            self_critique_factory=fake_sc,
            critic_factory=fake_critic,
        )
        assert service is not None
        # Les factories ne sont pas appelées à l'instanciation, juste stockées
        assert all(v is False for v in called.values())

    def test_generate_raises_not_implemented_with_clear_message(self):
        service = DraftService()
        ctx = DraftContext(
            recipient_email="a@b.com", subject="x", instructions="",
            knowledge_base="", user_email="me@b.com",
        )
        with pytest.raises(NotImplementedError) as exc_info:
            service.generate(ctx, mode="reply")
        # Message explicite — un dev qui tombe dessus doit comprendre que
        # c'est intentionnel (Phase 2a) et où chercher pour 2b/2c.
        assert "Phase 2b" in str(exc_info.value) or "Phase 2c" in str(exc_info.value)

    def test_generate_invalid_mode_raises_value_error_before_not_implemented(self):
        # Invalide mode = bug appelant. Doit lever ValueError tout de suite,
        # pas NotImplementedError (qui suggère "à venir") ni AttributeError.
        service = DraftService()
        ctx = DraftContext(
            recipient_email="a@b.com", subject="x", instructions="",
            knowledge_base="", user_email="me@b.com",
        )
        with pytest.raises(ValueError) as exc_info:
            service.generate(ctx, mode="banana")  # type: ignore[arg-type]
        assert "mode" in str(exc_info.value).lower()

    def test_generate_compose_mode_raises_not_implemented(self):
        # Phase 2b : compose mode is implemented and would attempt to call the
        # Container — without injected factories. Skip this test post-Phase 2b
        # (parité ensure that compose works is in test_draft_service_compose.py).
        # We only keep the reply test below since reply remains a Phase 2c stub.
        pass

    def test_generate_reply_mode_raises_not_implemented(self):
        service = DraftService()
        ctx = DraftContext(
            email_in={"sender": "a@b.com", "body": "Original email body"},
            recipient_email="a@b.com", subject="Re: subject",
            instructions="", knowledge_base="", user_email="me@b.com",
        )
        with pytest.raises(NotImplementedError):
            service.generate(ctx, mode="reply")
