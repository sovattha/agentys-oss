# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from app import draft_learning


def test_draft_learning_store_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    store = draft_learning.DraftLearningStore()

    assert store._path == str(tmp_path / "draft_corrections.json")


def test_account_draft_learning_path_honors_agentys_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTYS_DATA_DIR", str(tmp_path))

    assert draft_learning._path_for_account(42) == str(
        tmp_path / "draft_corrections" / "42.json"
    )
