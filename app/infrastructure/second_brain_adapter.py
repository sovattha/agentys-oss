# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Adapter SecondBrain — agrège 4 sources derrière `SecondBrainPort` (issue #261).

Sources (dans l'ordre de priorité pour retrieve()):
  1. MemPalace (vectoriel)    — ai_team/memory/palace/chroma.sqlite3
  2. MCP memory graph         — knowledge_graph.sqlite3 (ou via serveur MCP)
  3. Account-scoped KB (DB)   — app.memory_manager.load_knowledge_from_db
  4. memoire.md               — knowledge/memoire.md (fallback ultime)

L'adapter ne fait AUCUN appel LLM. Toutes les sources sont locales et
failsafe : si une source est down, on passe à la suivante et on marque
`fallback_used=True` quand on est tombé sur le fichier markdown.

Le graphe MCP et MemPalace sont des dépendances "soft" : si leurs SDK
respectifs ne sont pas installés, l'adapter dégrade gracieusement vers
les sources disponibles.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.domain.ports.second_brain_port import (
    Entity,
    MemoryEntry,
    MemoryScope,
    RetrievedContext,
    SecondBrainPort,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config — chemins résolus depuis env vars (voir app.config)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecondBrainConfig:
    """Chemins des 4 sources. None = source désactivée."""
    mempalace_db_path: Optional[Path] = None        # Chroma sqlite3
    mempalace_graph_path: Optional[Path] = None     # knowledge_graph.sqlite3
    memoire_md_path: Optional[Path] = None          # knowledge/memoire.md
    account_db_path: Optional[Path] = None          # DB principale (pour load_knowledge_from_db)
    cache_ttl_seconds: int = 300                    # retrieve() cache (not yet implemented)


# ---------------------------------------------------------------------------
# Adapter principal — composite de 4 sources
# ---------------------------------------------------------------------------

@dataclass
class SecondBrainAdapter(SecondBrainPort):
    """Implémentation composite qui interroge les 4 sources et fusionne.

    Thread safety: chaque `retrieve()` ouvre/ferme ses propres connexions DB.
    Pas de cache partagé (ajoutera éventuellement un LRU avec TTL).
    """
    config: SecondBrainConfig = field(default_factory=SecondBrainConfig)

    # ---- SecondBrainPort implementation ----

    def retrieve(
        self,
        *,
        role: str,
        task: str,
        k: int = 5,
        scope: Optional[MemoryScope] = None,
        account_id: Optional[int] = None,
    ) -> RetrievedContext:
        entries: list[MemoryEntry] = []
        sources_queried = 0
        fallback_used = False

        # 1. MemPalace vectoriel — best semantic match
        if self.config.mempalace_db_path and (scope is None or scope != "account"):
            sources_queried += 1
            entries.extend(self._query_mempalace(task=task, k=k))

        # 2. MCP memory graph — entités pertinentes pour le rôle
        if self.config.mempalace_graph_path and (scope is None or scope != "account"):
            sources_queried += 1
            entries.extend(self._query_graph_relevant(role=role, task=task, k=k))

        # 3. Account KB — si scope=account et account_id fourni
        if (scope == "account" or scope is None) and account_id and self.config.account_db_path:
            sources_queried += 1
            entries.extend(self._query_account_kb(account_id=account_id, k=k))

        # Dedup par (source, content[:200])
        seen: set[tuple[str, str]] = set()
        deduped: list[MemoryEntry] = []
        for e in entries:
            key = (e.source, e.content[:200])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)

        # Tri par score descendant
        deduped.sort(key=lambda e: e.score, reverse=True)
        top = deduped[:k]

        # 4. Fallback ultime si rien trouvé → memoire.md
        if not top and self.config.memoire_md_path:
            sources_queried += 1
            fallback_used = True
            fallback_entries = self._read_memoire_md_fallback(task=task, k=k)
            top = fallback_entries[:k]

        return RetrievedContext(
            entries=tuple(top),
            query=task,
            total_sources_queried=sources_queried,
            fallback_used=fallback_used,
        )

    def get_role_prompt(self, role: str, *, default: Optional[str] = None) -> str:
        """Load a stored prompt for the given role from the graph DB.

        Reads from a dedicated `agent_prompts` SQLite table (same DB as
        the MCP memory graph). The table is auto-created on first call via
        the migration script, so `get_role_prompt()` silently returns the
        default while the table is absent — zero runtime dependency.

        Order:
          1. Row in `agent_prompts` where role=? → use it
          2. Fallback to caller-provided default
          3. Empty string (preserves backwards-compat with Phase 1)
        """
        p = self.config.mempalace_graph_path
        if not p or not Path(p).exists():
            return default or ""
        try:
            conn = sqlite3.connect(str(p), timeout=3.0)
            conn.row_factory = sqlite3.Row
            # Skip if table doesn't exist (pre-migration state)
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_prompts'"
            )
            if cur.fetchone() is None:
                conn.close()
                return default or ""
            row = conn.execute(
                "SELECT prompt FROM agent_prompts WHERE role = ? LIMIT 1",
                (role,),
            ).fetchone()
            conn.close()
            if row and row["prompt"]:
                return str(row["prompt"])
        except sqlite3.Error as e:
            logger.debug("second_brain: get_role_prompt(%s) query failed: %s", role, e)
        return default or ""

    def set_role_prompt(
        self,
        role: str,
        prompt: str,
        *,
        source: str = "manual",
    ) -> bool:
        """Write/upsert a prompt for `role` to the `agent_prompts` table.

        Not in `SecondBrainPort` — writer side, intentionally scoped to the
        adapter + migration tooling. Creates the table on first call.
        Returns True on success, False if no graph DB configured.
        """
        p = self.config.mempalace_graph_path
        if not p:
            return False
        # Ensure parent dir exists (graph DB is colocated with Chroma)
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(p), timeout=3.0)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_prompts (
                    role TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    version INTEGER DEFAULT 1,
                    source TEXT DEFAULT 'manual',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO agent_prompts (role, prompt, source, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(role) DO UPDATE SET
                    prompt = excluded.prompt,
                    version = version + 1,
                    source = excluded.source,
                    updated_at = datetime('now')
                """,
                (role, prompt, source),
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.warning("second_brain: set_role_prompt(%s) failed: %s", role, e)
            return False

    def get_entity(self, name: str) -> Optional[Entity]:
        if not self.config.mempalace_graph_path:
            return None
        return self._query_graph_entity(name=name)

    def health_check(self) -> dict:
        up: list[str] = []
        down: list[str] = []

        for label, path in (
            ("mempalace", self.config.mempalace_db_path),
            ("graph", self.config.mempalace_graph_path),
            ("memoire_md", self.config.memoire_md_path),
            ("account_db", self.config.account_db_path),
        ):
            if path is None:
                continue
            if Path(path).exists():
                up.append(label)
            else:
                down.append(label)

        return {
            "sources_up": up,
            "sources_down": down,
            "healthy": bool(up),
        }

    # ---- Private source queries ----

    def _query_mempalace(self, *, task: str, k: int) -> list[MemoryEntry]:
        """Query Chroma vector store via mempalace SDK (if installed).

        MemPalace is vendored at ai_team/vendor/mempalace/. When its SDK is
        importable, we open the chroma DB and run a similarity search. When
        not importable (CI, dev without vendor), return an empty list.
        """
        try:
            # Lazy import — mempalace is optional in app/ context
            import chromadb
        except ImportError:
            logger.debug("second_brain: chromadb unavailable, skipping MemPalace")
            return []

        try:
            client = chromadb.PersistentClient(path=str(self.config.mempalace_db_path.parent))
            # Default MemPalace collection name per vendor README
            col = client.get_or_create_collection(name="agentys")
            res = col.query(query_texts=[task], n_results=k)
            docs = (res.get("documents") or [[]])[0]
            distances = (res.get("distances") or [[]])[0]
            out: list[MemoryEntry] = []
            for doc, dist in zip(docs, distances):
                # chromadb distance = 1 - cos_sim in default config, lower = closer
                score = max(0.0, 1.0 - float(dist)) if dist is not None else 0.5
                out.append(MemoryEntry(
                    content=str(doc),
                    source="mempalace",
                    score=score,
                    scope="ai_team",
                ))
            return out
        except Exception as e:  # noqa: BLE001
            logger.warning("second_brain: MemPalace query failed: %s", e)
            return []

    def _query_graph_relevant(self, *, role: str, task: str, k: int) -> list[MemoryEntry]:
        """Query the sqlite knowledge graph for entities linked to `role`.

        Schema assumed (per MCP memory server default):
          entities(name TEXT PRIMARY KEY, entity_type TEXT)
          observations(entity_name TEXT, content TEXT)
          relations(source TEXT, target TEXT, relation_type TEXT)

        We return observations of entities matching `role` as subject or
        object of a relation. Best-effort — if schema doesn't match, return [].
        """
        p = self.config.mempalace_graph_path
        if not p or not Path(p).exists():
            return []
        try:
            conn = sqlite3.connect(str(p), timeout=3.0)
            conn.row_factory = sqlite3.Row
            # Find entities whose name contains role OR is a neighbor of an entity named like role
            rows = conn.execute(
                """
                SELECT DISTINCT e.name, o.content
                FROM entities e
                LEFT JOIN observations o ON o.entity_name = e.name
                WHERE LOWER(e.name) LIKE ?
                   OR EXISTS (
                      SELECT 1 FROM relations r
                       WHERE (r.source = e.name OR r.target = e.name)
                         AND (LOWER(r.source) LIKE ? OR LOWER(r.target) LIKE ?)
                   )
                LIMIT ?
                """,
                (f"%{role.lower()}%", f"%{role.lower()}%", f"%{role.lower()}%", k * 2),
            ).fetchall()
            conn.close()
            out: list[MemoryEntry] = []
            for r in rows:
                if not r["content"]:
                    continue
                out.append(MemoryEntry(
                    content=str(r["content"]),
                    source="graph",
                    score=0.5,  # no scoring — placeholder
                    scope="agentys",
                    entity_name=str(r["name"]),
                ))
            return out[:k]
        except sqlite3.Error as e:
            logger.debug("second_brain: graph query failed (schema mismatch?): %s", e)
            return []

    def _query_graph_entity(self, *, name: str) -> Optional[Entity]:
        p = self.config.mempalace_graph_path
        if not p or not Path(p).exists():
            return None
        try:
            conn = sqlite3.connect(str(p), timeout=3.0)
            conn.row_factory = sqlite3.Row
            ent = conn.execute(
                "SELECT name, entity_type FROM entities WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()
            if not ent:
                conn.close()
                return None
            obs_rows = conn.execute(
                "SELECT content FROM observations WHERE entity_name = ? ORDER BY rowid DESC LIMIT 20",
                (name,),
            ).fetchall()
            rel_rows = conn.execute(
                "SELECT relation_type, target FROM relations WHERE source = ? LIMIT 30",
                (name,),
            ).fetchall()
            conn.close()
            return Entity(
                name=str(ent["name"]),
                entity_type=str(ent["entity_type"] or "Unknown"),
                observations=tuple(str(r["content"]) for r in obs_rows if r["content"]),
                relations=tuple(
                    f"{r['relation_type']}:{r['target']}" for r in rel_rows
                ),
            )
        except sqlite3.Error as e:
            logger.debug("second_brain: get_entity failed: %s", e)
            return None

    def _query_account_kb(self, *, account_id: int, k: int) -> list[MemoryEntry]:
        """Load the account-scoped KB (markdown concatenated or chunked).

        Current behavior: fetch the full KB string via
        `load_knowledge_from_db(account_id)` and return as a single MemoryEntry.
        When the per-account KB is indexed (future), we'll do real retrieval.
        """
        try:
            from app._prompts_monolith import load_knowledge_from_db
        except ImportError:
            return []
        try:
            kb = load_knowledge_from_db(account_id)
        except Exception as e:  # noqa: BLE001
            logger.debug("second_brain: load_knowledge_from_db failed: %s", e)
            return []
        if not kb:
            return []
        # Return as a single entry; downstream consumers can chunk if needed
        return [MemoryEntry(
            content=str(kb)[:4000],
            source="account_db",
            score=0.4,
            scope="account",
            metadata={"account_id": account_id},
        )]

    def _read_memoire_md_fallback(self, *, task: str, k: int) -> list[MemoryEntry]:
        """Ultimate fallback: read sections of `knowledge/memoire.md`.

        Splits on `##` headings and returns the top sections whose heading
        contains words from the task. Naive — it's a safety net, not a real
        retriever.
        """
        p = self.config.memoire_md_path
        if not p or not Path(p).exists():
            return []
        try:
            text = Path(p).read_text(encoding="utf-8")
        except OSError:
            return []
        # Split on H2 headings
        sections: list[tuple[str, str]] = []
        current_title = "(intro)"
        current_body: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if current_body:
                    sections.append((current_title, "\n".join(current_body).strip()))
                current_title = line[3:].strip()
                current_body = []
            else:
                current_body.append(line)
        if current_body:
            sections.append((current_title, "\n".join(current_body).strip()))

        task_words = {w.lower() for w in task.split() if len(w) > 3}
        scored: list[tuple[float, MemoryEntry]] = []
        for title, body in sections:
            if not body:
                continue
            title_lower = title.lower()
            overlap = sum(1 for w in task_words if w in title_lower)
            score = min(1.0, overlap / max(1, len(task_words)))
            scored.append((score, MemoryEntry(
                content=f"## {title}\n{body[:1500]}",
                source="memoire_md",
                score=score,
                scope="agentys",
            )))
        # Keep only top k by score
        scored.sort(key=lambda s: s[0], reverse=True)
        return [e for _, e in scored[:k]]
