# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les Email Templates.

Endpoints disponibles:
- GET /api/templates - Liste tous les templates
- POST /api/templates - Crée un template
- GET /api/templates/<id> - Récupère un template
- PUT /api/templates/<id> - Met à jour un template
- DELETE /api/templates/<id> - Supprime un template
- POST /api/templates/match - Trouve le meilleur template
- POST /api/templates/<id>/render - Rend un template avec variables
- GET /api/templates/stats - Statistiques d'utilisation
"""

import logging
import re
import uuid
from dataclasses import asdict
from functools import wraps
from typing import Callable, Tuple, Optional

from flask import Blueprint, jsonify, request, g


def _caller_email() -> Optional[str]:
    """Audit 2026-04-25 (HIGH-Backend-3): JWT-resolved email or loopback sentinel.

    Templates are now scoped per-user. Loopback (Tauri desktop) is a single-user
    host so we treat it as a global admin for backwards compat.
    """
    auth_user = getattr(g, "auth_user", None)
    if auth_user and auth_user.get("email"):
        return str(auth_user["email"]).lower()
    from app.api.auth import is_trusted_loopback
    if is_trusted_loopback():
        return None  # Tauri desktop — let routes treat None as "single user"
    return None


def _is_caller_admin() -> bool:
    auth_user = getattr(g, "auth_user", None)
    if not auth_user or not auth_user.get("email"):
        return False
    try:
        from app.api.admin import _is_admin
        return _is_admin(auth_user["email"])
    except Exception:
        return False


def _can_caller_edit_template(template) -> bool:
    """Owner of the template OR admin OR Tauri loopback (single-user) can edit."""
    from app.api.auth import is_trusted_loopback
    if is_trusted_loopback() and getattr(g, "auth_user", None) is None:
        return True
    owner = (getattr(template, "owner_email", None) or "").lower()
    caller = _caller_email() or ""
    if not owner:
        # Legacy template with no owner: only admins can mutate (defensive).
        return _is_caller_admin()
    return owner == caller or _is_caller_admin()


def _filter_visible_templates(templates):
    """Return only the templates the caller is allowed to see/use."""
    from app.api.auth import is_trusted_loopback
    if is_trusted_loopback() and getattr(g, "auth_user", None) is None:
        return templates  # Tauri single-user: no scoping
    caller = _caller_email() or ""
    out = []
    is_admin = _is_caller_admin()
    for t in templates:
        owner = (getattr(t, "owner_email", None) or "").lower()
        if not owner:
            # Legacy / unowned templates remain visible to all (read-only for
            # non-admins via _can_caller_edit_template).
            out.append(t)
        elif owner == caller or is_admin:
            out.append(t)
    return out

from app.application.email_template import (
    CreateTemplateUseCase,
    DeleteTemplateUseCase,
    GetTemplateStatsUseCase,
    GetTemplateUseCase,
    ListTemplatesUseCase,
    MatchTemplateUseCase,
    RenderTemplateUseCase,
    UpdateTemplateUseCase,
)
from app.domain.entities.email_template import EmailTemplate
from app.infrastructure.email_template_store import JsonEmailTemplateStore

logger = logging.getLogger(__name__)

email_templates_bp = Blueprint("email_templates", __name__)

_store = None


def get_store() -> JsonEmailTemplateStore:
    global _store
    if _store is None:
        _store = JsonEmailTemplateStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None


def require_json(f: Callable) -> Callable:
    """Require an object JSON body. silent=True + isinstance(dict) so a
    missing/non-JSON/array body returns a clean 400 instead of raising or
    blowing up on a later `data.get(...)` (audit 2026-05-19 STAB-02)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not body:
            return jsonify({"error": "JSON body required"}), 400
        return f(*args, **kwargs)
    return decorated


# ===========================================================================
# INPUT VALIDATION
# ===========================================================================

# Allowed categories (whitelist)
ALLOWED_CATEGORIES = {
    "URGENT", "MEETING", "QUESTION", "SUPPORT", "NORMAL", "FOLLOWUP",
    "INFO", "FEEDBACK", "COMPLAINT", "REQUEST", "OTHER"
}

# Allowed tones (whitelist)
ALLOWED_TONES = {"professional", "friendly", "formal"}

# Allowed languages (whitelist)
ALLOWED_LANGUAGES = {"fr", "en", "de", "es", "it"}

# Max lengths
MAX_NAME_LENGTH = 100
MAX_CATEGORY_LENGTH = 50
MAX_TEMPLATE_BODY_LENGTH = 10000
MAX_DESCRIPTION_LENGTH = 500
MAX_ID_LENGTH = 50

