# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lot 4 — logique admin : agrégation des commissions dues + marquage payé."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
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


def _seed(session):
    amb = Ambassador(user_id=42, code="MARIE", status="active")
    session.add(amb)
    session.commit()
    now = datetime(2026, 6, 18, 12, 0, 0)
    ref = Referral(
        ambassador_id=amb.id, referred_user_id=999,
        referred_stripe_customer_id="cus_1",
        signed_up_at=now, commission_window_end=now + timedelta(days=365),
    )
    session.add(ref)
    session.commit()
    # 2 commissions pending (1000 + 500) + 1 déjà payée (300)
    session.add_all([
        ReferralCommission(referral_id=ref.id, stripe_invoice_id="in_1",
                           amount_net=2000, commission_amount=1000, currency="chf", status="pending"),
        ReferralCommission(referral_id=ref.id, stripe_invoice_id="in_2",
                           amount_net=1000, commission_amount=500, currency="chf", status="pending"),
        ReferralCommission(referral_id=ref.id, stripe_invoice_id="in_3",
                           amount_net=600, commission_amount=300, currency="chf", status="paid"),
    ])
    session.commit()
    return amb, ref


def test_summary_aggregates_pending_per_ambassador(session):
    from app.billing.ambassador import admin_commission_summary

    _seed(session)
    rows = admin_commission_summary(session)

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "MARIE"
    assert row["currency"] == "chf"
    assert row["pending_amount"] == 1500
    assert row["pending_count"] == 2
    # Les ids pending sont nécessaires au bouton "marquer payé" de l'admin.
    pending_ids = [
        c.id for c in session.execute(
            select(ReferralCommission).where(ReferralCommission.status == "pending")
        ).scalars().all()
    ]
    assert sorted(row["pending_commission_ids"]) == sorted(pending_ids)


def test_mark_paid_transitions_pending_to_paid(session):
    from app.billing.ambassador import mark_commissions_paid

    _seed(session)
    pending_ids = [
        c.id for c in session.execute(
            select(ReferralCommission).where(ReferralCommission.status == "pending")
        ).scalars().all()
    ]
    now = datetime(2026, 7, 1, 9, 0, 0)
    updated = mark_commissions_paid(session, pending_ids, now=now)

    assert updated == 2
    remaining = session.execute(
        select(ReferralCommission).where(ReferralCommission.status == "pending")
    ).scalars().all()
    assert remaining == []
    one = session.execute(
        select(ReferralCommission).where(ReferralCommission.stripe_invoice_id == "in_1")
    ).scalar_one()
    assert one.status == "paid"
    assert one.paid_at == now


def test_mark_paid_ignores_already_paid(session):
    from app.billing.ambassador import mark_commissions_paid

    _seed(session)
    already_paid = session.execute(
        select(ReferralCommission).where(ReferralCommission.stripe_invoice_id == "in_3")
    ).scalar_one()
    updated = mark_commissions_paid(session, [already_paid.id], now=datetime(2026, 7, 1))
    assert updated == 0
