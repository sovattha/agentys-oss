"""
Adapter SQLite pour CommunicationChannelPort.

Clean Architecture: Infrastructure layer.

Security: Les credentials sont chiffres avant stockage via EncryptionManager.
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.domain.entities.communication_channel import (
    CommunicationChannel,
    ChannelConfig,
    ChannelMetrics,
    ChannelType,
    ChannelStatus,
)
from app.domain.ports.communication_channel_port import CommunicationChannelPort
from app.infrastructure.security import EncryptionManager


class CommunicationChannelAdapter(CommunicationChannelPort):
    """
    Adapter SQLite pour CommunicationChannelPort.

    Security: Les credentials sont chiffres (AES-128-CBC via Fernet)
    avant stockage dans la base de donnees.
    """

    TABLE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS communication_channels (
        id TEXT PRIMARY KEY,
        channel_type TEXT NOT NULL,
        name TEXT NOT NULL,
        config_credentials TEXT NOT NULL,
        config_endpoint TEXT,
        config_webhook_url TEXT,
        config_settings TEXT,
        status TEXT NOT NULL DEFAULT 'pending_setup',
        messages_sent INTEGER NOT NULL DEFAULT 0,
        messages_received INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT,
        error_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_channels_type ON communication_channels(channel_type);
    CREATE INDEX IF NOT EXISTS idx_channels_status ON communication_channels(status);
    """

    def __init__(
        self,
        db_path: Path = None,
        encryption_manager: EncryptionManager = None,
    ):
        self._db_path = db_path
        self._connection = None
        self._encryption = encryption_manager or EncryptionManager()
        # S-06 fix (2026-04-24): same single-shared-connection pattern as
        # CommitmentAdapter (S-05). Slack/Discord webhook handlers can hit
        # this adapter from separate Flask worker threads — without a lock
        # they race on cursor state and produce intermittent
        # `sqlite3.ProgrammingError: Recursive use of cursors`.
        self._db_lock = threading.RLock()
        self._ensure_table()

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            db_path = str(self._db_path) if self._db_path else ":memory:"
            self._connection = sqlite3.connect(db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _ensure_table(self) -> None:
        with self._db_lock:
            conn = self._get_connection()
            conn.executescript(self.TABLE_SCHEMA)
            conn.commit()

    def _parse_optional_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse une chaine ISO en datetime ou None."""
        return datetime.fromisoformat(value) if value else None

    def _format_optional_datetime(self, value: Optional[datetime]) -> Optional[str]:
        """Formate un datetime en chaine ISO ou None."""
        return value.isoformat() if value else None

    def _row_to_channel(self, row: sqlite3.Row) -> CommunicationChannel:
        # Dechiffrer les credentials stockes
        encrypted_credentials = row["config_credentials"]
        credentials = self._encryption.decrypt_dict(encrypted_credentials)
        settings_str = row["config_settings"]
        settings = json.loads(settings_str) if settings_str else {}

        return CommunicationChannel(
            id=row["id"],
            channel_type=ChannelType(row["channel_type"]),
            name=row["name"],
            config=ChannelConfig(
                credentials=credentials,
                endpoint=row["config_endpoint"],
                webhook_url=row["config_webhook_url"],
                settings=settings,
            ),
            status=ChannelStatus(row["status"]),
            metrics=ChannelMetrics(
                messages_sent=row["messages_sent"],
                messages_received=row["messages_received"],
                last_used_at=self._parse_optional_datetime(row["last_used_at"]),
                error_count=row["error_count"],
            ),
            created_at=self._parse_optional_datetime(row["created_at"]),
            updated_at=self._parse_optional_datetime(row["updated_at"]),
        )

    def save(self, channel: CommunicationChannel) -> CommunicationChannel:
        # Chiffrer les credentials avant stockage
        encrypted_credentials = self._encryption.encrypt_dict(channel.config.credentials)
        with self._db_lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO communication_channels
                (id, channel_type, name, config_credentials, config_endpoint,
                 config_webhook_url, config_settings, status, messages_sent,
                 messages_received, last_used_at, error_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel.id,
                    channel.channel_type.value,
                    channel.name,
                    encrypted_credentials,
                    channel.config.endpoint,
                    channel.config.webhook_url,
                    json.dumps(channel.config.settings),
                    channel.status.value,
                    channel.metrics.messages_sent,
                    channel.metrics.messages_received,
                    self._format_optional_datetime(channel.metrics.last_used_at),
                    channel.metrics.error_count,
                    self._format_optional_datetime(channel.created_at),
                    self._format_optional_datetime(channel.updated_at),
                ),
            )
            conn.commit()
        return channel

    def get_by_id(self, channel_id: str) -> Optional[CommunicationChannel]:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT * FROM communication_channels WHERE id = ?",
                (channel_id,),
            )
            row = cursor.fetchone()
        return self._row_to_channel(row) if row else None

    def get_by_type(self, channel_type: ChannelType) -> List[CommunicationChannel]:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT * FROM communication_channels WHERE channel_type = ?",
                (channel_type.value,),
            )
            rows = cursor.fetchall()
        return [self._row_to_channel(row) for row in rows]

    def get_all(self) -> List[CommunicationChannel]:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM communication_channels")
            rows = cursor.fetchall()
        return [self._row_to_channel(row) for row in rows]

    def delete(self, channel_id: str) -> bool:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "DELETE FROM communication_channels WHERE id = ?",
                (channel_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_metrics(self, channel_id: str, metrics: ChannelMetrics) -> bool:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                UPDATE communication_channels
                SET messages_sent = ?, messages_received = ?, last_used_at = ?, error_count = ?
                WHERE id = ?
                """,
                (
                    metrics.messages_sent,
                    metrics.messages_received,
                    self._format_optional_datetime(metrics.last_used_at),
                    metrics.error_count,
                    channel_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_status(self, channel_id: str, status: ChannelStatus) -> bool:
        with self._db_lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                UPDATE communication_channels
                SET status = ?
                WHERE id = ?
                """,
                (status.value, channel_id),
            )
            conn.commit()
            return cursor.rowcount > 0
