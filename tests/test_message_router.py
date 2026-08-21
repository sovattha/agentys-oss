# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour le module de routage de messages multi-canal.

pytest tests/test_message_router.py -v
"""

import pytest
from datetime import datetime

from app.message_router import (
    MessageChannel,
    RoutingStatus,
    MessagePriority,
    MessageCategory,
    IncomingMessage,
    RoutingDecision,
    SupervisionResult,
    DispatcherAgent,
    SupervisorAgent,
    MessageRouter,
    get_message_router,
    create_incoming_message,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def dispatcher():
    """Crée un dispatcher pour les tests."""
    return DispatcherAgent()


@pytest.fixture
def supervisor():
    """Crée un supervisor pour les tests."""
    return SupervisorAgent()


@pytest.fixture
def router():
    """Crée un router pour les tests."""
    return MessageRouter()


@pytest.fixture
def email_message():
    """Message email de test."""
    return IncomingMessage(
        channel=MessageChannel.EMAIL,
        content="Bonjour, j'ai un problème technique avec mon installation.",
        sender_id="user@example.com",
        sender_name="John Doe",
        subject="Problème technique"
    )


@pytest.fixture
def discord_message():
    """Message Discord de test."""
    return IncomingMessage(
        channel=MessageChannel.DISCORD,
        content="J'ai besoin d'aide avec un bug urgent !",
        sender_id="discord_user_123",
        sender_name="DiscordUser",
        guild_id="guild_456",
        channel_name="support"
    )


@pytest.fixture
def legal_message():
    """Message juridique de test."""
    return IncomingMessage(
        channel=MessageChannel.EMAIL,
        content="J'ai une question concernant mon contrat et mes obligations légales.",
        sender_id="client@company.com"
    )


@pytest.fixture
def spam_message():
    """Message spam de test."""
    return IncomingMessage(
        channel=MessageChannel.EMAIL,
        content="Félicitations ! Vous avez gagné à la loterie ! Cliquez ici pour récupérer votre prix gratuit !",
        sender_id="spam@lottery.com"
    )


# ============================================================================
# TESTS ENUMS
# ============================================================================

class TestEnums:
    """Tests pour les énumérations."""

    def test_message_channel_values(self):
        """Test des valeurs de MessageChannel."""
        assert MessageChannel.EMAIL.value == "email"
        assert MessageChannel.DISCORD.value == "discord"
        assert MessageChannel.TELEGRAM.value == "telegram"
        assert MessageChannel.SLACK.value == "slack"

    def test_routing_status_values(self):
        """Test des valeurs de RoutingStatus."""
        assert RoutingStatus.PENDING.value == "pending"
        assert RoutingStatus.DISPATCHED.value == "dispatched"
        assert RoutingStatus.VALIDATED.value == "validated"
        assert RoutingStatus.REJECTED.value == "rejected"

    def test_message_priority_values(self):
        """Test des valeurs de MessagePriority."""
        assert MessagePriority.CRITICAL.value == "critical"
        assert MessagePriority.HIGH.value == "high"
        assert MessagePriority.NORMAL.value == "normal"
        assert MessagePriority.LOW.value == "low"

    def test_message_category_values(self):
        """Test des valeurs de MessageCategory."""
        assert MessageCategory.SUPPORT_TECHNICAL.value == "support_technical"
        assert MessageCategory.LEGAL.value == "legal"
        assert MessageCategory.HR.value == "hr"
        assert MessageCategory.SPAM.value == "spam"


# ============================================================================
# TESTS DATA CLASSES
# ============================================================================

class TestIncomingMessage:
    """Tests pour IncomingMessage."""

    def test_create_email_message(self):
        """Test création d'un message email."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Test content",
            sender_id="test@test.com",
            subject="Test Subject"
        )
        assert msg.channel == MessageChannel.EMAIL
        assert msg.content == "Test content"
        assert msg.subject == "Test Subject"

    def test_create_discord_message(self):
        """Test création d'un message Discord."""
        msg = IncomingMessage(
            channel=MessageChannel.DISCORD,
            content="Discord message",
            sender_id="user123",
            guild_id="guild456",
            channel_name="general"
        )
        assert msg.channel == MessageChannel.DISCORD
        assert msg.guild_id == "guild456"
        assert msg.channel_name == "general"

    def test_to_dict(self, email_message):
        """Test conversion en dict."""
        data = email_message.to_dict()
        assert data["channel"] == "email"
        assert data["content"] == email_message.content
        assert data["sender_id"] == "user@example.com"

    def test_from_dict(self):
        """Test création depuis dict."""
        data = {
            "channel": "telegram",
            "content": "Telegram message",
            "sender_id": "tg_user"
        }
        msg = IncomingMessage.from_dict(data)
        assert msg.channel == MessageChannel.TELEGRAM
        assert msg.content == "Telegram message"

    def test_default_timestamp(self):
        """Test que le timestamp est généré automatiquement."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Test",
            sender_id="test"
        )
        assert msg.timestamp is not None
        # Vérifier que c'est une date ISO
        datetime.fromisoformat(msg.timestamp)

    def test_metadata_default(self):
        """Test que metadata est un dict vide par défaut."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Test",
            sender_id="test"
        )
        assert msg.metadata == {}

    def test_attachments_default(self):
        """Test que attachments est une liste vide par défaut."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Test",
            sender_id="test"
        )
        assert msg.attachments == []


class TestRoutingDecision:
    """Tests pour RoutingDecision."""

    def test_create_routing_decision(self):
        """Test création d'une décision de routage."""
        decision = RoutingDecision(
            target_agent_id="tech_support",
            target_agent_name="Expert Support Technique",
            category=MessageCategory.SUPPORT_TECHNICAL,
            priority=MessagePriority.HIGH,
            confidence=0.85,
            reasoning="Keywords techniques détectés"
        )
        assert decision.target_agent_id == "tech_support"
        assert decision.confidence == 0.85

    def test_to_dict(self):
        """Test conversion en dict."""
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.GENERAL,
            priority=MessagePriority.NORMAL,
            confidence=0.7,
            reasoning="Default"
        )
        data = decision.to_dict()
        assert data["category"] == "general"
        assert data["priority"] == "normal"


