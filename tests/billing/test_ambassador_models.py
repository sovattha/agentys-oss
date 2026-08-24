# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Modèles ORM du programme ambassadeur / parrainage.

Vérifie les noms de tables et les contraintes d'unicité — colonne vertébrale
anti-bug de la feature :
- ``code`` unique           → pas deux ambassadeurs avec le même code
- ``referred_stripe_customer_id`` unique → un filleul rattaché une seule fois
- ``stripe_invoice_id`` unique → idempotence du webhook ``invoice.paid``
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.billing import Ambassador, Referral, ReferralCommission


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_tablenames_are_prefixed_to_avoid_legacy_collision():
    # La table legacy ``referrals`` existe déjà dans le SCHEMA — on préfixe.
    assert Ambassador.__tablename__ == "ambassadors"
    assert Referral.__tablename__ == "ambassador_referrals"
    assert ReferralCommission.__tablename__ == "ambassador_commissions"


def _make_ambassador(code: str = "MARIE") -> Ambassador:
    return Ambassador(
        user_id=123456,
        code=code,
        stripe_coupon_id="coupon_x",
        stripe_promotion_code_id="promo_x",
        status="active",
    )


def test_ambassador_code_is_unique(session):
    session.add(_make_ambassador("MARIE"))
    session.commit()

    session.add(_make_ambassador("MARIE"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_referred_customer_is_unique(session):
    amb = _make_ambassador()
    session.add(amb)
    session.commit()

    now = datetime(2026, 6, 18, 12, 0, 0)
    for _ in range(2):
        session.add(
            Referral(
                ambassador_id=amb.id,
                referred_user_id=999,
                referred_stripe_customer_id="cus_dup",
                signed_up_at=now,
                commission_window_end=now + timedelta(days=365),
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_commission_invoice_id_is_unique_for_idempotency(session):
    amb = _make_ambassador()
    session.add(amb)
    session.commit()
    now = datetime(2026, 6, 18, 12, 0, 0)
    ref = Referral(
        ambassador_id=amb.id,
        referred_user_id=999,
        referred_stripe_customer_id="cus_1",
        signed_up_at=now,
        commission_window_end=now + timedelta(days=365),
    )
    session.add(ref)
    session.commit()

    for _ in range(2):
        session.add(
            ReferralCommission(
                referral_id=ref.id,
                stripe_invoice_id="in_dup",
                amount_net=1000,
                commission_amount=500,
                currency="chf",
                status="pending",
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()