# Safe ID pattern (alphanumeric, dash, underscore only)
SAFE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


def validate_template_id(template_id: str) -> Tuple[bool, Optional[str]]:
    """Validate template ID format."""
    if not template_id:
        return False, "Template ID is required"
    if len(template_id) > MAX_ID_LENGTH:
        return False, f"Template ID exceeds max length ({MAX_ID_LENGTH})"
    if not SAFE_ID_PATTERN.match(template_id):
        return False, "Template ID contains invalid characters (allowed: a-z, A-Z, 0-9, -, _)"
    return True, None


def _validate_required_string(
    data: dict,
    field_name: str,
    display_name: str,
    max_length: int,
    is_update: bool,
    allow_empty: bool = False
) -> Tuple[bool, Optional[str]]:
    """Validate a required string field with max length constraint."""
    if field_name in data:
        value = data[field_name]
        if not isinstance(value, str):
            return False, f"{display_name} must be a string"
        if len(value) > max_length:
            return False, f"{display_name} exceeds max length ({max_length})"
        if not allow_empty and len(value.strip()) == 0:
            return False, f"{display_name} cannot be empty"
    elif not is_update:
        return False, f"{display_name} is required"
    return True, None


def _validate_optional_string(
    data: dict,
    field_name: str,
    display_name: str,
    max_length: int
) -> Tuple[bool, Optional[str]]:
    """Validate an optional string field with max length constraint."""
    if field_name in data and data[field_name] is not None:
        value = data[field_name]
        if not isinstance(value, str):
            return False, f"{display_name} must be a string"
        if len(value) > max_length:
            return False, f"{display_name} exceeds max length ({max_length})"
    return True, None


def _validate_whitelist(
    data: dict,
    field_name: str,
    display_name: str,
    allowed_values: set,
    is_update: bool,
    case_insensitive: bool = False
) -> Tuple[bool, Optional[str]]:
    """Validate a field against a whitelist of allowed values."""
    if field_name in data:
        value = data[field_name]
        if not isinstance(value, str):
            return False, f"{display_name} must be a string"
        check_value = value.upper() if case_insensitive else value
        check_set = {v.upper() for v in allowed_values} if case_insensitive else allowed_values
        if check_value not in check_set:
            return False, f"Invalid {display_name.lower()}. Allowed: {', '.join(sorted(allowed_values))}"
    elif not is_update:
        return False, f"{display_name} is required"
    return True, None


def _validate_conditions(data: dict) -> Tuple[bool, Optional[str]]:
    """Validate the conditions field."""
    if "conditions" not in data or data["conditions"] is None:
        return True, None

    conditions = data["conditions"]
    if not isinstance(conditions, dict):
        return False, "Conditions must be a dictionary"

    allowed_condition_keys = {"subject_contains", "body_contains"}
    for key in conditions:
        if key not in allowed_condition_keys:
            return False, f"Invalid condition key: {key}. Allowed: {', '.join(allowed_condition_keys)}"
        if not isinstance(conditions[key], list):
            return False, f"Condition '{key}' must be a list"
        for item in conditions[key]:
            if not isinstance(item, str):
                return False, f"Condition '{key}' items must be strings"
            if len(item) > 200:
                return False, "Condition keyword too long (max 200 chars)"
    return True, None


