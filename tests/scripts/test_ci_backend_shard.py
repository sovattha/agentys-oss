# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci_backend_shard.py"
SPEC = importlib.util.spec_from_file_location("ci_backend_shard", SCRIPT_PATH)
ci_backend_shard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ci_backend_shard
SPEC.loader.exec_module(ci_backend_shard)


def write_test(path: Path, body: str = "def test_example():\n    pass\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_discover_test_files_excludes_fixtures(tmp_path: Path) -> None:
    write_test(tmp_path / "tests" / "test_top_level.py")
    write_test(tmp_path / "tests" / "api" / "test_api.py")
    write_test(tmp_path / "tests" / "fixtures" / "test_fixture_data.py")

    files = ci_backend_shard.discover_test_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "tests/api/test_api.py",
        "tests/test_top_level.py",
    ]


def test_balance_files_assigns_every_file_once() -> None:
    files = [
        ci_backend_shard.TestFile("tests/test_a.py", 10.0, 10),
        ci_backend_shard.TestFile("tests/test_b.py", 8.0, 8),
        ci_backend_shard.TestFile("tests/test_c.py", 7.0, 7),
        ci_backend_shard.TestFile("tests/test_d.py", 1.0, 1),
    ]

    shards = ci_backend_shard.balance_files(files, shard_count=2)

    assigned = sorted(test_file.path for shard in shards for test_file in shard.files)
    assert assigned == [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_c.py",
        "tests/test_d.py",
    ]
    assert sorted(shard.estimated_seconds for shard in shards) == pytest.approx([11.0, 15.0])


def test_estimate_test_count_expands_simple_parametrize(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_parametrize.py"
    write_test(
        test_file,
        """
import pytest


@pytest.mark.parametrize("value", [1, 2, 3])
def test_parametrized(value):
    assert value


def test_plain():
    assert True
""",
    )

    assert ci_backend_shard.estimate_test_count(test_file) == 4


def test_parse_shard_index_rejects_out_of_range() -> None:
    with pytest.raises(SystemExit):
        ci_backend_shard.parse_shard_index("backend-10", shard_count=10)
