from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.memory import MemoryFact, MemoryScope

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_facts (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'long_term',
    task_id     TEXT,
    embedding_id TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_task_id ON memory_facts (task_id);
CREATE INDEX IF NOT EXISTS idx_memory_facts_key ON memory_facts (key);
"""


class LongTermMemory:
    """Postgres-backed long-term memory store using asyncpg."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg

                self._pool = await asyncpg.create_pool(
                    dsn=settings.postgres_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=30,
                )
                async with self._pool.acquire() as conn:
                    await conn.execute(CREATE_TABLE_SQL)
                logger.info("LongTermMemory: connected to Postgres")
            except Exception as exc:
                logger.warning(
                    "LongTermMemory: Postgres unavailable (%s). "
                    "Operating without long-term persistence.",
                    exc,
                )
                self._pool = None
        return self._pool

    # ── Write ────────────────────────────────────────────────────────────────

    async def write_fact(self, fact: MemoryFact) -> Optional[MemoryFact]:
        pool = await self._get_pool()
        if pool is None:
            logger.debug("LongTermMemory: no pool, skipping write_fact")
            return fact

        value_str = (
            json.dumps(fact.value)
            if not isinstance(fact.value, str)
            else fact.value
        )

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO memory_facts (id, key, value, scope, task_id, embedding_id, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO UPDATE
                        SET value = EXCLUDED.value,
                            embedding_id = EXCLUDED.embedding_id
                    """,
                    fact.id,
                    fact.key,
                    value_str,
                    fact.scope.value,
                    fact.taskId,
                    fact.embedding_id,
                    fact.created_at,
                )
            return fact
        except Exception as exc:
            logger.warning("LongTermMemory.write_fact error: %s", exc)
            return fact

    # ── Search ───────────────────────────────────────────────────────────────

    async def search_facts(
        self,
        query: str,
        scope: Optional[MemoryScope] = None,
        task_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemoryFact]:
        pool = await self._get_pool()
        if pool is None:
            return []

        conditions: List[str] = ["(key ILIKE $1 OR value ILIKE $1)"]
        params: List[Any] = [f"%{query}%"]
        idx = 2

        if scope is not None:
            conditions.append(f"scope = ${idx}")
            params.append(scope.value)
            idx += 1

        if task_id is not None:
            conditions.append(f"task_id = ${idx}")
            params.append(task_id)
            idx += 1

        params.append(limit)
        where = " AND ".join(conditions)

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, key, value, scope, task_id, embedding_id, created_at
                    FROM memory_facts
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ${idx}
                    """,
                    *params,
                )
            return [self._row_to_fact(r) for r in rows]
        except Exception as exc:
            logger.warning("LongTermMemory.search_facts error: %s", exc)
            return []

    async def get_facts_by_task(self, task_id: str) -> List[MemoryFact]:
        pool = await self._get_pool()
        if pool is None:
            return []

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, key, value, scope, task_id, embedding_id, created_at
                    FROM memory_facts
                    WHERE task_id = $1
                    ORDER BY created_at ASC
                    """,
                    task_id,
                )
            return [self._row_to_fact(r) for r in rows]
        except Exception as exc:
            logger.warning("LongTermMemory.get_facts_by_task error: %s", exc)
            return []

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _row_to_fact(self, row: Any) -> MemoryFact:
        raw_value = row["value"]
        try:
            value = json.loads(raw_value)
        except (json.JSONDecodeError, TypeError):
            value = raw_value

        return MemoryFact(
            id=row["id"],
            key=row["key"],
            value=value,
            scope=MemoryScope(row["scope"]),
            taskId=row["task_id"],
            embedding_id=row["embedding_id"],
            created_at=row["created_at"],
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


# Singleton
longterm_memory = LongTermMemory()
