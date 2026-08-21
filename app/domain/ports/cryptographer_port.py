"""Port pour les opérations cryptographiques.

Ce port définit le contrat pour isoler les responsabilités de chiffrement
dans un composant dédié. L'objectif de sécurité est qu'aucun agent unique
n'ait accès à toute la chaîne de données : sans la clé de déchiffrement,
les données restent anonymes même en cas de fuite.

Architecture:
    - Le domaine définit cette interface (CryptographerPort)
    - L'infrastructure implémente l'adapter (ex: EncryptionManagerAdapter)
    - Les dépendances pointent vers l'intérieur (Dependency Inversion)
"""

from abc import ABC, abstractmethod
from typing import Any


class CryptographerPort(ABC):
    """Interface abstraite pour les opérations cryptographiques.

    Permet d'isoler les responsabilités de chiffrement dans un composant dédié,
    garantissant qu'aucun agent unique n'a accès à toute la chaîne de données.
    """

    @abstractmethod
    def encrypt(self, data: str) -> str:
        """Chiffre une chaîne de caractères.

        Args:
            data: La chaîne à chiffrer.

        Returns:
            La chaîne chiffrée (format dépend de l'implémentation).
        """
        pass

    @abstractmethod
    def decrypt(self, encrypted_data: str) -> str:
        """Déchiffre une chaîne de caractères.

        Args:
            encrypted_data: La chaîne chiffrée.

        Returns:
            La chaîne déchiffrée originale.

        Raises:
            ValueError: Si le déchiffrement échoue.
        """
        pass

    @abstractmethod
    def encrypt_dict(self, data: dict[str, Any]) -> str:
        """Chiffre un dictionnaire en JSON chiffré.

        Args:
            data: Le dictionnaire à chiffrer.

        Returns:
            Le JSON chiffré sous forme de chaîne.
        """
        pass

    @abstractmethod
    def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
        """Déchiffre un JSON chiffré en dictionnaire.

        Args:
            encrypted_data: Le JSON chiffré.

        Returns:
            Le dictionnaire original.

        Raises:
            ValueError: Si le déchiffrement échoue.
        """
        pass

    @abstractmethod
    def hash_email(self, email: str) -> str:
        """Génère un hash irréversible pour anonymisation d'email.

        Cette méthode permet d'anonymiser un email de manière déterministe
        mais irréversible, utile pour le tracking sans exposer les données.

        Args:
            email: L'adresse email à hasher.

        Returns:
            Le hash de l'email (format dépend de l'implémentation).
        """
        pass
