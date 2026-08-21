"""Pytest fixture wiring for `tests/scripts/`.

Re-exports the SQLAlchemy session fixtures from `tests/db/_fixtures.py` so
migration script tests can use the same in-memory database setup the model
tests rely on.
"""

from tests.db._fixtures import (  # noqa: F401 — pytest fixture re-export
    engine,
    session,
    test_db_path,
)
