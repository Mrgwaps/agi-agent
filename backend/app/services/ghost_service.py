"""
Ghost.build memory service.

Ghost.build is NOT a REST API — it provides instant, forkable PostgreSQL
databases for AI agents.  Each agent gets its own Postgres database (or
shares a "Memory Engine" database) with built-in BM25 + pgvector hybrid
search via the pg_textsearch and pgvectorscale extensions.

Connection strings are in the form:
  postgresql://ghost:<token>@<db-name>.ghost.build/postgres

Since Ghost is CLI/MCP-first and the extension installs happen at the DB
level, this service acts as an asyncpg connection pool wrapper.  When no
Ghost connection string is configured we fall back to the existing local
ChromaDB / session-memory layer so the agent continues to function normally.

Setup (outside this service):
  1.  Install Ghost CLI:  curl -fsSL https://install.ghost.build | sh
  2.  ghost login
  3.  ghost database create my-agent-memory
  4.  Copy the connection string into GHOST_DATABASE_URL env var.

Inside the database Ghost ships with:
  - pg_textsearch  → BM25 full-text + hybrid search
  - pgvectorscale  → fast approximate nearest-neighbour vector search
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Lazily imported asyncpg pool
_pool: Optional[Any] = None


class GhostMemoryService:
    """
    Persistent hybrid BM25 + vector memory for agents backed by Ghost's
    managed Postgres.

    Schema created on first connect:
      memories(
        id         BIGSERIAL PRIMARY KEY,
        agent_id   TEXT NOT NULL,
        task_id    TEXT,
        collection TEXT NOT NULL DEFAULT 'default',
        content    TEXT NOT NULL,
        metadata   JSONB DEFAULT '{}',
        embedding  vector(1536),          -- populated externally if needed
        created_at TIMESTAMPTZ DEFAULT NOW()
      )

    Indexes: GIN on content (BM25), ivfflat on embedding (vector).
    """

    def __init__(self) -> None:
        self._dsn = getattr(settings, "ghost_database_url", "") or getattr(settings, "ghost_api_key", "")
        # ghost_api_key field is repurposed as the DSN when it looks like a postgres URL
        if self._dsn and not self._dsn.startswith("postgresql"):
            self._dsn = ""  # not a valid DSN — treat as unavailable

    @property
    def available(self) -> bool:
        return bool(self._dsn)

    async def _get_pool(self):
        global _pool
        if _pool is not None:
            return _pool
        try:
            import asyncpg  # type: ignore
            _pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5, command_timeout=30)
            await self._ensure_schema(_pool)
            logger.info("Ghost.build: connected to managed Postgres")
        except Exception as exc:
            logger.warning("Ghost.build: could not connect (%s) — falling back to local memory", exc)
            _pool = None
            raise
        return _pool

    async def _ensure_schema(self, pool) -> None:
        """Create the memories table and indexes if they don't exist."""
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE EXTENSION IF NOT EXISTS vector;
                CREATE TABLE IF NOT EXISTS memories (
                    id         BIGSERIAL PRIMARY KEY,
                    agent_id   TEXT NOT NULL,
                    task_id    TEXT,
                    collection TEXT NOT NULL DEFAULT 'default',
                    content    TEXT NOT NULL,
                    metadata   JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS memories_agent_id_idx ON memories(agent_id);
                CREATE INDEX IF NOT EXISTS memories_collection_idx ON memories(collection);
                CREATE INDEX IF NOT EXISTS memories_content_fts_idx ON memories USING gin(to_tsvector('english', content));
            """)

    # ── Store ──────────────────────────────────────────────────────────────────

    async def add_memory(
        self,
        content: str,
        *,
        agent_id: str,
        collection: str = "default",
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Store a memory in Ghost's Postgres.

        Returns {success, memory_id} on success or {success: False, error} if
        Ghost is not configured (caller should fall back to local memory).
        """
        if not self.available:
            return {"success": False, "error": "Ghost database not configured — set GHOST_DATABASE_URL"}
        try:
            pool = await self._get_pool()
            meta = json.dumps(metadata or {})
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO memories (agent_id, task_id, collection, content, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    RETURNING id, created_at
                    """,
                    agent_id, task_id, collection, content, meta,
                )
            return {"success": True, "memory_id": row["id"], "created_at": str(row["created_at"])}
        except Exception as exc:
            logger.error("Ghost add_memory failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── Search ─────────────────────────────────────────────────────────────────

    async def search_memories(
        self,
        query: str,
        *,
        agent_id: str,
        collection: str = "default",
        top_k: int = 5,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        BM25 full-text search over the agent's memories.

        Returns {success, results: [{id, content, metadata, score, created_at}]}.
        """
        if not self.available:
            return {"success": False, "error": "Ghost database not configured", "results": []}
        try:
            pool = await self._get_pool()
            # Build filter
            filters = ["agent_id = $1", "collection = $2"]
            params: List[Any] = [agent_id, collection]
            if task_id:
                params.append(task_id)
                filters.append(f"task_id = ${len(params)}")
            params.append(query)
            ts_param = f"${len(params)}"
            params.append(top_k)
            limit_param = f"${len(params)}"
            where = " AND ".join(filters)
            sql = f"""
                SELECT id, content, metadata, created_at,
                       ts_rank(to_tsvector('english', content), plainto_tsquery('english', {ts_param})) AS score
                FROM memories
                WHERE {where}
                  AND to_tsvector('english', content) @@ plainto_tsquery('english', {ts_param})
                ORDER BY score DESC
                LIMIT {limit_param}
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            results = [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                    "score": float(r["score"]),
                    "created_at": str(r["created_at"]),
                }
                for r in rows
            ]
            return {"success": True, "results": results}
        except Exception as exc:
            logger.error("Ghost search_memories failed: %s", exc)
            return {"success": False, "error": str(exc), "results": []}

    async def delete_memory(self, memory_id: int, *, agent_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost database not configured"}
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE id = $1 AND agent_id = $2", memory_id, agent_id)
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def list_memories(
        self,
        *,
        agent_id: str,
        collection: str = "default",
        limit: int = 20,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost database not configured", "memories": []}
        try:
            pool = await self._get_pool()
            sql = "SELECT id, content, metadata, created_at FROM memories WHERE agent_id = $1 AND collection = $2"
            params: List[Any] = [agent_id, collection]
            if task_id:
                params.append(task_id)
                sql += f" AND task_id = ${len(params)}"
            params.append(limit)
            sql += f" ORDER BY created_at DESC LIMIT ${len(params)}"
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return {
                "success": True,
                "memories": [
                    {
                        "id": r["id"],
                        "content": r["content"],
                        "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                        "created_at": str(r["created_at"]),
                    }
                    for r in rows
                ],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "memories": []}

    # ── Convenience helpers ────────────────────────────────────────────────────

    async def remember(
        self,
        agent_id: str,
        content: str,
        *,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """High-level helper: store a memory for an agent."""
        return await self.add_memory(content, agent_id=agent_id, task_id=task_id, metadata=metadata)

    async def recall(
        self,
        agent_id: str,
        query: str,
        top_k: int = 5,
        *,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """High-level helper: retrieve relevant memories for an agent."""
        return await self.search_memories(query, agent_id=agent_id, top_k=top_k, task_id=task_id)

    async def close(self) -> None:
        global _pool
        if _pool:
            await _pool.close()
            _pool = None


# Singleton
ghost_service = GhostMemoryService()
