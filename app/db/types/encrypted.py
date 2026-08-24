# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Application-layer column encryption via Fernet.

The OAuth Fernet key is the same one used to seal `oauth_tokens.json`
(`app/api/oauth.py`). It is loaded lazily to avoid an import cycle between
the SQLAlchemy model layer and the Flask OAuth blueprint.

Backward compatibility:
    Rows written before this decorator was wired contain plaintext. We do
    NOT raise on legacy plaintext at read time — we return it as-is so the
    application keeps functioning while the migration script
    (`scripts/encrypt_existing_oauth_tokens.py`) re-encrypts each row.
"""

from __future__ import annotations

from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

_FERNET_TOKEN_PREFIX = "gAAAAA"


def _get_fernet() -> Fernet:
    # Lazy import: `app.api.oauth` pulls in Flask routes; importing it at
    # module load time from the ORM layer creates a cycle during test
    # collection and during Alembic autogenerate.
    from app.api.oauth import _fernet

    return _fernet


class EncryptedString(TypeDecorator[str]):
    """Transparent Fernet column encryption.

    - ``process_bind_param`` encrypts plaintext before the row is written.
    - ``process_result_value`` decrypts ciphertext when the row is loaded.
    - Legacy plaintext (no Fernet prefix or fails to decrypt) is returned
      as-is for backward compatibility with un-migrated rows.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        token = _get_fernet().encrypt(value.encode("utf-8"))
        return token.decode("ascii")

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if not value.startswith(_FERNET_TOKEN_PREFIX):
            return value
        try:
            return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return value
