# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke tests — import critical modules and verify symbols referenced in try-imports.

Motivation: bug #290 slipped through because `from app.infrastructure.database
import get_db_session` was inside an `except Exception` handler — the module
itself imports cleanly, but the inner import raised `ImportError` at runtime
which was then silently swallowed by `logger.debug(...)`.

Strategy:
1. `MODULE_IMPORTS`: each critical module must import without raising.
2. `SYMBOL_EXISTS`: symbols referenced inside `try:` blocks elsewhere in the
   codebase must exist on their declared module (catches the ImportError
   case even when the caller swallows it).
3. `METHOD_EXISTS`: methods called on those symbols must exist (catches the
   AttributeError case — that's how `AccountRepository.get_by_id` slipped in).

Extend these lists when new critical modules or cross-module symbol imports
appear. Keep scope focused: only include symbols that are imported from
within a function/try block, not module-level imports (those are covered
by MODULE_IMPORTS alone).
"""

from __future__ import annotations

import importlib

import pytest

# Modules whose top-level imports must never break CI. Extend carefully —
# every entry here is a promise that the module is safe to import from any
# context (worker, web request, cron, migration).
MODULE_IMPORTS: list[str] = [
    "app.api.websocket",
    "app.api.onboarding",
    "app.api.routes_helpers",
    "app.onboarding.manager",
    "app.faq_agent",
    "app.db.database",
    "app.db.repositories.account_repository",
]


# Symbols referenced via `from X import Y` inside try-blocks (and therefore
# invisible to MODULE_IMPORTS alone). Bug #290 root cause: two of these were
# wrong for 5 days in prod without any test catching it.
SYMBOL_EXISTS: list[tuple[str, str]] = [
    ("app.db.database", "get_db_session"),
    ("app.db.database", "get_session_factory"),
    ("app.db.repositories.account_repository", "AccountRepository"),
    ("app.api.websocket", "emit_to_account"),
    ("app.api.websocket", "_resolve_room_for_account"),
    ("app.db.models.account", "Account"),
    ("app.db.models.email", "Email"),
]


# Methods called on the symbols above. Catches the `AttributeError` category
# of silent failures (e.g. `AccountRepository.get_by_id` — which never
# existed but was called from 3 sites in prod).
METHOD_EXISTS: list[tuple[str, str, str]] = [
    # (module, class/obj, method)
    ("app.db.repositories.account_repository", "AccountRepository", "get"),
    ("app.db.repositories.account_repository", "AccountRepository", "get_by_email"),
    ("app.db.repositories.account_repository", "AccountRepository", "get_active_accounts"),
]


@pytest.mark.parametrize("module_path", MODULE_IMPORTS)
def test_module_imports_cleanly(module_path: str) -> None:
    """Importing the module must not raise — caught at PR CI time, not in prod."""
    importlib.import_module(module_path)


@pytest.mark.parametrize(("module_path", "symbol"), SYMBOL_EXISTS)
def test_symbol_is_exported(module_path: str, symbol: str) -> None:
    """The symbol must be importable via `from <module> import <symbol>`.

    Guards against renames and cross-module refactors that leave stale
    imports inside `try:` blocks — the exact pattern that caused #290.
    """
    module = importlib.import_module(module_path)
    assert hasattr(module, symbol), (
        f"Module {module_path!r} does not export {symbol!r}. "
        f"A caller importing this symbol inside a try-block will raise "
        f"ImportError at runtime and silently skip its logic."
    )


@pytest.mark.parametrize(("module_path", "cls_name", "method_name"), METHOD_EXISTS)
def test_method_exists(module_path: str, cls_name: str, method_name: str) -> None:
    """The method must exist on the class (either defined or inherited).

    Catches the `AttributeError` bucket of bug #290: `AccountRepository.get_by_id`
    was called from 3 sites but never existed (inherited method is `.get()`).
    """
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    assert hasattr(cls, method_name), (
        f"{cls_name}.{method_name} does not exist on {module_path!r}. "
        f"Callers expecting this method will raise AttributeError."
    )
