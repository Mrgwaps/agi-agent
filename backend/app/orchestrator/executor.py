from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import httpx

from app.models.event import AgentEvent, EventType
from app.models.task import StepStatus, TaskStep, TaskState
from app.services.openrouter import ModelQuality, infer_quality, openrouter_client
from app.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF = 3.0   # seconds for non-rate-limit errors
RATE_LIMIT_BACKOFF = 15.0  # seconds when 429 reaches the executor level


def _is_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


class ExecutorService:
    """
    Executes individual TaskStep objects, routing through the ToolRegistry.
    Emits AgentEvent objects for every significant action via a callback.
    """

    def __init__(
        self,
        emit: Callable[[AgentEvent], None],
        task_id: str,
    ) -> None:
        self._emit = emit
        self._task_id = task_id

    # ── Public ───────────────────────────────────────────────────────────────

    async def execute_step(self, step: TaskStep, state: TaskState) -> TaskStep:
        """
        Execute a single step with retry logic.
        Mutates and returns the step with updated status/result/cost.
        """
        step.status = StepStatus.running
        step.started_at = datetime.utcnow()

        self._emit(self._make_event(
            EventType.step_started,
            payload={
                "step_id": step.id,
                "description": step.description,
                "tool": step.tool_used,
            },
        ))

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await self._dispatch(step, state)
                step.result = result
                step.status = StepStatus.completed
                step.completed_at = datetime.utcnow()

                self._emit(self._make_event(
                    EventType.step_completed,
                    payload={
                        "step_id": step.id,
                        "description": step.description,
                        "result_preview": self._preview(result),
                        "attempt": attempt,
                    },
                ))
                return step

            except Exception as exc:
                logger.warning(
                    "Step '%s' attempt %d/%d failed: %s",
                    step.description[:60],
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                step.retry_count = attempt

                if attempt < MAX_RETRIES:
                    # Use a longer backoff for rate-limit errors
                    if _is_rate_limit(exc):
                        backoff = RATE_LIMIT_BACKOFF * attempt
                    else:
                        backoff = BASE_BACKOFF ** attempt
                    self._emit(self._make_event(
                        EventType.retry,
                        payload={
                            "step_id": step.id,
                            "attempt": attempt,
                            "max_retries": MAX_RETRIES,
                            "backoff_seconds": backoff,
                            "error": str(exc),
                            "rate_limited": _is_rate_limit(exc),
                        },
                    ))
                    await asyncio.sleep(backoff)
                else:
                    step.status = StepStatus.failed
                    step.error = str(exc)
                    step.completed_at = datetime.utcnow()
                    self._emit(self._make_event(
                        EventType.error,
                        payload={
                            "step_id": step.id,
                            "description": step.description,
                            "error": str(exc),
                            "attempts": attempt,
                        },
                    ))

        return step

    # ── Dispatch ─────────────────────────────────────────────────────────────

    async def _dispatch(self, step: TaskStep, state: TaskState) -> Any:
        tool_name = step.tool_used

        if tool_name in (None, "llm_only", ""):
            return await self._llm_only_step(step, state)

        tool = ToolRegistry.get(tool_name)
        if tool is None:
            logger.warning("Tool '%s' not found, falling back to LLM", tool_name)
            return await self._llm_only_step(step, state)

        # Build tool input from step description via LLM
        tool_input = await self._build_tool_input(step, tool.schema, state)

        t0 = time.monotonic()
        self._emit(self._make_event(
            EventType.tool_called,
            payload={
                "tool": tool_name,
                "step_id": step.id,
                "input": self._sanitize_input(tool_input),
            },
        ))

        result = await tool.execute(tool_input, self._task_id)
        latency_ms = int((time.monotonic() - t0) * 1000)

        self._emit(self._make_event(
            EventType.tool_result,
            payload={
                "tool": tool_name,
                "step_id": step.id,
                "success": result.get("success", False),
                "result_preview": self._preview(result.get("result")),
                "error": result.get("error"),
                "latency_ms": latency_ms,
            },
        ))

        if not result.get("success", True):
            raise RuntimeError(
                f"Tool '{tool_name}' failed: {result.get('error', 'unknown error')}"
            )

        return result

    # ── LLM-only execution ───────────────────────────────────────────────────

    async def _llm_only_step(self, step: TaskStep, state: TaskState) -> str:
        """Execute a step purely via LLM reasoning, using quality-appropriate model."""
        history = self._format_history(state)

        # Determine if this is the final (delivery) step
        is_final = (state.currentStep == len(state.plan) - 1)
        quality = infer_quality(
            step_description=step.description,
            goal=state.goal,
            is_final_step=is_final,
        )

        # Pick task type for model routing
        desc_lower = step.description.lower()
        if any(k in desc_lower for k in ("code", "script", "function", "implement", "program")):
            task_type = "code"
        elif any(k in desc_lower for k in ("write", "draft", "compose", "ebook", "guide", "report")):
            task_type = "writing"
        elif any(k in desc_lower for k in ("synthesize", "compile", "deliver", "final")):
            task_type = "synthesis"
        elif any(k in desc_lower for k in ("research", "analyze", "analyse", "summarize")):
            task_type = "analysis"
        else:
            task_type = "general"

        # System prompt varies by quality — premium gets a more authoritative persona
        if quality == ModelQuality.PREMIUM:
            system_content = (
                "You are an expert AI assistant producing high-quality, professional output. "
                "Be thorough, well-structured, and authoritative. "
                "Deliver complete, polished work — not outlines or placeholders."
            )
            max_tokens = 4096
        else:
            system_content = (
                "You are an AI assistant executing a task step-by-step. "
                "Complete the current step using your knowledge. "
                "Be thorough and concrete."
            )
            max_tokens = 2048

        logger.info(
            "Step '%s…' → quality=%s model_type=%s final=%s",
            step.description[:60], quality.value, task_type, is_final,
        )

        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"Task goal: {state.goal}\n\n"
                    f"Completed steps so far:\n{history}\n\n"
                    f"Current step: {step.description}\n\n"
                    "Complete this step:"
                ),
            },
        ]

        t0 = time.monotonic()
        text, model, cost = await openrouter_client.chat_completion(
            messages=messages,
            task_type=task_type,
            quality=quality,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        step.model_used = model
        step.cost_usd = cost

        self._emit(self._make_event(
            EventType.cost_update,
            payload={"step_id": step.id, "cost_usd": cost},
            model_used=model,
            cost_usd=cost,
            latency_ms=latency_ms,
        ))

        return text

    # ── Tool input building ──────────────────────────────────────────────────

    async def _build_tool_input(
        self, step: TaskStep, tool_schema: Dict[str, Any], state: TaskState
    ) -> Dict[str, Any]:
        """Ask the LLM to produce the correct JSON input for a tool call."""
        import json

        schema_str = json.dumps(tool_schema, indent=2)
        history = self._format_history(state)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a tool-call generator. Given a task step description "
                    "and a JSON schema, produce a single valid JSON object as tool input. "
                    "Return ONLY the JSON object, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task goal: {state.goal}\n"
                    f"Completed steps:\n{history}\n\n"
                    f"Step to execute: {step.description}\n\n"
                    f"Tool schema:\n{schema_str}\n\n"
                    "Generate the JSON input object:"
                ),
            },
        ]

        try:
            # Tool input building is always cheap/free — it's just JSON formatting
            text, model, cost = await openrouter_client.chat_completion(
                messages=messages,
                task_type="structured",
                quality=ModelQuality.FREE,
                max_tokens=512,
            )
            step.cost_usd = (step.cost_usd or 0) + cost
            step.model_used = model

            # Parse JSON from response
            text = text.strip()
            if "```" in text:
                import re
                m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
                if m:
                    text = m.group(1).strip()

            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start : end + 1])
        except Exception as exc:
            logger.warning("Failed to build tool input via LLM: %s", exc)

        # Fallback: pass description as query/path/code
        return {"query": step.description, "path": ".", "code": step.description}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _make_event(
        self,
        event_type: EventType,
        payload: Optional[Dict[str, Any]] = None,
        model_used: Optional[str] = None,
        cost_usd: float = 0.0,
        latency_ms: Optional[int] = None,
    ) -> AgentEvent:
        return AgentEvent(
            taskId=self._task_id,
            eventType=event_type,
            payload=payload or {},
            model_used=model_used,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

    def _format_history(self, state: TaskState) -> str:
        completed = [s for s in state.plan if s.status == StepStatus.completed]
        if not completed:
            return "(none)"
        lines = []
        for s in completed:
            preview = self._preview(s.result)
            lines.append(f"- {s.description}: {preview}")
        return "\n".join(lines)

    def _preview(self, value: Any, max_len: int = 200) -> str:
        import json as _json

        if value is None:
            return ""
        if isinstance(value, str):
            return value[:max_len]
        try:
            s = _json.dumps(value)
            return s[:max_len]
        except Exception:
            return str(value)[:max_len]

    def _sanitize_input(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy with long values truncated for event payloads."""
        sanitized = {}
        for k, v in tool_input.items():
            if isinstance(v, str) and len(v) > 300:
                sanitized[k] = v[:300] + "...[truncated]"
            else:
                sanitized[k] = v
        return sanitized
