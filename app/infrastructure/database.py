# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Module de persistance SQLite pour Agentys.

Remplace les fichiers JSON par une base SQLite pour:
- Meilleure performance sur grandes quantités de données
- Requêtes complexes (filtrage, agrégation)
- Transactions ACID
- Verrouillage automatique (accès concurrent)
"""

import sqlite3 as _stdlib_sqlite3
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from app.config import DATA_DIR, should_persist_email_content
from app.domain.ports.task_port import TaskPort
from app.infrastructure.text_io import read_text_legacy_safe

logger = logging.getLogger(__name__)

# CASA V6.2 (#206): pick sqlcipher3 when AGENTYS_ENCRYPTION_KEY is set so
# this layer can read the same encrypted DB file as app/db/database.py.
# sqlcipher3.dbapi2 is API-compatible with stdlib sqlite3 (same Row,
# OperationalError, IntegrityError, etc.), so the rest of this module is
# unchanged. Without the env var we fall back to plain sqlite3 → desktop
# installs that store the key in the OS Keychain still hit the keychain via
# `app/db/encryption.py`, which is read by `app/db/database.py`. This module
# is the legacy layer driven directly off `agentys.db` on the same path; it
# only sees the env var path.
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _resolve_sqlite_module():
    if os.environ.get("AGENTYS_ENCRYPTION_KEY"):
        try:
            from sqlcipher3 import dbapi2 as _sqlcipher

            return _sqlcipher
        except ImportError as exc:
            # CASA V6.2 #206 fail-closed: in production, refusing to boot is
            # safer than silently falling back to stdlib sqlite3 — the next
            # SELECT would otherwise raise the cryptic "file is not a database"
            # because the file IS encrypted.
            _is_prod = (
                os.environ.get("FLASK_ENV") == "production"
                or os.environ.get("ENVIRONMENT") == "production"
                or os.environ.get("RAILWAY_ENVIRONMENT") == "production"
                or os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production"
            )
            if _is_prod:
                raise ImportError(
                    "CRITICAL: AGENTYS_ENCRYPTION_KEY is set but `sqlcipher3` is not "
                    "installed in this environment. The DB is expected to be "
                    "encrypted; falling back to stdlib sqlite3 would corrupt-read "
                    "every query. Install sqlcipher3-binary or unset the env var "
                    "if the file is plaintext (then re-run the migration)."
                ) from exc
            logger.warning(
                "AGENTYS_ENCRYPTION_KEY set but sqlcipher3 not installed — "
                "falling back to plain sqlite3 (will fail on encrypted files)"
            )
    return _stdlib_sqlite3


# Resolved once per process. Existing callers that reference `sqlite3.Row`,
# `sqlite3.OperationalError`, etc. against this module's sqlite3 binding
# pick up the right type automatically.
sqlite3 = _resolve_sqlite_module()


def _apply_encryption_pragmas(conn) -> None:
    """Apply SQLCipher PRAGMAs to a freshly-opened connection.

    Must run BEFORE any read/write. SQLCipher needs `PRAGMA key` to decrypt
    the file header; without it, the very first statement (`PRAGMA
    journal_mode = WAL`) raises "file is not a database".

    Values must match `app/db/database.py:_create_connection` and
    `scripts/encrypt_existing_db.py` so all three layers agree on the same
    key derivation.
    """
    key = os.environ.get("AGENTYS_ENCRYPTION_KEY")
    if not key or sqlite3 is _stdlib_sqlite3:
        return
    if not _HEX_KEY_RE.match(key):
        raise ValueError("AGENTYS_ENCRYPTION_KEY must be 64 hex chars")
    conn.execute(f"PRAGMA key = \"x'{key}'\"")
    conn.execute("PRAGMA cipher_page_size = 4096")
    conn.execute("PRAGMA kdf_iter = 256000")
    conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA512")
    conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")


# Fichier de base de données
DATABASE_FILE = DATA_DIR / "agentys.db"

# Schéma de la base de données
SCHEMA = """
-- Table des emails traités
CREATE TABLE IF NOT EXISTS processed_emails (
    id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table de l'historique des brouillons
-- account_id est requis pour l'isolation multi-compte : toute lecture DOIT
-- filtrer par account_id. La colonne reste nullable au niveau DDL pour
-- compat legacy, mais les rows NULL sont quarantinés côté adapter (jamais
-- retournés à un utilisateur).
CREATE TABLE IF NOT EXISTS draft_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    email_id TEXT NOT NULL,
    email_sender TEXT,
    email_subject TEXT,
    email_body TEXT,
    draft_v1 TEXT,
    critique TEXT,
    draft_final TEXT,
    status TEXT,
    draft_id TEXT,
    tokens_used INTEGER DEFAULT 0,
    model TEXT,
    processing_time_ms INTEGER,
    priority_score INTEGER DEFAULT 50,
    category TEXT DEFAULT 'NORMAL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    feedback TEXT,
    feedback_score INTEGER
);

