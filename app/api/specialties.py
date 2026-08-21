# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API REST pour les spécialités (Expert Mode).

Endpoints:
- GET  /api/specialties              — Liste toutes les spécialités
- GET  /api/specialties/<id>         — Détail d'une spécialité
- POST /api/specialties/<id>/activate   — Activer une spécialité
- POST /api/specialties/<id>/deactivate — Désactiver une spécialité
"""

import logging
from datetime import datetime

from flask import Blueprint, jsonify

from app.specialty_engine import get_specialty_engine
from app.api.settings import load_settings, save_settings, _get_current_account_id
from app.api.utils.errors import error_response

logger = logging.getLogger(__name__)

specialties_bp = Blueprint("specialties", __name__)


@specialties_bp.route("/specialties", methods=["GET"])
def list_specialties():
    """
    Liste toutes les spécialités disponibles.
    ---
    tags:
      - Specialties
    responses:
      200:
        description: Liste des spécialités avec statut d'activation
    """
    engine = get_specialty_engine()
    specialties = engine.list_specialties()
    # Per-account specialty activation state — never read the process-global
    # settings.json, which would surface another tenant's activations
    # (audit 2026-05-29). Matches get_settings/update_settings (settings.py).
    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    active = settings.get("active_specialties", [])
    activations = settings.get("specialty_activations", {})

    result = []
    for spec in specialties:
        spec_id = spec.get("specialty_id", "")
        experts = spec.get("experts", [])
        activation = activations.get(spec_id, {})
        result.append({
            "id": spec_id,
            "name": spec.get("name", spec_id),
            "description": spec.get("description", ""),
            "jurisdiction": spec.get("jurisdiction", ""),
            "language": spec.get("language", "fr"),
            "expert_count": len(experts),
            "experts_summary": [
                {"id": e["id"], "name": e["name"]}
                for e in experts
            ],
            "is_active": spec_id in active,
            "activated_at": activation.get("activated_at"),
            "price_monthly": 20,
        })

    return jsonify(result), 200


@specialties_bp.route("/specialties/<spec_id>", methods=["GET"])
def get_specialty(spec_id: str):
    """
    Détail complet d'une spécialité.
    ---
    tags:
      - Specialties
    parameters:
      - name: spec_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Détail de la spécialité
      404:
        description: Spécialité introuvable
    """
    engine = get_specialty_engine()
    spec = engine.get_specialty(spec_id)
    if not spec:
        return error_response("SPECIALTY_NOT_FOUND", "Specialty not found", 404)

    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    active = settings.get("active_specialties", [])
    activations = settings.get("specialty_activations", {})
    activation = activations.get(spec_id, {})

    # Load response guidelines preview (first 500 chars)
    guidelines_preview = ""
    try:
        from app.specialty_engine import SPECIALTIES_DIR
        guidelines_file = SPECIALTIES_DIR / spec_id / "response-guidelines.md"
        if guidelines_file.exists():
            full = guidelines_file.read_text(encoding="utf-8")
            guidelines_preview = full[:500] + ("..." if len(full) > 500 else "")
    except Exception:
        pass

    # List templates
    templates = []
    try:
        from app.specialty_engine import SPECIALTIES_DIR
        tpl_dir = SPECIALTIES_DIR / spec_id / "templates"
        if tpl_dir.exists():
            templates = [f.stem for f in sorted(tpl_dir.glob("*.md"))]
    except Exception:
        pass

    experts = spec.get("experts", [])
    risk_levels = spec.get("risk_levels", {})

    return jsonify({
        "id": spec.get("specialty_id", spec_id),
        "name": spec.get("name", spec_id),
        "description": spec.get("description", ""),
        "jurisdiction": spec.get("jurisdiction", ""),
        "language": spec.get("language", "fr"),
        "version": spec.get("version", "1.0"),
        "target_users": spec.get("target_users", []),
        "experts": [
            {
                "id": e["id"],
                "name": e["name"],
                "topics": e.get("topics", []),
                "priority": e.get("priority", 2),
            }
            for e in experts
        ],
        "templates": templates,
        "guidelines_preview": guidelines_preview,
        "risk_levels": {
            level: {"description": info.get("description", ""), "trigger_count": len(info.get("triggers", []))}
            for level, info in risk_levels.items()
        },
        "routing": spec.get("routing", {}),
        "is_active": spec_id in active,
        "activated_at": activation.get("activated_at"),
        "price_monthly": 20,
    }), 200


@specialties_bp.route("/specialties/<spec_id>/activate", methods=["POST"])
def activate_specialty(spec_id: str):
    """
    Active une spécialité.
    ---
    tags:
      - Specialties
    parameters:
      - name: spec_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Spécialité activée
      404:
        description: Spécialité introuvable
    """
    engine = get_specialty_engine()
    spec = engine.get_specialty(spec_id)
    if not spec:
        return error_response("SPECIALTY_NOT_FOUND", "Specialty not found", 404)

    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    active = settings.get("active_specialties", [])
    activations = settings.get("specialty_activations", {})

    if spec_id not in active:
        active.append(spec_id)

    activations[spec_id] = {
        "activated_at": datetime.now().isoformat(),
        "status": "active",
    }

    settings["active_specialties"] = active
    settings["specialty_activations"] = activations

    if save_settings(settings, account_id=account_id):
        logger.info("[OK] Specialty activated: %s", spec_id)
        return jsonify({"success": True, "active_specialties": active}), 200
    else:
        return jsonify({"error": "Échec de sauvegarde"}), 500


@specialties_bp.route("/specialties/<spec_id>/deactivate", methods=["POST"])
def deactivate_specialty(spec_id: str):
    """
    Désactive une spécialité.
    ---
    tags:
      - Specialties
    parameters:
      - name: spec_id
        in: path
        type: string
        required: true
    responses:
      200:
        description: Spécialité désactivée
    """
    account_id = _get_current_account_id()
    settings = load_settings(account_id=account_id)
    active = settings.get("active_specialties", [])
    activations = settings.get("specialty_activations", {})

    if spec_id in active:
        active.remove(spec_id)

    if spec_id in activations:
        activations[spec_id]["status"] = "inactive"
        activations[spec_id]["deactivated_at"] = datetime.now().isoformat()

    settings["active_specialties"] = active
    settings["specialty_activations"] = activations

    if save_settings(settings, account_id=account_id):
        logger.info("[OK] Specialty deactivated: %s", spec_id)
        return jsonify({"success": True, "active_specialties": active}), 200
    else:
        return jsonify({"error": "Échec de sauvegarde"}), 500
