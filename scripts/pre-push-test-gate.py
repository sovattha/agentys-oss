#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pre-push test gate — mapping fichier modifié -> tests pytest à lancer.

Lit la liste des fichiers modifiés sur stdin (un par ligne), construit la
liste minimale de chemins de test à couvrir, puis invoque pytest.

Exit code 0 = tests verts (push autorisé) ou skip légitime.
Exit code != 0 = bloque le push.

Synchronisé avec `.claude/commands/commit.md` Étape 2b.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# Limite au-delà de laquelle on bascule sur un dir parent plutôt que des
# globs explicites — au-delà, l'overhead pytest collect dépasse le bénéfice.
MAX_TEST_PATHS = 30

# Limite de fichiers de test à exécuter — au-delà, on coupe (l'utilisateur
# pousse trop large, /commit aurait dû être plus chirurgical en amont).
MAX_TESTS_BUDGET_S = 120


def _glob_tests(*patterns: str) -> list[str]:
    """Glob plusieurs patterns relatifs au repo, dédoublonne, trie."""
    results: set[str] = set()
    for pattern in patterns:
        full_pattern = str(REPO_ROOT / pattern)
        results.update(
            os.path.relpath(p, REPO_ROOT) for p in glob.glob(full_pattern, recursive=True)
        )
    return sorted(results)


def map_file_to_tests(modified: str) -> list[str]:
    """Mapping principal — voir `.claude/commands/commit.md` Étape 2b."""
    p = Path(modified)

    # Fichier de test direct → on relance ce fichier.
    if modified.startswith("tests/") and p.name.startswith("test_") and p.suffix == ".py":
        return [modified]

    # Frontend / docs / config → pas de pytest.
    if modified.startswith(("agentys-app/", "docs/", "tasks/", ".claude/", "_bmad")):
        return []
    if p.suffix in {".md", ".toml", ".yml", ".yaml", ".json", ".lock", ".txt"}:
        # Exception : requirements*.txt impacte tout — laisser tomber, full
        # suite pertinente seulement en CI ; ici on évite le coût.
        return []

    # app/api/<X>.py → tests/api/test_<X>*.py + tests/test_*<X>*.py
    if modified.startswith("app/api/") and p.suffix == ".py":
        stem = p.stem
        return _glob_tests(
            f"tests/api/test_{stem}*.py",
            f"tests/api/test_*{stem}*.py",
            f"tests/test_api_{stem}*.py",
            f"tests/test_*{stem}*.py",
        )

    # app/application/<X>.py → tests/application/
    if modified.startswith("app/application/") and p.suffix == ".py":
        stem = p.stem
        targeted = _glob_tests(
            f"tests/application/test_{stem}*.py",
            f"tests/test_*{stem}*usecase*.py",
        )
        return targeted or ["tests/application/"]

    # app/domain/**/<X>.py → tests/domain/ + tests unitaires
    if modified.startswith("app/domain/") and p.suffix == ".py":
        return ["tests/domain/", "tests/unit/"] + _glob_tests("tests/test_*_unit*.py")

    # app/infrastructure/**/<X>.py → tests/infrastructure/ + tests/adapters/
    if modified.startswith("app/infrastructure/") and p.suffix == ".py":
        stem = p.stem
        targeted = _glob_tests(
            f"tests/infrastructure/test_{stem}*.py",
            f"tests/adapters/test_{stem}*.py",
            f"tests/test_*{stem}*.py",
        )
        return targeted or ["tests/infrastructure/", "tests/adapters/"]

    # app/services/<X>.py → tests/services/
    if modified.startswith("app/services/") and p.suffix == ".py":
        stem = p.stem
        targeted = _glob_tests(f"tests/services/test_{stem}*.py")
        return targeted or ["tests/services/"]

    # app/providers/ ou app/adapters/<X>.py
    if modified.startswith(("app/providers/", "app/adapters/")) and p.suffix == ".py":
        stem = p.stem
        return _glob_tests(
            f"tests/providers/test_{stem}*.py",
            f"tests/adapters/test_{stem}*.py",
            f"tests/test_*{stem}*.py",
        )

    # app/<root>.py (ex: app/draft_learning.py)
    if modified.startswith("app/") and p.suffix == ".py" and len(p.parts) == 2:
        stem = p.stem
        return _glob_tests(
            f"tests/test_{stem}*.py",
            f"tests/test_*{stem}*.py",
        )

    # Fichiers Python à la racine du repo (ex: run_api.py, run_daemon.py,
    # conftest.py). Ils orchestrent tout — on lance les tests qui matchent
    # leur nom + les tests d'API/intégration les plus susceptibles d'être
    # impactés par un changement d'entrée Flask/runtime.
    if "/" not in modified and p.suffix == ".py":
        stem = p.stem
        targeted = _glob_tests(
            f"tests/test_{stem}*.py",
            f"tests/test_*{stem}*.py",
        )
        if stem in ("run_api", "run_daemon"):
            # Smoke critique sur les entry points runtime.
            targeted = list(set(targeted) | {"tests/test_api_health_spec.py"})
        return targeted

    # scripts/<X>.py → s'il existe un test/fixture qui le mentionne, on l'inclut.
    # Sinon skip (la plupart des scripts sont du tooling sans test direct).
    if modified.startswith("scripts/") and p.suffix == ".py":
        stem = p.stem
        return _glob_tests(f"tests/test_*{stem}*.py")

    # Inconnu → conservateur, on skip plutôt que d'envoyer la suite entière.
    return []


