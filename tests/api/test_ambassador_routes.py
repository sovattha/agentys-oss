"""Lot 4 — endpoints HTTP du programme ambassadeur.

- POST /api/ambassador/activate (user authentifié)
- GET  /api/ambassador/admin/commissions (admin)
- POST /api/ambassador/admin/commissions/mark-paid (admin)
"""

import types
from datetime import datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def _reset_engine():
    yield
    from app.db.database import reset_engine
    reset_engine()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DB_PATH", str(tmp_path / "amb.db"))
    from app.db.database import get_engine, init_db, reset_engine

    reset_engine()
    init_db(get_engine())
    from app.api.app import create_app

    return create_app(config={"TESTING": True})


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_fake_stripe():
    state = {"n": 0}

    def coupon_create(**kw):
        state["n"] += 1
        return {"id": f"coupon_{state['n']}", **kw}

    def promo_create(**kw):
        state["n"] += 1
        return {"id": f"promo_{state['n']}", **kw}

    stripe = types.SimpleNamespace()
    stripe.Coupon = types.SimpleNamespace(create=coupon_create)
    stripe.PromotionCode = types.SimpleNamespace(create=promo_create)
    return stripe


# --- T4.1 : activate ---

def test_activate_requires_auth(client, monkeypatch):
    import app.api.ambassador as amb
    monkeypatch.setattr(amb, "_current_user_or_none", lambda: None)
    resp = client.post("/api/ambassador/activate")
    assert resp.status_code == 401


def test_activate_creates_ambassador_and_returns_link(client, monkeypatch):
    import app.api.ambassador as amb
    monkeypatch.setattr(amb, "_current_user_or_none", lambda: {"id": 42, "email": "marie@example.com"})
    monkeypatch.setattr(amb, "_get_stripe", lambda: _make_fake_stripe())

    resp = client.post("/api/ambassador/activate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["code"]
    assert data["status"] == "active"
    assert data["referral_link"].endswith("ref=" + data["code"])


# --- T4.2 / T4.3 : admin ---

def _seed_commissions(now=None):
    from app.db.database import get_db_session
    from app.db.models.billing import Ambassador, Referral, ReferralCommission

    now = now or datetime(2026, 6, 18, 12, 0, 0)
    with get_db_session() as session:
        amb = Ambassador(user_id=42, code="MARIE", status="active")
        session.add(amb)
        session.flush()
        ref = Referral(
            ambassador_id=amb.id, referred_user_id=999,
            referred_stripe_customer_id="cus_1",
            signed_up_at=now, commission_window_end=now + timedelta(days=365),
        )
        session.add(ref)
        session.flush()
        session.add_all([
            ReferralCommission(referral_id=ref.id, stripe_invoice_id="in_1",
                               amount_net=2000, commission_amount=1000, currency="chf", status="pending"),
            ReferralCommission(referral_id=ref.id, stripe_invoice_id="in_2",
                               amount_net=1000, commission_amount=500, currency="chf", status="pending"),
        ])


def test_admin_commissions_requires_admin(client):
    resp = client.get("/api/ambassador/admin/commissions")
    assert resp.status_code in (401, 403, 503)


def test_admin_commissions_summary_with_token(client, monkeypatch):
    monkeypatch.setenv("AGENTYS_ADMIN_TOKEN", "secret")
    _seed_commissions()
    resp = client.get(
        "/api/ambassador/admin/commissions", headers={"X-Admin-Token": "secret"}
    )
    assert resp.status_code == 200
    rows = resp.get_json()["ambassadors"]
    assert rows[0]["code"] == "MARIE"
    assert rows[0]["pending_amount"] == 1500


def test_admin_mark_paid_with_token(client, monkeypatch):
    monkeypatch.setenv("AGENTYS_ADMIN_TOKEN", "secret")
    _seed_commissions()
    from app.db.database import get_db_session
    from app.db.models.billing import ReferralCommission
    from sqlalchemy import select

    with get_db_session() as session:
        ids = [
            c.id for c in session.execute(
                select(ReferralCommission).where(ReferralCommission.status == "pending")
            ).scalars().all()
        ]

    resp = client.post(
        "/api/ambassador/admin/commissions/mark-paid",
        headers={"X-Admin-Token": "secret"},
        json={"commission_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == 2


def test_admin_mark_paid_rejects_non_integer_ids(client, monkeypatch):
    monkeypatch.setenv("AGENTYS_ADMIN_TOKEN", "secret")
    resp = client.post(
        "/api/ambassador/admin/commissions/mark-paid",
        headers={"X-Admin-Token": "secret"},
        json={"commission_ids": [1, None, "x"]},
    )
    assert resp.status_code == 400
