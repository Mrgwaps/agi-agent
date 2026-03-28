from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.memory.longterm import longterm_memory
from app.memory.session import session_memory
from app.memory.vector_store import vector_store
from app.models.memory import MemoryFact, MemoryQuery, MemoryScope, MemorySearchResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


class WriteFactRequest(BaseModel):
    key: str
    value: Any
    scope: MemoryScope = MemoryScope.long_term
    task_id: str = ""


@router.post("/write")
async def write_fact(body: WriteFactRequest) -> Dict[str, Any]:
    """Write a fact to long-term memory and vector store."""
    fact = MemoryFact(
        key=body.key,
        value=body.value,
        scope=body.scope,
        taskId=body.task_id or None,
    )

    # Store in Postgres
    saved = await longterm_memory.write_fact(fact)

    # Add to vector store for semantic search
    embedding_id = await vector_store.add_document(fact)
    if saved:
        saved.embedding_id = embedding_id

    return {
        "success": True,
        "fact_id": fact.id,
        "embedding_id": embedding_id,
    }


@router.post("/search")
async def search_memory(body: MemoryQuery) -> Dict[str, Any]:
    """Semantic + keyword search across memory."""
    # Vector search
    vector_results: List[MemorySearchResult] = await vector_store.search_similar(
        query=body.query,
        task_id=body.task_id,
        limit=body.limit,
    )

    # Postgres keyword search
    pg_facts = await longterm_memory.search_facts(
        query=body.query,
        scope=body.scope,
        task_id=body.task_id,
        limit=body.limit,
    )

    # Deduplicate by fact id
    seen_ids = set()
    combined: List[Dict[str, Any]] = []

    for vr in vector_results:
        if vr.fact.id not in seen_ids:
            seen_ids.add(vr.fact.id)
            combined.append({
                "fact": vr.fact.model_dump(mode="json"),
                "score": vr.score,
                "source": vr.source,
            })

    for fact in pg_facts:
        if fact.id not in seen_ids:
            seen_ids.add(fact.id)
            combined.append({
                "fact": fact.model_dump(mode="json"),
                "score": 0.5,
                "source": "postgres_keyword",
            })

    combined.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": body.query,
        "results": combined[: body.limit],
        "count": len(combined[: body.limit]),
    }


@router.get("/{task_id}")
async def get_task_memory(task_id: str) -> Dict[str, Any]:
    """Get all memory facts associated with a task."""
    facts = await longterm_memory.get_facts_by_task(task_id)
    return {
        "task_id": task_id,
        "facts": [f.model_dump(mode="json") for f in facts],
        "count": len(facts),
    }
