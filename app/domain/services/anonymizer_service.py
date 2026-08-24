# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import hashlib
import os
import uuid
from typing import Dict, List

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.domain.entities.anonymization import (
    AnonymizedResult,
    AnonymizedToken,
    SecureAnonymizedData,
    SecureTokenMapping,
)
from app.domain.entities.sensitive_data import SensitiveDataDetection


class InvalidCredentialsError(Exception):
    """Raised when credentials are invalid for reveal operation."""
    pass


class DataAnonymizer:
    """
    Service d'anonymisation sécurisée des données sensibles.

    SÉCURITÉ:
    - Les valeurs originales sont chiffrées avec AES-GCM (256 bits)
    - Chaque token a son propre sel (nonce)
    - Le reveal() nécessite la clé de déchiffrement
    - AnonymizedResult ne contient JAMAIS les valeurs en clair
    """

    def anonymize(
        self, text: str, detection: SensitiveDataDetection, encryption_key: bytes
    ) -> SecureAnonymizedData:
        """
        Anonymise les données sensibles avec chiffrement.

        Args:
            text: Texte à anonymiser
            detection: Résultat de la détection de données sensibles
            encryption_key: Clé AES-256 (32 bytes) pour le chiffrement

        Returns:
            SecureAnonymizedData avec les valeurs chiffrées
        """
        if len(encryption_key) != 32:
            raise ValueError("encryption_key must be 32 bytes for AES-256")

        text_hash = self._compute_hash(text)

        if not detection.is_sensitive or not detection.detected_items:
            return SecureAnonymizedData.create(
                result=AnonymizedResult.empty(text, text_hash),
                secure_mappings=[],
                key_id=self._compute_key_id(encryption_key),
            )

        tokens: List[AnonymizedToken] = []
        secure_mappings: List[SecureTokenMapping] = []
        anonymized_text = text
        aesgcm = AESGCM(encryption_key)

        for item in detection.detected_items:
            if item.snippet not in anonymized_text:
                continue

            token_id = self._generate_token_id()

            # Token public (sans valeur sensible)
            token = AnonymizedToken(
                token_id=token_id,
                data_type=item.data_type,
            )
            tokens.append(token)

            # Mapping sécurisé (valeur chiffrée)
            salt = os.urandom(12)  # Nonce GCM standard
            encrypted_value = aesgcm.encrypt(
                salt, item.snippet.encode("utf-8"), None
            )
            secure_mapping = SecureTokenMapping(
                token_id=token_id,
                encrypted_value=encrypted_value,
                salt=salt,
            )
            secure_mappings.append(secure_mapping)

            anonymized_text = anonymized_text.replace(item.snippet, token.placeholder)

        result = AnonymizedResult.create(anonymized_text, tokens, text_hash)
        return SecureAnonymizedData.create(
            result=result,
            secure_mappings=secure_mappings,
            key_id=self._compute_key_id(encryption_key),
        )

    def reveal(
        self, secure_data: SecureAnonymizedData, decryption_key: bytes
    ) -> str:
        """
        Révèle le texte original avec vérification de la clé.

        Args:
            secure_data: Données anonymisées avec mappings chiffrés
            decryption_key: Clé pour déchiffrer (doit correspondre à la clé de chiffrement)

        Returns:
            Texte original avec données sensibles restaurées

        Raises:
            InvalidCredentialsError: Si la clé est invalide
        """
        if len(decryption_key) != 32:
            raise InvalidCredentialsError("decryption_key must be 32 bytes")

        # Vérifier que la clé correspond
        key_id = self._compute_key_id(decryption_key)
        if key_id != secure_data.key_id:
            raise InvalidCredentialsError("Invalid decryption key")

        if not secure_data.secure_mappings:
            return secure_data.result.anonymized_text

        aesgcm = AESGCM(decryption_key)

        # Créer un mapping token_id -> valeur déchiffrée
        decrypted_values: Dict[str, str] = {}
        for mapping in secure_data.secure_mappings:
            try:
                decrypted_bytes = aesgcm.decrypt(
                    mapping.salt, mapping.encrypted_value, None
                )
                decrypted_values[mapping.token_id] = decrypted_bytes.decode("utf-8")
            except Exception as e:
                raise InvalidCredentialsError(f"Decryption failed: {e}")

        # Remplacer les placeholders par les valeurs originales
        revealed_text = secure_data.result.anonymized_text
        for token in secure_data.result.tokens:
            if token.token_id in decrypted_values:
                revealed_text = revealed_text.replace(
                    token.placeholder, decrypted_values[token.token_id]
                )

        return revealed_text

    def _generate_token_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def _compute_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _compute_key_id(self, key: bytes) -> str:
        """Compute a non-reversible identifier for the key."""
        return hashlib.sha256(key).hexdigest()[:16]


def generate_encryption_key() -> bytes:
    """Generate a secure 256-bit encryption key."""
    return os.urandom(32)
