# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Quick Steps test scoping.

The engine ships an audit-log writer that calls ``get_db_session`` against
the real DB. Engine unit tests stub provider/email/account loaders but
don't bring up a SQLAlchemy session — without this fixture, the audit
recorder would fall through to ``app.db.database.get_db_session``, which
may attach to the on-disk ``agentys.db`` and pollute real data.

Patching the engine module's ``_default_audit_recorder`` to a no-op keeps
unit tests pure-Python while leaving the production code path unchanged.
The dedicated audit tests opt back in by passing ``audit_recorder``
explicitly to ``execute()``.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _silence_engine_audit(monkeypatch):
    from app.quicksteps import engine as engine_module
    monkeypatch.setattr(
        engine_module,
        "_default_audit_recorder",
        lambda **_kwargs: None,
    )
    yield
