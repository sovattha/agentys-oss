"""
Adapter Fernet pour les operations cryptographiques.

Implemente CryptographerPort avec chiffrement symetrique AES-128-CBC
via la bibliotheque cryptography (Fernet).
"""

import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.domain.ports.cryptographer_port import CryptographerPort


class FernetCryptographerAdapter(CryptographerPort):
    """Adapter Fernet pour le chiffrement symetrique."""

    def __init__(self, key: bytes | str | None = None):
        if key is None:
            key = Fernet.generate_key()
        elif isinstance(key, str):
            key = key.encode("utf-8")
        self._fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        encrypted_bytes = self._fernet.encrypt(data.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")

    def decrypt(self, encrypted_data: str) -> str:
        try:
            decrypted_bytes = self._fernet.decrypt(encrypted_data.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as e:
            raise ValueError("Decryption failed: invalid token or key") from e

    def encrypt_dict(self, data: dict[str, Any]) -> str:
        json_str = json.dumps(data, ensure_ascii=False)
        return self.encrypt(json_str)

    def decrypt_dict(self, encrypted_data: str) -> dict[str, Any]:
        try:
            decrypted_str = self.decrypt(encrypted_data)
            result = json.loads(decrypted_str)
            if not isinstance(result, dict):
                raise ValueError(
                    f"Decryption failed: expected dict, got {type(result).__name__}"
                )
            return result
        except json.JSONDecodeError as e:
            raise ValueError("Decryption failed: invalid JSON") from e

    def hash_email(self, email: str) -> str:
        normalized = email.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
