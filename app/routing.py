# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Règles de routage personnalisées.

Ce module permet de définir des règles de routage pour les emails
selon l'expéditeur, le domaine, le sujet, etc.
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from enum import Enum

from app.config import DATA_DIR
from app.infrastructure.text_io import read_text_legacy_safe

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

ROUTING_RULES_FILE = DATA_DIR / "routing_rules.json"
ROUTING_ENABLED = os.getenv("ROUTING_RULES_ENABLED", "true").lower() == "true"


# ============================================================================
# ENUMS
# ============================================================================

class RoutingAction(Enum):
    """Actions possibles pour le routage."""
    PROCESS = "process"          # Traiter normalement
    SKIP = "skip"                # Ignorer l'email
    PRIORITY_HIGH = "priority_high"  # Forcer haute priorité
    PRIORITY_LOW = "priority_low"    # Forcer basse priorité
    FORWARD = "forward"          # Transférer à une autre adresse
    ARCHIVE = "archive"          # Archiver sans traiter
    TEMPLATE = "template"        # Utiliser un template spécifique
    REVIEW = "review"            # Forcer la review manuelle
    AUTO_REPLY = "auto_reply"    # Réponse automatique
    VIP_NOTIFY = "vip_notify"    # VIP : notification immédiate


class MatchType(Enum):
    """Types de matching."""
    EXACT = "exact"              # Correspondance exacte
    CONTAINS = "contains"        # Contient la chaîne
    STARTS_WITH = "starts_with"  # Commence par
    ENDS_WITH = "ends_with"      # Se termine par
    REGEX = "regex"              # Expression régulière
    DOMAIN = "domain"            # Domaine de l'email
    ANY = "any"                  # Tous (wildcard)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class RoutingCondition:
    """Condition de routage."""
    field: str  # sender, subject, body, domain, category
    match_type: str  # MatchType value
    value: str  # Valeur à matcher
    case_sensitive: bool = False


@dataclass
class RoutingRule:
    """Règle de routage."""
    id: str
    name: str
    conditions: List[Dict[str, Any]]  # Liste de RoutingCondition as dict
    action: str  # RoutingAction value
    action_params: Optional[Dict[str, Any]] = None
    enabled: bool = True
    priority: int = 0  # Plus haut = évalué en premier
    description: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    match_count: int = 0
    last_matched: Optional[str] = None


@dataclass
class RoutingResult:
    """Résultat du routage."""
    rule: Optional[RoutingRule]
    action: RoutingAction
    action_params: Optional[Dict[str, Any]]
    matched_conditions: List[str]


# ============================================================================
# DEFAULT RULES
# ============================================================================

DEFAULT_RULES = [
    RoutingRule(
        id="skip-noreply",
        name="Ignorer noreply",
        conditions=[
            {"field": "sender", "match_type": "contains", "value": "noreply@"},
            {"field": "sender", "match_type": "contains", "value": "no-reply@"},
        ],
        action=RoutingAction.SKIP.value,
        priority=100,
        description="Ignore les emails provenant d'adresses noreply",
    ),
    RoutingRule(
        id="skip-mailer-daemon",
        name="Ignorer Mailer Daemon",
        conditions=[
            {"field": "sender", "match_type": "contains", "value": "mailer-daemon@"},
            {"field": "sender", "match_type": "contains", "value": "postmaster@"},
        ],
        action=RoutingAction.SKIP.value,
        priority=100,
        description="Ignore les emails système",
    ),
    RoutingRule(
        id="priority-ceo",
        name="Priorité CEO",
        conditions=[
            {"field": "subject", "match_type": "contains", "value": "CEO"},
            {"field": "subject", "match_type": "contains", "value": "Direction"},
        ],
        action=RoutingAction.PRIORITY_HIGH.value,
        priority=90,
        description="Haute priorité pour les emails de la direction",
    ),
    RoutingRule(
        id="priority-urgent-keywords",
        name="Mots-clés urgents (sujet)",
        conditions=[
            {"field": "subject", "match_type": "regex", "value": r"(?i)\b(urgente?s?|asap|prioritaires?|critiques?|emergency|importan(t|te?s?))\b"},
        ],
        action=RoutingAction.PRIORITY_HIGH.value,
        priority=88,
        description="Haute priorité pour les emails contenant des mots-clés urgents dans le sujet",
    ),
    RoutingRule(
        id="priority-urgent-keywords-body",
        name="Mots-clés urgents (corps)",
        conditions=[
            {"field": "body", "match_type": "regex", "value": r"(?i)\b(urgente?s?|asap|prioritaires?|critiques?|emergency|importan(t|te?s?))\b"},
        ],
        action=RoutingAction.PRIORITY_HIGH.value,
        priority=87,
        description="Haute priorité pour les emails contenant des mots-clés urgents dans le corps",
    ),
    RoutingRule(
        id="review-legal",
        name="Review Legal",
        conditions=[
            {"field": "subject", "match_type": "regex", "value": r"(?i)(contrat|legal|juridique|avocat)"},
        ],
        action=RoutingAction.REVIEW.value,
        priority=85,
        description="Force la review pour les sujets légaux",
    ),
]


