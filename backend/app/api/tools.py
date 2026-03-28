from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.tools.base import ToolRegistry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


class ToolExecuteRequest(BaseModel):
    input: Dict[str, Any]
    task_id: str = ""


@router.get("")
async def list_tools() -> Dict[str, Any]:
    """List all available tools with their schemas."""
    return {
        "tools": ToolRegistry.list_tools(),
        "count": len(ToolRegistry.all_names()),
    }


@router.post("/{tool_name}")
async def execute_tool(
    tool_name: str,
    body: ToolExecuteRequest,
) -> Dict[str, Any]:
    """Execute a specific tool directly (for testing/debugging)."""
    tool = ToolRegistry.get(tool_name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found. "
            f"Available: {ToolRegistry.all_names()}",
        )

    task_id = body.task_id or str(uuid.uuid4())

    try:
        result = await tool.execute(body.input, task_id)
        return {
            "tool": tool_name,
            "task_id": task_id,
            "result": result,
        }
    except Exception as exc:
        logger.exception("Direct tool execution error for %s: %s", tool_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))