class TestSupervisionResult:
    """Tests pour SupervisionResult."""

    def test_approved_result(self):
        """Test résultat approuvé."""
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.GENERAL,
            priority=MessagePriority.NORMAL,
            confidence=0.8,
            reasoning="OK"
        )
        result = SupervisionResult(
            approved=True,
            original_decision=decision,
            feedback="Routing approuvé",
            confidence=0.9
        )
        assert result.approved is True
        assert result.corrected_agent_id is None

    def test_rejected_result_with_correction(self):
        """Test résultat rejeté avec correction."""
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.LEGAL,
            priority=MessagePriority.NORMAL,
            confidence=0.5,
            reasoning="Pas optimal"
        )
        result = SupervisionResult(
            approved=False,
            original_decision=decision,
            corrected_agent_id="legal_advisor",
            corrected_agent_name="Conseiller Juridique",
            feedback="Agent juridique plus approprié",
            issues_found=["Mauvais agent pour question juridique"]
        )
        assert result.approved is False
        assert result.corrected_agent_id == "legal_advisor"
        assert len(result.issues_found) == 1


# ============================================================================
# TESTS DISPATCHER AGENT
# ============================================================================

class TestDispatcherAgent:
    """Tests pour DispatcherAgent."""

    def test_dispatcher_creation(self, dispatcher):
        """Test création du dispatcher."""
        assert dispatcher is not None
        assert dispatcher.llm_provider is None

    def test_dispatch_technical_message(self, dispatcher, email_message):
        """Test dispatch d'un message technique."""
        decision = dispatcher.dispatch(email_message)

        assert decision is not None
        assert decision.target_agent_id in ["tech_support", "drafter"]
        assert decision.category in [MessageCategory.SUPPORT_TECHNICAL, MessageCategory.GENERAL]
        assert decision.confidence > 0

    def test_dispatch_legal_message(self, dispatcher, legal_message):
        """Test dispatch d'un message juridique."""
        decision = dispatcher.dispatch(legal_message)

        assert decision is not None
        assert decision.category == MessageCategory.LEGAL
        assert decision.target_agent_id == "legal_advisor"

    def test_dispatch_spam_message(self, dispatcher, spam_message):
        """Test dispatch d'un message spam."""
        decision = dispatcher.dispatch(spam_message)

        assert decision is not None
        assert decision.category == MessageCategory.SPAM

    def test_dispatch_discord_priority_boost(self, dispatcher, discord_message):
        """Test que Discord boost la priorité."""
        decision = dispatcher.dispatch(discord_message)

        # Discord devrait booster la priorité
        assert decision.priority in [MessagePriority.HIGH, MessagePriority.CRITICAL]

    def test_dispatch_critical_keywords(self, dispatcher):
        """Test détection de mots-clés critiques."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="URGENT ! Le système de production est down !",
            sender_id="admin@company.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.priority == MessagePriority.CRITICAL
        assert "urgent" in [k.lower() for k in decision.keywords_detected] or \
               "down" in [k.lower() for k in decision.keywords_detected]

    def test_dispatch_low_priority_keywords(self, dispatcher):
        """Test détection de mots-clés basse priorité."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Quand vous pouvez, j'aurais une petite suggestion.",
            sender_id="user@test.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.priority == MessagePriority.LOW

    def test_dispatch_hr_message(self, dispatcher):
        """Test dispatch d'un message RH."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="J'ai une question sur mes congés et ma paie.",
            sender_id="employee@company.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.category == MessageCategory.HR
        assert decision.target_agent_id == "hr_specialist"

    def test_dispatch_financial_message(self, dispatcher):
        """Test dispatch d'un message financier."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Pouvez-vous m'envoyer la facture et le devis ?",
            sender_id="client@test.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.category == MessageCategory.FINANCIAL
        assert decision.target_agent_id == "financial_advisor"

    def test_dispatch_medical_message(self, dispatcher):
        """Test dispatch d'un message médical."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="J'ai des symptômes, dois-je consulter un médecin ?",
            sender_id="patient@test.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.category == MessageCategory.MEDICAL
        assert decision.target_agent_id == "medical_info"

    def test_dispatch_complaint_message(self, dispatcher):
        """Test dispatch d'un message de plainte."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Je suis très mécontent ! C'est inacceptable ! Je veux un remboursement !",
            sender_id="angry@customer.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision.category == MessageCategory.COMPLAINT
        assert decision.requires_human_review is True

    def test_dispatch_generates_reasoning(self, dispatcher, email_message):
        """Test que le reasoning est généré."""
        decision = dispatcher.dispatch(email_message)

        assert decision.reasoning is not None
        assert len(decision.reasoning) > 0

    def test_dispatch_confidence_range(self, dispatcher, email_message):
        """Test que la confiance est dans la plage 0-1."""
        decision = dispatcher.dispatch(email_message)

        assert 0.0 <= decision.confidence <= 1.0

    def test_dispatch_empty_content(self, dispatcher):
        """Test dispatch avec contenu vide."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="",
            sender_id="test@test.com"
        )
        decision = dispatcher.dispatch(msg)

        # Devrait toujours retourner une décision
        assert decision is not None
        assert decision.confidence < 0.5  # Confiance basse

    def test_dispatch_very_long_content(self, dispatcher):
        """Test dispatch avec contenu très long."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="problème technique " * 500,
            sender_id="test@test.com"
        )
        decision = dispatcher.dispatch(msg)

        assert decision is not None
        assert decision.estimated_complexity == "high"


