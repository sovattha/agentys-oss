# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
from typing import Any, Dict, List, Optional

from app.domain.entities.email_template import EmailTemplate, TemplateMatch
from app.domain.ports.email_template_port import EmailTemplateStorePort


class CreateTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self, template: EmailTemplate) -> EmailTemplate:
        self.store.add(template)
        return template


class GetTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self, template_id: str) -> Optional[EmailTemplate]:
        return self.store.get(template_id)


class ListTemplatesUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self, category: Optional[str] = None) -> List[EmailTemplate]:
        if category:
            return self.store.get_by_category(category)
        return self.store.get_all()


class UpdateTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self, template: EmailTemplate) -> Optional[EmailTemplate]:
        existing = self.store.get(template.id)
        if not existing:
            return None
        self.store.add(template)
        return template


class DeleteTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self, template_id: str) -> bool:
        return self.store.remove(template_id)


class MatchTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(
        self,
        category: str,
        subject: str,
        body: str,
        language: str = "fr",
    ) -> Optional[TemplateMatch]:
        return self.store.find_best_match(category, subject, body, language)


class RenderTemplateUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(
        self,
        template: EmailTemplate,
        variables: Dict[str, str],
    ) -> str:
        return self.store.render(template, variables)


class GetTemplateStatsUseCase:
    def __init__(self, store: EmailTemplateStorePort):
        self.store = store

    def execute(self) -> Dict[str, Any]:
        return self.store.get_stats()
