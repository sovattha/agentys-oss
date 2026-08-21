"""Fixtures partagées pour les tests de l'API (tests/api/).

Ré-exporte la fixture ``admin_client`` depuis ``tests.audit_fixes._admin_helpers``
pour que les tests de ce dossier la consomment en paramètre sans import direct
(évite le faux-positif F811 « redéfinition » sur le pattern fixture pytest).
"""
from tests.audit_fixes._admin_helpers import admin_client  # noqa: F401 — fixture pytest ré-exportée
