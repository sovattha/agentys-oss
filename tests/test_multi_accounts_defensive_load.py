# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json

from app.multi_accounts import AccountManager


def test_account_manager_heals_empty_accounts_file(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("", encoding="utf-8")

    manager = AccountManager(filepath=path)

    assert manager.accounts == {}
    assert json.loads(path.read_text(encoding="utf-8"))["accounts"] == []
