# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Template loader with LRU cache for prompt templates.

Usage:
    from app.prompts.loader import load_template
    prompt = load_template("drafter_system_with_context")
    # Loads from app/prompts/templates/drafter_system_with_context.txt
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateNotFoundError(FileNotFoundError):
    """Raised when a prompt template file does not exist."""


@lru_cache(maxsize=50)
def load_template(name: str) -> str:
    """Load a prompt template by name from the templates directory.

    Args:
        name: Template name without extension (e.g. "drafter_system_with_context").

    Returns:
        The template content as a string.

    Raises:
        TemplateNotFoundError: If the template file does not exist.
    """
    path = TEMPLATES_DIR / f"{name}.txt"
    if not path.is_file():
        raise TemplateNotFoundError(
            f"Template '{name}' not found at {path}. "
            f"Available: {[f.stem for f in TEMPLATES_DIR.glob('*.txt')]}"
        )
    return path.read_text(encoding="utf-8")


def clear_template_cache() -> None:
    """Clear the template LRU cache (useful after hot-reload)."""
    load_template.cache_clear()
