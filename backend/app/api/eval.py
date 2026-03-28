from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.memory.session import session_memory
from app.models.event import EventType
from app.models.task import TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["eval"])

# In-memory eval event store (for demo; production would use Postgres)
_eval_events: List[Dict[str, Any]] = []


class EvalEventRequest(BaseModel):
    task_id: str
    event_type: str
    score: Optional[float] = None
    label: Optional[str] = None
    metadata: Dict[str, Any] = {}


@router.post("/events")
async def record_eval_event(body: EvalEventRequest) -> Dict[str, Any]:
    """Record an evaluation event (human feedback, automated score, etc.)."""
    event: Dict[str, Any] = {
        "task_id": body.task_id,
        "event_type": body.event_type,
        "score": body.score,
        "label": body.label,
        "metadata": body.metadata,
        "recorded_at": time.time(),
    }
    _eval_events.append(event)
    logger.info("Eval event recorded for task %s: %s", body.task_id, body.event_type)
    return {"success": True, "event": event}


@router.get("/summary/{task_id}")
async def get_eval_summary(task_id: str) -> Dict[str, Any]:
    """Compute evaluation metrics for a single task."""
    state = await session_memory.load_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    agent_events = await session_memory.get_events(task_id)

    # --- Step metrics
    total_steps = len(state.plan)
    completed_steps = sum(1 for s in state.plan if s.status.value == "completed")
    failed_steps = sum(1 for s in state.plan if s.status.value == "failed")
    retried_steps = sum(1 for s in state.plan if s.retry_count > 0)

    # --- Event counts
    event_counts: Dict[str, int] = defaultdict(int)
    for ev in agent_events:
        event_counts[ev.eventType.value] += 1

    # --- Latency
    total_latency_ms = sum(
        ev.latency_ms for ev in agent_events if ev.latency_ms is not None
    )

    # --- Cost
    total_cost = state.total_cost_usd

    # --- Human eval events for this task
    task_eval_events = [e for e in _eval_events if e["task_id"] == task_id]
    avg_score: Optional[float] = None
    scores = [e["score"] for e in task_eval_events if e.get("score") is not None]
    if scores:
        avg_score = sum(scores) / len(scores)

    # --- Success rate
    success = state.status == TaskStatus.completed
    step_success_rate = completed_steps / total_steps if total_steps > 0 else 0.0

    return {
        "task_id": task_id,
        "goal": state.goal[:100],
        "status": state.status,
        "success": success,
        "metrics": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "retried_steps": retried_steps,
            "step_success_rate": round(step_success_rate, 3),
            "total_events": len(agent_events),
            "event_breakdown": dict(event_counts),
            "total_latency_ms": total_latency_ms,
            "total_cost_usd": total_cost,
            "model_used": state.model_used,
            "human_eval_count": len(task_eval_events),
            "avg_human_score": avg_score,
        },
    }


@router.get("/dashboard")
async def get_eval_dashboard(limit: int = 50) -> Dict[str, Any]:
    """Aggregate evaluation metrics across all tasks."""
    task_ids = await session_memory.list_task_ids(limit=limit)

    totals = {
        "tasks": 0,
        "completed": 0,
        "failed": 0,
        "aborted": 0,
        "total_cost_usd": 0.0,
        "total_steps": 0,
        "completed_steps": 0,
        "failed_steps": 0,
    }

    per_task: List[Dict[str, Any]] = []

    for tid in task_ids:
        state = await session_memory.load_state(tid)
        if not state:
            continue

        totals["tasks"] += 1
        if state.status == TaskStatus.completed:
            totals["completed"] += 1
        elif state.status == TaskStatus.failed:
            totals["failed"] += 1
        elif state.status == TaskStatus.aborted:
            totals["aborted"] += 1

        totals["total_cost_usd"] += state.total_cost_usd
        totals["total_steps"] += len(state.plan)
        totals["completed_steps"] += sum(
            1 for s in state.plan if s.status.value == "completed"
        )
        totals["failed_steps"] += sum(
            1 for s in state.plan if s.status.value == "failed"
        )

        per_task.append({
            "task_id": tid,
            "goal": state.goal[:80],
            "status": state.status,
            "cost_usd": state.total_cost_usd,
            "steps": len(state.plan),
            "created_at": state.created_at.isoformat(),
        })

    success_rate = (
        totals["completed"] / totals["tasks"] if totals["tasks"] > 0 else 0.0
    )
    step_success_rate = (
        totals["completed_steps"] / totals["total_steps"]
        if totals["total_steps"] > 0
        else 0.0
    )

    # Human eval aggregates
    total_eval_events = len(_eval_events)
    all_scores = [e["score"] for e in _eval_events if e.get("score") is not None]
    global_avg_score = sum(all_scores) / len(all_scores) if all_scores else None

    return {
        "aggregate": {
            **totals,
            "success_rate": round(success_rate, 3),
            "step_success_rate": round(step_success_rate, 3),
            "avg_cost_per_task": round(
                totals["total_cost_usd"] / max(totals["tasks"], 1), 6
            ),
            "total_eval_events": total_eval_events,
            "global_avg_human_score": global_avg_score,
        },
        "recent_tasks": sorted(per_task, key=lambda x: x["created_at"], reverse=True)[
            :20
        ],
    }
