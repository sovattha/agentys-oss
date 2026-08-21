"""
Tests for the database module.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db.database import (
    _configure_postgres_session,
    _normalize_database_url,
    get_db_path,
    get_database_url,
    get_engine,
    get_session,
    get_session_factory,
    get_db_session,
    init_db,
    reset_engine,
    check_database_health,
)
from app.db.models import Base, Account


class TestGetDbPath:
    """Tests for get_db_path function."""

    def test_default_path_is_in_user_data(self):
        """Test default path uses user data directory."""
        # Clear any env override
        with patch.dict(os.environ, {}, clear=True):
            path = get_db_path()

        assert path.name == "agentys.db"
        # Path should contain 'agentys' in the parent directories
        assert "agentys" in str(path).lower()

    def test_env_override(self):
        """Test AGENTYS_DB_PATH environment variable override."""
        custom_path = "/custom/path/to/db.sqlite"
        with patch.dict(os.environ, {"AGENTYS_DB_PATH": custom_path}):
            path = get_db_path()

        # Normalize path separators for cross-platform compatibility
        import os as _os
        assert str(path) == str(_os.path.normpath(custom_path))

    def test_creates_parent_directory(self):
        """Test that parent directory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "nested" / "dir"
            custom_path = custom_dir / "agentys.db"

            with patch.dict(os.environ, {"AGENTYS_DB_PATH": str(custom_path)}):
                path = get_db_path()

            # Parent directory should NOT be created by get_db_path
            # (only user data dir is created)
            assert str(path) == str(custom_path)


class TestEngine:
    """Tests for engine management."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_get_engine_creates_engine(self):
        """Test get_engine creates an engine."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            assert engine is not None
            # Should return same engine on second call
            engine2 = get_engine()
            assert engine is engine2
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_get_engine_with_echo(self):
        """Test echo mode can be enabled."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"AGENTYS_DB_ECHO": "true"}):
                reset_engine()
                engine = get_engine(db_path)
                assert engine.echo is True
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_database_url_normalizes_railway_postgres_scheme(self):
        raw = "postgres://agentys:secret@localhost:5432/agentys"
        assert (
            _normalize_database_url(raw)
            == "postgresql+psycopg://agentys:secret@localhost:5432/agentys"
        )

    def test_get_database_url_normalizes_postgres_scheme(self):
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://agentys:secret@localhost/agentys"
        }):
            assert get_database_url() == "postgresql+psycopg://agentys:secret@localhost/agentys"

    def test_database_url_is_ignored_when_db_path_explicit(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            with patch.dict(os.environ, {
                "DATABASE_URL": "postgres://agentys:secret@localhost/agentys"
            }):
                engine = get_engine(db_path=db_path)
                assert engine.dialect.name == "sqlite"
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_non_postgres_database_url_is_rejected(self):
        # Belt-and-suspenders: setup_method already calls reset_engine, but
        # in CI's sharded runner a prior test in the shard can leave
        # `_engine` populated through a path that races setup_method. Reset
        # explicitly so the test asserts on a clean cache regardless.
        reset_engine()
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:////tmp/agentys.db"}):
            with pytest.raises(ValueError, match="DATABASE_URL is only supported"):
                get_engine()

    def test_production_requires_database_url(self):
        with patch.dict(os.environ, {
            "ENVIRONMENT": "production",
            "AGENTYS_DB_PATH": "/data/agentys/agentys.db",
        }, clear=True):
            with pytest.raises(RuntimeError, match="production requires DATABASE_URL"):
                get_engine()

    def test_production_allows_explicit_sqlite_path_for_tools(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
                engine = get_engine(db_path=db_path)
                assert engine.dialect.name == "sqlite"
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_configure_postgres_session_uses_set_config(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.closed = False

            def execute(self, sql, params):
                self.calls.append((sql, params))

            def close(self):
                self.closed = True

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

        conn = Connection()
        with patch.dict(os.environ, {
            "AGENTYS_PG_STATEMENT_TIMEOUT_MS": "12345",
            "AGENTYS_PG_IDLE_TX_TIMEOUT_MS": "23456",
        }):
            _configure_postgres_session(conn, None)

        assert conn.cursor_obj.calls == [
            ("SELECT set_config('statement_timeout', %s, false)", ("12345",)),
            (
                "SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
                ("23456",),
            ),
        ]
        assert conn.cursor_obj.closed is True


class TestSessionFactory:
    """Tests for session factory."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_get_session_factory_creates_factory(self):
        """Test get_session_factory creates a sessionmaker."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            factory = get_session_factory(engine)
            assert factory is not None

            # Should return same factory on second call
            factory2 = get_session_factory()
            assert factory is factory2
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_get_session_returns_session(self):
        """Test get_session returns a session."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            get_engine(db_path)
            session = get_session()
            assert session is not None
            session.close()
        finally:
            reset_engine()
            os.unlink(db_path)


class TestDbSessionContextManager:
    """Tests for get_db_session context manager."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_context_manager_commits_on_success(self):
        """Test context manager commits on successful exit."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            Base.metadata.create_all(bind=engine)

            with get_db_session() as session:
                account = Account(email="test@example.com", provider="gmail")
                session.add(account)

            # Should be committed - verify with new session
            with get_db_session() as session:
                count = session.query(Account).count()
                assert count == 1
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_context_manager_rollbacks_on_error(self):
        """Test context manager rolls back on error."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            Base.metadata.create_all(bind=engine)

            with pytest.raises(ValueError):
                with get_db_session() as session:
                    account = Account(email="test@example.com", provider="gmail")
                    session.add(account)
                    raise ValueError("Test error")

            # Should be rolled back - verify with new session
            with get_db_session() as session:
                count = session.query(Account).count()
                assert count == 0
        finally:
            reset_engine()
            os.unlink(db_path)


class TestInitDb:
    """Tests for init_db function."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_init_db_creates_tables(self):
        """Test init_db creates all tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            init_db(engine)

            # Check tables exist
            from sqlalchemy import inspect

            inspector = inspect(engine)
            tables = inspector.get_table_names()

            assert "accounts" in tables
            assert "emails" in tables
            assert "contacts" in tables
            assert "drafts" in tables
        finally:
            reset_engine()
            os.unlink(db_path)


class TestCheckDatabaseHealth:
    """Tests for check_database_health function."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_healthy_database(self):
        """Test health check on healthy database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            with patch.dict(os.environ, {"AGENTYS_DB_PATH": str(db_path)}):
                engine = get_engine(db_path)
                init_db(engine)

                health = check_database_health()

                assert health["status"] == "healthy"
                assert health["connection_test"] is True
                assert "database_path" in health
                assert "database_size_bytes" in health
        finally:
            reset_engine()
            os.unlink(db_path)


class TestSqlitePragmas:
    """Tests for SQLite pragma configuration."""

    def setup_method(self):
        """Reset engine before each test."""
        reset_engine()

    def teardown_method(self):
        """Reset engine after each test."""
        reset_engine()

    def test_foreign_keys_enabled(self):
        """Test foreign keys pragma is enabled."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            with engine.connect() as conn:
                result = conn.execute(
                    __import__("sqlalchemy").text("PRAGMA foreign_keys")
                ).scalar()
                assert result == 1
        finally:
            reset_engine()
            os.unlink(db_path)

    def test_wal_mode_enabled(self):
        """Test WAL journal mode is enabled."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            engine = get_engine(db_path)
            with engine.connect() as conn:
                result = conn.execute(
                    __import__("sqlalchemy").text("PRAGMA journal_mode")
                ).scalar()
                assert result.lower() == "wal"
        finally:
            reset_engine()
            os.unlink(db_path)
