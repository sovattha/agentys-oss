# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Agent de detection et traitement des demandes de compte (mot de passe, email)."""

import json
import logging
import re
import secrets
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# Patterns de detection — mot de passe
_PASSWORD_RESET_RE = re.compile(
    r"\b(mot\s+de\s+passe|password|mdp|r[eé]initialiser|reset\s+(my\s+)?password|"
    r"oubli[eé]|forgot\s+(my\s+)?password|perdu\s+(mon\s+)?mot|"
    r"changer\s+(mon\s+)?mot\s+de\s+passe|change\s+(my\s+)?password|"
    r"nouveau\s+mot\s+de\s+passe|new\s+password|"
    r"lost\s+(my\s+)?password|can'?t\s+log\s*in|impossible\s+de\s+(me\s+)?connecter)\b",
    re.IGNORECASE,
)

# Patterns de detection — changement d'email
_EMAIL_CHANGE_RE = re.compile(
    r"\b(changer\s+(mon\s+)?e?-?mail|modifier\s+(mon\s+)?adresse|"
    r"change\s+(my\s+)?e?-?mail|update\s+(my\s+)?e?-?mail|"
    r"nouvelle\s+adresse\s+e?-?mail|new\s+e?-?mail\s+address|"
    r"mettre\s+[aà]\s+jour\s+(mon\s+)?e?-?mail)\b",
    re.IGNORECASE,
)

