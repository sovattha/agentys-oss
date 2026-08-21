# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routeur de messages multi-canal pour Agentys.

Gère le routing des messages entrants (email, Discord, Telegram, etc.)
vers les agents spécialisés appropriés.

Architecture:
    Message Entrant → Dispatcher → Agent Spécialisé → Supervisor → Critic → Réponse

Usage:
    from app.message_router import MessageRouter, IncomingMessage, MessageChannel

    router = MessageRouter()

    message = IncomingMessage(
        channel=MessageChannel.EMAIL,
        content="J'ai un problème technique...",
        sender_id="user@example.com",
        metadata={"subject": "Support"}
    )

    result = router.process(message)
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class MessageChannel(Enum):
    """Canaux de communication supportés."""
    EMAIL = "email"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    SLACK = "slack"
    TEAMS = "teams"
    WEB_CHAT = "web_chat"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    API = "api"  # Appels API directs


class RoutingStatus(Enum):
    """Statut du routing."""
    PENDING = "pending"
    DISPATCHED = "dispatched"
    VALIDATED = "validated"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class MessagePriority(Enum):
    """Priorité du message."""
    CRITICAL = "critical"  # Réponse immédiate requise
    HIGH = "high"          # Dans l'heure
    NORMAL = "normal"      # Dans la journée
    LOW = "low"            # Quand possible


class MessageCategory(Enum):
    """Catégorie de message."""
    SUPPORT_TECHNICAL = "support_technical"
    SUPPORT_GENERAL = "support_general"
    SALES = "sales"
    LEGAL = "legal"
    HR = "hr"
    FINANCIAL = "financial"
    MEDICAL = "medical"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    SPAM = "spam"
    OUT_OF_SCOPE = "out_of_scope"
    GENERAL = "general"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class IncomingMessage:
    """Message entrant depuis n'importe quel canal."""
    channel: MessageChannel
    content: str
    sender_id: str
    sender_name: Optional[str] = None
    conversation_id: Optional[str] = None
    thread_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    language: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[str] = field(default_factory=list)

    # Champs spécifiques par canal (optionnels)
    # Email
    subject: Optional[str] = None
    cc: List[str] = field(default_factory=list)

    # Discord/Slack
    guild_id: Optional[str] = None
    channel_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        data = asdict(self)
        data["channel"] = self.channel.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IncomingMessage":
        """Crée depuis un dictionnaire."""
        if isinstance(data.get("channel"), str):
            data["channel"] = MessageChannel(data["channel"])
        return cls(**data)


@dataclass
class RoutingDecision:
    """Décision de routing du Dispatcher."""
    target_agent_id: str
    target_agent_name: str
    category: MessageCategory
    priority: MessagePriority
    confidence: float  # 0.0 - 1.0
    reasoning: str
    suggested_context: Optional[str] = None
    keywords_detected: List[str] = field(default_factory=list)
    requires_human_review: bool = False
    estimated_complexity: str = "medium"  # low, medium, high

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        data = asdict(self)
        data["category"] = self.category.value
        data["priority"] = self.priority.value
        return data


@dataclass
class SupervisionResult:
    """Résultat de la supervision."""
    approved: bool
    original_decision: RoutingDecision
    corrected_agent_id: Optional[str] = None
    corrected_agent_name: Optional[str] = None
    feedback: str = ""
    confidence: float = 0.0
    issues_found: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        data = asdict(self)
        data["original_decision"] = self.original_decision.to_dict()
        return data


@dataclass
class RoutingContext:
    """Contexte complet du routing."""
    message: IncomingMessage
    routing_decision: Optional[RoutingDecision] = None
    supervision_result: Optional[SupervisionResult] = None
    status: RoutingStatus = RoutingStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "message": self.message.to_dict(),
            "routing_decision": self.routing_decision.to_dict() if self.routing_decision else None,
            "supervision_result": self.supervision_result.to_dict() if self.supervision_result else None,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processing_time_ms": self.processing_time_ms
        }


# ============================================================================
# DISPATCHER AGENT
# ============================================================================

