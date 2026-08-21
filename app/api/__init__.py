# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
API REST pour Agentys.

Ce module expose les fonctionnalités du daemon via une API REST Flask.
"""

from .app import create_app
from .routes import api_bp

# Import route modules whose decorators must run for blueprint registration.
# (routes.py already imports the historical six; new ones live here.)
from . import routes_bulk_jobs  # noqa: F401

__all__ = ["create_app", "api_bp"]
