"""Logique webhook du programme ambassadeur (argent réel).

Lot 3 :
- attach_referral_from_checkout : rattache un filleul via le promo code utilisé,
  bloque l'auto-parrainage, idempotent par customer.
- record_commission_from_invoice : 50 % du NET encaissé, idempotent par invoice,
  seulement dans la fenêtre de 12 mois.
"""

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


def _ambassador(session, *, user_id=42, code="MARIE", promo="promo_2", coupon="coupon_1"):
    amb = Ambassador(
        user_id=user_id,
        code=code,
        stripe_coupon_id=coupon,
        stripe_promotion_code_id=promo,
        status="active",
    )
    session.add(amb)
    session.commit()
    return amb


def _checkout(*, customer="cus_filleul", user_id=999, promo="promo_2"):
    return {
        "customer": customer,
        "client_reference_id": str(user_id),
        "discounts": [{"coupon": "coupon_1", "promotion_code": promo}],
    }


# --- T3.1 : rattachement ---

def test_attach_referral_links_customer_to_ambassador(session):
    from app.billing.ambassador import attach_referral_from_checkout

    amb = _ambassador(session)
    ref = attach_referral_from_checkout(session, _checkout())

    assert ref is not None
    assert ref.ambassador_id == amb.id
    assert ref.referred_stripe_customer_id == "cus_filleul"
    assert ref.referred_user_id == 999
    # fenêtre 12 mois
    assert (ref.commission_window_end - ref.signed_up_at).days == 365


def test_attach_referral_ignores_unknown_promo(session):
    from app.billing.ambassador import attach_referral_from_checkout

    _ambassador(session, promo="promo_2")
    ref = attach_referral_from_checkout(session, _checkout(promo="promo_UNKNOWN"))
    assert ref is None


def test_attach_referral_is_idempotent_by_customer(session):
    from app.billing.ambassador import attach_referral_from_checkout

    _ambassador(session)
    first = attach_referral_from_checkout(session, _checkout())
    again = attach_referral_from_checkout(session, _checkout())
    assert first.id == again.id
    assert len(session.execute(select(Referral)).scalars().all()) == 1


# --- T3.2 : anti-auto-parrainage ---

def test_attach_referral_blocks_self_referral(session):
    from app.billing.ambassador import attach_referral_from_checkout

    _ambassador(session, user_id=42)
    # le filleul EST l'ambassadeur (même user_id)
    ref = attach_referral_from_checkout(session, _checkout(user_id=42))
    assert ref is None
    assert session.execute(select(Referral)).scalars().all() == []


def test_attach_referral_skips_when_user_unresolvable(session):
    from app.billing.ambassador import attach_referral_from_checkout

    _ambassador(session)
    # Pas de client_reference_id ni metadata.agentys_user_id → user non résolvable.
    # On ne rattache PAS (sinon referred_user_id=0 contourne l'anti-auto-parrainage).
    checkout = {"customer": "cus_x", "discounts": [{"promotion_code": "promo_2"}]}
    ref = attach_referral_from_checkout(session, checkout)
    assert ref is None
    assert session.execute(select(Referral)).scalars().all() == []


# --- T3.3 : commission ---

def _invoice(*, invoice_id="in_1", customer="cus_filleul", amount_paid=2000, currency="chf"):
    return {
        "id": invoice_id,
        "customer": customer,
        "amount_paid": amount_paid,
        "currency": currency,
    }


def _seed_referral(session, *, customer="cus_filleul", window_days=365, now=None):
    amb = _ambassador(session)
    now = now or datetime(2026, 6, 18, 12, 0, 0)
    ref = Referral(
        ambassador_id=amb.id,
        referred_user_id=999,
        referred_stripe_customer_id=customer,
        signed_up_at=now,
        commission_window_end=now + timedelta(days=window_days),
    )
    session.add(ref)
    session.commit()
    return ref


def test_record_commission_is_half_of_net(session):
    from app.billing.ambassador import record_commission_from_invoice

    _seed_referral(session)
    now = datetime(2026, 7, 1, 12, 0, 0)
    com = record_commission_from_invoice(session, _invoice(amount_paid=2000), now=now)

    assert com is not None
    assert com.amount_net == 2000
    assert com.commission_amount == 1000
    assert com.currency == "chf"
    assert com.status == "pending"


def test_record_commission_is_idempotent_by_invoice(session):
    from app.billing.ambassador import record_commission_from_invoice

    _seed_referral(session)
    now = datetime(2026, 7, 1, 12, 0, 0)
    record_commission_from_invoice(session, _invoice(invoice_id="in_dup"), now=now)
    record_commission_from_invoice(session, _invoice(invoice_id="in_dup"), now=now)
    assert len(session.execute(select(ReferralCommission)).scalars().all()) == 1


def test_record_commission_ignores_unknown_customer(session):
    from app.billing.ambassador import record_commission_from_invoice

    _seed_referral(session, customer="cus_filleul")
    now = datetime(2026, 7, 1, 12, 0, 0)
    com = record_commission_from_invoice(session, _invoice(customer="cus_inconnu"), now=now)
    assert com is None


# --- T3.4 : fenêtre 12 mois ---

def test_record_commission_skips_outside_window(session):
    from app.billing.ambassador import record_commission_from_invoice

    signup = datetime(2026, 1, 1, 12, 0, 0)
    _seed_referral(session, window_days=365, now=signup)
    # 13 mois après le signup → hors fenêtre
    too_late = signup + timedelta(days=400)
    com = record_commission_from_invoice(session, _invoice(), now=too_late)
    assert com is None
    assert session.execute(select(ReferralCommission)).scalars().all() == []
