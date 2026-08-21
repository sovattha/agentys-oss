# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Routes API pour les notifications push mobiles.

Endpoints disponibles:
- POST /push/devices - Enregistrer un device token
- DELETE /push/devices/<token> - Supprimer un device token
- GET /push/devices - Lister les devices enregistrés
- POST /push/send - Envoyer une notification push
- POST /push/broadcast - Envoyer une notification à tous les devices
- GET /push/stats - Statistiques des notifications
- GET /push/history - Historique des notifications envoyées
"""

import logging

from flask import Blueprint, request, jsonify, g

from app.api.admin import require_admin
from app.api.auth import is_trusted_loopback
from app.api.helpers import require_json
from app.domain.entities import PushNotificationCategory
from app.infrastructure.container import get_container

logger = logging.getLogger(__name__)


def _get_device_store():
    """Retourne le device store depuis le Container."""
    return get_container().get_device_store()


def _get_push_adapter():
    """Retourne le push adapter depuis le Container."""
    from app.infrastructure.push_adapter_factory import get_push_adapter
    return get_push_adapter()


def _get_push_notification_service():
    """Retourne le service de notifications push depuis le Container."""
    return get_container().get_push_notification_service()

push_bp = Blueprint("push", __name__)


# ============================================================================
# HELPERS
# ============================================================================

def mask_token(token: str, visible_chars: int = 20) -> str:
    """Masque un token pour l'affichage sécurisé."""
    if len(token) <= visible_chars:
        return token
    return token[:visible_chars] + "..."


def parse_category(category_str: str) -> PushNotificationCategory:
    """Parse une catégorie de notification avec fallback."""
    try:
        return PushNotificationCategory(category_str)
    except ValueError:
        return PushNotificationCategory.INFO


def _caller_owns_token(token: str) -> bool:
    """Vérifie que le caller JWT est bien propriétaire de ce device token.

    H-2 (audit security.md, issue #528) — `POST /push/send` était guardé par
    le blueprint auth guard mais n'inspectait pas l'ownership des tokens du
    body. N'importe quel caller authentifié pouvait ainsi pousser une notif
    à un device dont il avait simplement obtenu le token (DM screenshot,
    log leaké, install antérieure). Ce helper rétablit le check.

    Règles d'autorisation :
      - **Loopback Tauri sans JWT** (`g.auth_user is None`) : trusted, single
        host. La fenêtre desktop adresse forcément ses propres devices.
      - **JWT caller** : `device.user_id` doit matcher soit `auth_user["id"]`
        (sub JWT, string), soit `auth_user["email"]` (case-insensitive). Les
        clients mobile registrent avec l'un ou l'autre, on accepte les deux
        formes pour ne pas casser les devices existants.
      - **Device introuvable** OU `device.user_id` vide : refus. Un token
        non revendiqué ne doit appartenir à personne.
      - **Pas de JWT en remote** : l'auth guard a déjà rejeté en amont ; ce
        cas ne devrait pas être atteint mais on refuse par défaut.
    """
    auth_user = getattr(g, "auth_user", None)

    # Tauri desktop : le user IS le host. Pas de cross-tenant possible.
    if is_trusted_loopback() and auth_user is None:
        return True

    if not auth_user or not auth_user.get("email"):
        return False

    device = _get_device_store().get(token)
    if device is None:
        return False
    device_user_id = (device.user_id or "").strip()
    if not device_user_id:
        return False

    caller_id = str(auth_user.get("id") or "").strip()
    caller_email = (auth_user.get("email") or "").strip().lower()
    return (
        device_user_id == caller_id
        or device_user_id.lower() == caller_email
    )


# ============================================================================
# ROUTES - DEVICES
# ============================================================================

