"""Le Checkout Stripe doit accepter les promotion codes.

Sans `allow_promotion_codes=True`, un filleul ne peut pas saisir le code de
l'ambassadeur, et `checkout.session.completed` n'aura jamais de discount —
la chaîne de rattachement du programme ambassadeur ne se déclenche jamais.
"""


def test_checkout_session_allows_promotion_codes():
    from app.api.billing import _create_stripe_checkout_session

    captured: dict = {}

    class _Session:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return {"id": "cs_test"}

    class _Stripe:
        class checkout:
            Session = _Session

    _create_stripe_checkout_session(
        _Stripe,
        customer_id="cus_x",
        user_id=1,
        price_id="price_x",
        llm_overage_price_id=None,
        metadata={},
        success_url="https://ok",
        cancel_url="https://ko",
    )

    assert captured.get("allow_promotion_codes") is True
