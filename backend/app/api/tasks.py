from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.memory.session import session_memory
from app.models.event import AgentEvent, EventType
from app.models.task import (
    ApprovalResponse,
    TaskCreate,
    TaskState,
    TaskStatus,
)
from app.orchestrator.graph import OrchestratorGraph

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

# In-memory registry of active orchestrators (task_id -> OrchestratorGraph)
_active: Dict[str, OrchestratorGraph] = {}


# ── Helper ────────────────────────────────────────────────────────────────────

async def _get_task_or_404(task_id: str) -> TaskState:
    state = await session_memory.load_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return state


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_task(
    body: TaskCreate,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Create a new task and start orchestration in the background."""
    state = TaskState(
        goal=body.goal,
        mode=body.mode,
        constraints=body.constraints,
        status=TaskStatus.queued,
    )

    await session_memory.save_state(state)

    orch = OrchestratorGraph(task_id=state.taskId)
    _active[state.taskId] = orch

    # Kick off orchestration as a background asyncio task
    background_tasks.add_task(_run_orchestrator, orch, state)

    return {
        "taskId": state.taskId,
        "status": state.status,
        "goal": state.goal,
        "created_at": state.created_at.isoformat(),
    }


@router.get("")
async def list_tasks(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent tasks."""
    task_ids = await session_memory.list_task_ids(limit=limit)
    tasks = []
    for tid in task_ids:
        state = await session_memory.load_state(tid)
        if state:
            tasks.append({
                "taskId": state.taskId,
                "goal": state.goal[:100],
                "status": state.status,
                "total_cost_usd": state.total_cost_usd,
                "created_at": state.created_at.isoformat(),
                "updated_at": state.updated_at.isoformat(),
            })
    return tasks


@router.get("/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    """Get full task state."""
    state = await _get_task_or_404(task_id)
    return state.model_dump(mode="json")


@router.get("/{task_id}/events")
async def stream_events(request: Request, task_id: str) -> EventSourceResponse:
    """
    SSE endpoint that streams AgentEvent objects in real-time.
    Replays persisted events first, then streams new ones.
    """
    # Ensure the task exists
    await _get_task_or_404(task_id)

    async def generator() -> AsyncGenerator[Dict[str, Any], None]:
        # 1. Replay historical events
        past_events = await session_memory.get_events(task_id)
        for event in past_events:
            yield {"data": event.model_dump_json(), "event": event.eventType.value}

        # 2. If orchestrator is active, stream live events
        orch = _active.get(task_id)
        if orch is not None:
            async for event in orch.event_stream():
                if await request.is_disconnected():
                    break
                yield {"data": event.model_dump_json(), "event": event.eventType.value}
        else:
            # Task already finished – send a final status event and close
            state = await session_memory.load_state(task_id)
            if state:
                final_event = AgentEvent(
                    taskId=task_id,
                    eventType=EventType.task_completed
                    if state.status == TaskStatus.completed
                    else EventType.task_failed,
                    payload={"status": state.status, "replayed": True},
                )
                yield {
                    "data": final_event.model_dump_json(),
                    "event": final_event.eventType.value,
                }

    return EventSourceResponse(generator())


@router.post("/{task_id}/approve")
async def approve_action(task_id: str, body: ApprovalResponse) -> Dict[str, Any]:
    """Approve a pending action."""
    state = await _get_task_or_404(task_id)
    if state.status != TaskStatus.waiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not waiting for approval (status: {state.status})",
        )
    await session_memory.set_approval(task_id, approved=True)
    return {"taskId": task_id, "approved": True}


@router.post("/{task_id}/deny")
async def deny_action(task_id: str, body: ApprovalResponse) -> Dict[str, Any]:
    """Deny a pending action."""
    state = await _get_task_or_404(task_id)
    if state.status != TaskStatus.waiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not waiting for approval (status: {state.status})",
        )
    await session_memory.set_approval(task_id, approved=False)
    return {"taskId": task_id, "approved": False}


@router.post("/{task_id}/abort")
async def abort_task(task_id: str) -> Dict[str, Any]:
    """Abort a running task."""
    state = await _get_task_or_404(task_id)
    orch = _active.get(task_id)
    if orch:
        orch.abort()
    state.status = TaskStatus.aborted
    state.updated_at = datetime.utcnow()
    await session_memory.save_state(state)
    return {"taskId": task_id, "status": "aborted"}


# ── Background runner ─────────────────────────────────────────────────────────

async def _run_orchestrator(orch: OrchestratorGraph, state: TaskState) -> None:
    try:
        await orch.run(state)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.exception("Orchestrator background task failed for %s: %s", state.taskId, exc)
    finally:
        _active.pop(state.taskId, None)
