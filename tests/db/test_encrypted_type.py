"""Tests for EncryptedString SQLAlchemy TypeDecorator.

Behavior under test:
- bind_param encrypts plaintext via Fernet
- bind_param/result_value handle None
- result_value decrypts Fernet ciphertext
- result_value passes through legacy plaintext (backward compat for
  unmigrated rows whose tokens were stored before this type was wired)
- round-trip via SQLAlchemy persists ciphertext and yields plaintext on load
- raw SELECT (bypassing the decorator) returns ciphertext, not plaintext
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text

from app.db.types.encrypted import EncryptedString


@pytest.fixture
def fernet_type() -> EncryptedString:
    return EncryptedString()


def test_bind_param_encrypts_plaintext(fernet_type: EncryptedString) -> None:
    plaintext = "ya29.A0AfH6SMC_example_access_token"

    cipher = fernet_type.process_bind_param(plaintext, dialect=None)

    assert cipher is not None
    assert cipher != plaintext
    assert isinstance(cipher, str)
    # Fernet tokens are base64url-encoded and start with the version byte 0x80
    # which encodes to the literal prefix "gAAAAA" in urlsafe_b64.
    assert cipher.startswith("gAAAAA")


def test_bind_param_returns_none_for_none(fernet_type: EncryptedString) -> None:
    assert fernet_type.process_bind_param(None, dialect=None) is None


def test_result_value_decrypts_fernet_ciphertext(fernet_type: EncryptedString) -> None:
    plaintext = "refresh-1//token-payload"
    cipher = fernet_type.process_bind_param(plaintext, dialect=None)

    decrypted = fernet_type.process_result_value(cipher, dialect=None)

    assert decrypted == plaintext


def test_result_value_returns_none_for_none(fernet_type: EncryptedString) -> None:
    assert fernet_type.process_result_value(None, dialect=None) is None


def test_result_value_passes_through_legacy_plaintext(fernet_type: EncryptedString) -> None:
    """A pre-migration row contains plaintext. Loading must not crash."""
    legacy_plaintext = "ya29.legacy-plain-token"

    result = fernet_type.process_result_value(legacy_plaintext, dialect=None)

    assert result == legacy_plaintext


def test_round_trip_through_sqlalchemy_yields_plaintext_on_load() -> None:
    metadata = MetaData()
    sample = Table(
        "sample",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("secret", EncryptedString),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    plaintext = "secret-value-42"
    with engine.connect() as conn:
        conn.execute(sample.insert().values(id=1, secret=plaintext))
        conn.commit()

    with engine.connect() as conn:
        loaded = conn.execute(select(sample.c.secret).where(sample.c.id == 1)).scalar_one()

    assert loaded == plaintext


def test_raw_select_returns_ciphertext_not_plaintext() -> None:
    """Bypassing the decorator (raw SQL) must surface Fernet ciphertext.

    This is the contract the CASA audit screenshot depends on: a DBA-level
    view of the column shows opaque encrypted bytes, never the original token.
    """
    metadata = MetaData()
    sample = Table(
        "sample",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("secret", EncryptedString),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    plaintext = "ya29.cipher-check"
    with engine.connect() as conn:
        conn.execute(sample.insert().values(id=1, secret=plaintext))
        conn.commit()

    with engine.connect() as conn:
        raw = conn.execute(text("SELECT secret FROM sample WHERE id = 1")).scalar_one()

    assert raw != plaintext
    assert isinstance(raw, str)
    assert raw.startswith("gAAAAA")
