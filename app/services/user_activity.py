# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tracker d'activité utilisateur — partagé entre le hook Flask before_request
et le sync service. Permet à la sync de différer son cycle quand un utilisateur
vient d'interagir (transcribe, compose, refine...) pour éviter la collision
GIL/réseau qui ralentit les endpoints user-facing.
"""

import threading
import time

_lock = threading.Lock()
_last_activity_ts: float = 0.0


def record_activity() -> None:
    """Marque qu'une requête user vient d'être traitée."""
    global _last_activity_ts
    with _lock:
        _last_activity_ts = time.monotonic()


def seconds_since_activity() -> float:
    """Retourne les secondes depuis la dernière activité, ou +inf si jamais."""
    with _lock:
        ts = _last_activity_ts
    if ts == 0.0:
        return float("inf")
    return time.monotonic() - ts
