"""Use case pour anonymiser le contenu en remplaçant les données sensibles."""
import uuid
from dataclasses import dataclass
from typing import Dict

from app.domain.entities.anonymized_result import AnonymizedResult
from app.domain.ports.encryption_port import EncryptionPort
from app.domain.ports.sensitive_data_port import SensitiveDataDetectorPort


@dataclass
class AnonymizeContentUseCase:
    """Orchestre la détection et l'anonymisation des données sensibles."""

    detector: SensitiveDataDetectorPort
    encryption: EncryptionPort

    def execute(self, content: str, recipient: str) -> AnonymizedResult:
        detection = self.detector.detect(content, recipient)

        if not detection.is_sensitive:
            return AnonymizedResult.empty(content, detection)

        anonymized_content = content
        mapping: Dict[str, str] = {}

        for index, item in enumerate(detection.detected_items):
            marker = f"[REDACTED_{uuid.uuid4().hex[:8]}{index:04x}]"
            anonymized_content = anonymized_content.replace(item.snippet, marker, 1)
            mapping[marker] = item.snippet

        encrypted_token = self.encryption.encrypt_mapping(mapping) if mapping else ""

        return AnonymizedResult(
            anonymized_content=anonymized_content,
            encrypted_token=encrypted_token,
            items_anonymized=len(mapping),
            detection=detection,
        )
