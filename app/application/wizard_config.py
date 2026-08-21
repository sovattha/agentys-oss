# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Use Cases pour la configuration wizard d'entreprise.

Ces use cases gèrent la sauvegarde, le chargement et la validation
de la configuration d'onboarding entreprise.
"""

from dataclasses import dataclass
from typing import Optional, List
import uuid

from app.domain.entities import (
    WizardConfig,
    BusinessSector,
    CompanySize,
    ConfigPack,
)
from app.domain.ports import WizardConfigPort


@dataclass
class SaveWizardConfigUseCase:
    """
    Sauvegarde la configuration wizard.

    Ce use case valide et persiste la configuration
    d'onboarding entreprise.
    """
    persistence: WizardConfigPort

    def execute(self, config: WizardConfig) -> WizardConfig:
        """
        Sauvegarde la configuration.

        Args:
            config: Configuration à sauvegarder.

        Returns:
            Configuration sauvegardée avec métadonnées mises à jour.

        Raises:
            ValueError: Si la configuration est invalide.
        """
        self._validate(config)
        self.persistence.save(config)
        return config

    def _validate(self, config: WizardConfig) -> None:
        """Valide la configuration avant sauvegarde."""
        if not config.config_id:
            raise ValueError("config_id est requis")
        if not config.company_name or not config.company_name.strip():
            raise ValueError("company_name est requis")


@dataclass
class LoadWizardConfigUseCase:
    """
    Charge la configuration wizard.

    Ce use case récupère la configuration d'onboarding
    depuis la persistance.
    """
    persistence: WizardConfigPort

    def execute(self) -> Optional[WizardConfig]:
        """
        Charge la configuration.

        Returns:
            Configuration chargée ou None si inexistante.
        """
        return self.persistence.load()


@dataclass
class CreateWizardConfigUseCase:
    """
    Crée une nouvelle configuration wizard.

    Ce use case initialise une configuration avec
    les valeurs par défaut et optionnellement un pack.
    """
    persistence: WizardConfigPort

    def execute(
        self,
        company_name: str,
        sector: BusinessSector = BusinessSector.OTHER,
        size: CompanySize = CompanySize.SMB,
        pack: Optional[ConfigPack] = None,
    ) -> WizardConfig:
        """
        Crée une nouvelle configuration.

        Args:
            company_name: Nom de l'entreprise.
            sector: Secteur d'activité.
            size: Taille de l'entreprise.
            pack: Pack de configuration à appliquer.

        Returns:
            Nouvelle configuration créée.
        """
        config = WizardConfig(
            config_id=str(uuid.uuid4()),
            company_name=company_name,
            sector=sector,
            size=size,
            pack=pack or ConfigPack.CUSTOM,
        )

        if pack and pack != ConfigPack.CUSTOM:
            config = self._apply_pack(config, pack)

        return config

    def _apply_pack(self, config: WizardConfig, pack: ConfigPack) -> WizardConfig:
        """Applique un pack de configuration prédéfini."""
        pack_configs = PACK_CONFIGURATIONS.get(pack, {})

        # Appliquer les agents
        for agent_config in pack_configs.get("agents", []):
            config.activate_agent(
                agent_id=agent_config["id"],
                priority=agent_config.get("priority", 50)
            )

        # Appliquer les langues
        if "languages" in pack_configs:
            config.supported_languages = pack_configs["languages"]

        # Appliquer le tone guidelines par défaut
        if "tone_guidelines" in pack_configs:
            config.knowledge_base.tone_guidelines = pack_configs["tone_guidelines"]

        return config


@dataclass
class ToggleAgentUseCase:
    """
    Active ou désactive un agent dans la configuration.
    """
    persistence: WizardConfigPort

    def execute(
        self,
        agent_id: str,
        enabled: bool,
        priority: int = 50
    ) -> Optional[WizardConfig]:
        """
        Toggle l'état d'un agent.

        Args:
            agent_id: ID de l'agent à modifier.
            enabled: True pour activer, False pour désactiver.
            priority: Priorité de l'agent (0-100).

        Returns:
            Configuration mise à jour ou None si inexistante.
        """
        config = self.persistence.load()
        if not config:
            return None

        if enabled:
            config.activate_agent(agent_id, priority)
        else:
            config.deactivate_agent(agent_id)

        self.persistence.save(config)
        return config


@dataclass
class ImportKnowledgeBaseUseCase:
    """
    Importe une knowledge base depuis un fichier.
    """
    persistence: WizardConfigPort

    def execute(
        self,
        file_path: str,
        merge: bool = False
    ) -> Optional[WizardConfig]:
        """
        Importe une knowledge base.

        Args:
            file_path: Chemin du fichier à importer.
            merge: True pour fusionner avec l'existant.

        Returns:
            Configuration mise à jour ou None si inexistante.

        Raises:
            FileNotFoundError: Si le fichier n'existe pas.
        """
        config = self.persistence.load()
        if not config:
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if merge and config.knowledge_base.company_description:
            # Fusion avec le contenu existant
            config.knowledge_base.company_description += f"\n\n{content}"
        else:
            config.knowledge_base.company_description = content

        config.knowledge_base.custom_file_path = file_path
        self.persistence.save(config)
        return config


@dataclass
class ExportConfigUseCase:
    """
    Exporte la configuration vers un fichier.
    """
    persistence: WizardConfigPort

    def execute(self, file_path: str) -> bool:
        """
        Exporte la configuration.

        Args:
            file_path: Chemin du fichier de destination.

        Returns:
            True si l'export a réussi.

        Raises:
            ValueError: Si aucune configuration n'existe.
        """
        self.persistence.export_to_file(file_path)
        return True


# Configurations des packs prédéfinis
PACK_CONFIGURATIONS = {
    ConfigPack.STARTUP: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 90},
            {"id": "onboarding_specialist", "priority": 80},
            {"id": "sales_qualifier", "priority": 75},
        ],
        "languages": ["en", "fr"],
        "tone_guidelines": "Ton dynamique et enthousiaste, tutoiement accepté, réponses rapides et efficaces."
    },
    ConfigPack.SMB: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 90},
            {"id": "tech_support", "priority": 80},
            {"id": "meeting_scheduler", "priority": 75},
            {"id": "refund_handler", "priority": 70},
        ],
        "languages": ["fr", "en"],
        "tone_guidelines": "Ton professionnel mais accessible, vouvoiement par défaut, réponses claires et complètes."
    },
    ConfigPack.ENTERPRISE: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 95},
            {"id": "legal_advisor", "priority": 90},
            {"id": "hr_specialist", "priority": 85},
            {"id": "financial_advisor", "priority": 80},
            {"id": "tech_support", "priority": 75},
            {"id": "meeting_scheduler", "priority": 70},
            {"id": "onboarding_specialist", "priority": 65},
            {"id": "feedback_analyst", "priority": 60},
        ],
        "languages": ["fr", "en", "de", "es"],
        "tone_guidelines": "Ton très professionnel et formel, vouvoiement strict, réponses structurées et documentées."
    },
    ConfigPack.SAAS: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 90},
            {"id": "tech_support", "priority": 95},
            {"id": "onboarding_specialist", "priority": 85},
            {"id": "sales_qualifier", "priority": 80},
            {"id": "feedback_analyst", "priority": 75},
        ],
        "languages": ["en", "fr", "de"],
        "tone_guidelines": "Ton technique mais accessible, tutoiement en contexte startup, réponses avec références documentation."
    },
    ConfigPack.ECOMMERCE: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 90},
            {"id": "refund_handler", "priority": 95},
            {"id": "tech_support", "priority": 80},
            {"id": "feedback_analyst", "priority": 85},
            {"id": "meeting_scheduler", "priority": 60},
        ],
        "languages": ["fr", "en"],
        "tone_guidelines": "Ton commercial et empathique, vouvoiement, réponses rapides axées sur la satisfaction client."
    },
    ConfigPack.B2B: {
        "agents": [
            {"id": "drafter", "priority": 100},
            {"id": "critic", "priority": 90},
            {"id": "sales_qualifier", "priority": 95},
            {"id": "meeting_scheduler", "priority": 90},
            {"id": "legal_advisor", "priority": 75},
            {"id": "financial_advisor", "priority": 70},
        ],
        "languages": ["fr", "en"],
        "tone_guidelines": "Ton professionnel B2B, vouvoiement strict, réponses orientées partenariat et valeur ajoutée."
    },
}


def get_available_packs() -> List[dict]:
    """
    Retourne la liste des packs disponibles avec leur description.

    Returns:
        Liste des packs avec métadonnées.
    """
    return [
        {
            "id": ConfigPack.STARTUP.value,
            "name": "Startup",
            "description": "Équipe réduite, focus sur l'acquisition et l'onboarding clients.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.STARTUP]["agents"]),
        },
        {
            "id": ConfigPack.SMB.value,
            "name": "PME",
            "description": "Entreprise établie, besoin support client et organisation.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.SMB]["agents"]),
        },
        {
            "id": ConfigPack.ENTERPRISE.value,
            "name": "Enterprise",
            "description": "Grande entreprise, tous les agents avec conformité et RH.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.ENTERPRISE]["agents"]),
        },
        {
            "id": ConfigPack.SAAS.value,
            "name": "SaaS",
            "description": "Éditeur logiciel, focus sur le support technique et l'onboarding.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.SAAS]["agents"]),
        },
        {
            "id": ConfigPack.ECOMMERCE.value,
            "name": "E-commerce",
            "description": "Commerce en ligne, focus sur les remboursements et la satisfaction.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.ECOMMERCE]["agents"]),
        },
        {
            "id": ConfigPack.B2B.value,
            "name": "B2B",
            "description": "Business to Business, focus sur la qualification et les meetings.",
            "agents_count": len(PACK_CONFIGURATIONS[ConfigPack.B2B]["agents"]),
        },
    ]


def get_available_agents() -> List[dict]:
    """
    Retourne la liste de tous les agents disponibles.

    Returns:
        Liste des agents avec métadonnées.
    """
    return [
        {"id": "drafter", "name": "Drafter", "description": "Rédige les réponses emails", "category": "core"},
        {"id": "critic", "name": "Critic", "description": "Évalue et valide les réponses", "category": "core"},
        {"id": "tech_support", "name": "Support Technique", "description": "Expert questions techniques", "category": "support"},
        {"id": "legal_advisor", "name": "Conseiller Juridique", "description": "Questions légales et conformité", "category": "expert"},
        {"id": "medical_info", "name": "Info Médicale", "description": "Informations santé (non-diagnostic)", "category": "expert"},
        {"id": "financial_advisor", "name": "Conseiller Financier", "description": "Questions finances et comptabilité", "category": "expert"},
        {"id": "hr_specialist", "name": "Spécialiste RH", "description": "Questions ressources humaines", "category": "expert"},
        {"id": "onboarding_specialist", "name": "Spécialiste Onboarding", "description": "Accueil et activation clients", "category": "sales"},
        {"id": "sales_qualifier", "name": "Qualificateur Ventes", "description": "Qualification leads et pré-vente", "category": "sales"},
        {"id": "meeting_scheduler", "name": "Planificateur Meetings", "description": "Organisation de rendez-vous", "category": "productivity"},
        {"id": "refund_handler", "name": "Gestionnaire Remboursements", "description": "Traitement retours et remboursements", "category": "support"},
        {"id": "feedback_analyst", "name": "Analyste Feedback", "description": "Réponse aux avis et analyse sentiment", "category": "analytics"},
    ]
