# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Top-level pytest conftest (rootdir).

Pytest 8+ exige que ``pytest_plugins`` soit déclaré dans un conftest au
rootdir (cf. erreur "Defining 'pytest_plugins' in a non-top-level conftest
is no longer supported"). Avant ce fichier, la déclaration vivait dans
``tests/api/conftest.py`` et ``tests/services/conftest.py`` — supprimés
en faveur de cette centralisation.

Le module référencé ne peut PAS s'appeler ``conftest.py`` (sinon pytest
le découvre auto en plus de l'enregistrer ici → "Plugin already
registered under a different name"). D'où le rename
``tests/db/conftest.py`` → ``tests/db/_fixtures.py``.

Toutes les fixtures DB (``session``, ``engine``, ``sample_account``,
etc.) deviennent globalement disponibles à tous les tests sous
``tests/`` sans avoir à dupliquer le shim par sous-répertoire.
"""

pytest_plugins = ["tests.db._fixtures"]
