# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the SecondBrainAdapter foundation (issue #261).

All tests are offline: no MemPalace SDK, no real graph DB schema. The adapter
is designed to degrade gracefully when sources are missing, so we cover that
path extensively. When chromadb and the vendored mempalace are installed in
the test environment, richer tests can be added as a follow-up.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.domain.ports.second_brain_port import (
    Entity,
    MemoryEntry,
    RetrievedContext,
    SecondBrainPort,
)
from app.infrastructure.second_brain_adapter import (
    SecondBrainAdapter,
    SecondBrainConfig,
)


# ---------------------------------------------------------------------------
# Port contract — MemoryEntry / RetrievedContext rendering
# ---------------------------------------------------------------------------

class TestMemoryEntryRendering:
    def test_to_prompt_line_contains_source(self) -> None:
        e = MemoryEntry(content="Hello world", source="memoire_md")
        line = e.to_prompt_line()
        assert "[memoire_md]" in line
        assert "Hello world" in line

    def test_to_prompt_line_includes_entity_name(self) -> None:
        e = MemoryEntry(
            content="A", source="graph", entity_name="DrafterAgent", score=0.92,
        )
        line = e.to_prompt_line()
        assert "graph:DrafterAgent" in line
        assert "0.92" in line

    def test_to_prompt_line_truncates_long_content(self) -> None:
        e = MemoryEntry(content="x" * 2000, source="mempalace")
        line = e.to_prompt_line()
        # 800 char cap + header
        assert len(line) < 1000


class TestRetrievedContextRendering:
    def test_empty_returns_empty_string(self) -> None:
        ctx = RetrievedContext(entries=(), query="test")
        assert ctx.to_prompt_block() == ""
        assert ctx.is_empty() is True

    def test_respects_max_chars(self) -> None:
        entries = tuple(
            MemoryEntry(content="x" * 500, source="graph") for _ in range(10)
        )
        ctx = RetrievedContext(entries=entries, query="test")
        block = ctx.to_prompt_block(max_chars=1000)
        assert len(block) <= 1200  # header + one or two entries, not all 10


# ---------------------------------------------------------------------------
# SecondBrainAdapter — graceful degradation
# ---------------------------------------------------------------------------

class TestAdapterGracefulDegradation:
    def test_all_sources_absent_returns_empty(self, tmp_path: Path) -> None:
        """When no source file exists, retrieve() returns an empty context."""
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            mempalace_db_path=tmp_path / "nope1.sqlite3",
            mempalace_graph_path=tmp_path / "nope2.sqlite3",
            memoire_md_path=tmp_path / "nope3.md",
            account_db_path=tmp_path / "nope4.db",
        ))
        ctx = adapter.retrieve(role="drafter", task="test")
        assert ctx.is_empty() is True
        # Health says everything down
        h = adapter.health_check()
        assert h["healthy"] is False
        assert set(h["sources_down"]) == {
            "mempalace", "graph", "memoire_md", "account_db",
        }

    def test_config_none_path_is_skipped(self) -> None:
        """A config with None paths must not crash."""
        adapter = SecondBrainAdapter(config=SecondBrainConfig())
        ctx = adapter.retrieve(role="any", task="anything")
        assert isinstance(ctx, RetrievedContext)
        assert ctx.is_empty() is True
        h = adapter.health_check()
        assert h["healthy"] is False


# ---------------------------------------------------------------------------
# memoire.md fallback — naive title/task overlap retrieval
# ---------------------------------------------------------------------------

class TestMemoireMdFallback:
    def test_picks_section_matching_task_words(self, tmp_path: Path) -> None:
        memoire = tmp_path / "memoire.md"
        memoire.write_text(
            "## Drafter usage patterns\n"
            "Use short sentences. Prefer active voice.\n\n"
            "## Unrelated section about kubernetes\n"
            "Pod scheduling notes.\n\n"
            "## Critic scoring details\n"
            "Scores range 0-100.\n",
            encoding="utf-8",
        )
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            memoire_md_path=memoire,
        ))
        ctx = adapter.retrieve(role="drafter", task="drafter usage", k=3)
        assert ctx.fallback_used is True
        assert ctx.total_sources_queried == 1
        # Top result should be the drafter section (best title overlap)
        assert any("Drafter usage patterns" in e.content for e in ctx.entries)

    def test_returns_empty_when_md_is_empty(self, tmp_path: Path) -> None:
        memoire = tmp_path / "empty.md"
        memoire.write_text("", encoding="utf-8")
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            memoire_md_path=memoire,
        ))
        ctx = adapter.retrieve(role="x", task="y")
        assert ctx.is_empty() is True


