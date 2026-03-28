from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.memory import MemoryFact, MemoryScope

logger = logging.getLogger(__name__)

# Postgres DDL (asyncpg uses $N placeholders)
_PG_CREATE_SQL = """
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

# SQLite DDL (aiosqlite uses ? placeholders, no TIMESTAMPTZ)
_SQLITE_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS memory_facts (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'long_term',
    task_id     TEXT,
    embedding_id TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_task_id ON memory_facts (task_id);
CREATE INDEX IF NOT EXISTS idx_memory_facts_key ON memory_facts (key);
"""


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


class LongTermMemory:
    """
    Long-term memory store.

    Driver selection (automatic):
    - Postgres (asyncpg) when DATABASE_URL starts with ``postgresql``
    - SQLite  (aiosqlite) when DATABASE_URL starts with ``sqlite`` or is empty/disabled
    - In-memory dict fallback when neither driver is available
    """

    def __init__(self) -> None:
        self._pool: Optional[Any] = None          # asyncpg pool
        self._sqlite_db: Optional[Any] = None     # aiosqlite connection
        self._fallback: Dict[str, MemoryFact] = {}
        self._mode: str = "uninitialised"

    async def _init(self) -> None:
        if self._mode != "uninitialised":
            return

        url = settings.postgres_url or ""

        # ── SQLite path ──────────────────────────────────────────────────
        if not url or url in ("none", "disabled") or _is_sqlite_url(url):
            await self._init_sqlite(url)
            return

        # ── Postgres path ────────────────────────────────────────────────
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                dsn=url,
                min_size=1,
                max_size=10,
                command_timeout=5,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(_PG_CREATE_SQL)
            self._mode = "postgres"
            logger.info("LongTermMemory: connected to Postgres")
        except Exception as exc:
            logger.warning(
                "LongTermMemory: Postgres unavailable (%s) — falling back to SQLite", exc
            )
            self._pool = None
            await self._init_sqlite("")

    async def _init_sqlite(self, url: str) -> None:
        # Derive file path: sqlite:///./agi_memory.db  → ./agi_memory.db
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
        elif url.startswith("sqlite://"):
            path = url[len("sqlite://"):]
        else:
            path = "./agi_memory.db"

        try:
            import aiosqlite  # type: ignore

            self._sqlite_db = await aiosqlite.connect(path)
            self._sqlite_db.row_factory = aiosqlite.Row
            await self._sqlite_db.executescript(_SQLITE_CREATE_SQL)
            await self._sqlite_db.commit()
            self._mode = "sqlite"
            logger.info("LongTermMemory: using SQLite at %s", path)
        except ImportError:
            logger.warning("LongTermMemory: aiosqlite not installed — using in-memory dict fallback")
            self._mode = "memory"
        except Exception as exc:
            logger.warning("LongTermMemory: SQLite failed (%s) — using in-memory dict fallback", exc)
            self._mode = "memory"

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _get_pool(self) -> Optional[Any]:
        await self._init()
        return self._pool if self._mode == "postgres" else None

    async def _get_sqlite(self) -> Optional[Any]:
        await self._init()
        return self._sqlite_db if self._mode == "sqlite" else None

    # ── Write ────────────────────────────────────────────────────────────────

    async def write_fact(self, fact: MemoryFact) -> Optional[MemoryFact]:
        await self._init()
        value_str = json.dumps(fact.value) if not isinstance(fact.value, str) else fact.value
        ts = fact.created_at.isoformat() if isinstance(fact.created_at, datetime) else str(fact.created_at)

        # Postgres
        pool = await self._get_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO memory_facts (id, key, value, scope, task_id, embedding_id, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (id) DO UPDATE
                            SET value = EXCLUDED.value, embedding_id = EXCLUDED.embedding_id
                        """,
                        fact.id, fact.key, value_str, fact.scope.value,
                        fact.taskId, fact.embedding_id, fact.created_at,
                    )
                return fact
            except Exception as exc:
                logger.warning("LongTermMemory.write_fact (pg) error: %s", exc)
                return fact

        # SQLite
        db = await self._get_sqlite()
        if db is not None:
            try:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO memory_facts (id, key, value, scope, task_id, embedding_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fact.id, fact.key, value_str, fact.scope.value, fact.taskId, fact.embedding_id, ts),
                )
                await db.commit()
                return fact
            except Exception as exc:
                logger.warning("LongTermMemory.write_fact (sqlite) error: %s", exc)
                return fact

        # In-memory fallback
        self._fallback[fact.id] = fact
        return fact

    # ── Search ───────────────────────────────────────────────────────────────

    async def search_facts(
        self,
        query: str,
        scope: Optional[MemoryScope] = None,
        task_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemoryFact]:
        await self._init()
        pattern = f"%{query}%"

        # Postgres
        pool = await self._get_pool()
        if pool is not None:
            conditions: List[str] = ["(key ILIKE $1 OR value ILIKE $1)"]
            params: List[Any] = [pattern]
            idx = 2
            if scope is not None:
                conditions.append(f"scope = ${idx}"); params.append(scope.value); idx += 1
            if task_id is not None:
                conditions.append(f"task_id = ${idx}"); params.append(task_id); idx += 1
            params.append(limit)
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"SELECT * FROM memory_facts WHERE {' AND '.join(conditions)} ORDER BY created_at DESC LIMIT ${idx}",
                        *params,
                    )
                return [self._row_to_fact(r) for r in rows]
            except Exception as exc:
                logger.warning("LongTermMemory.search_facts (pg) error: %s", exc)
                return []

        # SQLite
        db = await self._get_sqlite()
        if db is not None:
            conditions_sq = ["(key LIKE ? OR value LIKE ?)"]
            params_sq: List[Any] = [pattern, pattern]
            if scope is not None:
                conditions_sq.append("scope = ?"); params_sq.append(scope.value)
            if task_id is not None:
                conditions_sq.append("task_id = ?"); params_sq.append(task_id)
            params_sq.append(limit)
            try:
                async with db.execute(
                    f"SELECT * FROM memory_facts WHERE {' AND '.join(conditions_sq)} ORDER BY created_at DESC LIMIT ?",
                    params_sq,
                ) as cursor:
                    rows = await cursor.fetchall()
                return [self._row_to_fact(r) for r in rows]
            except Exception as exc:
                logger.warning("LongTermMemory.search_facts (sqlite) error: %s", exc)
                return []

        # In-memory fallback
        results = [
            f for f in self._fallback.values()
            if query.lower() in f.key.lower() or query.lower() in str(f.value).lower()
        ]
        if scope:
            results = [f for f in results if f.scope == scope]
        if task_id:
            results = [f for f in results if f.taskId == task_id]
        return results[:limit]

    async def get_facts_by_task(self, task_id: str) -> List[MemoryFact]:
        await self._init()

        # Postgres
        pool = await self._get_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM memory_facts WHERE task_id = $1 ORDER BY created_at ASC",
                        task_id,
                    )
                return [self._row_to_fact(r) for r in rows]
            except Exception as exc:
                logger.warning("LongTermMemory.get_facts_by_task (pg) error: %s", exc)
                return []

        # SQLite
        db = await self._get_sqlite()
        if db is not None:
            try:
                async with db.execute(
                    "SELECT * FROM memory_facts WHERE task_id = ? ORDER BY created_at ASC",
                    (task_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                return [self._row_to_fact(r) for r in rows]
            except Exception as exc:
                logger.warning("LongTermMemory.get_facts_by_task (sqlite) error: %s", exc)
                return []

        # In-memory fallback
        return [f for f in self._fallback.values() if f.taskId == task_id]

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
        if self._sqlite_db is not None:
            await self._sqlite_db.close()
            self._sqlite_db = None


# Singleton
longterm_memory = LongTermMemory()
