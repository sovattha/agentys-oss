"""Use case pour restaurer le contenu original à partir du contenu anonymisé."""
from dataclasses import dataclass

from app.domain.ports.encryption_port import EncryptionPort


@dataclass
class RestoreContentUseCase:
    """Restaure le contenu original en déchiffrant et remplaçant les marqueurs."""

    encryption: EncryptionPort

    def execute(self, anonymized_content: str, encrypted_token: str) -> str:
        if not encrypted_token:
            return anonymized_content

        mapping = self.encryption.decrypt_mapping(encrypted_token)
        restored = anonymized_content

        for marker, original_value in mapping.items():
            restored = restored.replace(marker, original_value)

        return restored
