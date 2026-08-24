# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Greffe du programme ambassadeur dans le dispatch webhook ``_process_stripe_event``.

Vérifie le ROUTING (checkout → rattachement, invoice.paid → commission,
invoice.payment_failed → rien). La logique métier est testée ailleurs.

Les objets Stripe de test n'ont pas de ``subscription`` : le code billing
existant n'appelle donc pas le SDK Stripe (``stripe`` peut être ``None``).
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.billing import _process_stripe_event
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


def _ambassador(session):
    amb = Ambassador(
        user_id=42, code="MARIE", stripe_coupon_id="coupon_1",
        stripe_promotion_code_id="promo_2", status="active",
    )
    session.add(amb)
    session.commit()
    return amb


def _referral(session, amb):
    now = datetime(2026, 6, 18, 12, 0, 0)
    ref = Referral(
        ambassador_id=amb.id, referred_user_id=999,
        referred_stripe_customer_id="cus_filleul",
        signed_up_at=now, commission_window_end=now + timedelta(days=365),
    )
    session.add(ref)
    session.commit()
    return ref


def test_checkout_completed_attaches_referral(session):
    _ambassador(session)
    checkout = {
        "customer": "cus_filleul",
        "client_reference_id": "999",
        "discounts": [{"coupon": "coupon_1", "promotion_code": "promo_2"}],
    }
    _process_stripe_event(session, None, "checkout.session.completed", checkout)

    ref = session.execute(select(Referral)).scalar_one_or_none()
    assert ref is not None
    assert ref.referred_stripe_customer_id == "cus_filleul"


def test_invoice_paid_records_commission(session):
    amb = _ambassador(session)
    _referral(session, amb)
    invoice = {"id": "in_1", "customer": "cus_filleul", "amount_paid": 2000, "currency": "chf"}
    _process_stripe_event(session, None, "invoice.paid", invoice)

    com = session.execute(select(ReferralCommission)).scalar_one_or_none()
    assert com is not None
    assert com.commission_amount == 1000


def test_invoice_payment_failed_creates_no_commission(session):
    amb = _ambassador(session)
    _referral(session, amb)
    invoice = {"id": "in_2", "customer": "cus_filleul", "amount_paid": 2000, "currency": "chf"}
    _process_stripe_event(session, None, "invoice.payment_failed", invoice)

    assert session.execute(select(ReferralCommission)).scalars().all() == []
