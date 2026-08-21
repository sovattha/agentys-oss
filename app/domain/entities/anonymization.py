from dataclasses import dataclass
from typing import Any, Dict, List


from app.domain.entities.sensitive_data import SensitiveDataType


@dataclass(frozen=True)
class AnonymizedToken:
    """Token public sans valeur originale - sécurisé pour sérialisation."""
    token_id: str
    data_type: SensitiveDataType

    @property
    def placeholder(self) -> str:
        return f"[ANON:{self.data_type.value.upper()}:{self.token_id}]"

    def to_dict(self) -> Dict[str, str]:
        """Sérialise le token en dictionnaire."""
        return {"token_id": self.token_id, "data_type": self.data_type.value}

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "AnonymizedToken":
        """Crée un token depuis un dictionnaire."""
        return cls(
            token_id=data["token_id"],
            data_type=SensitiveDataType(data["data_type"]),
        )


@dataclass(frozen=True)
class SecureTokenMapping:
    """Mapping sécurisé token -> valeur chiffrée. À stocker séparément."""
    token_id: str
    encrypted_value: bytes
    salt: bytes

    def to_dict(self) -> Dict[str, str]:
        """Sérialise le mapping en dictionnaire (hex pour bytes)."""
        return {
            "token_id": self.token_id,
            "encrypted_value": self.encrypted_value.hex(),
            "salt": self.salt.hex(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "SecureTokenMapping":
        """Crée un mapping depuis un dictionnaire."""
        return cls(
            token_id=data["token_id"],
            encrypted_value=bytes.fromhex(data["encrypted_value"]),
            salt=bytes.fromhex(data["salt"]),
        )


@dataclass(frozen=True)
class AnonymizedResult:
    """Résultat public de l'anonymisation - NE CONTIENT PAS les valeurs originales."""
    anonymized_text: str
    tokens: tuple  # Tuple[AnonymizedToken] - sans valeurs sensibles
    original_text_hash: str

    @classmethod
    def create(
        cls, anonymized_text: str, tokens: List[AnonymizedToken], original_text_hash: str
    ) -> "AnonymizedResult":
        return cls(
            anonymized_text=anonymized_text,
            tokens=tuple(tokens),
            original_text_hash=original_text_hash,
        )

    @classmethod
    def empty(cls, original_text: str, original_text_hash: str) -> "AnonymizedResult":
        return cls(
            anonymized_text=original_text,
            tokens=(),
            original_text_hash=original_text_hash,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise le résultat en dictionnaire."""
        return {
            "anonymized_text": self.anonymized_text,
            "tokens": [t.to_dict() for t in self.tokens],
            "original_text_hash": self.original_text_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnonymizedResult":
        """Crée un résultat depuis un dictionnaire."""
        tokens = [AnonymizedToken.from_dict(t) for t in data["tokens"]]
        return cls(
            anonymized_text=data["anonymized_text"],
            tokens=tuple(tokens),
            original_text_hash=data["original_text_hash"],
        )


@dataclass(frozen=True)
class SecureAnonymizedData:
    """Conteneur complet avec données chiffrées - accès restreint."""
    result: AnonymizedResult
    secure_mappings: tuple  # Tuple[SecureTokenMapping]
    key_id: str  # Référence à la clé utilisée pour le chiffrement

    @classmethod
    def create(
        cls,
        result: AnonymizedResult,
        secure_mappings: List[SecureTokenMapping],
        key_id: str,
    ) -> "SecureAnonymizedData":
        return cls(
            result=result,
            secure_mappings=tuple(secure_mappings),
            key_id=key_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise les données anonymisées en dictionnaire."""
        return {
            "result": self.result.to_dict(),
            "secure_mappings": [m.to_dict() for m in self.secure_mappings],
            "key_id": self.key_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecureAnonymizedData":
        """Crée des données anonymisées depuis un dictionnaire."""
        result = AnonymizedResult.from_dict(data["result"])
        secure_mappings = [SecureTokenMapping.from_dict(m) for m in data["secure_mappings"]]
        return cls(
            result=result,
            secure_mappings=tuple(secure_mappings),
            key_id=data["key_id"],
        )
