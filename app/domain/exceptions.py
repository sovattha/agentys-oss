# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Exceptions de domaine pour Agentys.

Ce module définit les exceptions métier utilisées dans la couche Domain.
Ces exceptions représentent des violations de règles métier et sont
distinctes des erreurs techniques (infrastructure).

Clean Architecture:
- Exceptions définies dans le Domain
- Utilisées par les Entities et Use Cases
- Les Adapters traduisent vers/depuis ces exceptions
"""


class DomainError(Exception):
    """Exception de base pour toutes les erreurs du domaine."""

    def __init__(self, message: str, code: str = "DOMAIN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ValidationError(DomainError):
    """Erreur de validation des données."""

    def __init__(self, message: str, field: str = "", code: str = "VALIDATION_ERROR"):
        self.field = field
        super().__init__(message, code)


class EmptyValueError(ValidationError):
    """Valeur vide non autorisée."""

    def __init__(self, field: str, message: str = ""):
        msg = message or f"{field} cannot be empty"
        super().__init__(msg, field, "EMPTY_VALUE")


class InvalidBoundsError(ValidationError):
    """Valeur hors des bornes autorisées."""

    def __init__(
        self,
        field: str,
        value: float,
        min_val: float = None,
        max_val: float = None,
        message: str = ""
    ):
        self.value = value
        self.min_val = min_val
        self.max_val = max_val

        if not message:
            bounds_str = ""
            if min_val is not None and max_val is not None:
                bounds_str = f"[{min_val}, {max_val}]"
            elif min_val is not None:
                bounds_str = f">= {min_val}"
            elif max_val is not None:
                bounds_str = f"<= {max_val}"
            message = f"{field} must be {bounds_str}, got {value}"

        super().__init__(message, field, "INVALID_BOUNDS")


class InvalidFormatError(ValidationError):
    """Format de données invalide."""

    def __init__(self, field: str, expected_format: str, actual_value: str = ""):
        self.expected_format = expected_format
        self.actual_value = actual_value
        message = f"{field} has invalid format. Expected: {expected_format}"
        if actual_value:
            message += f", got: '{actual_value}'"
        super().__init__(message, field, "INVALID_FORMAT")


class EntityNotFoundError(DomainError):
    """Entité non trouvée."""

    def __init__(self, entity_type: str, entity_id: str):
        self.entity_type = entity_type
        self.entity_id = entity_id
        message = f"{entity_type} with id '{entity_id}' not found"
        super().__init__(message, "NOT_FOUND")


class BusinessRuleViolationError(DomainError):
    """Violation d'une règle métier."""

    def __init__(self, rule: str, message: str = ""):
        self.rule = rule
        msg = message or f"Business rule violated: {rule}"
        super().__init__(msg, "BUSINESS_RULE_VIOLATION")


class ConcurrencyError(DomainError):
    """Erreur de concurrence (modification simultanée)."""

    def __init__(self, entity_type: str, entity_id: str):
        self.entity_type = entity_type
        self.entity_id = entity_id
        message = f"Concurrent modification detected on {entity_type} '{entity_id}'"
        super().__init__(message, "CONCURRENCY_ERROR")


# =============================================================================
# Exceptions LLM (Infrastructure traduit vers ces exceptions Domain)
# =============================================================================


class LLMError(DomainError):
    """Exception de base pour toutes les erreurs LLM."""

    def __init__(self, message: str, provider: str = "", code: str = "LLM_ERROR"):
        self.provider = provider
        super().__init__(message, code)


class LLMAuthenticationError(LLMError):
    """Erreur d'authentification (API key invalide ou expirée)."""

    def __init__(self, provider: str, message: str = ""):
        msg = message or f"Authentication failed for {provider}"
        super().__init__(msg, provider, "LLM_AUTH_ERROR")


class LLMBillingError(LLMError):
    """Crédits épuisés ou erreur de facturation."""

    def __init__(self, provider: str, message: str = ""):
        msg = message or f"Crédits {provider} épuisés ou erreur de facturation"
        super().__init__(msg, provider, "LLM_BILLING_ERROR")


class LLMRateLimitError(LLMError):
    """Limite de requêtes atteinte (429)."""

    def __init__(self, provider: str, retry_after: int = None, message: str = ""):
        self.retry_after = retry_after
        msg = message or f"Rate limit exceeded for {provider}"
        if retry_after:
            msg += f". Retry after {retry_after} seconds"
        super().__init__(msg, provider, "LLM_RATE_LIMIT")


class LLMUnavailableError(LLMError):
    """Service LLM temporairement indisponible (5xx, timeout)."""

    def __init__(self, provider: str, message: str = ""):
        msg = message or f"{provider} service is unavailable"
        super().__init__(msg, provider, "LLM_UNAVAILABLE")


class LLMConnectionError(LLMError):
    """Impossible de se connecter au service LLM."""

    def __init__(self, provider: str, url: str = "", message: str = ""):
        self.url = url
        msg = message or f"Cannot connect to {provider}"
        if url:
            msg += f" at {url}"
        super().__init__(msg, provider, "LLM_CONNECTION_ERROR")