# ============================================================================
# TESTS SUPERVISOR AGENT
# ============================================================================

class TestSupervisorAgent:
    """Tests pour SupervisorAgent."""

    def test_supervisor_creation(self, supervisor):
        """Test création du supervisor."""
        assert supervisor is not None

    def test_supervise_valid_routing(self, supervisor, email_message):
        """Test supervision d'un routing valide."""
        decision = RoutingDecision(
            target_agent_id="tech_support",
            target_agent_name="Expert Support Technique",
            category=MessageCategory.SUPPORT_TECHNICAL,
            priority=MessagePriority.NORMAL,
            confidence=0.8,
            reasoning="Keywords techniques"
        )

        result = supervisor.supervise(email_message, decision)

        assert result.approved is True
        assert result.corrected_agent_id is None
        assert len(result.issues_found) == 0

    def test_supervise_incoherent_routing(self, supervisor, legal_message):
        """Test supervision d'un routing incohérent."""
        # Message juridique routé vers tech_support
        decision = RoutingDecision(
            target_agent_id="tech_support",
            target_agent_name="Expert Support Technique",
            category=MessageCategory.LEGAL,  # Catégorie juridique
            priority=MessagePriority.NORMAL,
            confidence=0.6,
            reasoning="Erreur"
        )

        result = supervisor.supervise(legal_message, decision)

        assert result.approved is False
        assert result.corrected_agent_id == "legal_advisor"
        assert len(result.issues_found) > 0

    def test_supervise_nonexistent_agent(self, supervisor, email_message):
        """Test supervision vers un agent inexistant."""
        decision = RoutingDecision(
            target_agent_id="nonexistent_agent",
            target_agent_name="Agent Inexistant",
            category=MessageCategory.GENERAL,
            priority=MessagePriority.NORMAL,
            confidence=0.7,
            reasoning="Test"
        )

        result = supervisor.supervise(email_message, decision)

        assert result.approved is False
        assert result.corrected_agent_id == "drafter"
        assert any("non trouvé" in issue or "désactivé" in issue for issue in result.issues_found)

    def test_supervise_low_confidence(self, supervisor, email_message):
        """Test supervision avec confiance trop basse."""
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.GENERAL,
            priority=MessagePriority.NORMAL,
            confidence=0.1,  # Très basse
            reasoning="Pas sûr"
        )

        result = supervisor.supervise(email_message, decision)

        assert any("Confiance" in issue for issue in result.issues_found)

    def test_supervise_spam_message(self, supervisor, spam_message):
        """Test supervision d'un spam vers un agent spécialisé."""
        decision = RoutingDecision(
            target_agent_id="tech_support",
            target_agent_name="Expert Support Technique",
            category=MessageCategory.SPAM,
            priority=MessagePriority.NORMAL,
            confidence=0.5,
            reasoning="Spam"
        )

        result = supervisor.supervise(spam_message, decision)

        assert any("spam" in issue.lower() for issue in result.issues_found)

    def test_supervise_critical_with_generic_agent(self, supervisor):
        """Test supervision d'un message critique routé vers drafter."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Question juridique urgente",
            sender_id="test@test.com"
        )
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.LEGAL,  # Juridique
            priority=MessagePriority.CRITICAL,  # Critique
            confidence=0.5,
            reasoning="Default"
        )

        result = supervisor.supervise(msg, decision)

        assert any("critique" in issue.lower() or "généraliste" in issue.lower()
                   for issue in result.issues_found)

    def test_supervise_confidence_calculation(self, supervisor, email_message):
        """Test calcul de confiance du supervisor."""
        decision = RoutingDecision(
            target_agent_id="drafter",
            target_agent_name="Drafter",
            category=MessageCategory.GENERAL,
            priority=MessagePriority.NORMAL,
            confidence=0.8,
            reasoning="OK"
        )

        result = supervisor.supervise(email_message, decision)

        assert 0.0 <= result.confidence <= 1.0


# ============================================================================
# TESTS MESSAGE ROUTER
# ============================================================================

class TestMessageRouter:
    """Tests pour MessageRouter."""

    def test_router_creation(self, router):
        """Test création du router."""
        assert router is not None
        assert router.dispatcher is not None
        assert router.supervisor is not None

    def test_route_email_message(self, router, email_message):
        """Test routage d'un email."""
        context = router.route(email_message)

        assert context is not None
        assert context.message == email_message
        assert context.routing_decision is not None
        assert context.supervision_result is not None
        assert context.status in [RoutingStatus.VALIDATED, RoutingStatus.REJECTED]

    def test_route_discord_message(self, router, discord_message):
        """Test routage d'un message Discord."""
        context = router.route(discord_message)

        assert context is not None
        assert context.message.channel == MessageChannel.DISCORD

    def test_route_processing_time(self, router, email_message):
        """Test que le temps de traitement est enregistré."""
        context = router.route(email_message)

        assert context.processing_time_ms > 0

    def test_route_updates_timestamp(self, router, email_message):
        """Test que le timestamp est mis à jour."""
        context = router.route(email_message)

        assert context.updated_at is not None
        # updated_at devrait être >= created_at
        assert context.updated_at >= context.created_at

    def test_get_final_agent_id_validated(self, router, email_message):
        """Test récupération de l'agent final - validé."""
        context = router.route(email_message)

        agent_id = router.get_final_agent_id(context)

        assert agent_id is not None
        assert isinstance(agent_id, str)

    def test_get_final_agent_id_corrected(self, router):
        """Test récupération de l'agent final - corrigé."""
        # Message juridique qui pourrait être mal routé
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="Question légale sur mon contrat",
            sender_id="test@test.com"
        )
        context = router.route(msg)

        agent_id = router.get_final_agent_id(context)

        # Devrait retourner un agent (original ou corrigé)
        assert agent_id is not None

    def test_routing_history(self, router, email_message):
        """Test que l'historique est enregistré."""
        initial_count = len(router._routing_history)

        router.route(email_message)
        router.route(email_message)

        assert len(router._routing_history) == initial_count + 2

    def test_get_routing_stats_empty(self):
        """Test stats avec historique vide."""
        router = MessageRouter()
        router.clear_history()

        stats = router.get_routing_stats()

        assert stats["total_routed"] == 0
        assert stats["avg_processing_time_ms"] == 0

    def test_get_routing_stats_with_data(self, router, email_message, discord_message):
        """Test stats avec données."""
        router.clear_history()
        router.route(email_message)
        router.route(discord_message)

        stats = router.get_routing_stats()

        assert stats["total_routed"] == 2
        assert "email" in stats["by_channel"]
        assert "discord" in stats["by_channel"]
        assert stats["avg_processing_time_ms"] > 0

    def test_clear_history(self, router, email_message):
        """Test effacement de l'historique."""
        router.route(email_message)
        assert len(router._routing_history) > 0

        router.clear_history()

        assert len(router._routing_history) == 0

    def test_route_multiple_channels(self, router):
        """Test routage depuis plusieurs canaux."""
        channels = [
            MessageChannel.EMAIL,
            MessageChannel.DISCORD,
            MessageChannel.TELEGRAM,
            MessageChannel.SLACK,
        ]

        for channel in channels:
            msg = IncomingMessage(
                channel=channel,
                content="Test message",
                sender_id="test"
            )
            context = router.route(msg)
            assert context is not None
            assert context.message.channel == channel


