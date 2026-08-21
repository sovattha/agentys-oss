"""Stable account identity helpers shared by auth and OAuth paths."""

from __future__ import annotations

import hashlib


def user_id_from_email(email: str) -> int:
    """Stable user_id derived from sha256(email)[:8] interpreted as int.

    Returns a 32-bit unsigned integer (range 0 .. 2**32 - 1). Idempotent
    on lowercase normalization. The previous implementation truncated
    further to ``% 100000`` which gave only ~17 bits of effective space; the
    audit found this could yield cross-user data leakage by birthday paradox
    once the install reached ~316 active users.
    """
    return int(hashlib.sha256(email.lower().encode()).hexdigest()[:8], 16)
