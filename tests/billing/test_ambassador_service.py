"""Service du programme ambassadeur (logique pure, sans Flask).

Lot 2 : génération de code unique + activation (création Coupon/PromoCode Stripe).
"""

import types

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models.base import Base
from app.db.models.billing import Ambassador


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


def _make_fake_stripe(fail_on=None):
    state = {"n": 0, "promo_kwargs": None}

    def coupon_create(**kw):
        if fail_on == "coupon":
            raise RuntimeError("stripe down")
        state["n"] += 1
        return {"id": f"coupon_{state['n']}", **kw}

    def promo_create(**kw):
        if fail_on == "promo":
            raise RuntimeError("stripe down")
        # API clover 2026-01-28 : le coupon est imbriqué dans `promotion`,
        # le param `coupon` direct est rejeté par le serveur Stripe.
        if "coupon" in kw:
            raise RuntimeError("Received unknown parameter: coupon")
        state["n"] += 1
        state["promo_kwargs"] = kw
        return {"id": f"promo_{state['n']}", **kw}

    stripe = types.SimpleNamespace(_state=state)
    stripe.Coupon = types.SimpleNamespace(create=coupon_create)
    stripe.PromotionCode = types.SimpleNamespace(create=promo_create)
    return stripe


# --- T2.1 : génération de code ---

def test_code_is_deterministic_for_same_seed(session):
    from app.billing.ambassador import generate_ambassador_code

    a = generate_ambassador_code(session, "marie@example.com")
    b = generate_ambassador_code(session, "marie@example.com")
    assert a == b


def test_code_uses_unambiguous_alphabet(session):
    from app.billing.ambassador import generate_ambassador_code

    code = generate_ambassador_code(session, "marie@example.com")
    assert 1 <= len(code) <= 32
    # Pas de caractères ambigus (0/O/1/I)
    assert not (set(code) & set("01OI"))


def test_code_avoids_collision_with_existing(session):
    from app.billing.ambassador import generate_ambassador_code

    forced = generate_ambassador_code(session, "marie@example.com")
    session.add(
        Ambassador(user_id=1, code=forced, status="active")
    )
    session.commit()

    other = generate_ambassador_code(session, "marie@example.com")
    assert other != forced


# --- T2.2 : activation ---

def test_activate_creates_coupon_promo_and_persists(session):
    from app.billing.ambassador import activate_ambassador

    stripe = _make_fake_stripe()
    amb = activate_ambassador(session, stripe, user_id=42, email="marie@example.com")

    assert amb.user_id == 42
    assert amb.code
    assert amb.stripe_coupon_id == "coupon_1"
    assert amb.stripe_promotion_code_id == "promo_2"
    assert amb.status == "active"
    # API clover : coupon imbriqué dans promotion={type:"coupon", coupon:id}
    assert stripe._state["promo_kwargs"]["promotion"] == {
        "type": "coupon",
        "coupon": "coupon_1",
    }
    # persisté
    row = session.execute(select(Ambassador).where(Ambassador.user_id == 42)).scalar_one()
    assert row.code == amb.code


def test_activate_is_idempotent_for_same_user(session):
    from app.billing.ambassador import activate_ambassador

    stripe = _make_fake_stripe()
    first = activate_ambassador(session, stripe, user_id=42, email="marie@example.com")
    again = activate_ambassador(session, stripe, user_id=42, email="marie@example.com")
    assert first.id == again.id
    assert session.execute(select(Ambassador)).scalars().all().__len__() == 1


def test_activate_propagates_stripe_failure(session):
    from app.billing.ambassador import activate_ambassador

    stripe = _make_fake_stripe(fail_on="coupon")
    with pytest.raises(RuntimeError):
        activate_ambassador(session, stripe, user_id=42, email="marie@example.com")
    # rien ne doit être persisté en cas d'échec Stripe
    assert session.execute(select(Ambassador)).scalars().all() == []
