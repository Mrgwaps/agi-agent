from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    aborted = "aborted"


class TaskMode(str, Enum):
    auto = "auto"
    interactive = "interactive"
    # legacy alias — accept 'demo' from older clients without breaking
    demo = "demo"


class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    waiting_approval = "waiting_approval"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskConstraints(BaseModel):
    allowWeb: bool = True
    allowFileSystem: bool = True
    allowCodeExecution: bool = True
    allowOllama: bool = True
    budget_usd: float = 1.0


class TaskCreate(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4096)
    mode: TaskMode = TaskMode.auto
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)


class TaskStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    status: StepStatus = StepStatus.pending
    tool_used: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    requires_approval: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cost_usd: float = 0.0
    model_used: Optional[str] = None
    retry_count: int = 0


class TaskState(BaseModel):
    taskId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    mode: TaskMode = TaskMode.auto
    status: TaskStatus = TaskStatus.queued
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    plan: List[TaskStep] = Field(default_factory=list)
    currentStep: int = 0
    events: List[str] = Field(default_factory=list)  # event IDs
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    model_used: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    pending_approval: Optional["ApprovalRequest"] = None

    def model_post_init(self, __context: Any) -> None:
        pass


class ApprovalRequest(BaseModel):
    taskId: str
    stepId: str
    action: str
    description: str
    risk_level: RiskLevel = RiskLevel.medium
    requested_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalResponse(BaseModel):
    approved: bool
    reason: Optional[str] = None


# Update forward ref
TaskState.model_rebuild()
