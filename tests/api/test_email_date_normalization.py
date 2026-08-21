# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Regression writer-level — bug « 14:47 (liste) vs 18:47 (fil) » (2026-06-09).

`_refresh_folder_cache_bg` stockait le datetime AWARE du provider tel quel dans
la colonne naïve `Email.date` → l'offset est perdu au round-trip SQLite et
`_to_iso_utc` re-étiquette l'heure murale locale en UTC. Ce test pilote le vrai
writer avec un faux provider renvoyant le header Date du bug réel et verrouille
la convention « colonne = UTC naïf ».

pytest tests/api/test_email_date_normalization.py -v
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from unittest.mock import MagicMock, patch

import pytest


KARINE_AWARE = parsedate_to_datetime("Mon, 09 Jun 2026 18:47:53 -0400")
TRUE_UTC = datetime(2026, 6, 9, 22, 47, 53)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from app.db.database import init_db, reset_engine

    db_path = tmp_path / "date_norm.db"
    monkeypatch.setenv("AGENTYS_DB_PATH", str(db_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()
    init_db()
    yield db_path
    reset_engine()


def _seed_account() -> int:
    from app.db.database import get_db_session
    from app.db.models.account import Account

    with get_db_session() as session:
        account = Account(email="karine.morel@gmail.com", provider="gmail", user_id=777)
        session.add(account)
        session.flush()
        account_id = account.id
        session.commit()
    return account_id


def _fake_header_email(received_at):
    obj = MagicMock()
    obj.id = "msg-aware-1"
    obj.subject = "Re: Test application aujourd'hui"
    obj.sender = "nathanroy@gmail.com"
    obj.sender_name = "Nathan Roy"
    obj.to = ["karine.morel@gmail.com"]
    obj.received_at = received_at
    obj.is_read = True
    obj.is_starred = False
    obj.body = ""
    obj.body_html = None
    obj.conversation_id = "thread-1"
    return obj


def test_folder_refresh_stores_naive_utc_from_aware_provider_datetime(temp_db):
    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.models.email import Email

    account_id = _seed_account()

    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_message_headers.return_value = [_fake_header_email(KARINE_AWARE)]

    with patch("app.providers.factory.get_pooled_provider", return_value=provider), \
         patch.object(rh, "_resolve_folder_for_provider", return_value="[Gmail]/Trash"):
        synced = rh._refresh_folder_cache_bg("trash", account_id, "oauth-hash", limit=5)

    assert synced == 1
    with get_db_session() as session:
        row = session.query(Email).filter_by(email_id="msg-aware-1").one()
        assert row.date == TRUE_UTC, (
            f"Email.date={row.date!r} — l'heure murale locale a été stockée au lieu de l'UTC"
        )
        assert rh._to_iso_utc(row.date) == "2026-06-09T22:47:53Z"


def test_folder_refresh_fallback_now_is_utc_not_local_wall_time(temp_db):
    """Sans received_at parsable, le fallback doit être l'instant UTC naïf —
    pas `datetime.now()` (heure murale locale) qui reproduirait le même
    décalage d'affichage pour ces lignes."""
    from datetime import timezone

    from app.api import routes_helpers as rh
    from app.db.database import get_db_session
    from app.db.models.email import Email

    account_id = _seed_account()

    provider = MagicMock()
    provider.authenticate.return_value = True
    provider.get_message_headers.return_value = [_fake_header_email(None)]

    with patch("app.providers.factory.get_pooled_provider", return_value=provider), \
         patch.object(rh, "_resolve_folder_for_provider", return_value="[Gmail]/Trash"):
        synced = rh._refresh_folder_cache_bg("trash", account_id, "oauth-hash", limit=5)

    assert synced == 1
    with get_db_session() as session:
        row = session.query(Email).filter_by(email_id="msg-aware-1").one()
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((row.date - utc_now).total_seconds()) < 120, (
            f"Fallback date={row.date!r} ≠ UTC now — datetime.now() local utilisé ?"
        )
