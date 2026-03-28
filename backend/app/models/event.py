from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    plan_created = "plan_created"
    step_started = "step_started"
    step_completed = "step_completed"
    tool_called = "tool_called"
    tool_result = "tool_result"
    retry = "retry"
    approval_required = "approval_required"
    approval_granted = "approval_granted"
    approval_denied = "approval_denied"
    error = "error"
    task_completed = "task_completed"
    task_failed = "task_failed"
    task_aborted = "task_aborted"
    cost_update = "cost_update"
    thinking = "thinking"
    replan = "replan"


class AgentEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    taskId: str
    eventType: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = Field(default_factory=dict)
    model_used: Optional[str] = None
    cost_usd: float = 0.0
    latency_ms: Optional[int] = None

    def to_sse(self) -> str:
        """Format as SSE data line."""
        import json
        data = self.model_dump(mode="json")
        return f"data: {json.dumps(data)}\n\n"
