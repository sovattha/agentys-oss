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

"""Inventory shared Claude Code / Codex commands and skills."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLAUDE_COMMANDS = ROOT / ".claude" / "commands"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"
AGENT_SKILLS = ROOT / ".agents" / "skills"

PILOT_COMMANDS = {
    "build-fix": "source-command-build-fix",
    "code-review": "source-command-code-review",
    "commit": "source-command-commit",
    "docs": "source-command-docs",
    "e2e": "source-command-e2e",
    "plan": "source-command-plan",
    "tdd": "source-command-tdd",
    "verify": "source-command-verify",
}


def command_name(path: Path) -> str:
    return path.relative_to(CLAUDE_COMMANDS).with_suffix("").as_posix()


def command_skill_name(name: str) -> str:
    return f"source-command-{name.replace('/', '-')}"


def skill_path(name: str) -> Path:
    return AGENT_SKILLS / name / "SKILL.md"


def all_command_names() -> list[str]:
    if not CLAUDE_COMMANDS.exists():
        return []
    return sorted(command_name(path) for path in CLAUDE_COMMANDS.rglob("*.md"))


def all_source_command_skills() -> set[str]:
    if not AGENT_SKILLS.exists():
        return set()
    return {
        path.parent.name
        for path in AGENT_SKILLS.glob("source-command-*/SKILL.md")
        if path.is_file()
    }


def tree_files(path: Path) -> list[Path]:
    return sorted(item.relative_to(path) for item in path.rglob("*") if item.is_file())


def trees_equal(left: Path, right: Path) -> bool:
    left_files = tree_files(left)
    right_files = tree_files(right)
    if left_files != right_files:
        return False
    return all((left / rel).read_bytes() == (right / rel).read_bytes() for rel in left_files)


def skill_entry_status(entry: Path) -> tuple[str, str]:
    canonical = AGENT_SKILLS / entry.name
    if entry.is_symlink():
        raw_target = os.readlink(entry)
        target = (entry.parent / raw_target).resolve()
        expected = canonical.resolve()
        if target == expected:
            return ("symlink_ok", raw_target)
        return ("symlink_wrong_target", raw_target)

    if not entry.is_dir():
        return ("ignored", "")

    if not canonical.exists():
        return ("claude_only", "")

    if trees_equal(entry, canonical):
        return ("duplicate_identical", "")

    return ("duplicate_divergent", "")


def command_mentions_skill(command: str, skill: str) -> bool:
    path = CLAUDE_COMMANDS / f"{command}.md"
    if not path.exists():
        return False
    expected = f".agents/skills/{skill}/SKILL.md"
    return expected in path.read_text(encoding="utf-8")


def build_inventory() -> dict[str, object]:
    commands = all_command_names()
    source_skills = all_source_command_skills()
    missing_commands = [
        (command, command_skill_name(command))
        for command in commands
        if command_skill_name(command) not in source_skills
    ]

    skill_entries: list[tuple[str, str, str]] = []
    if CLAUDE_SKILLS.exists():
        for entry in sorted(CLAUDE_SKILLS.iterdir()):
            if entry.name.startswith("."):
                continue
            status, detail = skill_entry_status(entry)
            if status != "ignored":
                skill_entries.append((entry.name, status, detail))

    pilot_issues: list[str] = []
    for command, skill in sorted(PILOT_COMMANDS.items()):
        command_file = CLAUDE_COMMANDS / f"{command}.md"
        if not command_file.exists():
            pilot_issues.append(f"missing command .claude/commands/{command}.md")
        if not skill_path(skill).exists():
            pilot_issues.append(f"missing skill .agents/skills/{skill}/SKILL.md")
        if command_file.exists() and not command_mentions_skill(command, skill):
            pilot_issues.append(f"{command} wrapper does not reference {skill}")

    return {
        "commands": commands,
        "source_skills": source_skills,
        "missing_commands": missing_commands,
        "skill_entries": skill_entries,
        "pilot_issues": pilot_issues,
    }


def render_text(inventory: dict[str, object], max_missing: int) -> str:
    commands = inventory["commands"]
    source_skills = inventory["source_skills"]
    missing_commands = inventory["missing_commands"]
    skill_entries = inventory["skill_entries"]
    pilot_issues = inventory["pilot_issues"]

    lines = [
        "Agent capability inventory",
        "==========================",
        f"Claude commands: {len(commands)}",
        f"source-command skills: {len(source_skills)}",
        f"Commands without source-command skill: {len(missing_commands)}",
        f"Pilot issues: {len(pilot_issues)}",
        "",
    ]

    if pilot_issues:
        lines.append("Pilot issues:")
        lines.extend(f"- {issue}" for issue in pilot_issues)
        lines.append("")

    status_counts: dict[str, int] = {}
    for _name, status, _detail in skill_entries:
        status_counts[status] = status_counts.get(status, 0) + 1

    lines.append("Claude skill entries:")
    for status in sorted(status_counts):
        lines.append(f"- {status}: {status_counts[status]}")
    lines.append("")

    divergent = [
        (name, status, detail)
        for name, status, detail in skill_entries
        if status in {"duplicate_divergent", "claude_only", "symlink_wrong_target"}
    ]
    if divergent:
        lines.append("Skill entries needing manual decision:")
        for name, status, detail in divergent:
            suffix = f" ({detail})" if detail else ""
            lines.append(f"- {name}: {status}{suffix}")
        lines.append("")

    if missing_commands:
        lines.append(f"Missing command mappings (first {max_missing}):")
        for command, skill in missing_commands[:max_missing]:
            lines.append(f"- /{command} -> {skill}")
        if len(missing_commands) > max_missing:
            lines.append(f"- ... {len(missing_commands) - max_missing} more")

    return "\n".join(lines)


def render_markdown(inventory: dict[str, object], max_missing: int) -> str:
    text = render_text(inventory, max_missing)
    return "# Agent Capability Inventory\n\n```text\n" + text + "\n```\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["text", "markdown"], default="text")
    parser.add_argument("--max-missing", type=int, default=120)
    parser.add_argument(
        "--require-pilot",
        action="store_true",
        help="Fail if the pilot command wrappers or source-command skills are missing.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail unless every Claude command and skill entry has been migrated.",
    )
    args = parser.parse_args()

    inventory = build_inventory()
    if args.format == "markdown":
        print(render_markdown(inventory, args.max_missing))
    else:
        print(render_text(inventory, args.max_missing))

    failed = False
    if args.require_pilot and inventory["pilot_issues"]:
        failed = True
    if args.strict:
        if inventory["missing_commands"]:
            failed = True
        for _name, status, _detail in inventory["skill_entries"]:
            if status != "symlink_ok":
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
