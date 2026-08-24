# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Interface abstraite pour les fournisseurs de gestion de comptes utilisateur."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AccountActionResult:
    """Resultat d'une action de compte (reset password, update email, etc.)."""
    success: bool
    message: str
    method: str = "direct"  # "direct" | "reset_link"
    details: Optional[dict] = None


class AccountProvider(ABC):
    """
    Interface abstraite pour les fournisseurs de gestion de comptes.

    Toutes les implementations (WordPress, Shopify, Custom API)
    doivent heriter de cette classe.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Retourne le nom du fournisseur (ex: 'wordpress', 'shopify', 'custom')."""
        pass

    @abstractmethod
    def test_connection(self) -> AccountActionResult:
        """Teste la connexion au fournisseur."""
        pass

    @abstractmethod
    def search_user(self, email: str) -> Optional[dict]:
        """
        Recherche un utilisateur par email.

        Returns:
            Dict normalise {id, username, email, display_name} ou None.
        """
        pass

    @abstractmethod
    def reset_password(self, user_id, new_password: str) -> AccountActionResult:
        """Reinitialise le mot de passe d'un utilisateur."""
        pass

    @abstractmethod
    def update_email(self, user_id, new_email: str) -> AccountActionResult:
        """Met a jour l'adresse email d'un utilisateur."""
        pass
