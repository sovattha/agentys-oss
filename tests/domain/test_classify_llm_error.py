# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""Tests pour le classificateur d'erreurs LLM (app.domain.exceptions.classify_llm_error).

Le classificateur distingue les erreurs LLM permanentes (retry inutile, surface
a l'utilisateur) des transitoires (retry + fallback gracieux). Il alimente :
- `_llm_generate` dans smart_routing.py : raise sur permanente, swallow sur transitoire
- `routes_misc.compose_email` : retourne 402/503 sur permanente, 500 generique
  sinon, sans fuiter le `request_id` Anthropic ni l'etat de billing au client

Reference : audit pipeline 2026-05-03, bugs #1/#2/#3.
"""


from app.domain.exceptions import (
    LLMResponseError,
    LLMModelNotFoundError,
    LLMContextLengthError,
    classify_llm_error,
)


class TestClassifyLLMError:
    """Verifie que les exceptions LLM sont correctement classifiees."""

    def test_credit_exhausted_anthropic_format(self):
        """Format reel renvoye par anthropic.BadRequestError quand credits epuises."""
        exc = LLMResponseError(
            provider="claude",
            message=(
                "Error code: 400 - {'type': 'error', 'error': "
                "{'type': 'invalid_request_error', "
                "'message': 'Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.'}, "
                "'request_id': 'req_011CafmonzYDSTmR4YR5D7Wa'}"
            ),
        )
        is_permanent, code, user_msg = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_CREDIT_EXHAUSTED"
        assert "Credit IA insuffisant" in user_msg
        # Critical : le message utilisateur ne doit PAS contenir le request_id
        # ni le nom "Anthropic" (fuite information vendor).
        assert "request_id" not in user_msg
        assert "Anthropic" not in user_msg
        assert "anthropic" not in user_msg.lower()

    def test_credit_insufficient_alt_phrasing(self):
        """Variante 'insufficient_quota' (format OpenAI / quota errors)."""
        exc = LLMResponseError(provider="openai", message="insufficient_quota: please add credit")
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_CREDIT_EXHAUSTED"

    def test_authentication_error(self):
        """Cle API invalide ou manquante."""
        exc = LLMResponseError(
            provider="claude",
            message="authentication_error: invalid API key provided",
        )
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_AUTH_ERROR"

    def test_model_not_found_via_class(self):
        """LLMModelNotFoundError est detectee par isinstance, pas par le message."""
        exc = LLMModelNotFoundError(provider="claude", model="claude-fake-99")
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_MODEL_NOT_FOUND"

    def test_model_not_found_via_message(self):
        """Provider retourne erreur generique avec 'model not found' dans le msg."""
        exc = LLMResponseError(
            provider="claude",
            message="The model 'claude-old-version' does not exist",
        )
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_MODEL_NOT_FOUND"

    def test_invalid_request_generic(self):
        """invalid_request_error sans credits ni auth : config erreur permanente."""
        exc = LLMResponseError(
            provider="claude",
            message="invalid_request_error: max_tokens must be positive",
        )
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is True
        assert code == "LLM_INVALID_REQUEST"

    def test_transient_timeout(self):
        """Timeout reseau : transitoire, retry OK."""
        exc = LLMResponseError(provider="claude", message="Request timed out")
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is False
        assert code == "LLM_TRANSIENT"

    def test_transient_5xx(self):
        """Erreur serveur 5xx : transitoire."""
        exc = LLMResponseError(provider="claude", message="503 Service Unavailable")
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is False
        assert code == "LLM_TRANSIENT"

    def test_transient_rate_limit(self):
        """Rate limit ponctuel : transitoire (le 429 sans 'invalid_request_error')."""
        exc = LLMResponseError(provider="claude", message="429 Too Many Requests")
        is_permanent, code, _ = classify_llm_error(exc)
        assert is_permanent is False
        assert code == "LLM_TRANSIENT"

    def test_user_messages_are_french_and_safe(self):
        """Tous les user_msg retournes sont en FR et ne fuitent rien de vendor."""
        test_cases = [
            LLMResponseError(provider="claude", message="credit balance is too low"),
            LLMResponseError(provider="claude", message="authentication_error"),
            LLMResponseError(provider="claude", message="model not found"),
            LLMResponseError(provider="claude", message="invalid_request_error"),
            LLMResponseError(provider="claude", message="timeout"),
        ]
        forbidden_in_user_msg = ["anthropic", "claude", "request_id", "openai", "api_key"]
        for exc in test_cases:
            _, _, user_msg = classify_llm_error(exc)
            user_msg_lower = user_msg.lower()
            for forbidden in forbidden_in_user_msg:
                assert forbidden not in user_msg_lower, (
                    f"Fuite vendor detectee dans user_msg: {user_msg!r} "
                    f"contient '{forbidden}' (source: {exc.message!r})"
                )

    def test_classification_returns_3_tuple(self):
        """Contract : classify_llm_error retourne exactement (bool, str, str)."""
        result = classify_llm_error(LLMResponseError(provider="claude", message="any"))
        assert isinstance(result, tuple)
        assert len(result) == 3
        is_permanent, code, user_msg = result
        assert isinstance(is_permanent, bool)
        assert isinstance(code, str) and code
        assert isinstance(user_msg, str) and user_msg

    def test_non_llm_exception_is_transient_default(self):
        """Une exception non-LLM est defaultee transitoire (pas un crash)."""
        exc = ValueError("some non-llm error")
        is_permanent, code, _ = classify_llm_error(exc)
        # ValueError sans contenu LLM-specifique tombe dans le default
        assert is_permanent is False
        assert code == "LLM_TRANSIENT"

    def test_context_length_error_currently_treated_transient(self):
        """LLMContextLengthError est rare; on documente le comportement actuel.

        Aujourd'hui : pas de match dans classify_llm_error -> default transitoire.
        Si un retry au tier inferieur (truncated context) est ajoute plus tard,
        il faudra aussi marquer CONTEXT_LENGTH comme permanent. Pour l'instant
        le retry du SmartRouter avec un prompt different peut potentiellement
        reussir, donc transitoire est defendable.
        """
        exc = LLMContextLengthError(provider="claude", max_tokens=200_000, actual_tokens=300_000)
        is_permanent, _, _ = classify_llm_error(exc)
        # Documentation behavior — pas une assertion forte
        assert is_permanent is False, "Si ce test casse, mettre a jour classify_llm_error"
