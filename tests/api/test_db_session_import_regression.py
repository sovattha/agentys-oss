# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Regression test for audit F-02 (2026-05-03).

Two recently-modified files imported `from app.db.session import get_db_session`
which raises ModuleNotFoundError because the correct module is
`app.db.database`. Both call sites silently swallowed via `except Exception:
pass`, so the wizard env-config endpoint reported OAuth-configured users as
unconfigured (matches MEMORY.md "Wizard env-config user scope" lesson) and
the spam-learn helper got empty subject/body for downstream LabelingRules.

This test locks the contract:
  1. `app.db.session` must NOT exist (so a future "fix" that re-adds the wrong
     name is caught at import time).
  2. `app.db.database` must export `get_db_session`.
  3. The two known-historic call sites must reference `app.db.database`,
     never `app.db.session` — verified via static AST scan so we don't have
     to spin up a Flask test client.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Files that historically imported the broken `app.db.session` name. Any new
# call site added in the future is welcome — but it must use the canonical
# `app.db.database` module.
_KNOWN_HISTORIC_CALLERS = (
    _REPO_ROOT / "app" / "api" / "wizard.py",
    _REPO_ROOT / "app" / "api" / "routes_helpers.py",
)


def test_app_db_session_module_must_not_exist():
    """Negative assertion: there must be no `app.db.session` module.

    If somebody re-adds it (e.g. as a thin re-export to "fix" the broken
    callers), the regression below stops protecting against the original
    bug. Better to keep the canonical module name unique.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.db.session")


def test_app_db_database_exports_get_db_session():
    """The canonical module must export the contextmanager the callers need."""
    module = importlib.import_module("app.db.database")
    assert hasattr(module, "get_db_session"), (
        "`app.db.database` must export `get_db_session` — historic callers "
        "in app/api/wizard.py and app/api/routes_helpers.py rely on it."
    )
    # And it should still be a context manager (callable returning a CM).
    assert callable(module.get_db_session)


@pytest.mark.parametrize("file_path", _KNOWN_HISTORIC_CALLERS, ids=lambda p: p.name)
def test_no_caller_imports_broken_app_db_session(file_path: Path):
    """Static AST scan: forbid `from app.db.session import …` in known callers.

    The audit's preferred verification was a Flask-test-client hit on
    /api/wizard/env-config, but that requires booting the whole app. AST is
    O(ms) and catches the same regression at the source level.
    """
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    offenders = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.db.session"
    ]
    assert not offenders, (
        f"{file_path.name} contains `from app.db.session import …` at "
        f"line(s) {[n.lineno for n in offenders]}. The module does not exist; "
        f"use `from app.db.database import …` instead. Audit F-02 (2026-05-03)."
    )


@pytest.mark.parametrize("file_path", _KNOWN_HISTORIC_CALLERS, ids=lambda p: p.name)
def test_caller_imports_canonical_app_db_database(file_path: Path):
    """Positive assertion: each historic caller must reference the right module.

    Pairs with the negative test above. If a future refactor moves the DB
    session helper out of `app.db.database`, this test forces the touch
    point to be updated explicitly rather than silently degrading.
    """
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    has_canonical = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.db.database"
        and any(alias.name == "get_db_session" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert has_canonical, (
        f"{file_path.name} must import `get_db_session` from `app.db.database` "
        f"so the DB-account branch / spam-learn email-fetch keep working. "
        f"Audit F-02 (2026-05-03)."
    )