@push_bp.route("/devices", methods=["GET"])
def list_devices():
    """
    Liste les devices enregistrés du caller.

    H-3 (audit security.md, issue #529) — avant le fix, la route renvoyait
    l'inventaire COMPLET des devices (token masqué + `device_name`,
    plateforme, `app_version`, last-used timestamps) et acceptait un
    `?user_id=` attaquant-controlled. Énumération cross-tenant : un user
    authentifié pouvait scanner « les iPhones des autres ».

    Règles d'autorisation :
      - **Loopback Tauri sans JWT** : trusted, single-user host → liste
        complète (tout appartient au user du host).
      - **JWT caller non-admin** : ne voit QUE ses propres devices.
        `?user_id=` est ignoré côté caller (un user qui passe son propre id
        verra le même résultat ; le passer à un autre est silently no-op).
      - **JWT caller admin** : peut filtrer via `?user_id=` ; sans param,
        renvoie son propre inventaire (l'enum complète passe par
        `/admin/...` côté outillage opérateur, pas par cette route).

    Query params:
        user_id: ignoré pour les non-admins ; admin-only override.
    """
    auth_user = getattr(g, "auth_user", None)
    is_loopback_tauri = is_trusted_loopback() and auth_user is None

    store = _get_device_store()

    if is_loopback_tauri:
        # Tauri desktop : single-user host, on garde le comportement legacy
        # (incluant `?user_id=` libre — utile pour le devtools local).
        devices = store.get_all(request.args.get("user_id"))
    else:
        if not auth_user or not auth_user.get("email"):
            # Belt-and-suspenders : la blueprint guard est censée avoir
            # rejeté en amont. Réponse vide si jamais on tombe ici.
            devices = []
        else:
            from app.api.admin import _is_admin

            caller_id = str(auth_user.get("id") or "").strip()
            caller_email = (auth_user.get("email") or "").strip().lower()
            requested_uid = request.args.get("user_id")

            if _is_admin(caller_email) and requested_uid:
                # Admin override explicite : on respecte le filtre.
                devices = store.get_all(requested_uid)
            else:
                # Caller standard : ignore tout `?user_id=`, scope sur soi.
                # `device.user_id` peut matcher l'id JWT (sub) OU l'email,
                # symétrique avec `_caller_owns_token` (H-2). On post-filtre
                # car `store.get_all(filter)` n'accepte qu'une seule forme.
                all_devices = store.get_all()
                devices = [
                    d for d in all_devices
                    if (d.user_id or "").strip() == caller_id
                    or (d.user_id or "").strip().lower() == caller_email
                ]

    return jsonify({
        "count": len(devices),
        "devices": [
            {
                "token": mask_token(d.token),
                "platform": d.platform.value,
                "user_id": d.user_id,
                "device_name": d.device_name,
                "app_version": d.app_version,
                "created_at": d.created_at.isoformat(),
                "last_used_at": d.last_used_at.isoformat() if d.last_used_at else None,
                "is_active": d.is_active,
            }
            for d in devices
        ],
    })