def validate_template_data(data: dict, is_update: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validate template input data.

    Security: Prevents injection attacks and ensures data integrity.
    """
    # Validate required string fields
    validators = [
        _validate_required_string(data, "name", "Name", MAX_NAME_LENGTH, is_update),
        _validate_whitelist(data, "category", "Category", ALLOWED_CATEGORIES, is_update, case_insensitive=True),
        _validate_required_string(data, "template_body", "Template body", MAX_TEMPLATE_BODY_LENGTH, is_update),
        _validate_optional_string(data, "description", "Description", MAX_DESCRIPTION_LENGTH),
        _validate_whitelist(data, "language", "Language", ALLOWED_LANGUAGES, is_update=True),
        _validate_whitelist(data, "tone", "Tone", ALLOWED_TONES, is_update=True),
    ]

    for is_valid, error in validators:
        if not is_valid:
            return False, error

    # Validate priority (integer with range)
    if "priority" in data:
        priority = data["priority"]
        if not isinstance(priority, int):
            return False, "Priority must be an integer"
        if priority < 0 or priority > 1000:
            return False, "Priority must be between 0 and 1000"

    # Validate enabled (boolean)
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            return False, "Enabled must be a boolean"

    # Validate conditions
    is_valid, error = _validate_conditions(data)
    if not is_valid:
        return False, error

    return True, None


def sanitize_template_data(data: dict) -> dict:
    """
    Sanitize template data by removing potentially dangerous fields.

    Security: Prevents mass assignment attacks. Note that `owner_email`
    is intentionally NOT in the allow-list — it's set by the route from
    the JWT, not by client input (audit 2026-04-25 HIGH-Backend-3).
    """
    allowed_fields = {
        "id", "name", "category", "template_body", "description",
        "language", "tone", "enabled", "priority", "conditions"
    }
    return {k: v for k, v in data.items() if k in allowed_fields}


@email_templates_bp.route("/templates", methods=["GET"])
def list_templates():
    store = get_store()
    category = request.args.get("category")

    # Validate category filter if provided
    if category:
        if len(category) > MAX_CATEGORY_LENGTH:
            return jsonify({"error": f"Category filter too long (max {MAX_CATEGORY_LENGTH} chars)"}), 400
        if category.upper() not in ALLOWED_CATEGORIES:
            return jsonify({"error": f"Invalid category. Allowed: {', '.join(sorted(ALLOWED_CATEGORIES))}"}), 400

    use_case = ListTemplatesUseCase(store)
    templates = use_case.execute(category)
    # Audit 2026-04-25 (HIGH-Backend-3): scope per-user.
    templates = _filter_visible_templates(templates)
    return jsonify({
        "templates": [asdict(t) for t in templates],
        "count": len(templates),
    })


@email_templates_bp.route("/templates", methods=["POST"])
@require_json
def create_template():
    store = get_store()
    data = request.get_json()

    # Sanitize input (prevent mass assignment)
    data = sanitize_template_data(data)

    # Generate ID if not provided
    if "id" not in data:
        data["id"] = str(uuid.uuid4())[:8]

    # Validate ID format
    is_valid, error = validate_template_id(data["id"])
    if not is_valid:
        return jsonify({"error": error}), 400

    # Validate all template data
    is_valid, error = validate_template_data(data)
    if not is_valid:
        return jsonify({"error": error}), 400

    # Audit 2026-04-25 (HIGH-Backend-3): stamp owner_email from JWT.
    owner = _caller_email()
    if owner is not None:
        data["owner_email"] = owner
    template = EmailTemplate(**data)
    use_case = CreateTemplateUseCase(store)
    result = use_case.execute(template)

    return jsonify(asdict(result)), 201


@email_templates_bp.route("/templates/<template_id>", methods=["GET"])
def get_template(template_id: str):
    # Validate ID format
    is_valid, error = validate_template_id(template_id)
    if not is_valid:
        return jsonify({"error": error}), 400

    store = get_store()
    use_case = GetTemplateUseCase(store)
    template = use_case.execute(template_id)

    if not template:
        return jsonify({"error": "Template not found"}), 404

    # Audit 2026-04-25 (HIGH-Backend-3): check visibility (legacy templates
    # without owner_email remain readable, owned templates only by owner/admin).
    if not _filter_visible_templates([template]):
        return jsonify({"error": "Template not found"}), 404

    return jsonify(asdict(template))


@email_templates_bp.route("/templates/<template_id>", methods=["PUT"])
@require_json
def update_template(template_id: str):
    # Validate ID format
    is_valid, error = validate_template_id(template_id)
    if not is_valid:
        return jsonify({"error": error}), 400

    store = get_store()
    data = request.get_json()

    # Sanitize input (prevent mass assignment)
    data = sanitize_template_data(data)

    get_use_case = GetTemplateUseCase(store)
    existing = get_use_case.execute(template_id)

    if not existing:
        return jsonify({"error": "Template not found"}), 404

    # Audit 2026-04-25 (HIGH-Backend-3): only owner / admin can mutate.
    if not _can_caller_edit_template(existing):
        return jsonify({"error": "Template not found"}), 404

    # Validate template data (partial update allowed)
    is_valid, error = validate_template_data(data, is_update=True)
    if not is_valid:
        return jsonify({"error": error}), 400

    # Merge with existing data — preserve original owner_email
    merged_data = asdict(existing)
    merged_data.update(data)
    merged_data["id"] = template_id
    merged_data["owner_email"] = existing.owner_email

    template = EmailTemplate(**merged_data)

    update_use_case = UpdateTemplateUseCase(store)
    result = update_use_case.execute(template)

    return jsonify(asdict(result))


@email_templates_bp.route("/templates/<template_id>", methods=["DELETE"])
def delete_template(template_id: str):
    # Validate ID format
    is_valid, error = validate_template_id(template_id)
    if not is_valid:
        return jsonify({"error": error}), 400

    store = get_store()
    # Audit 2026-04-25 (HIGH-Backend-3): only owner/admin can delete.
    get_use_case = GetTemplateUseCase(store)
    existing = get_use_case.execute(template_id)
    if not existing:
        return jsonify({"error": "Template not found"}), 404
    if not _can_caller_edit_template(existing):
        return jsonify({"error": "Template not found"}), 404

    use_case = DeleteTemplateUseCase(store)
    success = use_case.execute(template_id)

    if not success:
        return jsonify({"error": "Template not found"}), 404

    return jsonify({"message": "Template deleted", "id": template_id})


@email_templates_bp.route("/templates/match", methods=["POST"])
@require_json
def match_template():
    store = get_store()
    data = request.get_json()

    # Validate required fields
    required_fields = ["category", "subject", "body"]
    for field_name in required_fields:
        if field_name not in data:
            return jsonify({"error": f"Missing required field: {field_name}"}), 400

    # Validate category
    category = data["category"]
    if not isinstance(category, str):
        return jsonify({"error": "Category must be a string"}), 400
    if category.upper() not in ALLOWED_CATEGORIES:
        return jsonify({"error": f"Invalid category. Allowed: {', '.join(sorted(ALLOWED_CATEGORIES))}"}), 400

    # Validate subject and body lengths
    subject = data["subject"]
    body = data["body"]
    if not isinstance(subject, str) or not isinstance(body, str):
        return jsonify({"error": "Subject and body must be strings"}), 400
    if len(subject) > 1000:
        return jsonify({"error": "Subject too long (max 1000 chars)"}), 400
    if len(body) > 50000:
        return jsonify({"error": "Body too long (max 50000 chars)"}), 400

    # Validate language
    language = data.get("language", "fr")
    if language not in ALLOWED_LANGUAGES:
        return jsonify({"error": f"Invalid language. Allowed: {', '.join(sorted(ALLOWED_LANGUAGES))}"}), 400

    use_case = MatchTemplateUseCase(store)
    match = use_case.execute(
        category=category,
        subject=subject,
        body=body,
        language=language,
    )

    if not match:
        return jsonify({"match": None})

    # Audit 2026-04-25 (HIGH-Backend-3): hide cross-tenant template matches.
    if not _filter_visible_templates([match.template]):
        return jsonify({"match": None})

    return jsonify({
        "match": {
            "template": asdict(match.template),
            "score": match.score,
            "variables": match.variables,
        }
    })


# Maximum allowed variables in render request
MAX_RENDER_VARIABLES = 50
MAX_VARIABLE_KEY_LENGTH = 100
MAX_VARIABLE_VALUE_LENGTH = 5000


@email_templates_bp.route("/templates/<template_id>/render", methods=["POST"])
@require_json
def render_template(template_id: str):
    # Validate ID format
    is_valid, error = validate_template_id(template_id)
    if not is_valid:
        return jsonify({"error": error}), 400

    store = get_store()
    data = request.get_json()

    get_use_case = GetTemplateUseCase(store)
    template = get_use_case.execute(template_id)

    if not template:
        return jsonify({"error": "Template not found"}), 404

    # Audit 2026-04-25 (HIGH-Backend-3): hide cross-tenant render.
    if not _filter_visible_templates([template]):
        return jsonify({"error": "Template not found"}), 404

    variables = data.get("variables", {})

    # Validate variables
    if not isinstance(variables, dict):
        return jsonify({"error": "Variables must be a dictionary"}), 400

    if len(variables) > MAX_RENDER_VARIABLES:
        return jsonify({"error": f"Too many variables (max {MAX_RENDER_VARIABLES})"}), 400

    for key, value in variables.items():
        if not isinstance(key, str):
            return jsonify({"error": "Variable keys must be strings"}), 400
        if len(key) > MAX_VARIABLE_KEY_LENGTH:
            return jsonify({"error": f"Variable key too long (max {MAX_VARIABLE_KEY_LENGTH} chars)"}), 400
        if not isinstance(value, str):
            return jsonify({"error": f"Variable '{key}' value must be a string"}), 400
        if len(value) > MAX_VARIABLE_VALUE_LENGTH:
            return jsonify({"error": f"Variable '{key}' value too long (max {MAX_VARIABLE_VALUE_LENGTH} chars)"}), 400

    render_use_case = RenderTemplateUseCase(store)
    rendered = render_use_case.execute(template, variables)

    return jsonify({
        "rendered": rendered,
        "template_id": template_id,
    })


@email_templates_bp.route("/templates/stats", methods=["GET"])
def get_stats():
    store = get_store()
    use_case = GetTemplateStatsUseCase(store)
    stats = use_case.execute()

    return jsonify(stats)
