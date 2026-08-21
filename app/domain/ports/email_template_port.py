# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.domain.entities.email_template import EmailTemplate, TemplateMatch


class EmailTemplateStorePort(ABC):
    @abstractmethod
    def add(self, template: EmailTemplate) -> None:
        pass

    @abstractmethod
    def get(self, template_id: str) -> Optional[EmailTemplate]:
        pass

    @abstractmethod
    def get_all(self) -> List[EmailTemplate]:
        pass

    @abstractmethod
    def get_by_category(self, category: str) -> List[EmailTemplate]:
        pass

    @abstractmethod
    def remove(self, template_id: str) -> bool:
        pass

    @abstractmethod
    def find_best_match(
        self,
        category: str,
        subject: str,
        body: str,
        language: str = "fr",
    ) -> Optional[TemplateMatch]:
        pass

    @abstractmethod
    def render(
        self,
        template: EmailTemplate,
        variables: Dict[str, str],
    ) -> str:
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        pass