class DispatcherAgent:
    """
    Agent qui analyse les messages entrants et décide vers quel
    agent spécialisé les router.

    Responsabilités:
    - Analyser le contenu du message
    - Détecter la langue
    - Déterminer la catégorie
    - Évaluer la priorité
    - Choisir l'agent cible
    """

    # Mapping catégorie → agent par défaut
    CATEGORY_AGENT_MAP = {
        MessageCategory.SUPPORT_TECHNICAL: "tech_support",
        MessageCategory.SUPPORT_GENERAL: "drafter",
        MessageCategory.SALES: "drafter",  # Pourrait être "sales_agent" si créé
        MessageCategory.LEGAL: "legal_advisor",
        MessageCategory.HR: "hr_specialist",
        MessageCategory.FINANCIAL: "financial_advisor",
        MessageCategory.MEDICAL: "medical_info",
        MessageCategory.COMPLAINT: "drafter",
        MessageCategory.FEEDBACK: "drafter",
        MessageCategory.SPAM: None,  # Pas de traitement
        MessageCategory.OUT_OF_SCOPE: None,
        MessageCategory.GENERAL: "drafter",
    }

    # Keywords pour la détection de catégorie
    CATEGORY_KEYWORDS = {
        MessageCategory.SUPPORT_TECHNICAL: [
            "bug", "erreur", "error", "crash", "plante", "ne fonctionne pas",
            "doesn't work", "broken", "problème technique", "technical issue",
            "installer", "install", "configuration", "setup", "connexion",
            "mot de passe", "password", "login", "authentification"
        ],
        MessageCategory.LEGAL: [
            "contrat", "contract", "juridique", "legal", "avocat", "lawyer",
            "clause", "litige", "dispute", "droit", "rights", "obligation",
            "rgpd", "gdpr", "confidentialité", "privacy", "tribunal", "court"
        ],
        MessageCategory.HR: [
            "congé", "leave", "vacances", "holiday", "salaire", "salary",
            "paie", "payroll", "embauche", "hiring", "recrutement", "recruitment",
            "contrat de travail", "employment", "licenciement", "dismissal",
            "démission", "resignation", "formation", "training"
        ],
        MessageCategory.FINANCIAL: [
            "facture", "invoice", "paiement", "payment", "remboursement", "refund",
            "prix", "price", "tarif", "rate", "devis", "quote", "budget",
            "comptabilité", "accounting", "taxe", "tax", "impôt"
        ],
        MessageCategory.MEDICAL: [
            "santé", "health", "médecin", "doctor", "maladie", "illness",
            "symptôme", "symptom", "traitement", "treatment", "médicament",
            "medication", "urgence médicale", "medical emergency"
        ],
        MessageCategory.COMPLAINT: [
            "plainte", "complaint", "mécontent", "unhappy", "insatisfait",
            "dissatisfied", "inacceptable", "unacceptable", "scandaleux",
            "outrageous", "rembourser", "refund", "réclamation", "claim"
        ],
        MessageCategory.SPAM: [
            "gagné", "won", "lottery", "loterie", "gratuit", "free",
            "click here", "cliquez ici", "urgent action", "action urgente",
            "bitcoin", "crypto", "investment opportunity"
        ],
    }

    # Keywords de priorité
    PRIORITY_KEYWORDS = {
        MessagePriority.CRITICAL: [
            "urgent", "urgente", "immédiat", "immediate", "critique", "critical",
            "asap", "dès que possible", "bloquant", "blocking", "down", "en panne",
            "production", "p0", "p1", "emergency", "urgence"
        ],
        MessagePriority.HIGH: [
            "important", "prioritaire", "priority", "rapidement", "quickly",
            "bientôt", "soon", "aujourd'hui", "today", "ce jour"
        ],
        MessagePriority.LOW: [
            "quand vous pouvez", "when you can", "pas pressé", "no rush",
            "à l'occasion", "eventually", "suggestion", "idée", "idea"
        ],
    }

    def __init__(self, llm_provider: Optional[Any] = None):
        """
        Initialise le Dispatcher.

        Args:
            llm_provider: Provider LLM optionnel pour analyse avancée
        """
        self.llm_provider = llm_provider
        self._agent_registry = None

    @property
    def agent_registry(self):
        """Lazy loading du registre d'agents."""
        if self._agent_registry is None:
            from app.specialized_agents import get_agent_registry
            self._agent_registry = get_agent_registry()
        return self._agent_registry

    def dispatch(self, message: IncomingMessage) -> RoutingDecision:
        """
        Analyse un message et décide vers quel agent le router.

        Args:
            message: Le message entrant à analyser

        Returns:
            RoutingDecision avec l'agent cible et les détails
        """
        content_lower = message.content.lower()

        # Détecter la catégorie
        category, category_keywords = self._detect_category(content_lower)

        # Détecter la priorité
        priority, priority_keywords = self._detect_priority(content_lower)

        # Ajuster priorité selon le canal
        priority = self._adjust_priority_by_channel(priority, message.channel)

        # Déterminer l'agent cible
        target_agent_id = self._get_target_agent(category, content_lower)
        target_agent_name = self._get_agent_name(target_agent_id)

        # Calculer la confiance
        confidence = self._calculate_confidence(
            category_keywords, priority_keywords, content_lower
        )

        # Générer le raisonnement
        reasoning = self._generate_reasoning(
            category, priority, target_agent_id,
            category_keywords, message.channel
        )

        # Déterminer si review humaine nécessaire
        requires_review = (
            confidence < 0.5 or
            category == MessageCategory.COMPLAINT or
            priority == MessagePriority.CRITICAL
        )

        # Estimer la complexité
        complexity = self._estimate_complexity(message, category)

        return RoutingDecision(
            target_agent_id=target_agent_id or "drafter",
            target_agent_name=target_agent_name or "Drafter",
            category=category,
            priority=priority,
            confidence=confidence,
            reasoning=reasoning,
            keywords_detected=category_keywords + priority_keywords,
            requires_human_review=requires_review,
            estimated_complexity=complexity
        )

    def _detect_category(self, content: str) -> Tuple[MessageCategory, List[str]]:
        """Détecte la catégorie du message."""
        best_category = MessageCategory.GENERAL
        best_score = 0
        detected_keywords = []

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = 0
            found_keywords = []
            for keyword in keywords:
                if keyword in content:
                    score += 1
                    found_keywords.append(keyword)

            if score > best_score:
                best_score = score
                best_category = category
                detected_keywords = found_keywords

        return best_category, detected_keywords

    def _detect_priority(self, content: str) -> Tuple[MessagePriority, List[str]]:
        """Détecte la priorité du message."""
        detected_keywords = []

        for priority, keywords in self.PRIORITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content:
                    detected_keywords.append(keyword)
                    return priority, detected_keywords

        return MessagePriority.NORMAL, []

    def _adjust_priority_by_channel(
        self,
        priority: MessagePriority,
        channel: MessageChannel
    ) -> MessagePriority:
        """Ajuste la priorité selon le canal."""
        # Les messages Discord/Telegram sont souvent plus urgents
        if channel in [MessageChannel.DISCORD, MessageChannel.TELEGRAM, MessageChannel.SMS]:
            if priority == MessagePriority.NORMAL:
                return MessagePriority.HIGH

        return priority

    def _get_target_agent(
        self,
        category: MessageCategory,
        content: str
    ) -> Optional[str]:
        """Détermine l'agent cible."""
        # D'abord vérifier le mapping par catégorie
        agent_id = self.CATEGORY_AGENT_MAP.get(category)

        if agent_id:
            # Vérifier que l'agent existe et est activé
            agent = self.agent_registry.get_agent(agent_id)
            if agent:
                return agent_id

        # Sinon, utiliser find_best_agent du registre
        best_agent = self.agent_registry.find_best_agent(content, min_score=0.2)
        if best_agent:
            return best_agent.config.id

        # Par défaut, Drafter
        return "drafter"

    def _get_agent_name(self, agent_id: Optional[str]) -> str:
        """Récupère le nom de l'agent."""
        if not agent_id:
            return "Drafter"

        config = self.agent_registry.agents.get(agent_id)
        return config.name if config else agent_id.replace("_", " ").title()

    def _calculate_confidence(
        self,
        category_keywords: List[str],
        priority_keywords: List[str],
        content: str
    ) -> float:
        """Calcule le score de confiance."""
        # Base confidence
        confidence = 0.5

        # Bonus pour keywords détectés
        if category_keywords:
            confidence += min(0.3, len(category_keywords) * 0.1)

        if priority_keywords:
            confidence += 0.1

        # Malus pour messages très courts ou très longs
        word_count = len(content.split())
        if word_count < 5:
            confidence -= 0.2
        elif word_count > 500:
            confidence -= 0.1

        return max(0.1, min(1.0, confidence))

    def _generate_reasoning(
        self,
        category: MessageCategory,
        priority: MessagePriority,
        target_agent: Optional[str],
        keywords: List[str],
        channel: MessageChannel
    ) -> str:
        """Génère l'explication du routing."""
        parts = []

        parts.append(f"Canal: {channel.value}")
        parts.append(f"Catégorie détectée: {category.value}")
        parts.append(f"Priorité: {priority.value}")

        if keywords:
            parts.append(f"Mots-clés: {', '.join(keywords[:5])}")

        parts.append(f"Agent assigné: {target_agent or 'drafter'}")

        return " | ".join(parts)

    def _estimate_complexity(
        self,
        message: IncomingMessage,
        category: MessageCategory
    ) -> str:
        """Estime la complexité du message."""
        word_count = len(message.content.split())

        # Catégories complexes
        complex_categories = [
            MessageCategory.LEGAL,
            MessageCategory.FINANCIAL,
            MessageCategory.MEDICAL
        ]

        if category in complex_categories:
            return "high"

        if word_count > 200 or message.attachments:
            return "high"
        elif word_count > 50:
            return "medium"
        else:
            return "low"