# ---------------------------------------------------------------------------
# Graph DB query — with a realistic MCP-memory schema
# ---------------------------------------------------------------------------

_GRAPH_SCHEMA = """
CREATE TABLE entities (
    name TEXT PRIMARY KEY,
    entity_type TEXT
);
CREATE TABLE observations (
    entity_name TEXT,
    content TEXT
);
CREATE TABLE relations (
    source TEXT,
    target TEXT,
    relation_type TEXT
);
"""


def _seed_graph(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(_GRAPH_SCHEMA)
    conn.executemany(
        "INSERT INTO entities (name, entity_type) VALUES (?, ?)",
        [
            ("DrafterAgent", "Component"),
            ("CriticAgent", "Component"),
            ("Agentys", "Project"),
            ("SomeUnrelatedThing", "Other"),
        ],
    )
    conn.executemany(
        "INSERT INTO observations (entity_name, content) VALUES (?, ?)",
        [
            ("DrafterAgent", "[2026-04-19] Uses Haiku by default for cost"),
            ("DrafterAgent", "[2026-04-10] Max retries = 3 on rate limits"),
            ("CriticAgent", "[2026-04-15] Quality threshold 70 default"),
            ("Agentys", "[2026-04-01] Deployed on Railway backend"),
        ],
    )
    conn.executemany(
        "INSERT INTO relations (source, target, relation_type) VALUES (?, ?, ?)",
        [
            ("DrafterAgent", "CriticAgent", "validated_by"),
            ("DrafterAgent", "Agentys", "part_of"),
        ],
    )
    conn.commit()
    conn.close()


class TestGraphQuery:
    def test_retrieves_observations_for_role(self, tmp_path: Path) -> None:
        graph = tmp_path / "graph.sqlite3"
        _seed_graph(graph)

        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            mempalace_graph_path=graph,
        ))
        ctx = adapter.retrieve(role="drafter", task="tune drafter", k=5)
        contents = [e.content for e in ctx.entries]
        assert any("Haiku by default" in c for c in contents)
        assert any("Max retries" in c for c in contents)
        # Tags on source
        assert all(e.source == "graph" for e in ctx.entries)

    def test_get_entity_returns_full_record(self, tmp_path: Path) -> None:
        graph = tmp_path / "graph.sqlite3"
        _seed_graph(graph)
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            mempalace_graph_path=graph,
        ))
        entity = adapter.get_entity("DrafterAgent")
        assert isinstance(entity, Entity)
        assert entity.name == "DrafterAgent"
        assert entity.entity_type == "Component"
        assert len(entity.observations) >= 2
        assert "validated_by:CriticAgent" in entity.relations

    def test_get_entity_returns_none_when_missing(self, tmp_path: Path) -> None:
        graph = tmp_path / "graph.sqlite3"
        _seed_graph(graph)
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            mempalace_graph_path=graph,
        ))
        assert adapter.get_entity("NonExistent") is None


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_partial_up(self, tmp_path: Path) -> None:
        memoire = tmp_path / "memoire.md"
        memoire.write_text("## test\n", encoding="utf-8")
        adapter = SecondBrainAdapter(config=SecondBrainConfig(
            memoire_md_path=memoire,
            mempalace_db_path=tmp_path / "missing.sqlite3",
        ))
        h = adapter.health_check()
        assert "memoire_md" in h["sources_up"]
        assert "mempalace" in h["sources_down"]
        assert h["healthy"] is True  # at least one up


# ---------------------------------------------------------------------------
# Port implementation — sanity check the adapter honors the contract
# ---------------------------------------------------------------------------

def test_adapter_is_instance_of_port() -> None:
    adapter = SecondBrainAdapter()
    assert isinstance(adapter, SecondBrainPort)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
