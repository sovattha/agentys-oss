# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Port pour le comptage des tokens.

Ce port definit le contrat pour le suivi de l'utilisation
des tokens LLM et des couts associes.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class TokenCounterPort(ABC):
    """
    Port pour le comptage des tokens.

    Responsabilites:
    - Compter les tokens utilises
    - Calculer les couts
    - Fournir des breakdowns par modele/agent
    - Supporter le reset
    """

    # =========================================================================
    # Comptage
    # =========================================================================

    @abstractmethod
    def add(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        agent: str = "",
    ) -> None:
        """
        Ajoute des tokens au compteur.

        Args:
            input_tokens: Nombre de tokens en entree.
            output_tokens: Nombre de tokens en sortie.
            model: Modele LLM utilise.
            agent: Nom de l'agent (drafter, critic, etc.).
        """
        pass

    @abstractmethod
    def get_total(self) -> int:
        """
        Recupere le total des tokens utilises.

        Returns:
            Total des tokens (input + output).
        """
        pass

    @abstractmethod
    def get_input_tokens(self) -> int:
        """
        Recupere le total des tokens en entree.

        Returns:
            Total des tokens d'entree.
        """
        pass

    @abstractmethod
    def get_output_tokens(self) -> int:
        """
        Recupere le total des tokens en sortie.

        Returns:
            Total des tokens de sortie.
        """
        pass

    # =========================================================================
    # Couts
    # =========================================================================

    @abstractmethod
    def get_cost(self) -> float:
        """
        Calcule le cout total en dollars.

        Returns:
            Cout estime en USD.
        """
        pass

    @abstractmethod
    def get_cost_by_model(self) -> Dict[str, float]:
        """
        Recupere le cout par modele.

        Returns:
            Dictionnaire {modele: cout}.
        """
        pass

    # =========================================================================
    # Breakdown
    # =========================================================================

    @abstractmethod
    def get_breakdown(self) -> Dict[str, Any]:
        """
        Recupere le breakdown complet.

        Returns:
            Dictionnaire avec:
            - total: Total tokens
            - input: Tokens entree
            - output: Tokens sortie
            - cost: Cout total
            - by_model: Par modele
            - by_agent: Par agent
        """
        pass

    @abstractmethod
    def get_breakdown_by_agent(self) -> Dict[str, Dict[str, int]]:
        """
        Recupere le breakdown par agent.

        Returns:
            Dictionnaire {agent: {input, output, total}}.
        """
        pass

    @abstractmethod
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Recupere l'historique recent des utilisations.

        Args:
            limit: Nombre d'entrees.

        Returns:
            Liste des dernières utilisations.
        """
        pass

    # =========================================================================
    # Gestion
    # =========================================================================

    @abstractmethod
    def reset(self) -> None:
        """Remet le compteur a zero."""
        pass

    @abstractmethod
    def get_model(self) -> str:
        """
        Recupere le modele actuel.

        Returns:
            Nom du modele.
        """
        pass

    @abstractmethod
    def set_model(self, model: str) -> None:
        """
        Definit le modele actuel.

        Args:
            model: Nom du modele.
        """
        pass