# ============================================================================
# SUPERVISOR AGENT
# ============================================================================

class SupervisorAgent:
    """
    Agent qui valide les décisions de routing du Dispatcher.

    Responsabilités:
    - Vérifier que le bon agent a été choisi
    - Détecter les erreurs de routing
    - Suggérer des corrections si nécessaire
    """

    def __init__(self, llm_provider: Optional[Any] = None):
        """
        Initialise le Supervisor.

        Args:
            llm_provider: Provider LLM optionnel pour validation avancée
        """
        self.llm_provider = llm_provider
        self._agent_registry = None

    @property
    def agent_registry(self):
        """Lazy loading du registre d'agents."""
        if self._agent_registry is None:
            from app.specialized_agents import get_agent_registry
            self._agent_registry = get_agent_registry()
        return self._agent_registry

    def supervise(
        self,
        message: IncomingMessage,
        decision: RoutingDecision
    ) -> SupervisionResult:
        """
        Valide une décision de routing.

        Args:
            message: Le message original
            decision: La décision du Dispatcher

        Returns:
            SupervisionResult avec l'approbation ou correction
        """
        issues = []
        corrected_agent = None

        # Vérification 1: L'agent existe-t-il ?
        agent = self.agent_registry.get_agent(decision.target_agent_id)
        if not agent:
            issues.append(f"Agent '{decision.target_agent_id}' non trouvé ou désactivé")
            corrected_agent = "drafter"

        # Vérification 2: Cohérence catégorie/agent
        if not issues:
            coherence_issue = self._check_label_agent_coherence(
                decision.category, decision.target_agent_id
            )
            if coherence_issue:
                issues.append(coherence_issue)
                corrected_agent = self._suggest_better_agent(decision.category)

        # Vérification 3: Spam/Out of scope devrait être bloqué
        if decision.category in [MessageCategory.SPAM, MessageCategory.OUT_OF_SCOPE]:
            if decision.target_agent_id not in [None, "drafter"]:
                issues.append("Messages spam/hors-scope ne devraient pas être traités")

        # Vérification 4: Confiance trop basse
        if decision.confidence < 0.3:
            issues.append(f"Confiance trop basse ({decision.confidence:.0%})")

        # Vérification 5: Messages critiques avec agent généraliste
        if (decision.priority == MessagePriority.CRITICAL and
            decision.target_agent_id == "drafter" and
            decision.category != MessageCategory.GENERAL):
            issues.append("Message critique routé vers agent généraliste")
            corrected_agent = self._suggest_better_agent(decision.category)

        # Calculer la confiance du supervisor
        supervisor_confidence = self._calculate_supervisor_confidence(
            decision, issues
        )

        # Décision finale
        approved = len(issues) == 0

        return SupervisionResult(
            approved=approved,
            original_decision=decision,
            corrected_agent_id=corrected_agent if not approved else None,
            corrected_agent_name=self._get_agent_name(corrected_agent) if corrected_agent else None,
            feedback="; ".join(issues) if issues else "Routing approuvé",
            confidence=supervisor_confidence,
            issues_found=issues
        )

    def _check_label_agent_coherence(
        self,
        category: MessageCategory,
        agent_id: str
    ) -> Optional[str]:
        """Vérifie la cohérence entre catégorie et agent."""
        # Mapping des catégories vers les agents attendus
        expected_agents = {
            MessageCategory.SUPPORT_TECHNICAL: ["tech_support", "drafter"],
            MessageCategory.LEGAL: ["legal_advisor", "drafter"],
            MessageCategory.HR: ["hr_specialist", "drafter"],
            MessageCategory.FINANCIAL: ["financial_advisor", "drafter"],
            MessageCategory.MEDICAL: ["medical_info", "drafter"],
        }

        expected = expected_agents.get(category)
        if expected and agent_id not in expected:
            return f"Agent '{agent_id}' non optimal pour catégorie '{category.value}'"

        return None

    def _suggest_better_agent(self, category: MessageCategory) -> str:
        """Suggère un meilleur agent pour une catégorie."""
        suggestions = {
            MessageCategory.SUPPORT_TECHNICAL: "tech_support",
            MessageCategory.LEGAL: "legal_advisor",
            MessageCategory.HR: "hr_specialist",
            MessageCategory.FINANCIAL: "financial_advisor",
            MessageCategory.MEDICAL: "medical_info",
        }

        return suggestions.get(category, "drafter")

    def _get_agent_name(self, agent_id: Optional[str]) -> Optional[str]:
        """Récupère le nom de l'agent."""
        if not agent_id:
            return None

        config = self.agent_registry.agents.get(agent_id)
        return config.name if config else None

    def _calculate_supervisor_confidence(
        self,
        decision: RoutingDecision,
        issues: List[str]
    ) -> float:
        """Calcule la confiance du supervisor."""
        base_confidence = decision.confidence

        # Réduire selon le nombre d'issues
        penalty = len(issues) * 0.15

        return max(0.1, min(1.0, base_confidence - penalty))


