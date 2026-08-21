"""Programme ambassadeur — logique métier (parrainage + commission).

Module sans Flask : fonctions pures prenant une ``session`` SQLAlchemy et un
client ``stripe`` déjà configuré. Appelé par les webhooks (``app/api/billing.py``)
et les endpoints (``app/api/ambassador.py``).

Décisions produit :
- Réduction filleul : -20 % sur le 1er paiement (coupon ``duration="once"``).
- Commission ambassadeur : 50 % du NET encaissé, sur 12 mois.
- Source de vérité du cash : Stripe (``invoice.paid`` → ``amount_paid``).
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.billing.stripe_sync import object_get, resolve_user_id_from_stripe_object
from app.db.models.billing import Ambassador, Referral, ReferralCommission

logger = logging.getLogger(__name__)

FILLEUL_DISCOUNT_PERCENT = 20
COMMISSION_RATE = 0.5
COMMISSION_WINDOW_DAYS = 365

# Alphabet sans caractères ambigus (0/O, 1/I) pour des codes lisibles à l'oral.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _base_code(seed: str) -> str:
    # Sel serveur optionnel : rend le code imprévisible à partir du seul email
    # public (évite l'énumération d'ambassadeurs) tout en restant déterministe.
    secret = os.environ.get("AMBASSADOR_CODE_SECRET", "")
    digest = hashlib.sha256(f"{secret}:{seed}".encode("utf-8")).digest()
    return "".join(_CODE_ALPHABET[b % len(_CODE_ALPHABET)] for b in digest[:_CODE_LENGTH])


def generate_ambassador_code(session, seed: str) -> str:
    """Code public déterministe et collision-safe.

    Déterministe pour un même ``seed`` (un ambassadeur réactivé garde son code),
    avec suffixe numérique si le code dérivé est déjà pris.
    """
    base = _base_code(seed)
    candidate = base
    suffix = 1
    while (
        session.execute(select(Ambassador).where(Ambassador.code == candidate)).scalar_one_or_none()
        is not None
    ):
        suffix += 1
        candidate = f"{base[:6]}{suffix:02d}"
    return candidate


def activate_ambassador(
    session,
    stripe,
    *,
    user_id: int,
    email: str = "",
    percent_off: int = FILLEUL_DISCOUNT_PERCENT,
) -> Ambassador:
    """Inscrit un utilisateur comme ambassadeur.

    Idempotent : si l'utilisateur est déjà ambassadeur, renvoie sa ligne sans
    recréer d'objets Stripe. Les appels Stripe sont effectués AVANT toute
    écriture DB, donc un échec réseau ne laisse aucune ligne orpheline (la
    transaction reste propre, l'erreur remonte au caller qui la classera).
    """
    existing = session.execute(
        select(Ambassador).where(Ambassador.user_id == int(user_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    code = generate_ambassador_code(session, f"{user_id}:{email}")
    coupon = stripe.Coupon.create(
        percent_off=percent_off,
        duration="once",
        name=f"Agentys ambassadeur {code}",
    )
    # API Stripe « clover » (2026-01-28+) : le coupon est imbriqué dans
    # `promotion`, le paramètre `coupon` direct n'est plus accepté.
    promo = stripe.PromotionCode.create(
        promotion={"type": "coupon", "coupon": object_get(coupon, "id")},
        code=code,
    )
    ambassador = Ambassador(
        user_id=int(user_id),
        code=code,
        stripe_coupon_id=str(object_get(coupon, "id")),
        stripe_promotion_code_id=str(object_get(promo, "id")),
        status="active",
    )
    session.add(ambassador)
    session.flush()
    logger.info("[AMBASSADOR] activated user_id=%s code=%s", user_id, code)
    return ambassador


def _utcnow_naive() -> datetime:
    # Aligné sur le reste du billing (timestamps naïfs en UTC).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _extract_discount_ids(checkout_session: Any) -> tuple[Optional[str], Optional[str]]:
    """Renvoie (promotion_code_id, coupon_id) du premier discount appliqué."""
    discounts = object_get(checkout_session, "discounts") or []
    for item in discounts:
        promo = object_get(item, "promotion_code")
        coupon = object_get(item, "coupon")
        if promo or coupon:
            return (str(promo) if promo else None, str(coupon) if coupon else None)
    return (None, None)


def _find_ambassador_by_discount(
    session, promo_id: Optional[str], coupon_id: Optional[str]
) -> Optional[Ambassador]:
    # Le promotion_code fait foi : s'il est présent, on NE retombe PAS sur le
    # coupon (un promo inconnu = pas de rattachement). Le coupon ne sert de clé
    # que lorsqu'aucun promotion_code n'accompagne le discount.
    if promo_id:
        return session.execute(
            select(Ambassador).where(Ambassador.stripe_promotion_code_id == promo_id)
        ).scalar_one_or_none()
    if coupon_id:
        return session.execute(
            select(Ambassador).where(Ambassador.stripe_coupon_id == coupon_id)
        ).scalar_one_or_none()
    return None


def attach_referral_from_checkout(session, checkout_session: Any) -> Optional[Referral]:
    """Rattache un filleul à un ambassadeur depuis ``checkout.session.completed``.

    No-op (renvoie ``None``) si : aucun discount, promo/coupon inconnu, pas de
    customer, ou auto-parrainage. Idempotent par ``referred_stripe_customer_id``.
    """
    promo_id, coupon_id = _extract_discount_ids(checkout_session)
    if not promo_id and not coupon_id:
        return None

    ambassador = _find_ambassador_by_discount(session, promo_id, coupon_id)
    if ambassador is None:
        return None

    customer_id = object_get(checkout_session, "customer")
    if not customer_id:
        return None

    referred_user_id = resolve_user_id_from_stripe_object(session, checkout_session)
    if referred_user_id is None:
        # Sans user résolvable, ne pas rattacher : sinon referred_user_id=0
        # contournerait silencieusement l'anti-auto-parrainage.
        logger.info("[AMBASSADOR] referral skipped: user unresolvable customer=%s", customer_id)
        return None
    if int(referred_user_id) == int(ambassador.user_id):
        logger.info("[AMBASSADOR] self-referral blocked user_id=%s", referred_user_id)
        return None

    existing = session.execute(
        select(Referral).where(Referral.referred_stripe_customer_id == str(customer_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    now = _utcnow_naive()
    referral = Referral(
        ambassador_id=ambassador.id,
        referred_user_id=int(referred_user_id),
        referred_stripe_customer_id=str(customer_id),
        signed_up_at=now,
        commission_window_end=now + timedelta(days=COMMISSION_WINDOW_DAYS),
    )
    session.add(referral)
    session.flush()
    logger.info(
        "[AMBASSADOR] referral attached ambassador_id=%s customer=%s",
        ambassador.id,
        customer_id,
    )
    return referral


def record_commission_from_invoice(
    session, invoice: Any, *, now: Optional[datetime] = None
) -> Optional[ReferralCommission]:
    """Crée la commission (50 % du NET) pour une ``invoice.paid`` d'un filleul.

    No-op si : customer/invoice manquants, montant nul, customer non parrainé,
    hors fenêtre 12 mois. Idempotent par ``stripe_invoice_id`` (contrainte
    unique + court-circuit applicatif).
    """
    customer_id = object_get(invoice, "customer")
    invoice_id = object_get(invoice, "id")
    amount_paid = object_get(invoice, "amount_paid")
    currency = object_get(invoice, "currency") or "chf"
    if not customer_id or not invoice_id:
        return None
    if not amount_paid or int(amount_paid) <= 0:
        return None

    referral = session.execute(
        select(Referral).where(Referral.referred_stripe_customer_id == str(customer_id))
    ).scalar_one_or_none()
    if referral is None:
        return None

    now = now or _utcnow_naive()
    if now > referral.commission_window_end:
        logger.info("[AMBASSADOR] commission skipped (outside window) invoice=%s", invoice_id)
        return None

    existing = session.execute(
        select(ReferralCommission).where(ReferralCommission.stripe_invoice_id == str(invoice_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    net = int(amount_paid)
    commission = ReferralCommission(
        referral_id=referral.id,
        stripe_invoice_id=str(invoice_id),
        amount_net=net,
        commission_amount=int(round(net * COMMISSION_RATE)),
        currency=str(currency),
        status="pending",
    )
    session.add(commission)
    session.flush()
    logger.info(
        "[AMBASSADOR] commission %s %s recorded invoice=%s",
        commission.commission_amount,
        currency,
        invoice_id,
    )
    return commission


def admin_commission_summary(session) -> list:
    """Agrège les commissions par (ambassadeur, devise) pour le dashboard admin.

    Agrégation en Python (volume faible, portable cross-dialecte). Trié par
    montant dû décroissant : l'admin voit en tête qui payer en priorité.
    """
    rows = session.execute(
        select(ReferralCommission, Ambassador)
        .join(Referral, ReferralCommission.referral_id == Referral.id)
        .join(Ambassador, Referral.ambassador_id == Ambassador.id)
    ).all()

    buckets: dict = {}
    for commission, ambassador in rows:
        key = (ambassador.id, commission.currency)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "ambassador_id": ambassador.id,
                "code": ambassador.code,
                "user_id": ambassador.user_id,
                "currency": commission.currency,
                "pending_amount": 0,
                "pending_count": 0,
                "pending_commission_ids": [],
                "paid_amount": 0,
                "paid_count": 0,
            }
            buckets[key] = bucket
        if commission.status == "paid":
            bucket["paid_amount"] += commission.commission_amount
            bucket["paid_count"] += 1
        else:
            bucket["pending_amount"] += commission.commission_amount
            bucket["pending_count"] += 1
            bucket["pending_commission_ids"].append(commission.id)

    return sorted(buckets.values(), key=lambda r: (-r["pending_amount"], r["code"]))


def mark_commissions_paid(session, commission_ids, *, now: Optional[datetime] = None) -> int:
    """Passe des commissions ``pending`` → ``paid`` (versement manuel effectué).

    Ignore les commissions déjà payées ou inexistantes. Renvoie le nombre
    réellement mis à jour.
    """
    ids = [int(i) for i in (commission_ids or [])]
    if not ids:
        return 0
    now = now or _utcnow_naive()
    commissions = session.execute(
        select(ReferralCommission).where(
            ReferralCommission.id.in_(ids),
            ReferralCommission.status == "pending",
        )
    ).scalars().all()
    for commission in commissions:
        commission.status = "paid"
        commission.paid_at = now
    session.flush()
    return len(commissions)
