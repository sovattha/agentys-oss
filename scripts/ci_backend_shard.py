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

"""Select balanced backend pytest shards for GitHub Actions."""

from __future__ import annotations

import argparse
import ast
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_SHARD_COUNT = 10
DEFAULT_TIMINGS_PATH = Path("scripts/ci_backend_test_timings.json")
EXCLUDED_PARTS = {"fixtures", "__pycache__"}
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test.py",)


@dataclass(frozen=True)
class TestFile:
    path: str
    estimated_seconds: float
    estimated_tests: int


@dataclass
class Shard:
    index: int
    files: list[TestFile]
    estimated_seconds: float = 0.0

    def add(self, test_file: TestFile) -> None:
        self.files.append(test_file)
        self.estimated_seconds += test_file.estimated_seconds


def is_test_file(path: Path) -> bool:
    name = path.name
    return (
        name.endswith(".py")
        and (name.startswith(TEST_FILE_PREFIXES) or name.endswith(TEST_FILE_SUFFIXES))
        and not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def discover_test_files(repo_root: Path) -> list[Path]:
    tests_root = repo_root / "tests"
    return sorted(path for path in tests_root.rglob("*.py") if is_test_file(path.relative_to(repo_root)))


def count_parametrize_values(decorator: ast.AST) -> int:
    call = decorator if isinstance(decorator, ast.Call) else None
    if call is None:
        return 1

    func_text = ast.unparse(call.func) if hasattr(ast, "unparse") else ""
    if "parametrize" not in func_text or len(call.args) < 2:
        return 1

    values = call.args[1]
    if isinstance(values, (ast.List, ast.Tuple, ast.Set)):
        return max(1, len(values.elts))
    return 1


def estimate_test_count(path: Path) -> int:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return 1

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            multiplier = 1
            for decorator in node.decorator_list:
                multiplier *= count_parametrize_values(decorator)
            count += multiplier
    return max(1, count)


def load_timing_model(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def prefix_factor(relative_path: str, model: dict[str, object]) -> float:
    factors = model.get("prefix_seconds_per_test", {})
    if not isinstance(factors, dict):
        return 0.12

    best_prefix = ""
    best_factor = 0.12
    for prefix, factor in factors.items():
        if relative_path.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_factor = float(factor)
    return best_factor


def estimate_seconds(relative_path: str, test_count: int, model: dict[str, object]) -> float:
    file_seconds = model.get("file_seconds", {})
    if isinstance(file_seconds, dict) and relative_path in file_seconds:
        return float(file_seconds[relative_path])

    fixed_overhead = float(model.get("default_file_overhead_seconds", 0.35))
    return fixed_overhead + (test_count * prefix_factor(relative_path, model))


def build_test_files(repo_root: Path, timings_path: Path) -> list[TestFile]:
    model = load_timing_model(timings_path)
    test_files = []
    for path in discover_test_files(repo_root):
        relative_path = path.relative_to(repo_root).as_posix()
        test_count = estimate_test_count(path)
        test_files.append(
            TestFile(
                path=relative_path,
                estimated_seconds=estimate_seconds(relative_path, test_count, model),
                estimated_tests=test_count,
            )
        )
    return test_files


def balance_files(test_files: Iterable[TestFile], shard_count: int) -> list[Shard]:
    shards = [Shard(index=index, files=[]) for index in range(shard_count)]
    for test_file in sorted(test_files, key=lambda item: (-item.estimated_seconds, item.path)):
        shard = min(shards, key=lambda item: (item.estimated_seconds, len(item.files), item.index))
        shard.add(test_file)
    return shards


def parse_shard_index(shard: str, shard_count: int) -> int:
    raw = shard.removeprefix("backend-")
    try:
        index = int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid shard name: {shard}") from exc

    if index < 0 or index >= shard_count:
        raise SystemExit(f"Shard index {index} is outside 0..{shard_count - 1}")
    return index


def format_summary(shards: list[Shard]) -> str:
    lines = ["Backend pytest shard plan:"]
    for shard in shards:
        test_count = sum(item.estimated_tests for item in shard.files)
        lines.append(
            f"  backend-{shard.index}: "
            f"{len(shard.files)} files, "
            f"{test_count} estimated tests, "
            f"{shard.estimated_seconds:.1f}s estimated"
        )
    return "\n".join(lines)


def write_files(files: list[TestFile], output: Path | None) -> None:
    content = "\n".join(item.path for item in sorted(files, key=lambda item: item.path)) + "\n"
    if output is None:
        print(content, end="")
    else:
        output.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--timings", type=Path, default=DEFAULT_TIMINGS_PATH)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--shard", help="Shard name, e.g. backend-0")
    parser.add_argument("--output", type=Path, help="Write selected files to this path")
    parser.add_argument("--summary", action="store_true", help="Print the full shard plan")
    parser.add_argument("--validate", action="store_true", help="Validate all shards are non-empty")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    timings_path = args.timings
    if not timings_path.is_absolute():
        timings_path = repo_root / timings_path

    test_files = build_test_files(repo_root, timings_path)
    shards = balance_files(test_files, args.shard_count)

    if args.summary:
        print(format_summary(shards))

    if args.validate:
        empty = [shard.index for shard in shards if not shard.files]
        if empty:
            raise SystemExit(f"Empty backend shards: {empty}")

    if args.shard is not None:
        index = parse_shard_index(args.shard, args.shard_count)
        write_files(shards[index].files, args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