# ============================================================================
# MESSAGE ROUTER (ORCHESTRATEUR)
# ============================================================================

class MessageRouter:
    """
    Orchestrateur principal du routing de messages.

    Coordonne le Dispatcher et le Supervisor pour router les messages
    vers les agents appropriés.
    """

    def __init__(
        self,
        dispatcher: Optional[DispatcherAgent] = None,
        supervisor: Optional[SupervisorAgent] = None,
        llm_provider: Optional[Any] = None
    ):
        """
        Initialise le router.

        Args:
            dispatcher: Agent Dispatcher (créé si non fourni)
            supervisor: Agent Supervisor (créé si non fourni)
            llm_provider: Provider LLM partagé
        """
        self.dispatcher = dispatcher or DispatcherAgent(llm_provider)
        self.supervisor = supervisor or SupervisorAgent(llm_provider)
        self.llm_provider = llm_provider
        self._routing_history: List[RoutingContext] = []

    def route(self, message: IncomingMessage) -> RoutingContext:
        """
        Route un message entrant.

        Args:
            message: Le message à router

        Returns:
            RoutingContext avec toutes les informations de routing
        """
        import time
        start_time = time.time()

        context = RoutingContext(message=message)

        try:
            # Étape 1: Dispatch
            routing_decision = self.dispatcher.dispatch(message)
            context.routing_decision = routing_decision
            context.status = RoutingStatus.DISPATCHED

            # Étape 2: Supervision
            supervision_result = self.supervisor.supervise(message, routing_decision)
            context.supervision_result = supervision_result

            # Étape 3: Déterminer le statut final
            if supervision_result.approved:
                context.status = RoutingStatus.VALIDATED
            else:
                context.status = RoutingStatus.REJECTED
                # Utiliser l'agent corrigé si disponible
                if supervision_result.corrected_agent_id:
                    logger.info(
                        f"Routing corrigé: {routing_decision.target_agent_id} → "
                        f"{supervision_result.corrected_agent_id}"
                    )

        except Exception as e:
            logger.exception(f"Erreur de routing: {e}")
            context.status = RoutingStatus.FAILED

        # Mettre à jour le timing
        context.processing_time_ms = (time.time() - start_time) * 1000
        context.updated_at = datetime.now().isoformat()

        # Sauvegarder dans l'historique
        self._routing_history.append(context)

        return context

    def get_final_agent_id(self, context: RoutingContext) -> Optional[str]:
        """
        Retourne l'ID de l'agent final à utiliser.

        Args:
            context: Le contexte de routing

        Returns:
            L'ID de l'agent à utiliser, ou None si non routable
        """
        if context.status == RoutingStatus.FAILED:
            return None

        # Si le Supervisor a corrigé le routing
        if (context.supervision_result and
            context.supervision_result.corrected_agent_id):
            return context.supervision_result.corrected_agent_id

        # Sinon utiliser la décision originale
        if context.routing_decision:
            return context.routing_decision.target_agent_id

        return "drafter"  # Fallback

    def get_routing_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de routing."""
        if not self._routing_history:
            return {
                "total_routed": 0,
                "by_status": {},
                "by_category": {},
                "by_channel": {},
                "by_agent": {},
                "avg_processing_time_ms": 0,
                "correction_rate": 0.0
            }

        total = len(self._routing_history)

        # Compter par statut
        by_status = {}
        for ctx in self._routing_history:
            status = ctx.status.value
            by_status[status] = by_status.get(status, 0) + 1

        # Compter par catégorie
        by_category = {}
        for ctx in self._routing_history:
            if ctx.routing_decision:
                cat = ctx.routing_decision.category.value
                by_category[cat] = by_category.get(cat, 0) + 1

        # Compter par canal
        by_channel = {}
        for ctx in self._routing_history:
            channel = ctx.message.channel.value
            by_channel[channel] = by_channel.get(channel, 0) + 1

        # Compter par agent final
        by_agent = {}
        for ctx in self._routing_history:
            agent = self.get_final_agent_id(ctx) or "unknown"
            by_agent[agent] = by_agent.get(agent, 0) + 1

        # Temps de traitement moyen
        avg_time = sum(
            ctx.processing_time_ms for ctx in self._routing_history
        ) / total

        # Taux de correction
        corrections = sum(
            1 for ctx in self._routing_history
            if ctx.supervision_result and ctx.supervision_result.corrected_agent_id
        )
        correction_rate = corrections / total if total > 0 else 0

        return {
            "total_routed": total,
            "by_status": by_status,
            "by_category": by_category,
            "by_channel": by_channel,
            "by_agent": by_agent,
            "avg_processing_time_ms": round(avg_time, 2),
            "correction_rate": round(correction_rate, 3)
        }

    def clear_history(self) -> None:
        """Efface l'historique de routing."""
        self._routing_history.clear()


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

_message_router: Optional[MessageRouter] = None


def get_message_router() -> MessageRouter:
    """Retourne l'instance singleton du MessageRouter."""
    global _message_router
    if _message_router is None:
        _message_router = MessageRouter()
    return _message_router


def create_incoming_message(
    content: str,
    channel: str = "email",
    sender_id: str = "unknown",
    **kwargs
) -> IncomingMessage:
    """
    Helper pour créer un IncomingMessage.

    Args:
        content: Contenu du message
        channel: Canal (email, discord, telegram, etc.)
        sender_id: ID de l'expéditeur
        **kwargs: Autres champs optionnels

    Returns:
        IncomingMessage configuré
    """
    return IncomingMessage(
        channel=MessageChannel(channel),
        content=content,
        sender_id=sender_id,
        **kwargs
    )