# Email extraction regex
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _load_agent_config() -> dict:
    """Lit app/data/agent_configs/account.json avec auto-migration du format legacy."""
    try:
        path = Path(__file__).parent / "data" / "agent_configs" / "account.json"
        if path.exists():
            config = json.loads(path.read_text(encoding="utf-8"))
            # Auto-migrate from old flat format
            if "wordpress_site_url" in config and "providers" not in config:
                migrated = {
                    "provider": "wordpress",
                    "brand_name": config.get("brand_name", ""),
                    "custom_reply_instructions": config.get("custom_reply_instructions", ""),
                    "admin_notification_email": config.get("admin_notification_email", ""),
                    "webhook_url": config.get("webhook_url", ""),
                    "auto_approve": config.get("auto_approve", False),
                    "notify_user_by_email": config.get("notify_user_by_email", True),
                    "password_policy": config.get("password_policy", {
                        "min_length": 12,
                        "require_uppercase": True,
                        "require_numbers": True,
                        "require_special": False,
                    }),
                    "rate_limits": config.get("rate_limits", {
                        "max_per_hour": 20,
                        "max_per_day": 100,
                    }),
                    "allowed_domains": config.get("allowed_domains", []),
                    "providers": {
                        "wordpress": {
                            "site_url": config.get("wordpress_site_url", ""),
                            "username": config.get("wordpress_username", ""),
                            "app_password": config.get("wordpress_app_password", ""),
                        },
                        "shopify": {"shop_domain": "", "admin_api_token": ""},
                        "custom": {
                            "base_url": "", "auth_type": "none",
                            "auth_credentials": {}, "endpoints": {},
                            "success_codes": [200, 201, 204],
                        },
                    },
                }
                path.write_text(json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("[AccountAgent] Config migrée du format legacy vers le nouveau format")
                return migrated
            return config
    except Exception:
        pass
    return {}


def _generate_password(policy: dict) -> str:
    """Genere un mot de passe respectant la politique configuree."""
    min_length = max(policy.get("min_length", 12), 8)
    require_uppercase = policy.get("require_uppercase", True)
    require_numbers = policy.get("require_numbers", True)
    require_special = policy.get("require_special", False)

    chars = string.ascii_lowercase
    required = []

    if require_uppercase:
        chars += string.ascii_uppercase
        required.append(secrets.choice(string.ascii_uppercase))
    if require_numbers:
        chars += string.digits
        required.append(secrets.choice(string.digits))
    if require_special:
        special = "!@#$%^&*"
        chars += special
        required.append(secrets.choice(special))

    # Fill remaining length
    remaining = min_length - len(required)
    password_chars = required + [secrets.choice(chars) for _ in range(remaining)]

    # Shuffle
    import random
    rng = random.SystemRandom()
    rng.shuffle(password_chars)

    return "".join(password_chars)


@dataclass
class AccountResult:
    detected: bool = False
    action: Literal["password_reset", "email_change", ""] = ""
    requester_email: str = ""
    requester_name: Optional[str] = None
    wp_user: Optional[dict] = None
    new_email: Optional[str] = None
    generated_password: Optional[str] = None        # Masked (last 4 chars)
    generated_password_full: Optional[str] = None    # Never serialized
    confidence: float = 0.0
    reason: str = ""
    status: Literal["pending", "approved", "rejected", "executed", "not_found", "done"] = "pending"
    method: str = "direct"  # "direct" | "reset_link"
    brand_name: str = ""
    provider_name: str = "wordpress"

    def to_dict(self) -> dict:
        """Safe serialization — masks password, omits full password."""
        d = {
            "detected": self.detected,
            "action": self.action,
            "requester_email": self.requester_email,
            "requester_name": self.requester_name,
            "wp_user_id": self.wp_user.get("id") if self.wp_user else None,
            "wp_username": self.wp_user.get("slug") if self.wp_user else None,
            "wp_user_email": self.wp_user.get("email") if self.wp_user else None,
            "new_email": self.new_email,
            "generated_password": self.generated_password,
            "confidence": self.confidence,
            "reason": self.reason,
            "status": self.status,
            "method": self.method,
            "brand_name": self.brand_name,
            "provider_name": self.provider_name,
        }
        return d

    def to_dict_full(self) -> dict:
        """Internal only — includes full password for execution."""
        d = self.to_dict()
        d["generated_password_full"] = self.generated_password_full
        return d


class AccountAgent:
    """Detecte les demandes de compte (mot de passe, email) — multi-provider."""

    def _get_config(self) -> dict:
        return _load_agent_config()

    def _get_provider(self):
        from app.integrations.account_provider_factory import create_account_provider
        config = self._get_config()
        return create_account_provider(config)

    def detect_and_analyze(
        self,
        sender_email: str,
        sender_name: Optional[str],
        subject: str,
        body: str,
    ) -> Optional[AccountResult]:
        """
        Retourne un AccountResult si l'email est une demande de compte, None sinon.
        """
        text = f"{subject}\n{body}"

        # Detect action type
        is_password = bool(_PASSWORD_RESET_RE.search(text))
        is_email_change = bool(_EMAIL_CHANGE_RE.search(text))

        if not is_password and not is_email_change:
            return None

        # Prefer password reset if both match (more common)
        action = "email_change" if is_email_change and not is_password else "password_reset"

        config = self._get_config()
        brand_name = config.get("brand_name", "")
        provider_name = config.get("provider", "wordpress")

        # Check allowed domains
        allowed_domains = config.get("allowed_domains", [])
        if allowed_domains:
            sender_domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
            if sender_domain not in [d.lower() for d in allowed_domains]:
                logger.info("[AccountAgent] Sender domain %s not in allowed list, ignoring", sender_domain)
                return None

        logger.info("[AccountAgent] Demande detectee: %s (from %s)", action, sender_email)

        # For email change: extract new email from body
        new_email = None
        if action == "email_change":
            new_email = self._extract_new_email(body, sender_email)

        # Provider lookup — try sender email first, then any email mentioned in the body
        lookup_email = sender_email
        wp_user = None
        try:
            provider = self._get_provider()
            wp_user = provider.search_user(sender_email)
            if not wp_user:
                # Sender not found — try emails extracted from body (e.g. "Voici mon email : x@y.com")
                body_emails = [e for e in _EMAIL_RE.findall(body) if e.lower() != sender_email.lower()]
                for candidate in body_emails:
                    wp_user = provider.search_user(candidate)
                    if wp_user:
                        lookup_email = candidate
                        logger.info("[AccountAgent] Sender not found, matched body email %s", candidate)
                        break
        except Exception as exc:
            if any(marker in str(exc) for marker in ("masqué", "••", "not configured", "masked")):
                logger.error("[AccountAgent] Credentials invalides/masqués — config à corriger: %s", exc)
                return AccountResult(
                    detected=True, action=action, requester_email=sender_email,
                    requester_name=sender_name,
                    status="pending",
                    reason="Credentials WordPress invalides ou masqués — vérifiez la configuration de l'Account Agent.",
                    confidence=0.9,
                    brand_name=brand_name, provider_name=provider_name,
                )
            logger.warning("[AccountAgent] Provider lookup failed: %s", exc)
            wp_user = None

        if not wp_user:
            if action == "password_reset":
                # Generate password anyway — admin will manually apply it on the platform
                password_policy = config.get("password_policy", {})
                _pwd_full = _generate_password(password_policy)
                _pwd_masked = "••••" + _pwd_full[-4:]
                return AccountResult(
                    detected=True, action=action, requester_email=lookup_email,
                    requester_name=sender_name,
                    generated_password=_pwd_masked, generated_password_full=_pwd_full,
                    confidence=0.6,
                    reason="Utilisateur non trouvé sur la plateforme — mise à jour manuelle requise.",
                    status="pending", method="direct",
                    brand_name=brand_name, provider_name=provider_name,
                )
            return AccountResult(
                detected=True,
                action=action,
                requester_email=lookup_email,
                requester_name=sender_name,
                confidence=0.3,
                reason="Utilisateur non trouvé sur la plateforme.",
                status="not_found",
                brand_name=brand_name,
                provider_name=provider_name,
            )

        # Password reset: generate secure password
        generated_password = None
        generated_password_full = None
        method = "direct"
        if action == "password_reset":
            # Shopify sends reset link, not direct password
            if provider_name == "shopify":
                method = "reset_link"
            else:
                password_policy = config.get("password_policy", {})
                generated_password_full = _generate_password(password_policy)
                generated_password = "••••" + generated_password_full[-4:]

        # Email change without new email specified
        if action == "email_change" and not new_email:
            return AccountResult(
                detected=True,
                action=action,
                requester_email=sender_email,
                requester_name=sender_name,
                wp_user=wp_user,
                confidence=0.5,
                reason="Nouvelle adresse email non specifiee dans le message.",
                status="pending",
                method=method,
                brand_name=brand_name,
                provider_name=provider_name,
            )

        confidence = 0.9 if wp_user else 0.5
        user_display = wp_user.get("slug", wp_user.get("username", "N/A"))

        # Apply the action automatically on the provider
        status = "pending"
        if action == "password_reset" and generated_password_full and method == "direct":
            try:
                apply_result = provider.reset_password(wp_user["id"], generated_password_full)
                if apply_result.success:
                    status = "done"
                    reason = f"Mot de passe réinitialisé automatiquement pour {user_display}"
                    logger.info("[AccountAgent] Mot de passe appliqué sur WP pour user_id=%s", wp_user["id"])
                else:
                    reason = f"Échec de la mise à jour WP ({apply_result.message}) — application manuelle requise pour {user_display}"
                    logger.warning("[AccountAgent] reset_password échoué: %s", apply_result.message)
            except Exception as exc:
                reason = f"Erreur WP ({exc}) — application manuelle requise pour {user_display}"
                logger.warning("[AccountAgent] reset_password exception: %s", exc)
        elif action == "email_change" and new_email:
            try:
                apply_result = provider.update_email(wp_user["id"], new_email)
                if apply_result.success:
                    status = "done"
                    reason = f"Email mis à jour vers {new_email} pour {user_display}"
                    logger.info("[AccountAgent] Email mis à jour sur WP pour user_id=%s", wp_user["id"])
                else:
                    reason = f"Échec de la mise à jour email ({apply_result.message}) pour {user_display}"
                    logger.warning("[AccountAgent] update_email échoué: %s", apply_result.message)
            except Exception as exc:
                reason = f"Erreur WP ({exc}) pour {user_display}"
                logger.warning("[AccountAgent] update_email exception: %s", exc)
        else:
            reason = (
                f"Reinitialisation du mot de passe pour {user_display}"
                if action == "password_reset"
                else f"Changement d'email vers {new_email} pour {user_display}"
            )

        return AccountResult(
            detected=True,
            action=action,
            requester_email=lookup_email,
            requester_name=sender_name,
            wp_user=wp_user,
            new_email=new_email,
            generated_password=generated_password,
            generated_password_full=generated_password_full,
            confidence=confidence,
            reason=reason,
            status=status,
            method=method,
            brand_name=brand_name,
            provider_name=provider_name,
        )

    def execute_action(self, result: AccountResult) -> bool:
        """Execute l'action apres approbation admin (provider-agnostic)."""
        if not result.wp_user:
            logger.error("[AccountAgent] No user to execute action on")
            return False

        user_id = result.wp_user.get("id")
        if not user_id:
            logger.error("[AccountAgent] User has no ID")
            return False

        try:
            provider = self._get_provider()
        except Exception as exc:
            logger.error("[AccountAgent] Cannot create provider: %s", exc)
            return False

        if result.action == "password_reset":
            if result.method == "reset_link":
                # Shopify-style: send invite, no password needed
                action_result = provider.reset_password(user_id, "")
            else:
                if not result.generated_password_full:
                    logger.error("[AccountAgent] No generated password for reset")
                    return False
                action_result = provider.reset_password(user_id, result.generated_password_full)
            return action_result.success

        if result.action == "email_change":
            if not result.new_email:
                logger.error("[AccountAgent] No new email for change")
                return False
            action_result = provider.update_email(user_id, result.new_email)
            return action_result.success

        logger.error("[AccountAgent] Unknown action: %s", result.action)
        return False

    # ── Private helpers ────────────────────────────────────────────────────

    def _extract_new_email(self, body: str, sender_email: str) -> Optional[str]:
        """Extract the new email address from body (exclude sender's own)."""
        emails = _EMAIL_RE.findall(body)
        for email in emails:
            if email.lower() != sender_email.lower():
                return email
        return None