def has_signature_change(modified_files: list[str]) -> bool:
    """Détection grossière : un diff qui touche à une signature publique
    (`def execute`, `def __init__`, `def get_*_use_case`, etc.) augmente
    le blast radius et justifie de relancer les tests d'intégration.
    """
    try:
        diff = subprocess.run(
            ["git", "diff", "@{push}..HEAD", "--unified=0"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False

    signature_patterns = (
        "def execute(",
        "def __init__(",
        "def get_",
        "_use_case(",
        "def save(",
        "def update_",
    )
    for line in diff.splitlines():
        if not (line.startswith("+") or line.startswith("-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        if any(pat in line for pat in signature_patterns):
            return True
    return False


def expand_for_signatures(modified: list[str], paths: list[str]) -> list[str]:
    """Si signature publique touchée, élargit aux tests d'intégration matchant."""
    if not has_signature_change(modified):
        return paths

    integration_extras: set[str] = set()
    for f in modified:
        if not f.startswith("app/"):
            continue
        # On garde simple : ajoute tests/integration/ si non déjà couvert.
        # Évite d'exploser le périmètre — c'est un canari, pas une suite full.
        integration_extras.add("tests/integration/")
        break

    return sorted(set(paths) | integration_extras)


def main() -> int:
    modified = [line.strip() for line in sys.stdin if line.strip()]
    if not modified:
        print("[test-gate] aucun fichier modifié — skip")
        return 0

    test_paths: set[str] = set()
    for f in modified:
        for tp in map_file_to_tests(f):
            test_paths.add(tp)

    if not test_paths:
        print("[test-gate] modifs sans impact pytest (docs/config/frontend) — skip")
        return 0

    test_paths_list = sorted(test_paths)
    test_paths_list = expand_for_signatures(modified, test_paths_list)

    if len(test_paths_list) > MAX_TEST_PATHS:
        print(
            f"[test-gate] {len(test_paths_list)} chemins de test → trop large, "
            f"bascule sur le dir parent commun. Si c'est intentionnel, "
            f"`SKIP_TEST_GATE=1 git push`."
        )
        # Heuristique : trouver les dirs parents.
        parents = sorted({Path(p).parent.as_posix() for p in test_paths_list})
        test_paths_list = parents[:5]  # 5 dirs max

    print(f"[test-gate] lancement pytest sur {len(test_paths_list)} chemin(s) :")
    for p in test_paths_list:
        print(f"  - {p}")
    print()

    # `sys.executable` est le binaire Python qui exécute ce script — quand
    # le venv est activé en amont par le wrapper .sh, il pointe sur le venv.
    # Évite les pièges Windows où `python` peut être absent du PATH global
    # mais présent dans venv/Scripts/.
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *test_paths_list,
        "--tb=short",
        "-q",
        "--timeout=30",
        "--maxfail=10",
    ]
    try:
        result = subprocess.run(cmd, cwd=REPO_ROOT, timeout=MAX_TESTS_BUDGET_S)
    except subprocess.TimeoutExpired:
        print(
            f"\n[test-gate] BLOQUÉ : pytest a dépassé {MAX_TESTS_BUDGET_S}s. "
            f"Périmètre trop large — affine ton commit ou bypass avec "
            f"`SKIP_TEST_GATE=1 git push` après vérification manuelle."
        )
        return 1

    if result.returncode != 0:
        print(
            f"\n[test-gate] BLOQUÉ : pytest a échoué (exit {result.returncode}).\n"
            f"  - Corrige les tests, ou\n"
            f"  - Bypass explicite : `SKIP_TEST_GATE=1 git push` "
            f"(uniquement si tu as une raison valable, à documenter dans le commit)."
        )
        return result.returncode

    print("\n[test-gate] OK ✓ tests verts, push autorisé")
    return 0


if __name__ == "__main__":
    sys.exit(main())
