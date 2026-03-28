from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class MemoryScope(str, Enum):
    session = "session"
    long_term = "long_term"


class MemoryFact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    key: str
    value: Any
    scope: MemoryScope = MemoryScope.session
    taskId: Optional[str] = None
    embedding_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryQuery(BaseModel):
    query: str
    scope: Optional[MemoryScope] = None
    task_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


class MemorySearchResult(BaseModel):
    fact: MemoryFact
    score: float = 1.0
    source: str = "exact"
