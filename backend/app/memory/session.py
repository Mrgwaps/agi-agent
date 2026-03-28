from __future__ import annotations

import json
import logging
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


class SessionMemory:
    """Redis-backed session store for task state and events."""

    def __init__(self) -> None:
        self._client: Optional[Any] = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
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
