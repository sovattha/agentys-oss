# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Port abstrait pour les opérations de chiffrement."""
from abc import ABC, abstractmethod
from typing import Dict


class EncryptionPort(ABC):
    """Interface abstraite pour le chiffrement de mappings."""

    @abstractmethod
    def encrypt_mapping(self, mapping: Dict[str, str]) -> str:
        """
        Chiffre un mapping marqueur -> valeur originale.

        Args:
            mapping: Dictionnaire {marqueur: valeur_originale}

        Returns:
            Token chiffré contenant le mapping sérialisé.
        """
        pass

    @abstractmethod
    def decrypt_mapping(self, encrypted_token: str) -> Dict[str, str]:
        """
        Déchiffre un token pour récupérer le mapping original.

        Args:
            encrypted_token: Token chiffré précédemment généré.

        Returns:
            Dictionnaire {marqueur: valeur_originale}

        Raises:
            InvalidToken: Si le token est invalide ou corrompu.
        """
        pass
