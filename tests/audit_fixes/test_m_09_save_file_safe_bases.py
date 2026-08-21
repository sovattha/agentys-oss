# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix M-9 (issue #543) — `_SAFE_BASES` trop large ($HOME).

Bug: ``_SAFE_BASES`` contenait ``$HOME``, donc tout chemin sous le home
de l'utilisateur passait ``_is_safe_path``. Combiné avec un éventuel
bypass des gardes loopback / prod-disable de ``/save-file``, un attaquant
pouvait planter un fichier dans ``~/.ssh/authorized_keys2``,
``~/.config/...``, ``~/.zshrc`` etc. Risque actuel faible (le endpoint
est déjà loopback-only + non-prod) mais defense-in-depth.

Fix: ``_SAFE_BASES = [~/Downloads/Agentys, project_root]``. Subdirs OK.

Ces tests vérifient le comportement de la fonction pure ``_is_safe_path``
— pas la route entière (déjà couverte par les gardes loopback / prod).

Run: ``pytest tests/audit_fixes/test_m_09_save_file_safe_bases.py -v``
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.api.routes_helpers import _SAFE_BASES, _is_safe_path


HOME = Path(os.path.expanduser("~"))
AGENTYS_DIR = HOME / "Downloads" / "Agentys"


# --------------------------------------------------------------------------- #
# 1. Paths that MUST be rejected (M-9 attack surface)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "evil_path",
    [
        # SSH config & keys — original attack vector cited in the audit
        str(HOME / ".ssh" / "authorized_keys"),
        str(HOME / ".ssh" / "authorized_keys2"),
        str(HOME / ".ssh" / "id_rsa"),
        # Shell startup files
        str(HOME / ".zshrc"),
        str(HOME / ".bashrc"),
        str(HOME / ".bash_profile"),
        # XDG config
        str(HOME / ".config" / "systemd" / "user" / "evil.service"),
        str(HOME / ".config" / "claude" / "claude.json"),
        # Other sensitive home locations
        str(HOME / ".aws" / "credentials"),
        str(HOME / ".gnupg" / "trustdb.gpg"),
        # Plain home root
        str(HOME / "evil.txt"),
        # System paths (already rejected pre-fix, regression-test for safety)
        "/etc/passwd",
        "/var/log/syslog",
    ],
)
def test_evil_home_paths_rejected(evil_path):
    """M-9: paths under ``~`` outside ``~/Downloads/Agentys`` must be rejected."""
    assert not _is_safe_path(evil_path), (
        f"M-9 leak: {evil_path!r} should NOT pass _is_safe_path "
        f"(_SAFE_BASES={_SAFE_BASES})"
    )


# --------------------------------------------------------------------------- #
# 2. Paths that MUST still be accepted (legitimate Tauri export flows)
# --------------------------------------------------------------------------- #


def test_dedicated_agentys_dir_accepted():
    """The dedicated ``~/Downloads/Agentys`` folder itself is safe."""
    assert _is_safe_path(str(AGENTYS_DIR))


@pytest.mark.parametrize(
    "ok_subpath",
    [
        "Project1",
        "Project1/attachments",
        "Project1/attachments/invoice.pdf",
        "exports/2026-05/file.txt",
    ],
)
def test_subdirs_under_agentys_dir_accepted(ok_subpath):
    """Subdirs under the dedicated folder must be accepted (export use case)."""
    candidate = str(AGENTYS_DIR / ok_subpath)
    assert _is_safe_path(candidate), (
        f"Legitimate export path rejected: {candidate!r}"
    )


def test_project_root_still_safe():
    """The repo root (used by dev/CI to read fixtures, write tasks/) is kept
    as a safe base. Regression-test so a future narrowing doesn't drop it."""
    project_root = Path(__file__).resolve().parents[2]
    assert _is_safe_path(str(project_root))
    assert _is_safe_path(str(project_root / "tasks" / "report.md"))


# --------------------------------------------------------------------------- #
# 3. Path-traversal sanity (the route also rejects ".." but we check the
# resolution layer here so a future caller that drops the literal check
# doesn't lose the safety net)
# --------------------------------------------------------------------------- #


def test_traversal_out_of_agentys_dir_rejected():
    """``~/Downloads/Agentys/../.ssh`` resolves outside the safe base and
    must be rejected by the realpath comparison even if the literal
    ``..`` check is bypassed upstream."""
    traversal = str(AGENTYS_DIR / ".." / ".ssh" / "id_rsa")
    assert not _is_safe_path(traversal), (
        f"Traversal escaped safe base: realpath={os.path.realpath(traversal)!r}"
    )


# --------------------------------------------------------------------------- #
# 4. Defence-in-depth on the constant itself — make sure $HOME isn't there
# --------------------------------------------------------------------------- #


def test_safe_bases_does_not_contain_bare_home():
    """Regression-lock the constant: if a refactor ever re-adds ``$HOME``
    to ``_SAFE_BASES`` the test fails immediately. The dedicated app
    folder MUST be a strict subdirectory of ``$HOME``, not ``$HOME``."""
    home_real = os.path.realpath(HOME)
    for base in _SAFE_BASES:
        base_real = os.path.realpath(base)
        assert base_real != home_real, (
            f"_SAFE_BASES regressed: {base!r} resolves to bare $HOME"
        )
