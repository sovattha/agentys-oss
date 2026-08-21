# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional

from app.config import PROJECT_ROOT
from app.domain.entities.email_template import EmailTemplate, TemplateMatch
from app.domain.ports.email_template_port import EmailTemplateStorePort

logger = logging.getLogger(__name__)

TEMPLATES_FILE = PROJECT_ROOT / "data" / "email_templates.json"
TEMPLATES_ENABLED = os.getenv("EMAIL_TEMPLATES_ENABLED", "true").lower() == "true"

DEFAULT_TEMPLATES = [
    EmailTemplate(
        id="urgent-response",
        name="Réponse Urgente",
        category="URGENT",
        description="Template pour les emails urgents nécessitant une action immédiate",
        template_body="""${greeting} ${sender_name},

Merci pour votre message concernant "${subject}".

Je comprends l'urgence de votre demande et je m'en occupe en priorité.
Je reviendrai vers vous dans les plus brefs délais avec une réponse complète.

${signature}""",
        language="fr",
        tone="professional",
        priority=100,
    ),
    EmailTemplate(
        id="meeting-request",
        name="Demande de Réunion",
        category="MEETING",
        description="Template pour les demandes de réunion",
        template_body="""${greeting} ${sender_name},

Merci pour votre proposition de réunion.

Je suis disponible pour en discuter. Voici mes créneaux libres cette semaine :
- [À compléter avec vos disponibilités]

N'hésitez pas à me proposer le créneau qui vous convient le mieux.

${signature}""",
        language="fr",
        tone="professional",
        priority=80,
    ),
    EmailTemplate(
        id="question-response",
        name="Réponse à Question",
        category="QUESTION",
        description="Template pour répondre aux questions",
        template_body="""${greeting} ${sender_name},

Merci pour votre question concernant "${subject}".

Voici les éléments de réponse :
[À compléter avec la réponse]

N'hésitez pas si vous avez besoin de précisions supplémentaires.

${signature}""",
        language="fr",
        tone="professional",
        priority=60,
    ),
    EmailTemplate(
        id="support-ticket",
        name="Ticket Support",
        category="SUPPORT",
        description="Template pour les demandes de support",
        template_body="""${greeting} ${sender_name},

Merci de nous avoir contactés concernant "${subject}".

J'ai bien pris note de votre demande et je vais examiner ce point attentivement.
Je vous tiendrai informé(e) de l'avancement.

Référence de suivi : [À générer]

${signature}""",
        language="fr",
        tone="professional",
        priority=70,
    ),
    EmailTemplate(
        id="acknowledgment",
        name="Accusé de Réception",
        category="NORMAL",
        description="Template d'accusé de réception standard",
        template_body="""${greeting} ${sender_name},

Bien reçu, merci pour votre message.

Je prendrai le temps d'examiner votre demande et reviendrai vers vous prochainement.

${signature}""",
        language="fr",
        tone="professional",
        priority=10,
    ),
    EmailTemplate(
        id="follow-up-response",
        name="Réponse Relance",
        category="FOLLOWUP",
        description="Template pour répondre à une relance",
        template_body="""${greeting} ${sender_name},

Suite à votre relance concernant "${subject}", je vous présente mes excuses pour le délai de réponse.

[Contenu de la réponse]

Je reste à votre disposition pour toute question.

${signature}""",
        language="fr",
        tone="professional",
        priority=75,
    ),
]


