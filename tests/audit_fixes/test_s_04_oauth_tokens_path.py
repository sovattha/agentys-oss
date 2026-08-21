# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Audit fix S-04 — `_TOKENS_FILE` ignores `AGENTYS_DATA_DIR`.

Bug: `app/api/oauth.py:66-70` hard-codes `<project-root>/data/oauth_tokens.json`.
On Railway this lives on the ephemeral container FS, so every deploy wipes
OAuth tokens and forces every user through re-OAuth (or breaks sync until
they reconnect).

Fix: read `AGENTYS_DATA_DIR` from the environment (same pattern as the
container's `data_dir` property). Mount this on the persistent volume.

Run: `pytest tests/audit_fixes/test_s_04_oauth_tokens_path.py -v`
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="agentys-s04-")
    monkeypatch.setenv("AGENTYS_DATA_DIR", tmp)
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


def test_tokens_file_path_honors_agentys_data_dir(isolated_data_dir):
    """S-04: when AGENTYS_DATA_DIR is set, _TOKENS_FILE must live under
    that directory — not the hard-coded `<project-root>/data/`."""
    import importlib
    import app.api.oauth as oauth_mod
    importlib.reload(oauth_mod)

    tokens_path = oauth_mod._TOKENS_FILE
    expected_root = str(isolated_data_dir.resolve())
    assert os.path.commonpath([expected_root, str(Path(tokens_path).resolve())]) == expected_root, (
        f"S-04 leak: tokens file at {tokens_path!r} not under "
        f"AGENTYS_DATA_DIR={expected_root!r} → tokens lost on every "
        f"Railway redeploy."
    )
