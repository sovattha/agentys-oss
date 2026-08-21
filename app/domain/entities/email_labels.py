# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Entités pour les labels email personnalisés (Read, Action, FYI, etc.).

Les labels sont différents de la classification système (URGENT, NORMAL, etc.).
- Classification : détermine le traitement (skip spam, priorité, etc.)
- Labels : organisation utilisateur (Read, Action, FYI, Agentys, custom)

Un email peut avoir plusieurs labels simultanément.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class DefaultLabel(Enum):
    """Labels par défaut fournis par Agentys.

    Ces labels sont créés automatiquement et ont des couleurs prédéfinies.
    L'utilisateur peut en créer d'autres.
    """
    ACTION = "Action"       # Requiert une action de ma part (Rouge)
    FYI = "FYI"             # Pour info seulement, pas d'action requise (Bleu)
    NOISE = "Noise"         # Newsletters, notifications, etc. (Gris)


# Set of default label names for quick membership checks
DEFAULT_LABEL_NAMES = {dl.value for dl in DefaultLabel}


# Couleurs pour les labels par défaut
LABEL_COLORS = {
    DefaultLabel.ACTION.value: {"backgroundColor": "#dc2626", "textColor": "#ffffff"},   # Rouge
    DefaultLabel.FYI.value: {"backgroundColor": "#3b82f6", "textColor": "#ffffff"},      # Bleu
    DefaultLabel.NOISE.value: {"backgroundColor": "#6b7280", "textColor": "#ffffff"},    # Gris
}


