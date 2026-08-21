"""Adapter Fernet pour le port EncryptionPort."""
from typing import Dict

from app.domain.ports.encryption_port import EncryptionPort
from app.infrastructure.security import EncryptionManager


class FernetEncryptionAdapter(EncryptionPort):
    """Implémentation du port EncryptionPort utilisant Fernet via EncryptionManager."""

    def __init__(self):
        self._manager = EncryptionManager()

    def encrypt_mapping(self, mapping: Dict[str, str]) -> str:
        return self._manager.encrypt_dict(mapping)

    def decrypt_mapping(self, encrypted_token: str) -> Dict[str, str]:
        return self._manager.decrypt_dict(encrypted_token)
