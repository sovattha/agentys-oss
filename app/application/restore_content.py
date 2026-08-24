# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

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
