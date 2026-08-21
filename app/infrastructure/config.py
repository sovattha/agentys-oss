# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Configuration centralisée pour l'infrastructure.

Utilise les constantes définies dans app/config.py pour éviter la duplication.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Importer les constantes centralisées
from app.config import (
    PROJECT_ROOT,
    INPUTS_DIR,
    OUTPUTS_DIR,
    LLM_PROVIDER,
    ANTHROPIC_API_KEY,
    ANTHROPIC_API_KEY_DRAFTING,
    ANTHROPIC_API_KEY_ONBOARDING,
    ANTHROPIC_API_KEY_BACKGROUND,
    OLLAMA_BASE_URL,
    CLAUDE_MODEL_OPUS,
    OLLAMA_MODEL_SMART,
    MODEL_DEFAULT,
    MAX_TOKENS_DRAFT,
    MAX_TOKENS_CRITIC,
    MAX_TOKENS_PRIORITIZATION,
    MAX_TOKENS_CLASSIFICATION,
)


@dataclass
class Config:
    """
    Configuration de l'application pour l'injection de dépendances.

    Cette classe encapsule la configuration pour faciliter l'injection
    dans le Container. Les valeurs par défaut proviennent des constantes
    centralisées dans app/config.py.
    """

    # Chemins
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)

    # LLM
    llm_provider: str = field(default_factory=lambda: LLM_PROVIDER.lower())
    llm_model: Optional[str] = field(default_factory=lambda: MODEL_DEFAULT)
    anthropic_api_key: Optional[str] = field(default_factory=lambda: ANTHROPIC_API_KEY)
    # Clés spécialisées (fallback vers anthropic_api_key au niveau app/config.py)
    anthropic_api_key_drafting: Optional[str] = field(default_factory=lambda: ANTHROPIC_API_KEY_DRAFTING)
    anthropic_api_key_onboarding: Optional[str] = field(default_factory=lambda: ANTHROPIC_API_KEY_ONBOARDING)
    anthropic_api_key_background: Optional[str] = field(default_factory=lambda: ANTHROPIC_API_KEY_BACKGROUND)
    ollama_base_url: str = field(default_factory=lambda: OLLAMA_BASE_URL)

    # Modèles par défaut (pour référence, utiliser MODEL_DEFAULT directement)
    claude_model_default: str = field(default_factory=lambda: CLAUDE_MODEL_OPUS)
    ollama_model_default: str = field(default_factory=lambda: OLLAMA_MODEL_SMART)

    # Tokens
    max_tokens_draft: int = MAX_TOKENS_DRAFT
    max_tokens_critique: int = MAX_TOKENS_CRITIC
    max_tokens_prioritization: int = MAX_TOKENS_PRIORITIZATION
    max_tokens_classification: int = MAX_TOKENS_CLASSIFICATION

    @classmethod
    def from_env(cls, env_path: Path = None) -> "Config":
        """
        Charge la configuration depuis les variables d'environnement.

        Note: Les variables sont déjà chargées par app/config.py au démarrage.
        Cette méthode permet de créer une instance avec les valeurs actuelles.
        """
        if env_path is not None and env_path.exists():
            load_dotenv(env_path)

        llm_provider = os.getenv("LLM_PROVIDER", LLM_PROVIDER).lower()

        # Modèle par défaut selon le provider
        if llm_provider == "ollama":
            default_model = os.getenv("LLM_MODEL", OLLAMA_MODEL_SMART)
        else:
            default_model = os.getenv("LLM_MODEL", CLAUDE_MODEL_OPUS)

        _master_key = os.getenv("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
        return cls(
            project_root=PROJECT_ROOT,
            llm_provider=llm_provider,
            llm_model=default_model,
            anthropic_api_key=_master_key,
            anthropic_api_key_drafting=os.getenv("ANTHROPIC_API_KEY_DRAFTING") or _master_key,
            anthropic_api_key_onboarding=os.getenv("ANTHROPIC_API_KEY_ONBOARDING") or _master_key,
            anthropic_api_key_background=os.getenv("ANTHROPIC_API_KEY_BACKGROUND") or _master_key,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", OLLAMA_BASE_URL),
            max_tokens_draft=int(os.getenv("MAX_TOKENS_DRAFT", str(MAX_TOKENS_DRAFT))),
            max_tokens_critique=int(os.getenv("MAX_TOKENS_CRITIQUE", str(MAX_TOKENS_CRITIC))),
        )

    @property
    def knowledge_path(self) -> Path:
        """Chemin vers la base de connaissances."""
        return self.project_root / "knowledge" / "memoire.md"

    @property
    def data_inputs_path(self) -> Path:
        """Chemin vers les fichiers d'entrée."""
        return INPUTS_DIR

    @property
    def data_outputs_path(self) -> Path:
        """Chemin vers les fichiers de sortie."""
        return OUTPUTS_DIR

    def validate(self) -> None:
        """Valide la configuration."""
        if (
            self.llm_provider == "claude"
            and os.getenv("AGENTYS_MOCK_LLM", "").strip().lower()
            not in {"1", "true", "yes", "on"}
            and not self.anthropic_api_key
        ):
            raise ValueError(
                "ANTHROPIC_API_KEY requise pour le provider Claude. "
                "Configurez-la dans .env ou utilisez LLM_PROVIDER=ollama ou LLM_PROVIDER=claude-code"
            )