@dataclass
class EmailLabel:
    """Définition d'un label email.

    Attributes:
        name: Nom du label (unique, case-insensitive)
        color: Couleur d'affichage (hex ou nom couleur Gmail)
        description: Description du label pour l'IA
        is_default: Si c'est un label système (Action, FYI, Noise)
        is_favorite: Si le label est en favori (épinglé dans la sidebar)
        created_at: Date de création
        rules: Règles de détection automatique (apprises ou définies)
        ai_prompt: Prompt IA personnalisé pour la classification
    """
    name: str
    color: Optional[str] = None
    description: str = ""
    is_default: bool = False
    is_favorite: bool = True  # Les labels custom sont favoris par défaut
    is_project: bool = False  # Si le label représente un projet (groupes de contacts)
    project_name: Optional[str] = None  # Nom complet du projet
    project_number: Optional[str] = None  # Numéro de projet pour renforcer le tri (objet/sujet)
    project_abbreviation: Optional[str] = None  # Abréviation du projet (ex: RSW, P142)
    subject_prefix: Optional[str] = None  # Préfixe à insérer en début de sujet (ex: "01345 Agenty - ")
    created_at: str = ""
    rules: List[str] = field(default_factory=list)  # Règles textuelles pour l'IA
    ai_prompt: Optional[str] = None  # Prompt IA pour classification personnalisée

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("Label name cannot be empty")
        self.name = self.name.strip()
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    @classmethod
    def create_default(cls, label: DefaultLabel) -> "EmailLabel":
        """Crée un label par défaut avec sa configuration."""
        descriptions = {
            DefaultLabel.ACTION: "Emails nécessitant une action de votre part",
            DefaultLabel.FYI: "Emails personnels écrits par une vraie personne, pour information uniquement",
            DefaultLabel.NOISE: "Emails automatisés, newsletters, réseaux sociaux, abonnements et marketing",
        }

        initial_rules = {
            DefaultLabel.ACTION: [
                "Explicit request to do something: reply, approve, review, sign, pay, complete a task",
                "Unpaid invoice or payment due requiring the recipient to pay",
                "Direct question addressed to the recipient requiring an answer",
                "Document or contract to review/sign with a deadline",
                "NOT: receipts, payment confirmations, payout notifications, automated summaries",
                "NOT: newsletters, marketing, or founder product announcements",
            ],
            DefaultLabel.FYI: [
                "Recipient is in CC (copy) — no action expected",
                "Personal human-written email sharing information for awareness",
                "A real person writing directly to inform about something relevant",
                "NOT: automated emails, newsletters, founder marketing, social media, subscriptions",
                "NOT: emails from SaaS companies even if signed by a person's name",
            ],
            DefaultLabel.NOISE: [
                "ANY automated, machine-generated, or bulk email without exception",
                "Newsletters, marketing, promotional content, product updates, founder letters",
                "SaaS notifications: Stripe payouts, Expensify reports, GitHub alerts, Slack digests",
                "Transactional receipts, payment confirmations, order confirmations, shipping updates",
                "Social media notifications (LinkedIn, Twitter/X, Facebook, Instagram, Reddit)",
                "Crypto/finance newsletters, daily briefs, market updates, portfolio summaries",
                "Subscription emails, digests, mailing lists, noreply@ senders",
                "Automated payout/deposit/transfer notifications from any financial service",
                "Any email not personally and individually written by a human for the recipient",
            ],
        }

        color = LABEL_COLORS.get(label.value, {}).get("backgroundColor")

        return cls(
            name=label.value,
            color=color,
            description=descriptions.get(label, ""),
            is_default=True,
            is_favorite=False,
            rules=initial_rules.get(label, []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        result = {
            "name": self.name,
            "color": self.color,
            "description": self.description,
            "is_default": self.is_default,
            "is_favorite": self.is_favorite,
            "is_project": self.is_project,
            "project_name": self.project_name,
            "project_number": self.project_number,
            "project_abbreviation": self.project_abbreviation,
            "subject_prefix": self.subject_prefix,
            "created_at": self.created_at,
            "rules": self.rules,
        }
        if self.ai_prompt:
            result["ai_prompt"] = self.ai_prompt
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailLabel":
        """Crée depuis un dictionnaire."""
        return cls(
            name=data.get("name") or "",
            color=data.get("color"),
            description=data.get("description", ""),
            is_default=data.get("is_default", False),
            is_favorite=data.get("is_favorite", True),
            is_project=data.get("is_project", False),
            project_name=data.get("project_name"),
            project_number=data.get("project_number"),
            project_abbreviation=data.get("project_abbreviation"),
            subject_prefix=data.get("subject_prefix"),
            created_at=data.get("created_at", ""),
            rules=data.get("rules", []),
            ai_prompt=data.get("ai_prompt"),
        )


@dataclass
class LabelAssignment:
    """Assignation d'un ou plusieurs labels à un email.

    Each email has exactly 1 default label (Action/FYI/Noise)
    plus 0..N custom labels (VIP, Client, Urgent, etc.).
    The flat `labels` list is rebuilt from default_label + custom_labels.

    Attributes:
        email_id: ID de l'email
        default_label: The single default label (Action/FYI/Noise) or None
        custom_labels: List of custom label names (VIP, Client, etc.)
        labels: Flat list of all labels (default + custom) — auto-rebuilt
        confidences: Confiance pour chaque label (0.0-1.0)
        reasons: Raisons de l'assignation pour chaque label
        is_cc: Si l'utilisateur est en CC
        assigned_at: Date d'assignation
        assigned_by: 'ai' ou 'user' (pour le learning)
    """
    email_id: str
    default_label: Optional[str] = None
    custom_labels: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    confidences: Dict[str, float] = field(default_factory=dict)
    reasons: Dict[str, str] = field(default_factory=dict)
    is_cc: bool = False
    assigned_at: str = ""
    assigned_by: str = "ai"  # 'ai' ou 'user'
    matched_rule_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.email_id:
            raise ValueError("email_id cannot be empty")
        if not self.assigned_at:
            self.assigned_at = datetime.now().isoformat()

    def _rebuild_labels(self) -> None:
        """Reconstruit la liste plate `labels` depuis default_label + custom_labels.

        Purge au passage tout label par défaut contradictoire qui aurait pu
        se glisser dans custom_labels (ex: Action + Noise sur le même email).
        """
        if self.default_label:
            self.custom_labels = [
                cl for cl in self.custom_labels
                if cl not in DEFAULT_LABEL_NAMES or cl == self.default_label
            ]
        result = []
        if self.default_label:
            result.append(self.default_label)
        for cl in self.custom_labels:
            if cl not in result:
                result.append(cl)
        self.labels = result

    def set_default_label(
        self,
        label: str,
        confidence: float = 1.0,
        reason: str = "",
    ) -> None:
        """Sets the single default label, replacing any previous one."""
        # Remove old default from confidences/reasons
        if self.default_label and self.default_label != label:
            self.confidences.pop(self.default_label, None)
            self.reasons.pop(self.default_label, None)
        self.default_label = label
        self.confidences[label] = confidence
        self.reasons[label] = reason
        self._rebuild_labels()

    def add_custom_label(
        self,
        label: str,
        confidence: float = 1.0,
        reason: str = "",
    ) -> None:
        """Adds a custom (non-default) label.

        Si le label est un label par défaut (Action/FYI/Noise) et qu'un
        default_label différent existe déjà, on ignore silencieusement pour
        éviter les contradictions (ex: Action + Noise sur le même email).
        """
        if label in DEFAULT_LABEL_NAMES and self.default_label and self.default_label != label:
            return
        if label not in self.custom_labels:
            self.custom_labels.append(label)
        self.confidences[label] = confidence
        self.reasons[label] = reason
        self._rebuild_labels()

    def remove_custom_label(self, label: str) -> None:
        """Removes a custom label."""
        if label in self.custom_labels:
            self.custom_labels.remove(label)
            self.confidences.pop(label, None)
            self.reasons.pop(label, None)
            self._rebuild_labels()

    def add_label(
        self,
        label: str,
        confidence: float = 1.0,
        reason: str = ""
    ) -> None:
        """Ajoute un label à l'assignation (legacy compat).

        Routes to set_default_label or add_custom_label based on label name.
        """
        if label in DEFAULT_LABEL_NAMES:
            self.set_default_label(label, confidence, reason)
        else:
            self.add_custom_label(label, confidence, reason)

    def remove_label(self, label: str) -> None:
        """Retire un label de l'assignation."""
        if label == self.default_label:
            self.default_label = None
            self.confidences.pop(label, None)
            self.reasons.pop(label, None)
            self._rebuild_labels()
        elif label in self.custom_labels:
            self.remove_custom_label(label)

    def has_label(self, label: str) -> bool:
        """Vérifie si un label est assigné."""
        return label in self.labels

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        d = {
            "email_id": self.email_id,
            "default_label": self.default_label,
            "custom_labels": self.custom_labels,
            "labels": self.labels,
            "confidences": self.confidences,
            "reasons": self.reasons,
            "is_cc": self.is_cc,
            "assigned_at": self.assigned_at,
            "assigned_by": self.assigned_by,
        }
        if self.matched_rule_ids:
            d["matched_rule_ids"] = self.matched_rule_ids
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LabelAssignment":
        """Crée depuis un dictionnaire (with migration from legacy format)."""
        default_label = data.get("default_label")
        custom_labels = data.get("custom_labels", [])
        labels = data.get("labels", [])

        # Migration: if default_label is missing but labels exist (legacy data),
        # infer default_label and custom_labels from the flat list
        if default_label is None and not custom_labels and labels:
            for lbl in labels:
                if lbl in DEFAULT_LABEL_NAMES:
                    default_label = lbl
                else:
                    custom_labels.append(lbl)

        instance = cls(
            email_id=data["email_id"],
            default_label=default_label,
            custom_labels=custom_labels,
            confidences=data.get("confidences", {}),
            reasons=data.get("reasons", {}),
            is_cc=data.get("is_cc", False),
            assigned_at=data.get("assigned_at", ""),
            assigned_by=data.get("assigned_by", "ai"),
            matched_rule_ids=data.get("matched_rule_ids", []),
        )
        instance._rebuild_labels()
        return instance


@dataclass
class LabelingRule:
    """Règle de labellisation apprise ou définie par l'utilisateur.

    Attributes:
        rule_id: ID unique de la règle
        label_name: Label à appliquer
        condition_type: Type de condition (sender, subject, body, cc, custom)
        condition_value: Valeur de la condition (regex, texte, etc.)
        priority: Priorité de la règle (plus haut = appliquée en premier)
        learned_from: ID de l'email source si appris, None si défini manuellement
        confidence: Confiance dans la règle (0.0-1.0)
        created_at: Date de création
        last_used_at: Dernière utilisation
        use_count: Nombre de fois utilisée
    """
    rule_id: str
    label_name: str
    condition_type: str  # sender, subject, body, cc, recipient, custom
    condition_value: str
    priority: int = 50
    learned_from: Optional[str] = None
    confidence: float = 1.0
    created_at: str = ""
    last_used_at: Optional[str] = None
    use_count: int = 0
    is_active: bool = True
    total_matches: int = 0
    corrections: int = 0
    disabled_reason: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def matches(self, email_data: Dict[str, Any]) -> bool:
        """Vérifie si la règle s'applique à un email.

        User-entered condition values are treated as **literal substrings**.
        Treating them as regex was a footgun: a subject rule with value
        "[Newsletter]" becomes the regex character class [Newsletter] which
        matches any subject containing N, e, w, s, l, t, or r — i.e. almost
        every email. Use explicit ``subject_regex`` / ``body_regex`` condition
        types if regex semantics are needed.
        """
        import re

        if self.condition_type == "sender":
            sender = email_data.get("sender", "").lower()
            return self.condition_value.lower() in sender

        elif self.condition_type == "subject":
            subject = email_data.get("subject", "").lower()
            return self.condition_value.lower() in subject

        elif self.condition_type == "subject_regex":
            subject = email_data.get("subject", "").lower()
            try:
                return bool(re.search(self.condition_value, subject, re.IGNORECASE))
            except re.error:
                return False

        elif self.condition_type == "body":
            body = email_data.get("body", "").lower()
            return self.condition_value.lower() in body

        elif self.condition_type == "body_regex":
            body = email_data.get("body", "").lower()
            try:
                return bool(re.search(self.condition_value, body, re.IGNORECASE))
            except re.error:
                return False

        elif self.condition_type == "cc":
            # Vérifie si l'utilisateur est en CC
            return email_data.get("is_cc", False)

        elif self.condition_type == "recipient":
            recipients = email_data.get("recipients", [])
            return any(
                self.condition_value.lower() in r.lower()
                for r in recipients
            )

        return False

    def record_use(self) -> None:
        """Enregistre une utilisation de la règle."""
        self.last_used_at = datetime.now().isoformat()
        self.use_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "rule_id": self.rule_id,
            "label_name": self.label_name,
            "condition_type": self.condition_type,
            "condition_value": self.condition_value,
            "priority": self.priority,
            "learned_from": self.learned_from,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
            "is_active": self.is_active,
            "total_matches": self.total_matches,
            "corrections": self.corrections,
            "disabled_reason": self.disabled_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LabelingRule":
        """Crée depuis un dictionnaire."""
        return cls(
            rule_id=data["rule_id"],
            label_name=data["label_name"],
            condition_type=data["condition_type"],
            condition_value=data["condition_value"],
            priority=data.get("priority", 50),
            learned_from=data.get("learned_from"),
            confidence=data.get("confidence", 1.0),
            created_at=data.get("created_at", ""),
            last_used_at=data.get("last_used_at"),
            use_count=data.get("use_count", 0),
            is_active=data.get("is_active", True),
            total_matches=data.get("total_matches", 0),
            corrections=data.get("corrections", 0),
            disabled_reason=data.get("disabled_reason"),
        )

    def to_markdown(self) -> str:
        """Convertit en format markdown pour documentation."""
        return f"""### Règle: {self.label_name}
- **Type**: {self.condition_type}
- **Condition**: `{self.condition_value}`
- **Confiance**: {self.confidence * 100:.0f}%
- **Utilisations**: {self.use_count}
- **Apprise de**: {self.learned_from or 'Définie manuellement'}
"""


def get_default_labels() -> List[EmailLabel]:
    """Retourne la liste des labels par défaut."""
    return [
        EmailLabel.create_default(label)
        for label in DefaultLabel
    ]