class JsonEmailTemplateStore(EmailTemplateStorePort):
    def __init__(self, filepath: Path = TEMPLATES_FILE):
        self.filepath = filepath
        self.templates: Dict[str, EmailTemplate] = {}
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                content = self.filepath.read_text(encoding='utf-8').strip()
                if not content:
                    logger.warning("Template file is empty, reinitializing defaults")
                    self._init_defaults()
                    return
                data = json.loads(content)
                for tpl_data in data.get("templates", []):
                    tpl = EmailTemplate(**tpl_data)
                    self.templates[tpl.id] = tpl
                logger.debug(f"Loaded {len(self.templates)} email templates")
            except Exception as e:
                logger.warning(f"Corrupt template file, reinitializing defaults: {e}")
                self._init_defaults()
        else:
            self._init_defaults()

    def _init_defaults(self) -> None:
        for tpl in DEFAULT_TEMPLATES:
            self.templates[tpl.id] = tpl
        self._save()
        logger.info(f"Initialized {len(DEFAULT_TEMPLATES)} default templates")

    def _save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "templates": [asdict(t) for t in self.templates.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def add(self, template: EmailTemplate) -> None:
        if template.id in self.templates:
            template.updated_at = datetime.now().isoformat()
        self.templates[template.id] = template
        self._save()
        logger.info(f"Template saved: {template.id}")

    def remove(self, template_id: str) -> bool:
        if template_id in self.templates:
            del self.templates[template_id]
            self._save()
            logger.info(f"Template removed: {template_id}")
            return True
        return False

    def get(self, template_id: str) -> Optional[EmailTemplate]:
        return self.templates.get(template_id)

    def get_all(self) -> List[EmailTemplate]:
        return list(self.templates.values())

    def get_by_category(self, category: str) -> List[EmailTemplate]:
        return [
            t for t in self.templates.values()
            if t.category == category and t.enabled
        ]

    def find_best_match(
        self,
        category: str,
        subject: str,
        body: str,
        language: str = "fr",
    ) -> Optional[TemplateMatch]:
        candidates = self.get_by_category(category)

        if not candidates:
            candidates = self.get_by_category("NORMAL")

        if not candidates:
            return None

        lang_candidates = [t for t in candidates if t.language == language]
        if lang_candidates:
            candidates = lang_candidates

        candidates.sort(key=lambda t: t.priority, reverse=True)

        best_match = None
        best_score = 0.0

        for template in candidates:
            score = self._calculate_match_score(template, subject, body)
            if score > best_score:
                best_score = score
                best_match = template

        if best_match:
            return TemplateMatch(
                template=best_match,
                score=best_score,
                variables={},
            )

        return None

    def _calculate_match_score(
        self,
        template: EmailTemplate,
        subject: str,
        body: str,
    ) -> float:
        score = 0.0

        score += template.priority / 100 * 0.5

        if template.conditions:
            conditions_met = 0
            total_conditions = len(template.conditions)

            if "subject_contains" in template.conditions:
                keywords = template.conditions["subject_contains"]
                if any(kw.lower() in subject.lower() for kw in keywords):
                    conditions_met += 1

            if "body_contains" in template.conditions:
                keywords = template.conditions["body_contains"]
                if any(kw.lower() in body.lower() for kw in keywords):
                    conditions_met += 1

            if total_conditions > 0:
                score += (conditions_met / total_conditions) * 0.5

        else:
            score += 0.3

        return min(score, 1.0)

    def render(
        self,
        template: EmailTemplate,
        variables: Dict[str, str],
    ) -> str:
        tpl = Template(template.template_body)

        now = datetime.now()
        # Heure au format de la langue du template : FR `17h00`, EN/ES `17:00`.
        # (Latent aujourd'hui — aucun template livré ne consomme ${time} — mais
        # corrige le défaut pour un futur template FR. Cf. audit 2026-06-23.)
        time_str = now.strftime("%Hh%M") if getattr(template, "language", "fr") == "fr" else now.strftime("%H:%M")
        default_vars = {
            "date": now.strftime("%d/%m/%Y"),
            "time": time_str,
            "greeting": self._get_greeting(),
            "signature": variables.get("signature", "Cordialement"),
        }

        all_vars = {**default_vars, **variables}

        try:
            rendered = tpl.safe_substitute(all_vars)
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            rendered = template.template_body

        template.usage_count += 1
        self._save()

        return rendered

    @staticmethod
    def _get_greeting() -> str:
        """Generate appropriate greeting based on time of day."""
        hour = datetime.now().hour

        if hour < 18:
            greeting = "Bonjour"
        else:
            greeting = "Bonsoir"

        return greeting

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "total": len(self.templates),
            "enabled": sum(1 for t in self.templates.values() if t.enabled),
            "by_category": {},
            "most_used": [],
            "languages": {},
        }

        for template in self.templates.values():
            cat = template.category
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

            lang = template.language
            stats["languages"][lang] = stats["languages"].get(lang, 0) + 1

        sorted_by_usage = sorted(
            self.templates.values(),
            key=lambda t: t.usage_count,
            reverse=True,
        )[:5]
        stats["most_used"] = [
            {"id": t.id, "name": t.name, "usage_count": t.usage_count}
            for t in sorted_by_usage
        ]

        return stats