# ============================================================================
# TESTS FACTORY FUNCTIONS
# ============================================================================

class TestFactoryFunctions:
    """Tests pour les fonctions factory."""

    def test_get_message_router_singleton(self):
        """Test que get_message_router retourne un singleton."""
        router1 = get_message_router()
        router2 = get_message_router()

        assert router1 is router2

    def test_create_incoming_message(self):
        """Test création de message via helper."""
        msg = create_incoming_message(
            content="Test content",
            channel="email",
            sender_id="test@test.com",
            subject="Test Subject"
        )

        assert msg.channel == MessageChannel.EMAIL
        assert msg.content == "Test content"
        assert msg.subject == "Test Subject"

    def test_create_incoming_message_discord(self):
        """Test création de message Discord via helper."""
        msg = create_incoming_message(
            content="Discord message",
            channel="discord",
            sender_id="user123",
            guild_id="guild456"
        )

        assert msg.channel == MessageChannel.DISCORD
        assert msg.guild_id == "guild456"


# ============================================================================
# TESTS INTEGRATION
# ============================================================================

class TestIntegration:
    """Tests d'intégration."""

    def test_full_routing_flow_email(self, router):
        """Test flow complet pour un email."""
        msg = IncomingMessage(
            channel=MessageChannel.EMAIL,
            content="J'ai un bug critique en production, c'est urgent !",
            sender_id="admin@company.com",
            subject="URGENT - Bug production"
        )

        # Route le message
        context = router.route(msg)

        # Vérifie le flow complet
        assert context.status in [RoutingStatus.VALIDATED, RoutingStatus.REJECTED]
        assert context.routing_decision.priority in [MessagePriority.CRITICAL, MessagePriority.HIGH]
        assert context.routing_decision.category == MessageCategory.SUPPORT_TECHNICAL

        # Vérifie l'agent final
        agent_id = router.get_final_agent_id(context)
        assert agent_id in ["tech_support", "drafter"]

    def test_full_routing_flow_discord_legal(self, router):
        """Test flow complet pour Discord + juridique."""
        msg = IncomingMessage(
            channel=MessageChannel.DISCORD,
            content="Question urgente sur mon contrat de travail et mes droits",
            sender_id="discord_user",
            guild_id="support_guild"
        )

        context = router.route(msg)

        # Discord boost la priorité
        assert context.routing_decision.priority in [MessagePriority.HIGH, MessagePriority.CRITICAL]

        # Devrait être catégorisé juridique ou HR
        assert context.routing_decision.category in [MessageCategory.LEGAL, MessageCategory.HR]

    def test_routing_context_serialization(self, router, email_message):
        """Test sérialisation du contexte."""
        context = router.route(email_message)

        data = context.to_dict()

        assert "message" in data
        assert "routing_decision" in data
        assert "supervision_result" in data
        assert "status" in data
        assert isinstance(data["status"], str)

    def test_multi_message_stats(self, router):
        """Test stats après plusieurs messages."""
        router.clear_history()

        messages = [
            create_incoming_message("Bug technique", "email", "user1@test.com"),
            create_incoming_message("Question contrat", "email", "user2@test.com"),
            create_incoming_message("Aide Discord", "discord", "discord_user"),
            create_incoming_message("Spam lottery", "email", "spam@spam.com"),
        ]

        for msg in messages:
            router.route(msg)

        stats = router.get_routing_stats()

        assert stats["total_routed"] == 4
        assert stats["by_channel"]["email"] == 3
        assert stats["by_channel"]["discord"] == 1

    def test_edge_case_unicode_content(self, router):
        """Test avec contenu Unicode."""
        msg = create_incoming_message(
            content="问题：我需要帮助 🆘 émojis et accénts",
            channel="telegram",
            sender_id="unicode_user"
        )

        context = router.route(msg)

        assert context is not None
        assert context.status != RoutingStatus.FAILED

    def test_edge_case_very_short_message(self, router):
        """Test avec message très court."""
        msg = create_incoming_message(
            content="?",
            channel="email",
            sender_id="test"
        )

        context = router.route(msg)

        assert context is not None
        # Confiance devrait être basse
        assert context.routing_decision.confidence < 0.5


