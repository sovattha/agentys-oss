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
