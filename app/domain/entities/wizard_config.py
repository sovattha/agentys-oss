# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Entité WizardConfig pour la configuration d'entreprise."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict


class BusinessSector(Enum):
    """Secteur d'activité de l'entreprise."""
    TECH = "tech"
    SAAS = "saas"
    ECOMMERCE = "ecommerce"
    FINANCE = "finance"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    RETAIL = "retail"
    CONSULTING = "consulting"
    MANUFACTURING = "manufacturing"
    LEGAL = "legal"
    REAL_ESTATE = "real_estate"
    HOSPITALITY = "hospitality"
    MEDIA = "media"
    NONPROFIT = "nonprofit"
    OTHER = "other"


class CompanySize(Enum):
    """Taille de l'entreprise."""
    SOLO = "solo"           # 1 personne
    STARTUP = "startup"     # 2-10
    SMB = "smb"             # 11-50
    MIDMARKET = "midmarket" # 51-200
    ENTERPRISE = "enterprise" # 200+


class ConfigPack(Enum):
    """Packs de configuration préconfigurés."""
    CUSTOM = "custom"
    STARTUP = "startup"
    SMB = "smb"
    ENTERPRISE = "enterprise"
    SAAS = "saas"
    ECOMMERCE = "ecommerce"
    B2B = "b2b"


@dataclass
class AgentActivation:
    """Configuration d'activation d'un agent."""
    agent_id: str
    enabled: bool = True
    priority: int = 50  # 0-100, 100 = priorité max
    custom_prompt_override: Optional[str] = None


@dataclass
class KnowledgeBaseConfig:
    """Configuration de la knowledge base entreprise."""
    company_name: str = ""
    company_description: str = ""
    products_services: str = ""
    tone_guidelines: str = ""
    forbidden_topics: List[str] = field(default_factory=list)
    custom_signatures: Dict[str, str] = field(default_factory=dict)
    faq_entries: Dict[str, str] = field(default_factory=dict)
    custom_file_path: Optional[str] = None


@dataclass
class WizardConfig:
    """Configuration complète du wizard d'onboarding entreprise.

    Cette entité pure du domaine représente la configuration
    d'une entreprise utilisant Agentys.
    """
    # Identifiant unique
    config_id: str

    # Informations entreprise
    company_name: str
    sector: BusinessSector = BusinessSector.OTHER
    size: CompanySize = CompanySize.SMB

    # Langues supportées (ISO 639-1)
    primary_language: str = "fr"
    supported_languages: List[str] = field(default_factory=lambda: ["fr", "en"])

    # Pack de configuration
    pack: ConfigPack = ConfigPack.CUSTOM

    # Agents activés
    agents: List[AgentActivation] = field(default_factory=list)

    # Knowledge base
    knowledge_base: KnowledgeBaseConfig = field(default_factory=KnowledgeBaseConfig)

    # Métadonnées
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version: int = 1
    is_complete: bool = False

    def activate_agent(self, agent_id: str, priority: int = 50) -> None:
        """Active un agent avec une priorité donnée."""
        existing = next((a for a in self.agents if a.agent_id == agent_id), None)
        if existing:
            existing.enabled = True
            existing.priority = priority
        else:
            self.agents.append(AgentActivation(
                agent_id=agent_id,
                enabled=True,
                priority=priority
            ))
        self.updated_at = datetime.now()

    def deactivate_agent(self, agent_id: str) -> None:
        """Désactive un agent."""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                agent.enabled = False
                self.updated_at = datetime.now()
                return

    def is_agent_active(self, agent_id: str) -> bool:
        """Vérifie si un agent est actif."""
        agent = next((a for a in self.agents if a.agent_id == agent_id), None)
        return agent.enabled if agent else False

    def get_active_agents(self) -> List[AgentActivation]:
        """Retourne les agents actifs triés par priorité."""
        return sorted(
            [a for a in self.agents if a.enabled],
            key=lambda x: x.priority,
            reverse=True
        )

    def mark_complete(self) -> None:
        """Marque la configuration comme complète."""
        self.is_complete = True
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict:
        """Sérialise la config en dictionnaire."""
        return {
            "config_id": self.config_id,
            "company_name": self.company_name,
            "sector": self.sector.value,
            "size": self.size.value,
            "primary_language": self.primary_language,
            "supported_languages": self.supported_languages,
            "pack": self.pack.value,
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "enabled": a.enabled,
                    "priority": a.priority,
                    "custom_prompt_override": a.custom_prompt_override
                }
                for a in self.agents
            ],
            "knowledge_base": {
                "company_name": self.knowledge_base.company_name,
                "company_description": self.knowledge_base.company_description,
                "products_services": self.knowledge_base.products_services,
                "tone_guidelines": self.knowledge_base.tone_guidelines,
                "forbidden_topics": self.knowledge_base.forbidden_topics,
                "custom_signatures": self.knowledge_base.custom_signatures,
                "faq_entries": self.knowledge_base.faq_entries,
                "custom_file_path": self.knowledge_base.custom_file_path
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_complete": self.is_complete
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WizardConfig":
        """Désérialise depuis un dictionnaire."""
        knowledge_base_data = data.get("knowledge_base", {})
        knowledge_base = KnowledgeBaseConfig(
            company_name=knowledge_base_data.get("company_name", ""),
            company_description=knowledge_base_data.get("company_description", ""),
            products_services=knowledge_base_data.get("products_services", ""),
            tone_guidelines=knowledge_base_data.get("tone_guidelines", ""),
            forbidden_topics=knowledge_base_data.get("forbidden_topics", []),
            custom_signatures=knowledge_base_data.get("custom_signatures", {}),
            faq_entries=knowledge_base_data.get("faq_entries", {}),
            custom_file_path=knowledge_base_data.get("custom_file_path")
        )

        agents = [
            AgentActivation(
                agent_id=a["agent_id"],
                enabled=a.get("enabled", True),
                priority=a.get("priority", 50),
                custom_prompt_override=a.get("custom_prompt_override")
            )
            for a in data.get("agents", [])
        ]

        return cls(
            config_id=data.get("config_id", str(uuid.uuid4())[:8]),
            company_name=data.get("company_name", ""),
            sector=BusinessSector(data.get("sector", "other")),
            size=CompanySize(data.get("size", "smb")),
            primary_language=data.get("primary_language", "fr"),
            supported_languages=data.get("supported_languages", ["fr", "en"]),
            pack=ConfigPack(data.get("pack", "custom")),
            agents=agents,
            knowledge_base=knowledge_base,
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            version=data.get("version", 1),
            is_complete=data.get("is_complete", False)
        )
