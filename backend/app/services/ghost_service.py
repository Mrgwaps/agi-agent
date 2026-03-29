"""
Ghost.build memory service — managed PostgreSQL with hybrid BM25+pgvector
search for persistent agent memory.

Ghost provides each agent an isolated ephemeral Postgres database with
full-text and semantic search built-in.  When no Ghost key is configured the
service falls back to the existing local ChromaDB / session-memory layer so
the agent continues to function normally.

API: https://api.ghost.build  (Bearer auth)
Docs: https://docs.ghost.build
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.ghost.build"


class GhostMemoryService:
    """
    Wraps Ghost.build's memory API.

    Key concepts
    ────────────
    • Collection  — a named group of memories (analogous to a table / namespace)
    • Memory      — a text document + metadata + embedding stored in Ghost
    • Search      — hybrid BM25 (keyword) + vector (semantic) retrieval
    """

    def __init__(self) -> None:
        self._key = getattr(settings, "ghost_api_key", "")

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    # ── Collections ────────────────────────────────────────────────────────────

    async def create_collection(self, name: str, description: str = "") -> Dict[str, Any]:
        """Create a new memory collection for an agent."""
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_BASE_URL}/v1/collections",
                headers=self._headers(),
                json={"name": name, "description": description},
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "collection_id": data.get("id"), "raw": data}

    async def list_collections(self) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured", "collections": []}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{_BASE_URL}/v1/collections", headers=self._headers())
            resp.raise_for_status()
        return {"success": True, "collections": resp.json().get("collections", resp.json())}

    async def delete_collection(self, collection_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(
                f"{_BASE_URL}/v1/collections/{collection_id}", headers=self._headers()
            )
            resp.raise_for_status()
        return {"success": True}

    # ── Memories ───────────────────────────────────────────────────────────────

    async def add_memory(
        self,
        collection_id: str,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Store a piece of text in Ghost.  Embeddings are computed server-side.

        Args:
            collection_id: Target collection.
            content:       Text to store.
            metadata:      Arbitrary JSON metadata attached to the memory.
            task_id:       If provided, tagged on the memory for retrieval.
            agent_id:      If provided, tagged on the memory.
        """
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        meta = metadata or {}
        if task_id:
            meta["task_id"] = task_id
        if agent_id:
            meta["agent_id"] = agent_id
        meta.setdefault("created_at", time.time())
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_BASE_URL}/v1/collections/{collection_id}/memories",
                headers=self._headers(),
                json={"content": content, "metadata": meta},
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "memory_id": data.get("id"), "raw": data}

    async def add_memories_batch(
        self, collection_id: str, items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Bulk-insert memories.  Each item: {content, metadata?}
        """
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_BASE_URL}/v1/collections/{collection_id}/memories/batch",
                headers=self._headers(),
                json={"memories": items},
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "inserted": data.get("inserted", len(items)), "raw": data}

    async def search_memories(
        self,
        collection_id: str,
        query: str,
        *,
        top_k: int = 5,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        hybrid_alpha: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Hybrid BM25 + vector search over a collection.

        Args:
            query:         Natural-language search query.
            top_k:         Maximum results to return.
            task_id:       Filter by task_id metadata field.
            agent_id:      Filter by agent_id metadata field.
            hybrid_alpha:  0.0 = pure BM25, 1.0 = pure vector, 0.5 = equal blend.
        """
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured", "results": []}
        payload: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "hybrid_alpha": hybrid_alpha,
        }
        filters: Dict[str, str] = {}
        if task_id:
            filters["task_id"] = task_id
        if agent_id:
            filters["agent_id"] = agent_id
        if filters:
            payload["filters"] = filters
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_BASE_URL}/v1/collections/{collection_id}/search",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, "results": data.get("results", data), "raw": data}

    async def get_memory(self, collection_id: str, memory_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{_BASE_URL}/v1/collections/{collection_id}/memories/{memory_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
        return {"success": True, **resp.json()}

    async def delete_memory(self, collection_id: str, memory_id: str) -> Dict[str, Any]:
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(
                f"{_BASE_URL}/v1/collections/{collection_id}/memories/{memory_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
        return {"success": True}

    # ── Convenience helpers ────────────────────────────────────────────────────

    async def remember(self, agent_id: str, content: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        High-level helper: store a memory under the agent's default collection.
        Creates the collection if it doesn't exist yet.
        """
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured"}
        collection_name = f"agent_{agent_id}"
        # Try to create — Ghost returns 409 if already exists, which we ignore
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    f"{_BASE_URL}/v1/collections",
                    headers=self._headers(),
                    json={"name": collection_name},
                )
        except Exception:
            pass
        # Fetch or use cached collection id
        cols = await self.list_collections()
        col_id = None
        for c in cols.get("collections", []):
            if c.get("name") == collection_name:
                col_id = c.get("id")
                break
        if not col_id:
            created = await self.create_collection(collection_name)
            col_id = created.get("collection_id")
        return await self.add_memory(col_id, content, metadata=metadata, agent_id=agent_id)

    async def recall(self, agent_id: str, query: str, top_k: int = 5) -> Dict[str, Any]:
        """High-level helper: search the agent's default collection."""
        if not self.available:
            return {"success": False, "error": "Ghost API key not configured", "results": []}
        collection_name = f"agent_{agent_id}"
        cols = await self.list_collections()
        col_id = None
        for c in cols.get("collections", []):
            if c.get("name") == collection_name:
                col_id = c.get("id")
                break
        if not col_id:
            return {"success": True, "results": [], "note": "No memories stored yet"}
        return await self.search_memories(col_id, query, top_k=top_k, agent_id=agent_id)


# Singleton
ghost_service = GhostMemoryService()
