# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

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
