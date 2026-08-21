# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class TaskPort(ABC):
    @abstractmethod
    def get_all(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def mark_completed(self, task_id: int) -> bool:
        pass

    @abstractmethod
    def create(
        self,
        title: str,
        description: Optional[str] = None,
        priority: str = "medium",
        deadline: Optional[str] = None,
    ) -> Dict[str, Any]:
        pass
