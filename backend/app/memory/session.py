from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.event import AgentEvent
from app.models.task import TaskState

logger = logging.getLogger(__name__)

SESSION_TTL = 24 * 3600  # 24 hours


def _state_key(task_id: str) -> str:
    return f"agi:state:{task_id}"


def _events_key(task_id: str) -> str:
    return f"agi:events:{task_id}"


def _approval_key(task_id: str) -> str:
    return f"agi:approval:{task_id}"


class _InMemoryStore:
    """Lightweight in-process fallback used when Redis is unavailable."""

    def __init__(self) -> None:
        self._kv: Dict[str, str] = {}
        self._lists: Dict[str, List[str]] = defaultdict(list)

    async def set(self, key: str, value: str, ex: int = 0) -> None:
        self._kv[key] = value

    async def get(self, key: str) -> Optional[str]:
        return self._kv.get(key)

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._kv.pop(k, None)
            self._lists.pop(k, None)

    async def rpush(self, key: str, value: str) -> None:
        self._lists[key].append(value)

    async def expire(self, key: str, seconds: int) -> None:
        pass  # no TTL enforcement in fallback

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        items = self._lists.get(key, [])
        return items[start: None if end == -1 else end + 1]

    async def keys(self, pattern: str) -> List[str]:
        prefix = pattern.rstrip("*")
        return [k for k in list(self._kv.keys()) + list(self._lists.keys()) if k.startswith(prefix)]

    async def aclose(self) -> None:
        pass


class SessionMemory:
    """Redis-backed session store with automatic in-memory fallback for local mode."""

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._use_fallback: bool = False

    async def _get_client(self) -> Any:
        if self._use_fallback:
            if self._client is None:
                self._client = _InMemoryStore()
            return self._client

        if self._client is None:
            # Skip Redis entirely if no URL configured or local mode
            if not settings.redis_url or settings.redis_url in ("", "none", "disabled"):
                logger.info("SessionMemory: Redis disabled — using in-memory store")
                self._use_fallback = True
                self._client = _InMemoryStore()
                return self._client
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                await client.ping()
                self._client = client
                logger.info("SessionMemory: connected to Redis")
            except Exception as exc:
                logger.warning(
                    "SessionMemory: Redis unavailable (%s) — falling back to in-memory store", exc
                )
                self._use_fallback = True
                self._client = _InMemoryStore()
        return self._client

    # ── Task state ───────────────────────────────────────────────────────────

    async def save_state(self, state: TaskState) -> None:
        try:
            client = await self._get_client()
            key = _state_key(state.taskId)
            payload = state.model_dump_json()
            await client.set(key, payload, ex=SESSION_TTL)
        except Exception as exc:
            logger.warning("SessionMemory.save_state failed: %s", exc)

    async def load_state(self, task_id: str) -> Optional[TaskState]:
        try:
            client = await self._get_client()
            raw = await client.get(_state_key(task_id))
            if raw is None:
                return None
            return TaskState.model_validate_json(raw)
        except Exception as exc:
            logger.warning("SessionMemory.load_state failed for %s: %s", task_id, exc)
            return None

    async def delete(self, task_id: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(
                _state_key(task_id),
                _events_key(task_id),
                _approval_key(task_id),
            )
        except Exception as exc:
            logger.warning("SessionMemory.delete failed: %s", exc)

    # ── Events ───────────────────────────────────────────────────────────────

    async def save_event(self, event: AgentEvent) -> None:
        try:
            client = await self._get_client()
            key = _events_key(event.taskId)
            await client.rpush(key, event.model_dump_json())
            await client.expire(key, SESSION_TTL)
        except Exception as exc:
            logger.warning("SessionMemory.save_event failed: %s", exc)

    async def get_events(self, task_id: str) -> List[AgentEvent]:
        try:
            client = await self._get_client()
            raw_list = await client.lrange(_events_key(task_id), 0, -1)
            events: List[AgentEvent] = []
            for raw in raw_list:
                try:
                    events.append(AgentEvent.model_validate_json(raw))
                except Exception:
                    pass
            return events
        except Exception as exc:
            logger.warning("SessionMemory.get_events failed for %s: %s", task_id, exc)
            return []

    # ── Approval signalling ──────────────────────────────────────────────────

    async def set_approval(self, task_id: str, approved: bool) -> None:
        try:
            client = await self._get_client()
            await client.set(
                _approval_key(task_id),
                "approved" if approved else "denied",
                ex=3600,
            )
        except Exception as exc:
            logger.warning("SessionMemory.set_approval failed: %s", exc)

    async def get_approval(self, task_id: str) -> Optional[bool]:
        try:
            client = await self._get_client()
            val = await client.get(_approval_key(task_id))
            if val is None:
                return None
            return val == "approved"
        except Exception as exc:
            logger.warning("SessionMemory.get_approval failed: %s", exc)
            return None

    async def clear_approval(self, task_id: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(_approval_key(task_id))
        except Exception as exc:
            logger.warning("SessionMemory.clear_approval failed: %s", exc)

    # ── List recent tasks ────────────────────────────────────────────────────

    async def list_task_ids(self, limit: int = 50) -> List[str]:
        try:
            client = await self._get_client()
            keys = await client.keys("agi:state:*")
            task_ids = [k.replace("agi:state:", "") for k in keys]
            return task_ids[:limit]
        except Exception as exc:
            logger.warning("SessionMemory.list_task_ids failed: %s", exc)
            return []

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Singleton
session_memory = SessionMemory()
