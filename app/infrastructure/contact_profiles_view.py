# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Dict-like proxy over :class:`ContactStyleStorePort` (PR6 step 2).

Replaces the legacy ``Dict[str, Any]`` field that was attached to
``WritingStyleProfile.contact_profiles``. Preserves the entire callsite API
(``profile.contact_profiles.get(key)``, ``profile.contact_profiles[key] = data``,
``del profile.contact_profiles[key]``, ``len()``, iteration, ``.items()``,
``.keys()``, ``.values()``) so the ~25 existing callers continue to work
unchanged while the underlying source of truth migrates to SQLite.

Construction picks the backend ONCE :
    - production : the Container exposes a real ``ContactStyleStorePort``
      → all reads/writes route to SQLite (per-row locking, no global
      ``_FILE_LOCK`` corruption window, O(1) per-contact lookup)
    - tests / standalone : the Container or DB is unavailable → falls back
      to a per-instance in-memory dict so legacy tests that construct
      ``WritingStyleProfile(contact_profiles={...})`` keep working without
      requiring a mock store.

The fallback is opaque to callers : the same dict-like surface is honoured
in both modes. Tests that explicitly want store semantics can wire one via
``WritingStyleProfile.bind_contact_store(store)``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Tuple

logger = logging.getLogger(__name__)


class _ContactProfilesView:
    """Dict-like view over a ``ContactStyleStorePort``.

    Mode pinned at construction. ``store`` is resolved lazily from the
    Container ; if resolution fails (no Container in scope, no DB engine,
    schema bootstrap error) the view falls back to a per-instance dict so
    construction never raises.
    """

    __slots__ = ("_account_id", "_store", "_memory")

    def __init__(self, account_id: int, store: Any | None = None) -> None:
        self._account_id = account_id
        self._memory: Dict[str, dict] = {}
        if store is not None:
            self._store = store
            return
        # Lazy container resolution. Failure is benign — fall back to memory.
        try:
            from app.infrastructure.container import get_container

            self._store = get_container().get_contact_style_store()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Contact-style store unavailable (account=%s) — falling back to in-memory view: %s",
                account_id, exc,
            )
            self._store = None

    # ------------------------------------------------------------------
    # Dict protocol — reads
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        if not isinstance(key, str):
            return default
        key_lower = key.lower()
        if self._store is not None:
            cp = self._store.get(self._account_id, key_lower)
            return cp.to_dict() if cp is not None else default
        return self._memory.get(key_lower, default)

    def __getitem__(self, key: str) -> dict:
        value = self.get(key, default=None)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        key_lower = key.lower()
        if self._store is not None:
            return self._store.get(self._account_id, key_lower) is not None
        return key_lower in self._memory

    def __len__(self) -> int:
        if self._store is not None:
            return self._store.count_for_account(self._account_id)
        return len(self._memory)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __bool__(self) -> bool:
        return self.__len__() > 0

    def keys(self) -> List[str]:
        if self._store is not None:
            return [cp.email.lower() for cp in self._store.list_for_account(self._account_id)]
        return list(self._memory.keys())

    def values(self) -> List[dict]:
        if self._store is not None:
            return [cp.to_dict() for cp in self._store.list_for_account(self._account_id)]
        return list(self._memory.values())

    def items(self) -> List[Tuple[str, dict]]:
        if self._store is not None:
            from_db = {
                cp.email.lower(): cp.to_dict()
                for cp in self._store.list_for_account(self._account_id)
            }
            if not self._memory:
                return list(from_db.items())
            # Write-through cache entries override stale SQLite rows so that
            # snapshot() → JSON write captures the correct value even when a
            # prior upsert failed transiently.
            return list({**from_db, **self._memory}.items())
        return list(self._memory.items())

    # ------------------------------------------------------------------
    # Dict protocol — writes
    # ------------------------------------------------------------------

    def __setitem__(self, key: str, value: dict) -> None:
        """Upsert a contact's profile.

        ``value`` is the dict-form of a ``ContactStyleProfile`` (i.e. the
        output of ``ContactStyleProfile.to_dict()``). The view reconstitutes
        an entity instance for the upsert so the store sees a typed object.
        """
        if not isinstance(key, str):
            raise TypeError("contact email must be a string")
        if not isinstance(value, dict):
            raise TypeError("contact profile value must be a dict")
        key_lower = key.lower()
        # Defensive: ensure the email field matches the key (legacy JSON sometimes
        # had inconsistent casing between dict-key and inner ``email`` field).
        if "email" not in value or not value["email"]:
            value = {**value, "email": key_lower}
        # Always populate _memory as a write-through cache so that snapshot()
        # → items() returns the correct value even when the SQLite upsert fails
        # transiently.  This keeps the JSON mirror accurate and avoids a
        # vicious cycle where a failed upsert causes the JSON to be
        # (re-)written with the old value, perpetuating stale data across
        # restarts.
        self._memory[key_lower] = value
        if self._store is not None:
            from app.domain.entities.writing_style import ContactStyleProfile
            cp = ContactStyleProfile.from_dict(value)
            if not self._store.upsert(self._account_id, cp):
                logger.warning(
                    "Contact-style SQLite upsert failed for '%s' (account=%s) — "
                    "data kept in memory cache; JSON mirror will be written correctly",
                    key_lower, self._account_id,
                )

    def __delitem__(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("contact email must be a string")
        key_lower = key.lower()
        if self._store is not None:
            removed = self._store.delete(self._account_id, key_lower)
            if not removed:
                raise KeyError(key)
            self._memory.pop(key_lower, None)  # keep write-through cache consistent
        else:
            del self._memory[key_lower]

    def update(self, other: Dict[str, dict]) -> None:
        """Bulk-set entries (used by tests + ``WritingStyleProfile.from_dict``)."""
        for k, v in other.items():
            self[k] = v

    def clear(self) -> None:
        if self._store is not None:
            # Atomic clear via replace_account with empty list
            self._store.replace_account(self._account_id, [])
            self._memory.clear()  # keep write-through cache consistent
        else:
            self._memory.clear()

    # ------------------------------------------------------------------
    # JSON serialization helpers
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, dict]:
        """Return a plain ``dict`` snapshot for ``to_dict`` / JSON dump.

        Used by ``WritingStyleProfile.to_dict()`` so the legacy JSON file
        layout is preserved during the transition (the JSON profile file
        will keep emitting a ``contact_profiles`` key that mirrors the
        SQLite state). Once the migration is fully validated, the
        ``to_dict`` path can drop this snapshot entirely.
        """
        return dict(self.items())

    # ------------------------------------------------------------------
    # Repr — keep it short, debug-friendly
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        backend = "sqlite" if self._store is not None else "memory"
        return f"_ContactProfilesView(account_id={self._account_id}, backend={backend}, n={len(self)})"

    def __eq__(self, other: object) -> bool:
        """Support ``view == dict`` comparisons used by legacy tests
        (``assert profile.contact_profiles == {}``). Compares as a dict via
        items snapshot."""
        if isinstance(other, dict):
            return self.snapshot() == other
        if isinstance(other, _ContactProfilesView):
            return self.snapshot() == other.snapshot()
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    # ``__slots__`` disables ``__hash__`` auto-generation when ``__eq__`` is
    # defined manually. The view is mutable so it's intentionally unhashable —
    # explicit ``None`` makes that contract clear to callers.
    __hash__ = None  # type: ignore[assignment]