# ============================================================================
# TESTS SPECIALIZED AGENTS INTEGRATION
# ============================================================================

class TestSpecializedAgentsIntegration:
    """Tests d'intégration avec les agents spécialisés."""

    def test_dispatcher_in_registry(self):
        """Test que Dispatcher est dans le registre."""
        from app.specialized_agents import get_agent_registry

        registry = get_agent_registry()
        assert "dispatcher" in registry.agents

    def test_supervisor_in_registry(self):
        """Test que Supervisor est dans le registre."""
        from app.specialized_agents import get_agent_registry

        registry = get_agent_registry()
        assert "supervisor" in registry.agents

    def test_dispatcher_agent_config(self):
        """Test configuration de l'agent Dispatcher."""
        from app.specialized_agents import get_agent_registry, AgentDomain

        registry = get_agent_registry()
        dispatcher = registry.agents["dispatcher"]

        assert dispatcher.domain == AgentDomain.CORE.value
        assert len(dispatcher.capabilities) > 0
        assert "Dispatcher" in dispatcher.system_prompt

    def test_supervisor_agent_config(self):
        """Test configuration de l'agent Supervisor."""
        from app.specialized_agents import get_agent_registry, AgentDomain

        registry = get_agent_registry()
        supervisor = registry.agents["supervisor"]

        assert supervisor.domain == AgentDomain.CORE.value
        assert len(supervisor.capabilities) > 0
        assert "Supervisor" in supervisor.system_prompt