# ============================================================================
# ROUTING ENGINE
# ============================================================================

class RoutingEngine:
    """
    Moteur de routage pour les emails.

    Évalue les règles de routage pour déterminer l'action à effectuer
    sur un email donné.
    """

    def __init__(self, filepath: Path = ROUTING_RULES_FILE):
        self.filepath = filepath
        self.rules: Dict[str, RoutingRule] = {}
        self._load()

    def _load(self) -> None:
        """Charge les règles depuis le fichier."""
        if not self.filepath.exists():
            self._init_defaults()
            return
        try:
            raw, recovered = read_text_legacy_safe(self.filepath)
            data = json.loads(raw)
            for rule_data in data.get("rules", []):
                rule = RoutingRule(**rule_data)
                self.rules[rule.id] = rule
            logger.debug(f"Loaded {len(self.rules)} routing rules")
        except Exception as e:
            # Vrai fichier corrompu (JSON invalide, octets non décodables) :
            # comportement historique conservé. NB : un fichier simplement
            # écrit en cp1252 par l'ancien code est récupéré par
            # read_text_legacy_safe et ne tombe PAS ici (audit 2026-05-14 F-01).
            logger.error(f"Error loading routing rules: {e}")
            self._init_defaults()
            return
        if recovered:
            # Fichier hérité cp1252 décodé via le repli : on le ré-enregistre
            # en UTF-8 pour qu'il soit propre au prochain chargement.
            logger.warning(
                f"Routing rules file was legacy cp1252, re-saved as UTF-8: {self.filepath}"
            )
            self._save()

    def _init_defaults(self) -> None:
        """Initialise avec les règles par défaut."""
        for rule in DEFAULT_RULES:
            self.rules[rule.id] = rule
        self._save()
        logger.info(f"Initialized {len(DEFAULT_RULES)} default routing rules")

    def _save(self) -> None:
        """Sauvegarde les règles."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "rules": [asdict(r) for r in self.rules.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_rule(self, rule: RoutingRule) -> None:
        """Ajoute ou met à jour une règle."""
        self.rules[rule.id] = rule
        self._save()
        logger.info(f"Routing rule saved: {rule.id}")

    def remove_rule(self, rule_id: str) -> bool:
        """Supprime une règle."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            self._save()
            logger.info(f"Routing rule removed: {rule_id}")
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[RoutingRule]:
        """Récupère une règle par ID."""
        return self.rules.get(rule_id)

    def get_all_rules(self) -> List[RoutingRule]:
        """Retourne toutes les règles triées par priorité."""
        return sorted(
            self.rules.values(),
            key=lambda r: r.priority,
            reverse=True,
        )

    def evaluate(
        self,
        sender: str,
        subject: str,
        body: str,
        category: Optional[str] = None,
        **extra_fields,
    ) -> RoutingResult:
        """
        Évalue les règles pour un email.

        Args:
            sender: Adresse de l'expéditeur.
            subject: Sujet de l'email.
            body: Corps de l'email.
            category: Catégorie de l'email (optionnel).
            **extra_fields: Champs supplémentaires.

        Returns:
            RoutingResult avec l'action à effectuer.
        """
        # Préparer les données pour le matching
        email_data = {
            "sender": sender,
            "subject": subject,
            "body": body,
            "category": category or "",
            "domain": self._extract_domain(sender),
            **extra_fields,
        }

        # Évaluer les règles par ordre de priorité
        for rule in self.get_all_rules():
            if not rule.enabled:
                continue

            matched, matched_conditions = self._evaluate_rule(rule, email_data)

            if matched:
                # Mettre à jour les stats
                rule.match_count += 1
                rule.last_matched = datetime.now().isoformat()
                self._save()

                logger.debug(f"Email matched rule: {rule.id}")

                return RoutingResult(
                    rule=rule,
                    action=RoutingAction(rule.action),
                    action_params=rule.action_params,
                    matched_conditions=matched_conditions,
                )

        # Aucune règle ne matche -> action par défaut
        return RoutingResult(
            rule=None,
            action=RoutingAction.PROCESS,
            action_params=None,
            matched_conditions=[],
        )

    def _evaluate_rule(
        self,
        rule: RoutingRule,
        email_data: Dict[str, str],
    ) -> tuple:
        """
        Évalue une règle contre les données de l'email.

        Args:
            rule: Règle à évaluer.
            email_data: Données de l'email.

        Returns:
            Tuple (matched: bool, matched_conditions: List[str])
        """
        matched_conditions = []

        # Toutes les conditions doivent matcher (AND logic)
        # Mais conditions avec même field: une seule doit matcher (OR logic)
        conditions_by_field: Dict[str, List[Dict]] = {}
        for cond in rule.conditions:
            field = cond.get("field", "")
            if field not in conditions_by_field:
                conditions_by_field[field] = []
            conditions_by_field[field].append(cond)

        for field, conditions in conditions_by_field.items():
            field_matched = False
            for cond in conditions:
                if self._match_condition(cond, email_data):
                    field_matched = True
                    matched_conditions.append(f"{field}:{cond.get('match_type')}")
                    break

            if not field_matched:
                return False, []

        return True, matched_conditions

    def _match_condition(
        self,
        condition: Dict[str, Any],
        email_data: Dict[str, str],
    ) -> bool:
        """
        Vérifie si une condition est remplie.

        Args:
            condition: Condition à vérifier.
            email_data: Données de l'email.

        Returns:
            True si la condition est remplie.
        """
        field = condition.get("field", "")
        match_type = condition.get("match_type", "contains")
        value = condition.get("value", "")
        case_sensitive = condition.get("case_sensitive", False)

        field_value = email_data.get(field, "")

        if not case_sensitive:
            field_value = field_value.lower()
            value = value.lower()

        try:
            if match_type == MatchType.EXACT.value:
                return field_value == value

            elif match_type == MatchType.CONTAINS.value:
                return value in field_value

            elif match_type == MatchType.STARTS_WITH.value:
                return field_value.startswith(value)

            elif match_type == MatchType.ENDS_WITH.value:
                return field_value.endswith(value)

            elif match_type == MatchType.REGEX.value:
                pattern = value if case_sensitive else f"(?i){value}"
                return bool(re.search(pattern, email_data.get(field, "")))

            elif match_type == MatchType.DOMAIN.value:
                domain = self._extract_domain(email_data.get("sender", ""))
                return domain.lower() == value.lower()

            elif match_type == MatchType.ANY.value:
                return True

        except Exception as e:
            logger.error(f"Error matching condition: {e}")

        return False

    def _extract_domain(self, email: str) -> str:
        """Extrait le domaine d'une adresse email."""
        if "@" in email:
            return email.split("@")[1]
        return ""

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de routage."""
        stats = {
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules.values() if r.enabled),
            "by_action": {},
            "most_matched": [],
        }

        for rule in self.rules.values():
            action = rule.action
            stats["by_action"][action] = stats["by_action"].get(action, 0) + 1

        # Les plus matchées
        sorted_by_match = sorted(
            self.rules.values(),
            key=lambda r: r.match_count,
            reverse=True,
        )[:5]
        stats["most_matched"] = [
            {"id": r.id, "name": r.name, "match_count": r.match_count}
            for r in sorted_by_match
        ]

        return stats


# ============================================================================
# SINGLETON & HELPERS
# ============================================================================

_routing_engine: Optional[RoutingEngine] = None


def get_routing_engine() -> RoutingEngine:
    """Retourne le moteur de routage singleton."""
    global _routing_engine
    if _routing_engine is None:
        _routing_engine = RoutingEngine()
    return _routing_engine


def route_email(
    sender: str,
    subject: str,
    body: str,
    category: Optional[str] = None,
) -> RoutingResult:
    """
    Détermine l'action de routage pour un email.

    Args:
        sender: Adresse de l'expéditeur.
        subject: Sujet de l'email.
        body: Corps de l'email.
        category: Catégorie de l'email.

    Returns:
        RoutingResult avec l'action à effectuer.
    """
    if not ROUTING_ENABLED:
        return RoutingResult(
            rule=None,
            action=RoutingAction.PROCESS,
            action_params=None,
            matched_conditions=[],
        )

    engine = get_routing_engine()
    return engine.evaluate(sender, subject, body, category)


def create_routing_rule(
    name: str,
    conditions: List[Dict[str, Any]],
    action: RoutingAction,
    **kwargs,
) -> RoutingRule:
    """
    Crée une nouvelle règle de routage.

    Args:
        name: Nom de la règle.
        conditions: Liste des conditions.
        action: Action à effectuer.
        **kwargs: Options supplémentaires.

    Returns:
        Règle créée.
    """
    import uuid
    rule_id = kwargs.pop("id", str(uuid.uuid4())[:8])

    rule = RoutingRule(
        id=rule_id,
        name=name,
        conditions=conditions,
        action=action.value,
        **kwargs,
    )

    engine = get_routing_engine()
    engine.add_rule(rule)

    return rule


def should_skip_email(
    sender: str,
    subject: str,
    body: str = "",
) -> bool:
    """
    Vérifie si un email doit être ignoré.

    Args:
        sender: Adresse de l'expéditeur.
        subject: Sujet de l'email.
        body: Corps de l'email.

    Returns:
        True si l'email doit être ignoré.
    """
    result = route_email(sender, subject, body)
    return result.action == RoutingAction.SKIP


def should_force_review(
    sender: str,
    subject: str,
    body: str = "",
) -> bool:
    """
    Vérifie si un email nécessite une review forcée.

    Args:
        sender: Adresse de l'expéditeur.
        subject: Sujet de l'email.
        body: Corps de l'email.

    Returns:
        True si une review est requise.
    """
    result = route_email(sender, subject, body)
    return result.action == RoutingAction.REVIEW