@push_bp.route("/devices", methods=["POST"])
@require_json
def register_device():
    """
    Enregistre un nouveau device token.

    Body JSON:
        token: Token push du device (required)
        platform: "ios" | "android" | "web" (required)
        user_id: ID utilisateur (optional)
        device_name: Nom du device (optional)
        app_version: Version de l'app (optional)

    Returns:
        Device enregistré.
    """
    data = request.get_json()
    token = data.get("token")
    platform = data.get("platform")

    if not token:
        return jsonify({"error": "token is required"}), 400

    if not platform or platform not in ("ios", "android", "web"):
        return jsonify({"error": "platform must be 'ios', 'android', or 'web'"}), 400

    store = _get_device_store()

    try:
        device = store.register(
            token=token,
            platform=platform,
            user_id=data.get("user_id"),
            device_name=data.get("device_name"),
            app_version=data.get("app_version"),
        )

        return jsonify({
            "success": True,
            "device": {
                "token": mask_token(device.token),
                "platform": device.platform.value,
                "user_id": device.user_id,
                "device_name": device.device_name,
                "created_at": device.created_at.isoformat(),
            },
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@push_bp.route("/devices/<token>", methods=["DELETE"])
def unregister_device(token: str):
    """
    Supprime un device token.

    Args:
        token: Token du device à supprimer.

    Returns:
        Succès ou erreur.
    """
    store = _get_device_store()

    # Audit 2026-05-29: without this any authenticated user holding a victim's
    # full device token could unregister it and silence their push
    # notifications. Mirror the /push/send ownership guard (H-2). 404 (not 403)
    # avoids confirming the token exists but isn't yours.
    if not _caller_owns_token(token):
        return jsonify({"error": "Device not found"}), 404

    if store.unregister(token):
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Device not found"}), 404


# ============================================================================
# ROUTES - NOTIFICATIONS
# ============================================================================

@push_bp.route("/send", methods=["POST"])
@require_json
def send_notification():
    """
    Envoie une notification push à un ou plusieurs devices.

    Body JSON:
        tokens: Liste des tokens ou token unique (required)
        title: Titre de la notification (required)
        body: Corps du message (required)
        category: Catégorie (optional, default: "info")
        data: Données additionnelles (optional)
        priority: "low" | "normal" | "high" (optional, default: "normal")

    Returns:
        Résultat de l'envoi.
    """
    data = request.get_json()
    tokens = data.get("tokens", data.get("token"))
    title = data.get("title")
    body = data.get("body")

    if not tokens:
        return jsonify({"error": "tokens or token is required"}), 400
    if not title:
        return jsonify({"error": "title is required"}), 400
    if not body:
        return jsonify({"error": "body is required"}), 400

    # Normaliser en liste
    if isinstance(tokens, str):
        tokens = [tokens]

    # H-2 (audit security.md, issue #528): vérifier que le caller JWT possède
    # bien CHAQUE token avant de relayer la notif au push adapter. Sans ce
    # check, n'importe quel user authentifié pouvait push à un device dont
    # il connaissait juste le token (phishing surface évidente). All-or-
    # nothing : si UN seul token n'appartient pas au caller, on rejette
    # tout — cohérent avec `_check_token_ownership` côté oauth.py et évite
    # la confusion d'un 200 partiel.
    denied = [t for t in tokens if not _caller_owns_token(t)]
    if denied:
        auth_user = getattr(g, "auth_user", None)
        caller_email = (auth_user or {}).get("email") or "<no-jwt>"
        logger.warning(
            "[push/send] token ownership denied: caller=%s, denied_count=%d/%d",
            caller_email, len(denied), len(tokens),
        )
        # Réponse uniforme (token introuvable VS token d'autrui) pour ne pas
        # devenir un oracle d'existence.
        return jsonify({
            "error": "One or more tokens are not owned by the caller",
            "code": "TOKEN_OWNERSHIP_DENIED",
        }), 403

    category = parse_category(data.get("category", "info"))
    priority = data.get("priority", "normal")
    extra_data = data.get("data", {})

    service = _get_push_notification_service()

    # Envoyer les notifications
    if len(tokens) == 1:
        result = service.send_to_token(
            token=tokens[0],
            title=title,
            body=body,
            category=category,
            data=extra_data,
            priority=priority,
        )

        return jsonify({
            "success": result.success,
            "message_id": result.message_id,
            "error": result.error_message,
        }), 200 if result.success else 500
    else:
        results = service.send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            category=category,
            data=extra_data,
            priority=priority,
        )

        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        return jsonify({
            "total": len(results),
            "success": success_count,
            "failed": failed_count,
            "results": [
                {
                    "token": mask_token(t),
                    "success": r.success,
                    "message_id": r.message_id,
                    "error": r.error_message,
                }
                for t, r in zip(tokens, results)
            ],
        })


@push_bp.route("/broadcast", methods=["POST"])
@require_admin
@require_json
def broadcast_notification():
    """
    Envoie une notification à tous les devices enregistrés. **Admin only**.

    Audit C-3 (issue #523, 2026-05-05): cette route était protégée par le
    blueprint auth guard mais pas par `@require_admin`. N'importe quel user
    authentifié pouvait broadcast une notif phishing à toute la base mobile.
    Aligné sur `marketplace.approve_agent` (`@require_admin`).

    Body JSON:
        title: Titre de la notification (required)
        body: Corps du message (required)
        category: Catégorie (optional)
        data: Données additionnelles (optional)
        priority: Priorité (optional)
        user_id: Limiter à un utilisateur (optional)

    Returns:
        Résultat du broadcast.
    """
    data = request.get_json()
    title = data.get("title")
    body = data.get("body")

    if not title or not body:
        return jsonify({"error": "title and body are required"}), 400

    category = parse_category(data.get("category", "info"))
    service = _get_push_notification_service()
    results = service.broadcast(
        title=title,
        body=body,
        category=category,
        data=data.get("data", {}),
        priority=data.get("priority", "normal"),
        user_id=data.get("user_id"),
    )

    if not results:
        return jsonify({
            "success": True,
            "message": "No devices registered",
            "sent": 0,
        })

    success_count = sum(1 for r in results if r.success)

    return jsonify({
        "total_devices": len(results),
        "success": success_count,
        "failed": len(results) - success_count,
    })


# ============================================================================
# ROUTES - STATS & HISTORY
# ============================================================================

@push_bp.route("/stats", methods=["GET"])
@require_admin
def push_stats():
    """
    Statistiques des notifications push.

    Audit 2026-05-29: this aggregated the ENTIRE device inventory + global
    notification volume across all tenants for any authenticated caller (BI /
    enumeration leak). Gated to admins, mirroring /broadcast. No client calls
    this route, so the gate is non-breaking.

    Returns:
        Métriques des notifications.
    """
    service = _get_push_notification_service()
    store = _get_device_store()

    stats = service.get_stats()
    devices = store.get_all()

    # Breakdown par plateforme
    by_platform = {}
    for d in devices:
        p = d.platform.value
        by_platform[p] = by_platform.get(p, 0) + 1

    return jsonify({
        "notifications": stats,
        "devices": {
            "total": len(devices),
            "by_platform": by_platform,
        },
        "provider": _get_push_adapter().name,
    })


@push_bp.route("/history", methods=["GET"])
@require_admin
def push_history():
    """
    Historique des notifications envoyées.

    Audit 2026-05-29: this returned every tenant's notification titles + bodies
    (masked token) to any authenticated caller. Gated to admins, mirroring
    /broadcast and /stats. No client calls this route, so the gate is
    non-breaking.

    Query params:
        limit: Nombre max (default: 50)

    Returns:
        Liste des notifications récentes.
    """
    limit = request.args.get("limit", 50, type=int)
    service = _get_push_notification_service()
    records = service.get_records(limit=limit)

    return jsonify({
        "count": len(records),
        "history": [
            {
                "title": r.notification.title,
                "body": r.notification.body,
                "category": r.notification.category.value,
                "device_token": mask_token(r.device_token),
                "status": r.status.value,
                "message_id": r.message_id,
                "sent_at": r.sent_at.isoformat(),
                "error": r.error_message,
            }
            for r in records
        ],
    })