-- Table des emails envoyés (pour follow-ups)
CREATE TABLE IF NOT EXISTS sent_emails (
    id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    subject TEXT,
    body_preview TEXT,
    original_email_id TEXT,
    thread_id TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    replied_at TIMESTAMP,
    followup_sent_at TIMESTAMP,
    status TEXT DEFAULT 'pending'
);

-- Table des patterns appris
CREATE TABLE IF NOT EXISTS learned_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type TEXT NOT NULL,
    pattern_value TEXT NOT NULL,
    correction TEXT DEFAULT '',
    examples TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.5,
    occurrences INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Table des ajustements de prompts
CREATE TABLE IF NOT EXISTS prompt_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adjustment TEXT NOT NULL,
    reason TEXT,
    section TEXT DEFAULT '',
    applied_count INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Table d'audit
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    success INTEGER DEFAULT 1,
    email_id TEXT,
    draft_id TEXT,
    user TEXT,
    duration_ms INTEGER,
    error TEXT,
    details TEXT
);

-- Table de configuration des coûts
CREATE TABLE IF NOT EXISTS cost_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    request_count INTEGER DEFAULT 0,
    UNIQUE(date, model)
);

-- Journal granulaire des tokens pour le dashboard admin privé (#551).
-- Ne contient jamais de contenu email/draft/contact : uniquement compteurs et coûts.
CREATE TABLE IF NOT EXISTS token_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    user_id INTEGER,
    agent TEXT DEFAULT 'unknown',
    agent_name TEXT DEFAULT 'unknown',
    feature TEXT DEFAULT 'unknown',
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_creation_input_tokens INTEGER DEFAULT 0,
    cache_read_input_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Journal granulaire des appels API externes (#551 follow-up).
-- Aucun secret, payload, query string ni contenu métier : seulement métadonnées
-- d'observabilité pour détecter coûts/fuites/boucles provider.
CREATE TABLE IF NOT EXISTS api_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    user_id INTEGER,
    feature TEXT DEFAULT 'unknown',
    provider TEXT DEFAULT 'unknown',
    method TEXT DEFAULT 'GET',
    url_host TEXT NOT NULL,
    url_path TEXT DEFAULT '/',
    status_code INTEGER,
    success INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    auth_present INTEGER DEFAULT 0,
    auth_type TEXT DEFAULT 'unknown',
    process_name TEXT DEFAULT 'backend',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des tâches extraites
-- AUTHZ-VULN-04 (Shannon pentest, issue #557): account_id ajouté pour
-- isolation par tenant. Pour les bases existantes, l'ALTER TABLE est
-- déclenché dans `_init_schema` ci-dessous (la colonne ne peut pas
-- être ajoutée dans le CREATE IF NOT EXISTS — il deviendrait un no-op
-- sur une DB pré-existante).
CREATE TABLE IF NOT EXISTS extracted_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT DEFAULT '',
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'MEDIUM',
    deadline TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    account_id INTEGER
);

-- Table des utilisateurs admin
CREATE TABLE IF NOT EXISTS admin_users (
    email TEXT PRIMARY KEY,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit obligatoire des accès au dashboard admin privé (#551).
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT DEFAULT 'unknown',
    action TEXT NOT NULL,
    metadata TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table d'activité utilisateur (analytics admin)
CREATE TABLE IF NOT EXISTS user_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    action TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des événements de revenus
CREATE TABLE IF NOT EXISTS revenue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    event_type TEXT NOT NULL,
    amount_usd REAL DEFAULT 0.0,
    plan TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des parrainages
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_email TEXT NOT NULL,
    referred_email TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour les performances
CREATE INDEX IF NOT EXISTS idx_draft_history_email_id ON draft_history(email_id);
CREATE INDEX IF NOT EXISTS idx_draft_history_created_at ON draft_history(created_at);
-- Note: idx_draft_history_account_created est créé par la migration Alembic
--       20260415_000001 (account_id n'existe pas sur les DB pré-migration).
CREATE INDEX IF NOT EXISTS idx_sent_emails_recipient ON sent_emails(recipient);
CREATE INDEX IF NOT EXISTS idx_sent_emails_status ON sent_emails(status);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_date ON cost_tracking(date);
CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage_log(created_at);
CREATE INDEX IF NOT EXISTS idx_token_usage_account_created ON token_usage_log(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_token_usage_model_created ON token_usage_log(model, created_at);
-- idx_token_usage_feature_created and idx_api_usage_feature_created are
-- created in the Python block below, AFTER the ALTER TABLE migrations have
-- added the `feature` column on existing DBs. Keeping them inside SCHEMA
-- crashed boot on prod because executescript() halts at the first error
-- (token_usage_log was created earlier by Alembic 021 without `feature`).
CREATE INDEX IF NOT EXISTS idx_api_usage_created ON api_usage_log(created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider_created ON api_usage_log(provider, created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_account_created ON api_usage_log(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_user_created ON api_usage_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_extracted_tasks_email_id ON extracted_tasks(email_id);
CREATE INDEX IF NOT EXISTS idx_extracted_tasks_status ON extracted_tasks(status);
-- AUTHZ-VULN-04 (issue #557): the (account_id, status) composite index
-- is created by alembic migration 021 because it can only exist after
-- the account_id column has been backfilled. On fresh DBs the schema
-- above already contains the column; the migration runs as a no-op for
-- the column but still creates the index.
CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_emails(processed_at);
CREATE INDEX IF NOT EXISTS idx_user_activity_email ON user_activity(user_email);
CREATE INDEX IF NOT EXISTS idx_user_activity_created ON user_activity(created_at);
CREATE INDEX IF NOT EXISTS idx_user_activity_action ON user_activity(action);
CREATE INDEX IF NOT EXISTS idx_revenue_events_email ON revenue_events(user_email);
CREATE INDEX IF NOT EXISTS idx_revenue_events_created ON revenue_events(created_at);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_email);
"""


class Database:
    """
    Gestionnaire de base de données SQLite thread-safe.

    Utilise un pool de connexions par thread pour la concurrence.
    """

    _local = threading.local()
    _lock = threading.Lock()
    _initialized = False

    def __init__(self, db_path: Path = DATABASE_FILE):
        """
        Initialise le gestionnaire de base de données.

        Args:
            db_path: Chemin vers le fichier SQLite.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialiser le schéma si nécessaire
        if not Database._initialized:
            with Database._lock:
                if not Database._initialized:
                    self._init_schema()
                    Database._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        """Obtient une connexion pour le thread courant."""
        if not hasattr(Database._local, 'connection') or Database._local.connection is None:
            Database._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            # CASA V6.2 (#206): apply SQLCipher PRAGMAs FIRST when encryption
            # is enabled. Any other PRAGMA (or plain SELECT) before the key
            # is set fails with "file is not a database" on an encrypted
            # file — exactly the boot crash that motivated this patch.
            _apply_encryption_pragmas(Database._local.connection)
            Database._local.connection.row_factory = sqlite3.Row
            # Activer les clés étrangères et le mode WAL pour les performances
            Database._local.connection.execute("PRAGMA foreign_keys = ON")
            Database._local.connection.execute("PRAGMA journal_mode = WAL")
            Database._local.connection.execute("PRAGMA busy_timeout = 30000")
            Database._local.connection.execute("PRAGMA synchronous = NORMAL")
            Database._local.connection.execute("PRAGMA cache_size = -64000")
            Database._local.connection.execute("PRAGMA temp_store = MEMORY")
            Database._local.connection.execute("PRAGMA mmap_size = 268435456")
        return Database._local.connection

    @contextmanager
    def transaction(self):
        """Context manager pour les transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def _init_schema(self) -> None:
        """Initialise le schéma de la base de données."""
        conn = self._get_connection()
        self._migrate_pre_schema_usage_columns(conn)
        conn.executescript(SCHEMA)
        conn.commit()
        # Migrations pour bases existantes (colonnes ajoutées après création initiale)
        migrations = [
            "ALTER TABLE learned_patterns ADD COLUMN correction TEXT DEFAULT ''",
            "ALTER TABLE learned_patterns ADD COLUMN examples TEXT DEFAULT '[]'",
            "ALTER TABLE prompt_adjustments ADD COLUMN section TEXT DEFAULT ''",
            # Isolation multi-compte (voir migration Alembic 014_add_account_id_to_draft_history)
            "ALTER TABLE draft_history ADD COLUMN account_id INTEGER",
            # AUTHZ-VULN-04 (Shannon pentest, issue #557) — voir migration
            # Alembic 021_add_account_id_to_extracted_tasks pour le backfill.
            "ALTER TABLE extracted_tasks ADD COLUMN account_id INTEGER",
            # Issue #551 follow-up: Alembic 021_add_token_usage_log creates
            # token_usage_log with a minimal schema (id, account_id, agent, model,
            # input/output_tokens, cost_usd, created_at). The legacy SCHEMA above
            # declares extra columns used by admin.py (`feature`) and the LLM
            # cache accounting path. On a fresh DB the SCHEMA's CREATE TABLE
            # creates everything; on an existing DB the CREATE TABLE IF NOT
            # EXISTS is a no-op and these ALTER TABLE statements bring the row
            # in line. Each is wrapped in the try/except below so it is a
            # no-op when the column already exists.
            "ALTER TABLE token_usage_log ADD COLUMN user_id INTEGER",
            "ALTER TABLE token_usage_log ADD COLUMN agent TEXT DEFAULT 'unknown'",
            "ALTER TABLE token_usage_log ADD COLUMN agent_name TEXT DEFAULT 'unknown'",
            "ALTER TABLE token_usage_log ADD COLUMN feature TEXT DEFAULT 'unknown'",
            "ALTER TABLE token_usage_log ADD COLUMN cache_creation_input_tokens INTEGER DEFAULT 0",
            "ALTER TABLE token_usage_log ADD COLUMN cache_read_input_tokens INTEGER DEFAULT 0",
            # Defensive: api_usage_log is only declared in SCHEMA (no Alembic
            # migration), so on a fresh boot it's created with `feature` from
            # the start. These ALTERs only do work on installs that somehow
            # ended up with the table missing the column.
            "ALTER TABLE api_usage_log ADD COLUMN feature TEXT DEFAULT 'unknown'",
            "ALTER TABLE api_usage_log ADD COLUMN user_id INTEGER",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
                conn.commit()
            except sqlite3.OperationalError:
                pass  # colonne existe déjà
        # Index composite account_id + created_at — créé seulement après la
        # migration ALTER TABLE ci-dessus (sinon la colonne n'existe pas).
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_draft_history_account_created "
                "ON draft_history(account_id, created_at)"
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass
        # Issue #551 : tables admin ajoutées après les premières bases locales.
        # `executescript(SCHEMA)` couvre les nouvelles bases ; ces statements
        # rendent le boot idempotent pour les bases existantes.
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    user_id INTEGER,
                    agent TEXT DEFAULT 'unknown',
                    agent_name TEXT DEFAULT 'unknown',
                    feature TEXT DEFAULT 'unknown',
                    model TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cache_creation_input_tokens INTEGER DEFAULT 0,
                    cache_read_input_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT DEFAULT 'unknown',
                    action TEXT NOT NULL,
                    metadata TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    user_id INTEGER,
                    feature TEXT DEFAULT 'unknown',
                    provider TEXT DEFAULT 'unknown',
                    method TEXT DEFAULT 'GET',
                    url_host TEXT NOT NULL,
                    url_path TEXT DEFAULT '/',
                    status_code INTEGER,
                    success INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0,
                    auth_present INTEGER DEFAULT 0,
                    auth_type TEXT DEFAULT 'unknown',
                    process_name TEXT DEFAULT 'backend',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_account_created ON token_usage_log(account_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_model_created ON token_usage_log(model, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_feature_created ON token_usage_log(feature, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_created ON api_usage_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_provider_created ON api_usage_log(provider, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_account_created ON api_usage_log(account_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_user_created ON api_usage_log(user_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_feature_created ON api_usage_log(feature, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at)")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        logger.info(f"[INIT] Base de données initialisée: {self.db_path}")

    def _migrate_pre_schema_usage_columns(self, conn) -> None:
        """Add usage columns before SCHEMA creates indexes on them.

        `CREATE TABLE IF NOT EXISTS` is a no-op for existing databases. If an
        older `token_usage_log` exists without `feature`, the index statement in
        SCHEMA would crash before the post-schema migrations can run.
        """
        usage_columns = {
            "token_usage_log": [
                ("account_id", "INTEGER"),
                ("user_id", "INTEGER"),
                ("agent", "TEXT DEFAULT 'unknown'"),
                ("agent_name", "TEXT DEFAULT 'unknown'"),
                ("feature", "TEXT DEFAULT 'unknown'"),
                ("input_tokens", "INTEGER DEFAULT 0"),
                ("output_tokens", "INTEGER DEFAULT 0"),
                ("cache_creation_input_tokens", "INTEGER DEFAULT 0"),
                ("cache_read_input_tokens", "INTEGER DEFAULT 0"),
                ("cost_usd", "REAL DEFAULT 0.0"),
                ("created_at", "TIMESTAMP"),
            ],
            "api_usage_log": [
                ("account_id", "INTEGER"),
                ("user_id", "INTEGER"),
                ("feature", "TEXT DEFAULT 'unknown'"),
                ("provider", "TEXT DEFAULT 'unknown'"),
                ("method", "TEXT DEFAULT 'GET'"),
                ("url_host", "TEXT DEFAULT ''"),
                ("url_path", "TEXT DEFAULT '/'"),
                ("status_code", "INTEGER"),
                ("success", "INTEGER DEFAULT 0"),
                ("duration_ms", "INTEGER DEFAULT 0"),
                ("auth_present", "INTEGER DEFAULT 0"),
                ("auth_type", "TEXT DEFAULT 'unknown'"),
                ("process_name", "TEXT DEFAULT 'backend'"),
                ("created_at", "TIMESTAMP"),
            ],
        }
        for table_name, columns in usage_columns.items():
            try:
                existing = {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                }
            except sqlite3.OperationalError:
                continue
            if not existing:
                continue
            for column_name, definition in columns:
                if column_name in existing:
                    continue
                try:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Exécute une requête SQL."""
        conn = self._get_connection()
        return conn.execute(query, params)

    def executemany(self, query: str, params_list: List[tuple]) -> sqlite3.Cursor:
        """Exécute une requête SQL pour plusieurs jeux de paramètres."""
        conn = self._get_connection()
        return conn.executemany(query, params_list)

    def commit(self) -> None:
        """Valide les changements."""
        self._get_connection().commit()

    def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Exécute et retourne une ligne."""
        return self.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Exécute et retourne toutes les lignes."""
        return self.execute(query, params).fetchall()

    def close(self) -> None:
        """Ferme la connexion du thread courant."""
        if hasattr(Database._local, 'connection') and Database._local.connection:
            Database._local.connection.close()
            Database._local.connection = None


# Instance globale
db = Database()


# ============================================================================
# REPOSITORIES
# ============================================================================

class ProcessedEmailsRepository:
    """Repository pour les emails traités."""

    def __init__(self, database: Database = None):
        self.db = database or db

    def is_processed(self, email_id: str) -> bool:
        """Vérifie si un email a été traité."""
        result = self.db.fetchone(
            "SELECT id FROM processed_emails WHERE id = ?",
            (email_id,)
        )
        return result is not None

    def mark_processed(self, email_id: str) -> None:
        """Marque un email comme traité."""
        self.db.execute(
            "INSERT OR IGNORE INTO processed_emails (id) VALUES (?)",
            (email_id,)
        )
        self.db.commit()

    def count(self) -> int:
        """Retourne le nombre d'emails traités."""
        result = self.db.fetchone("SELECT COUNT(*) as count FROM processed_emails")
        return result['count'] if result else 0

    def get_all_ids(self) -> List[str]:
        """Retourne tous les IDs traités."""
        rows = self.db.fetchall("SELECT id FROM processed_emails")
        return [row['id'] for row in rows]


class DraftHistoryRepository:
    """Repository pour l'historique des brouillons."""

    def __init__(self, database: Database = None):
        self.db = database or db

    def add(self, record: Dict[str, Any]) -> int:
        """Ajoute un enregistrement à l'historique."""
        persist_content = should_persist_email_content()
        cursor = self.db.execute("""
            INSERT INTO draft_history
            (email_id, email_sender, email_subject, email_body, draft_v1,
             critique, draft_final, status, draft_id, tokens_used, model,
             processing_time_ms, priority_score, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('email_id'),
            record.get('email_sender'),
            record.get('email_subject'),
            record.get('email_body') if persist_content else None,
            record.get('draft_v1') if persist_content else None,
            record.get('critique') if persist_content else None,
            record.get('draft_final') if persist_content else None,
            record.get('status'),
            record.get('draft_id'),
            record.get('tokens_used', 0),
            record.get('model'),
            record.get('processing_time_ms'),
            record.get('priority_score', 50),
            record.get('category', 'NORMAL'),
        ))
        self.db.commit()
        return cursor.lastrowid

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retourne les enregistrements récents."""
        rows = self.db.fetchall(
            "SELECT * FROM draft_history ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in rows]

    def get_by_email_id(self, email_id: str) -> Optional[Dict[str, Any]]:
        """Retourne un enregistrement par ID d'email."""
        row = self.db.fetchone(
            "SELECT * FROM draft_history WHERE email_id = ?",
            (email_id,)
        )
        return dict(row) if row else None

    def update_feedback(self, email_id: str, feedback: str, score: int) -> None:
        """Met à jour le feedback pour un email."""
        self.db.execute(
            "UPDATE draft_history SET feedback = ?, feedback_score = ? WHERE email_id = ?",
            (feedback, score, email_id)
        )
        self.db.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques."""
        row = self.db.fetchone("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status LIKE '%V1%' THEN 1 ELSE 0 END) as validated_v1,
                SUM(CASE WHEN status LIKE '%V2%' THEN 1 ELSE 0 END) as corrected_v2,
                SUM(tokens_used) as total_tokens,
                AVG(processing_time_ms) as avg_processing_time,
                AVG(priority_score) as avg_priority
            FROM draft_history
        """)
        return dict(row) if row else {}

    def get_by_category(self) -> Dict[str, int]:
        """Retourne le breakdown par catégorie."""
        rows = self.db.fetchall("""
            SELECT category, COUNT(*) as count
            FROM draft_history
            GROUP BY category
        """)
        return {row['category']: row['count'] for row in rows}


class SentEmailsRepository:
    """Repository pour les emails envoyés (follow-ups)."""

    def __init__(self, database: Database = None):
        self.db = database or db

    @staticmethod
    def _body_preview_for_storage(record: Dict[str, Any]) -> str:
        """Return the persistable preview for a sent-email follow-up row."""
        if not should_persist_email_content():
            return ""
        return record.get('body_preview', record.get('body', '')[:200])

    @staticmethod
    def _row_for_output(row: Dict[str, Any]) -> Dict[str, Any]:
        """Apply metadata-only minimization to legacy sent email rows."""
        out = dict(row)
        if not should_persist_email_content():
            out["body_preview"] = ""
        return out

    def add(self, record: Dict[str, Any]) -> None:
        """Ajoute un email envoyé."""
        self.db.execute("""
            INSERT OR REPLACE INTO sent_emails
            (id, recipient, subject, body_preview, original_email_id, thread_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record.get('id'),
            record.get('recipient'),
            record.get('subject'),
            self._body_preview_for_storage(record),
            record.get('original_email_id'),
            record.get('thread_id'),
        ))
        self.db.commit()

    def get_pending(self, delay_days: int = 3) -> List[Dict[str, Any]]:
        """Retourne les emails en attente de réponse."""
        cutoff = datetime.now() - timedelta(days=delay_days)
        rows = self.db.fetchall("""
            SELECT * FROM sent_emails
            WHERE status = 'pending'
            AND sent_at < ?
            AND replied_at IS NULL
            AND followup_sent_at IS NULL
        """, (cutoff.isoformat(),))
        return [self._row_for_output(dict(row)) for row in rows]

    def mark_replied(self, email_id: str) -> None:
        """Marque un email comme ayant reçu une réponse."""
        self.db.execute(
            "UPDATE sent_emails SET replied_at = ?, status = 'replied' WHERE id = ?",
            (datetime.now().isoformat(), email_id)
        )
        self.db.commit()

    def mark_followup_sent(self, email_id: str) -> None:
        """Marque un email comme ayant eu un follow-up."""
        self.db.execute(
            "UPDATE sent_emails SET followup_sent_at = ?, status = 'followup_sent' WHERE id = ?",
            (datetime.now().isoformat(), email_id)
        )
        self.db.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques des follow-ups."""
        row = self.db.fetchone("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END) as replied,
                SUM(CASE WHEN status = 'followup_sent' THEN 1 ELSE 0 END) as followup_sent,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM sent_emails
        """)
        return dict(row) if row else {}


class CostTrackingRepository:
    """Repository pour le suivi des coûts."""

    def __init__(self, database: Database = None):
        self.db = database or db

    def record_usage(self, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        """Enregistre l'utilisation."""
        today = datetime.now().date().isoformat()
        self.db.execute("""
            INSERT INTO cost_tracking (date, model, input_tokens, output_tokens, cost_usd, request_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(date, model) DO UPDATE SET
                input_tokens = input_tokens + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens,
                cost_usd = cost_usd + excluded.cost_usd,
                request_count = request_count + 1
        """, (today, model, input_tokens, output_tokens, cost_usd))
        self.db.commit()

    def get_daily_cost(self, date: str = None) -> float:
        """Retourne le coût pour une journée."""
        if date is None:
            date = datetime.now().date().isoformat()
        row = self.db.fetchone(
            "SELECT SUM(cost_usd) as total FROM cost_tracking WHERE date = ?",
            (date,)
        )
        return row['total'] or 0.0 if row else 0.0

    def get_monthly_cost(self, year: int = None, month: int = None) -> float:
        """Retourne le coût pour un mois."""
        if year is None:
            year = datetime.now().year
        if month is None:
            month = datetime.now().month

        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        row = self.db.fetchone(
            "SELECT SUM(cost_usd) as total FROM cost_tracking WHERE date >= ? AND date < ?",
            (start_date, end_date)
        )
        return row['total'] or 0.0 if row else 0.0

    def get_by_model(self, days: int = 30) -> Dict[str, Dict[str, Any]]:
        """Retourne le breakdown par modèle."""
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
        rows = self.db.fetchall("""
            SELECT
                model,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cost_usd) as cost_usd,
                SUM(request_count) as requests
            FROM cost_tracking
            WHERE date >= ?
            GROUP BY model
        """, (cutoff,))
        return {row['model']: dict(row) for row in rows}

    def get_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """Retourne la tendance des coûts."""
        cutoff = (datetime.now() - timedelta(days=days)).date().isoformat()
        rows = self.db.fetchall("""
            SELECT
                date,
                SUM(cost_usd) as cost_usd,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens
            FROM cost_tracking
            WHERE date >= ?
            GROUP BY date
            ORDER BY date
        """, (cutoff,))
        return [dict(row) for row in rows]


class AuditLogRepository:
    """Repository pour les logs d'audit."""

    def __init__(self, database: Database = None):
        self.db = database or db

    def log(
        self,
        event_type: str,
        success: bool = True,
        email_id: str = None,
        draft_id: str = None,
        user: str = None,
        duration_ms: int = None,
        error: str = None,
        details: Dict[str, Any] = None
    ) -> int:
        """Ajoute une entrée d'audit."""
        cursor = self.db.execute("""
            INSERT INTO audit_log
            (event_type, success, email_id, draft_id, user, duration_ms, error, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_type,
            1 if success else 0,
            email_id,
            draft_id,
            user,
            duration_ms,
            error,
            json.dumps(details) if details else None
        ))
        self.db.commit()
        return cursor.lastrowid

    def get_recent(self, limit: int = 100, event_type: str = None) -> List[Dict[str, Any]]:
        """Retourne les entrées récentes."""
        if event_type:
            rows = self.db.fetchall(
                "SELECT * FROM audit_log WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (event_type, limit)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
        return [dict(row) for row in rows]

    def purge_old(self, days: int = 90) -> int:
        """Purge les entrées anciennes."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.db.execute(
            "DELETE FROM audit_log WHERE timestamp < ?",
            (cutoff,)
        )
        self.db.commit()
        return cursor.rowcount


class TaskRepository(TaskPort):

    def __init__(self, database: Database = None):
        self.db = database or db

    def add(self, email_id: str, task, account_id: Optional[int] = None) -> int:
        # AUTHZ-VULN-04 (issue #557): when caller provides account_id, persist it
        # so subsequent get_by_id can verify ownership. When NOT provided, look
        # it up via emails table (covers legacy callers like daemon).
        resolved_account_id = account_id
        if resolved_account_id is None and email_id:
            try:
                row = self.db.fetchone(
                    "SELECT account_id FROM emails WHERE email_id = ? LIMIT 1",
                    (email_id,)
                )
            except sqlite3.OperationalError as exc:
                if "no such table: emails" not in str(exc):
                    raise
                row = None
            if row is not None:
                resolved_account_id = row["account_id"] if hasattr(row, "__getitem__") else None
        cursor = self.db.execute("""
            INSERT INTO extracted_tasks
            (email_id, title, description, priority, deadline, account_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            email_id,
            task.title,
            task.description,
            task.priority,
            task.deadline,
            resolved_account_id,
        ))
        self.db.commit()
        return cursor.lastrowid

    def add_many(self, email_id: str, tasks: list, account_id: Optional[int] = None) -> List[int]:
        if not tasks:
            return []
        task_ids = []
        for task in tasks:
            task_id = self.add(email_id, task, account_id=account_id)
            task_ids.append(task_id)
        return task_ids

    def get_by_email_id(self, email_id: str) -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM extracted_tasks WHERE email_id = ? ORDER BY id",
            (email_id,)
        )
        return [dict(row) for row in rows]

    def get_pending(self, limit: int = 100, account_id: Optional[int] = None) -> List[Dict[str, Any]]:
        # AUTHZ-VULN-04 (issue #557): scope by account_id when provided.
        if account_id is not None:
            rows = self.db.fetchall(
                "SELECT * FROM extracted_tasks WHERE status = 'pending' AND account_id = ? ORDER BY created_at DESC LIMIT ?",
                (account_id, limit)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM extracted_tasks WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        return [dict(row) for row in rows]

    def get_all(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        account_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        # AUTHZ-VULN-04 (issue #557): scope by account_id when provided.
        # Tasks with NULL account_id (legacy / non-backfilled / manually created
        # without ownership) are hard-quarantined — never surface in any list.
        clauses = []
        params: list[Any] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(account_id)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self.db.fetchall(
            f"SELECT * FROM extracted_tasks {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        return [dict(row) for row in rows]

    def get_by_id(self, task_id: int, account_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        # AUTHZ-VULN-04 (issue #557): when account_id provided, refuse to
        # return the task if it belongs to a different account. NULL
        # account_id rows are also refused — quarantine semantics.
        if account_id is not None:
            row = self.db.fetchone(
                "SELECT * FROM extracted_tasks WHERE id = ? AND account_id = ?",
                (task_id, account_id)
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM extracted_tasks WHERE id = ?",
                (task_id,)
            )
        if row is None:
            return None
        return dict(row)

    def mark_completed(self, task_id: int, account_id: Optional[int] = None) -> bool:
        # AUTHZ-VULN-04 (issue #557): same scoping as get_by_id.
        task = self.get_by_id(task_id, account_id=account_id)
        if task is None:
            return False
        self.db.execute(
            "UPDATE extracted_tasks SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), task_id)
        )
        self.db.commit()
        return True

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        priority: str = "medium",
        deadline: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # AUTHZ-VULN-04 (issue #557): persist account_id at creation so the
        # row is not stuck in NULL-quarantine. Caller MUST pass account_id
        # for user-created tasks (POST /api/tasks).
        created_at = datetime.now().isoformat()
        cursor = self.db.execute("""
            INSERT INTO extracted_tasks
            (email_id, title, description, priority, deadline, status, created_at, account_id)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (
            "",
            title,
            description,
            priority.upper(),
            deadline,
            created_at,
            account_id,
        ))
        self.db.commit()
        task_id = cursor.lastrowid
        return {
            "id": task_id,
            "email_id": None,
            "title": title,
            "description": description,
            "priority": priority.lower(),
            "deadline": deadline,
            "status": "pending",
            "created_at": created_at,
            "completed_at": None,
            "account_id": account_id,
        }


# ============================================================================
# MIGRATION DEPUIS JSON
# ============================================================================

def migrate_from_json() -> Dict[str, int]:
    """
    Migre les données des fichiers JSON vers SQLite.

    Returns:
        Dict avec le nombre d'enregistrements migrés par type.
    """
    results = {"processed_emails": 0, "draft_history": 0, "sent_emails": 0}

    # Migrer les emails traités
    processed_file = DATA_DIR / ".processed_emails.json"
    if processed_file.exists():
        try:
            # read_text_legacy_safe : un fichier hérité écrit en cp1252 par
            # l'ancien code est récupéré au lieu de faire échouer la migration
            # (audit 2026-05-14 F-01). Pas de ré-enregistrement : ce sont des
            # sources de migration one-shot, pas un état persistant possédé.
            raw, _ = read_text_legacy_safe(processed_file)
            data = json.loads(raw)
            ids = data.get("processed_ids", [])
            repo = ProcessedEmailsRepository()
            for email_id in ids:
                repo.mark_processed(email_id)
            results["processed_emails"] = len(ids)
            logger.info(f"[OK] Migré {len(ids)} emails traités")
        except Exception as e:
            logger.error(f"[ERROR] Erreur migration processed_emails: {e}")

    # Migrer l'historique des brouillons
    history_file = DATA_DIR / "history.json"
    if history_file.exists():
        try:
            raw, _ = read_text_legacy_safe(history_file)
            data = json.loads(raw)
            records = data.get("drafts", [])
            repo = DraftHistoryRepository()
            for record in records:
                repo.add(record)
            results["draft_history"] = len(records)
            logger.info(f"[OK] Migré {len(records)} brouillons")
        except Exception as e:
            logger.error(f"[ERROR] Erreur migration draft_history: {e}")

    # Migrer les emails envoyés
    sent_file = DATA_DIR / "followups" / "sent_emails.json"
    if sent_file.exists():
        try:
            raw, _ = read_text_legacy_safe(sent_file)
            data = json.loads(raw)
            records = data.get("sent_emails", [])
            repo = SentEmailsRepository()
            for record in records:
                repo.add(record)
            results["sent_emails"] = len(records)
            logger.info(f"[OK] Migré {len(records)} emails envoyés")
        except Exception as e:
            logger.error(f"[ERROR] Erreur migration sent_emails: {e}")

    return results