class LLMTimeoutError(LLMError):
    """Timeout lors de la requête LLM."""

    def __init__(self, provider: str, timeout_seconds: int = None, message: str = ""):
        self.timeout_seconds = timeout_seconds
        msg = message or f"Request to {provider} timed out"
        if timeout_seconds:
            msg += f" after {timeout_seconds} seconds"
        super().__init__(msg, provider, "LLM_TIMEOUT")


class LLMContextLengthError(LLMError):
    """Le prompt dépasse la limite de contexte du modèle."""

    def __init__(self, provider: str, max_tokens: int = None, actual_tokens: int = None, message: str = ""):
        self.max_tokens = max_tokens
        self.actual_tokens = actual_tokens
        msg = message or f"Context length exceeded for {provider}"
        if max_tokens and actual_tokens:
            msg += f". Max: {max_tokens}, got: {actual_tokens}"
        super().__init__(msg, provider, "LLM_CONTEXT_LENGTH")


class LLMResponseError(LLMError):
    """Réponse LLM invalide ou malformée."""

    def __init__(self, provider: str, message: str = ""):
        msg = message or f"Invalid response from {provider}"
        super().__init__(msg, provider, "LLM_RESPONSE_ERROR")


def classify_llm_error(exc: BaseException) -> tuple[bool, str, str]:
    """Classifie une exception LLM comme permanente vs transitoire.

    Une erreur permanente ne disparaitra pas avec un retry — il faut la surfacer
    a l'utilisateur immediatement (credits epuises, cle API invalide, modele
    inexistant). Une erreur transitoire (timeout, 5xx, rate-limit ponctuel)
    merite un retry et un fallback gracieux.

    Cette classification permet :
    1. A `_llm_generate` de propager les erreurs permanentes au lieu de les
       avaler silencieusement (sinon retries gaspilles + draft vide silencieux).
    2. Aux endpoints REST (compose, refine) de retourner un status code et
       un message utilisateur appropries au lieu de fuiter l'erreur brute du
       provider (qui contient `request_id` Anthropic + etat de billing).

    Args:
        exc: L'exception levee par le client LLM.

    Returns:
        (is_permanent, error_code, user_message)
        - is_permanent: True si retry inutile, False si transitoire
        - error_code: code court machine-readable ("LLM_CREDIT_EXHAUSTED", etc.)
        - user_message: message FR safe a renvoyer au client, sans details vendor
    """
    msg = str(exc).lower()

    # Credit balance / billing — "credit balance is too low", "insufficient_quota"
    if "credit balance" in msg or "insufficient_quota" in msg or (
        "insufficient" in msg and ("credit" in msg or "quota" in msg)
    ):
        return (
            True,
            "LLM_CREDIT_EXHAUSTED",
            "Credit IA insuffisant. Le service AI est temporairement indisponible.",
        )

    # Authentication failures — invalid/missing API key
    if (
        "authentication_error" in msg
        or "invalid api key" in msg
        or "invalid_api_key" in msg
        or "x-api-key" in msg
        or "401" in msg and "unauthorized" in msg
    ):
        return (
            True,
            "LLM_AUTH_ERROR",
            "Cle API invalide ou expiree. Verifiez la configuration du service AI.",
        )

    # Model not found / not available — config error, not transient
    if isinstance(exc, LLMModelNotFoundError) or (
        "model" in msg and ("not found" in msg or "not_found" in msg or "does not exist" in msg)
    ):
        return (
            True,
            "LLM_MODEL_NOT_FOUND",
            "Modele IA non trouve. Verifiez la configuration du service AI.",
        )

    # Bad request — invalid_request_error covers credits + most config errors
    # Match Anthropic's "invalid_request_error" type from the API response.
    if "invalid_request_error" in msg or ("400" in msg and "bad request" in msg):
        return (
            True,
            "LLM_INVALID_REQUEST",
            "Requete au service AI invalide. Si le probleme persiste, contactez le support.",
        )

    # Default: transient (timeout, 5xx, network blip, rate-limit ponctuel)
    return (
        False,
        "LLM_TRANSIENT",
        "Le service AI est temporairement indisponible. Reessayez dans quelques instants.",
    )


class LLMModelNotFoundError(LLMError):
    """Le modèle demandé n'existe pas."""

    def __init__(self, provider: str, model: str, message: str = ""):
        self.model = model
        msg = message or f"Model '{model}' not found on {provider}"
        super().__init__(msg, provider, "LLM_MODEL_NOT_FOUND")


# =============================================================================
# Exceptions Permissions (RBAC)
# =============================================================================


class InsufficientPermissionError(DomainError):
    """Accès refusé - permissions insuffisantes."""

    def __init__(self, holder_id: str, action: str):
        self.holder_id = holder_id
        self.action = action
        message = f"Permission denied: {holder_id} cannot perform '{action}'"
        super().__init__(message, "INSUFFICIENT_PERMISSION")


# Aliases pour rétrocompatibilité avec les tests
DomainValidationError = ValidationError
