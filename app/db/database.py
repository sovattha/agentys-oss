"""
Database engine and session management for Agentys.

Uses SQLAlchemy 2.x with PostgreSQL in production, selected by DATABASE_URL.
Local/desktop installs keep SQLite/SQLCipher by default, stored in the user
data directory (~/.agentys/data/agentys.db).

Supports optional AES-256 encryption via SQLCipher.
Encryption key stored in OS Keychain (NFR10, NFR11 compliance).
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from platformdirs import user_data_dir
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.encryption import (
    EncryptionConfig,
    WrongKeyError,
    _validate_hex_key,
    get_encryption_config,
    get_or_create_encryption_key,
    get_sqlcipher_pragmas,
    is_encryption_enabled,
)

logger = logging.getLogger(__name__)

# Application identifiers for platformdirs
APP_NAME = "agentys"
APP_AUTHOR = "agentys"

# Database filename
DB_FILENAME = "agentys.db"
DB_ENCRYPTED_FILENAME = "agentys_encrypted.db"

# Global engine and session factory (lazy initialized)
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_encryption_config: EncryptionConfig | None = None


def _normalize_database_url(raw_url: str) -> str:
    """Return a SQLAlchemy URL string with an explicit supported driver."""
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://"):]
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://"):]
    return raw_url


def get_database_url() -> str | None:
    """Return the configured SQL database URL, if any.

    DATABASE_URL is intentionally ignored when get_engine(db_path=...) is used:
    explicit test/local SQLite paths must keep winning over ambient prod env.
    """
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        return None
    return _normalize_database_url(raw_url)


def _is_postgres_url(database_url: str) -> bool:
    return make_url(database_url).get_backend_name() == "postgresql"


def _redact_database_url(database_url: str) -> str:
    url = make_url(database_url)
    return url.render_as_string(hide_password=True)


def _is_production_environment() -> bool:
    if os.environ.get("AGENTYS_LOAD_TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return any(
        os.environ.get(name) == "production"
        for name in (
            "FLASK_ENV",
            "ENVIRONMENT",
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
        )
    )


def _sqlite_busy_timeout_ms(default: int = 60000) -> int:
    raw = os.environ.get("AGENTYS_SQLITE_BUSY_TIMEOUT_MS")
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid AGENTYS_SQLITE_BUSY_TIMEOUT_MS=%r; using %d", raw, default)
        return default
    return max(1000, min(value, 300000))


def get_db_path(encrypted: bool = False) -> Path:
    """
    Get the database file path.

    Uses platformdirs for cross-platform user data directory:
    - macOS: ~/Library/Application Support/agentys/
    - Windows: C:/Users/<user>/AppData/Local/agentys/agentys/
    - Linux: ~/.local/share/agentys/

    Can be overridden with AGENTYS_DB_PATH environment variable.

    Args:
        encrypted: If True, returns path for encrypted database.

    Returns:
        Path to the SQLite database file.
    """
    # Allow override via environment variable
    env_path = os.environ.get("AGENTYS_DB_PATH")
    if env_path:
        return Path(env_path)

    # Use platformdirs for user data directory
    data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = DB_ENCRYPTED_FILENAME if encrypted else DB_FILENAME
    return data_dir / filename


def _get_sqlite_module():
    """
    Get the appropriate SQLite module based on encryption config.

    Returns sqlcipher3 if encryption is enabled, else sqlite3.
    """
    if is_encryption_enabled():
        try:
            from sqlcipher3 import dbapi2 as sqlcipher

            return sqlcipher
        except ImportError:
            logger.warning(
                "sqlcipher3 not installed, falling back to unencrypted sqlite3"
            )
            return sqlite3
    return sqlite3


def _configure_sqlite_pragmas(
    dbapi_conn, connection_record, encryption_config: Optional[EncryptionConfig] = None
) -> None:
    """
    Configure SQLite/SQLCipher pragmas for optimal performance and security.

    Called on each new connection via SQLAlchemy event.
    """
    cursor = dbapi_conn.cursor()

    # Apply encryption pragmas first if enabled
    if encryption_config and encryption_config.enabled and encryption_config.key:
        pragmas = get_sqlcipher_pragmas(encryption_config)
        for pragma in pragmas:
            cursor.execute(pragma)

    # Enable foreign key constraints
    cursor.execute("PRAGMA foreign_keys = ON")

    # Use WAL mode for better concurrent read/write performance
    cursor.execute("PRAGMA journal_mode = WAL")

    # Wait for transient writer locks instead of failing immediately.
    cursor.execute(f"PRAGMA busy_timeout = {_sqlite_busy_timeout_ms()}")

    # Synchronous NORMAL for better performance with WAL
    cursor.execute("PRAGMA synchronous = NORMAL")

    # Increase cache size to 64MB for better read performance
    cursor.execute("PRAGMA cache_size = -64000")

    # Store temp tables in memory
    cursor.execute("PRAGMA temp_store = MEMORY")

    # Enable memory-mapped I/O (256MB)
    cursor.execute("PRAGMA mmap_size = 268435456")

    cursor.close()


def _configure_postgres_session(dbapi_conn, connection_record) -> None:
    """Apply conservative per-connection PostgreSQL session limits."""
    statement_timeout_ms = int(os.environ.get("AGENTYS_PG_STATEMENT_TIMEOUT_MS", "30000"))
    idle_timeout_ms = int(os.environ.get("AGENTYS_PG_IDLE_TX_TIMEOUT_MS", "30000"))
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("SELECT set_config('statement_timeout', %s, false)", (str(statement_timeout_ms),))
        cursor.execute(
            "SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
            (str(idle_timeout_ms),),
        )
    finally:
        cursor.close()


def _create_connection(
    db_path: Path, encryption_config: Optional[EncryptionConfig] = None
):
    """
    Create a database connection with optional encryption.

    Args:
        db_path: Path to the database file.
        encryption_config: Optional encryption configuration.

    Returns:
        Database connection object.

    Raises:
        WrongKeyError: If encryption key is invalid.
    """
    sqlite_module = _get_sqlite_module()
    conn = sqlite_module.connect(
        str(db_path),
        check_same_thread=False,
        timeout=_sqlite_busy_timeout_ms() / 1000,
    )

    if encryption_config and encryption_config.enabled and encryption_config.key:
        cursor = conn.cursor()
        try:
            # Validate key format before PRAGMA (prevents injection)
            _validate_hex_key(encryption_config.key)
            # Apply encryption key
            cursor.execute(f"PRAGMA key = \"x'{encryption_config.key}'\"")
            # Verify the key is correct by reading from database
            cursor.execute("SELECT count(*) FROM sqlite_master")
            cursor.fetchone()
        except Exception as e:
            conn.close()
            if "file is not a database" in str(e).lower():
                raise WrongKeyError("Invalid encryption key for database") from e
            raise
        finally:
            cursor.close()

    return conn


def get_engine(
    db_path: Path | None = None, encryption_key: str | None = None
) -> Engine:
    """
    Get or create the SQLAlchemy engine.

    Args:
        db_path: Optional path to database file. If None, uses default path.
        encryption_key: Optional encryption key. If None, retrieves from keychain.

    Returns:
        SQLAlchemy Engine configured for PostgreSQL in production, or
        SQLite/SQLCipher for local/desktop paths.

    Raises:
        WrongKeyError: If encryption key is invalid.
    """
    global _engine, _encryption_config

    if _engine is not None:
        return _engine

    database_url = get_database_url() if db_path is None else None
    if database_url is not None:
        if not _is_postgres_url(database_url):
            raise ValueError(
                "DATABASE_URL is only supported for PostgreSQL in Agentys prod. "
                "Use AGENTYS_DB_PATH for SQLite."
            )

        _encryption_config = EncryptionConfig(enabled=False, key=None)
        logger.info("Database backend: PostgreSQL (%s)", _redact_database_url(database_url))
        _engine = create_engine(
            database_url,
            pool_size=int(os.environ.get("AGENTYS_PG_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("AGENTYS_PG_MAX_OVERFLOW", "10")),
            pool_timeout=int(os.environ.get("AGENTYS_PG_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.environ.get("AGENTYS_PG_POOL_RECYCLE", "1800")),
            pool_pre_ping=True,
            echo=os.environ.get("AGENTYS_DB_ECHO", "").lower() == "true",
        )
        event.listen(_engine, "connect", _configure_postgres_session)
        return _engine

    if db_path is None and _is_production_environment():
        raise RuntimeError(
            "CRITICAL: production requires DATABASE_URL for the main database. "
            "Refusing to fall back to SQLite/SQLCipher because that can split "
            "writes between PostgreSQL and /data/agentys/agentys.db. Set "
            "DATABASE_URL to the Railway PostgreSQL URL, or pass db_path "
            "explicitly only for one-off migration/inspection scripts."
        )

    # Get encryption configuration
    _encryption_config = get_encryption_config()

    # Override key if provided
    if encryption_key and _encryption_config.enabled:
        _encryption_config = EncryptionConfig(
            enabled=True,
            key=encryption_key,
            cipher_page_size=_encryption_config.cipher_page_size,
            kdf_iter=_encryption_config.kdf_iter,
            cipher_hmac_algorithm=_encryption_config.cipher_hmac_algorithm,
            cipher_kdf_algorithm=_encryption_config.cipher_kdf_algorithm,
        )

    # Get or create key if encryption enabled but no key
    if _encryption_config.enabled and not _encryption_config.key:
        try:
            key = get_or_create_encryption_key()
            _encryption_config = EncryptionConfig(
                enabled=True,
                key=key,
                cipher_page_size=_encryption_config.cipher_page_size,
                kdf_iter=_encryption_config.kdf_iter,
                cipher_hmac_algorithm=_encryption_config.cipher_hmac_algorithm,
                cipher_kdf_algorithm=_encryption_config.cipher_kdf_algorithm,
            )
        except Exception as e:
            # CASA V6.2 #206 fail-closed: in production, refuse to boot if the
            # encryption key is unavailable AND the on-disk DB looks encrypted.
            # The previous behaviour silently fell back to plaintext, which on
            # a now-encrypted DB produced the cryptic "file is not a database"
            # at first PRAGMA — masking a real key-config problem as a corruption
            # report.
            _candidate_path = db_path or get_db_path(encrypted=True)
            try:
                _file_is_encrypted = is_database_encrypted(_candidate_path)
            except Exception:
                _file_is_encrypted = False
            if _is_production_environment() and _file_is_encrypted:
                raise RuntimeError(
                    f"CRITICAL: production DB at {_candidate_path} is encrypted "
                    f"but AGENTYS_ENCRYPTION_KEY is not set (or keychain lookup failed: {e}). "
                    "Booting plaintext on an encrypted file would crash on the first "
                    "PRAGMA with a misleading 'file is not a database' error. "
                    "Set AGENTYS_ENCRYPTION_KEY to the SQLCipher hex key from your "
                    "password manager. See docs/security/data-at-rest.md."
                ) from e
            # Dev / non-prod / not-yet-encrypted: graceful fallback so local
            # dev installs that haven't set up the keychain still boot.
            logger.warning(f"Encryption key unavailable, booting unencrypted: {e}")
            # Fall back to unencrypted
            _encryption_config = EncryptionConfig(enabled=False, key=None)

    if db_path is None:
        db_path = get_db_path(encrypted=_encryption_config.enabled)

    # Log encryption status
    if _encryption_config.enabled:
        logger.info(f"Database encryption enabled (AES-256, {db_path})")
    else:
        logger.info(f"Database encryption disabled ({db_path})")

    # Create engine with custom connection creator
    def _creator():
        return _create_connection(db_path, _encryption_config)

    # Create SQLite connection URL (using standard sqlite for URL, custom creator handles SQLCipher)
    db_url = f"sqlite:///{db_path}"

    # Create engine with connection pooling
    # WAL mode allows concurrent readers — pool_size=5 handles parallel requests
    # (inbox + sent + archives loading simultaneously from the frontend).
    _engine = create_engine(
        db_url,
        creator=_creator,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_pre_ping=True,  # Verify connections before use
        echo=os.environ.get("AGENTYS_DB_ECHO", "").lower() == "true",
    )

    # Register event listener for SQLite pragmas
    def _configure_pragmas(dbapi_conn, connection_record):
        _configure_sqlite_pragmas(dbapi_conn, connection_record, _encryption_config)

    event.listen(_engine, "connect", _configure_pragmas)

    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """
    Get or create the session factory.

    Args:
        engine: Optional engine to use. If None, uses default engine.

    Returns:
        SQLAlchemy sessionmaker configured for the engine.
    """
    global _session_factory

    if _session_factory is not None:
        return _session_factory

    if engine is None:
        engine = get_engine()

    _session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    return _session_factory


def get_session() -> Session:
    """
    Create a new database session.

    Returns:
        New SQLAlchemy Session instance.

    Note:
        Caller is responsible for closing the session.
        Prefer using get_db_session() context manager instead.
    """
    factory = get_session_factory()
    return factory()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Automatically commits on success and rolls back on error.

    Yields:
        SQLAlchemy Session that will be properly cleaned up.

    Example:
        with get_db_session() as session:
            email = session.query(Email).first()
            email.is_read = True
            # Commits automatically on exit
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_db_session_with_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> Generator[Session, None, None]:
    """Context manager with retry on SQLite 'database is locked'.

    Uses exponential backoff: 0.5s, 1.0s, 2.0s.
    """
    import time

    for attempt in range(max_retries):
        try:
            with get_db_session() as session:
                yield session
                return
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "[DB] database is locked, retry %d/%d in %.1fs",
                    attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
            else:
                raise


def init_db(engine: Engine | None = None) -> None:
    """
    Initialize the database by creating all tables.

    Args:
        engine: Optional engine to use. If None, uses default engine.

    Note:
        This imports all models to ensure they're registered with the
        declarative base before creating tables.
    """
    if engine is None:
        engine = get_engine()

    # Import models to register them with Base
    from app.db.models.base import Base

    # Import all models (they register themselves with Base)
    import app.db.models  # noqa: F401 — registers all models with Base

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Ensure new columns exist on existing SQLite databases. PostgreSQL schema
    # changes must go through Alembic rather than startup-time ad hoc DDL.
    if engine.dialect.name == "sqlite":
        _ensure_schema_columns(engine, Base)
    else:
        logger.info("Skipping SQLite auto schema repair for %s backend", engine.dialect.name)

    # Backfill email_labels from assignments.json only for SQLite installs.
    if engine.dialect.name == "sqlite":
        _backfill_email_labels(engine)


def _column_default_sql(col) -> str:
    if col.server_default is not None:
        return f" DEFAULT {col.server_default.arg}"

    default = col.default
    if default is None or not getattr(default, "is_scalar", False):
        return ""

    value = default.arg
    if value is None:
        return ""
    if isinstance(value, bool):
        return f" DEFAULT {1 if value else 0}"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def _ensure_schema_columns(engine: Engine, base) -> None:
    """
    Compare model columns with actual DB schema and add any missing columns.

    SQLite's CREATE TABLE IF NOT EXISTS doesn't add new columns to existing tables.
    This runs at startup to ensure the DB schema matches the SQLAlchemy models.
    """
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    with engine.connect() as conn:
        for table in base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                # Build column type DDL
                col_type = col.type.compile(dialect=engine.dialect)
                nullable = "NULL" if col.nullable else "NOT NULL"
                default = _column_default_sql(col)
                stmt = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type} {nullable}{default}"
                try:
                    conn.execute(text(stmt))
                    logger.info(f"Schema migration: added column {table.name}.{col.name}")
                except OperationalError as exc:
                    logger.warning(
                        "Schema migration: failed to add column %s.%s: %s",
                        table.name,
                        col.name,
                        exc,
                    )
        conn.commit()


def _backfill_email_labels(engine: Engine) -> None:
    """
    Backfill email_labels table from assignments.json if empty.

    Runs once on startup; skipped if any rows already exist.
    """
    try:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM email_labels")).scalar() or 0
            if count > 0:
                return

        import os
        from app.infrastructure.adapters.label_store import LabelStore

        storage_dir = os.environ.get("AGENTYS_DATA_DIR", "data")
        label_store = LabelStore(storage_dir=os.path.join(storage_dir, "labels"))
        assignments = label_store.get_assignments(limit=10000)

        if not assignments:
            return

        rows = []
        with engine.connect() as conn:
            for assignment in assignments:
                # Resolve account_id: look up in emails table, default to 1
                try:
                    account_id = conn.execute(
                        text("SELECT account_id FROM emails WHERE email_id = :eid LIMIT 1"),
                        {"eid": assignment.email_id},
                    ).scalar() or 1
                except Exception:
                    account_id = 1

                for label_name in assignment.labels:
                    rows.append({
                        "email_id": assignment.email_id,
                        "account_id": account_id,
                        "label_name": label_name,
                    })

            if rows:
                conn.execute(
                    text("INSERT INTO email_labels (email_id, account_id, label_name) "
                         "VALUES (:email_id, :account_id, :label_name)"),
                    rows,
                )
                conn.commit()
                logger.info(f"[OK] Backfilled {len(rows)} email_labels rows from assignments.json")
    except Exception as e:
        logger.warning(f"[WARN] email_labels backfill skipped: {e}")


def reset_engine() -> None:
    """
    Reset the global engine and session factory.

    Useful for testing or when switching databases.
    """
    global _engine, _session_factory, _encryption_config

    if _engine is not None:
        _engine.dispose()
        _engine = None

    _session_factory = None
    _encryption_config = None


def check_database_health() -> dict:
    """
    Check database health and return status.

    Returns:
        Dict with health status information.
    """
    try:
        with get_db_session() as session:
            # Run a simple query to verify connectivity
            result = session.execute(text("SELECT 1")).scalar()
            engine = session.get_bind()

            if engine.dialect.name != "sqlite":
                return {
                    "status": "healthy",
                    "backend": engine.dialect.name,
                    "database_url": _redact_database_url(str(engine.url)),
                    "connection_test": result == 1,
                    "encryption_enabled": False,
                }

            # Get database file size
            db_path = get_db_path(encrypted=is_encryption_enabled())
            db_size = db_path.stat().st_size if db_path.exists() else 0

            return {
                "status": "healthy",
                "backend": "sqlite",
                "database_path": str(db_path),
                "database_size_bytes": db_size,
                "connection_test": result == 1,
                "encryption_enabled": is_encryption_enabled(),
            }
    except WrongKeyError:
        return {
            "status": "unhealthy",
            "error": "Invalid encryption key",
            "encryption_enabled": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


_PLAINTEXT_SQLITE_MAGIC = b"SQLite format 3\x00"


def is_database_encrypted(db_path: Path) -> bool:
    """
    Check if a database file is encrypted.

    Reads the first 16 bytes and compares against the canonical SQLite
    plaintext header (`SQLite format 3\\0`). An encrypted SQLCipher file
    has random ciphertext in those bytes — not the magic header. This is
    the canonical CASA V6.2.1 acceptance check (cf. data-at-rest.md
    runbook step 7: `head -c 16 .../agentys.db | od -c`).

    Falls back to a connect probe only if the magic-byte read fails
    (e.g. permission denied) — that branch logs a warning so operators
    notice the missing capability.

    Args:
        db_path: Path to the database file.

    Returns:
        True if database appears to be encrypted.
    """
    if not db_path.exists():
        return False

    # Primary check: magic-byte header inspection. Cheap (16 bytes), no
    # SQLite open, no key required, works for both SQLAlchemy and stdlib paths.
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        if not header:
            return False  # empty file
        if header.startswith(_PLAINTEXT_SQLITE_MAGIC):
            return False
        return True  # any non-magic bytes = ciphertext (encrypted)
    except OSError as e:
        logger.warning(
            f"Could not read DB header for encryption check ({db_path}): {e} — "
            "falling back to connect probe"
        )

    # Fallback: try opening as plaintext.
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
        return False  # Opened successfully without key = not encrypted
    except sqlite3.DatabaseError as e:
        if "file is not a database" in str(e).lower():
            return True  # Failed to open = likely encrypted
        return False  # Other error
