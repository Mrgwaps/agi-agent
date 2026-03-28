from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from app.memory.session import session_memory
from app.models.event import AgentEvent, EventType
from app.models.task import (
    ApprovalRequest,
    RiskLevel,
    StepStatus,
    TaskState,
    TaskStatus,
    TaskStep,
)
from app.orchestrator.executor import ExecutorService
from app.orchestrator.planner import planner_service
from app.services.openrouter import openrouter_client

logger = logging.getLogger(__name__)

APPROVAL_POLL_INTERVAL = 1.0  # seconds
APPROVAL_TIMEOUT = 300  # 5 minutes


class OrchestratorGraph:
    """
    LangGraph-style state machine that orchestrates task execution.
    Each node is an async method that transforms TaskState.
    Events are emitted to the SSE queue in real-time.
    """

    def __init__(self, task_id: str) -> None:
        self._task_id = task_id
        self._event_queue: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()
        self._stopped = False

    # ── Public entry ─────────────────────────────────────────────────────────

    async def run(self, state: TaskState) -> None:
        """
        Drive the state machine from start to finish.
        Persists state after every node.
        """
        try:
            state = await self._intake_node(state)
            await self._save(state)

            state = await self._plan_node(state)
            await self._save(state)

            while state.status == TaskStatus.running and not self._stopped:
                if state.currentStep >= len(state.plan):
                    break

                step = state.plan[state.currentStep]

                # Check if approval needed
                if step.requires_approval and state.mode.value == "interactive":
                    state = await self._approval_node(state, step)
                    await self._save(state)

                    if step.status == StepStatus.skipped:
                        state.currentStep += 1
                        continue

                state = await self._execute_node(state)
                await self._save(state)

                current_step = state.plan[state.currentStep]
                if current_step.status == StepStatus.failed:
                    if step.retry_count >= 3:
                        # Too many retries: attempt replan
                        state = await self._replan_node(state)
                        await self._save(state)
                        if not state.plan[state.currentStep:]:
                            break
                    else:
                        state.currentStep += 1
                elif current_step.status == StepStatus.completed:
                    state = await self._verify_node(state)
                    await self._save(state)
                    state.currentStep += 1

            state = await self._deliver_node(state)
            await self._save(state)

        except asyncio.CancelledError:
            state.status = TaskStatus.aborted
            self._emit(self._event(EventType.task_aborted, {"reason": "cancelled"}))
            await self._save(state)
            raise
        except Exception as exc:
            logger.exception("Orchestrator fatal error for task %s: %s", self._task_id, exc)
            state.status = TaskStatus.failed
            state.error = str(exc)
            self._emit(self._event(EventType.task_failed, {"error": str(exc)}))
            await self._save(state)
        finally:
            # Signal SSE stream to close
            self._event_queue.put_nowait(None)

    async def event_stream(self) -> AsyncGenerator[AgentEvent, None]:
        """Async generator that yields events as they arrive."""
        while True:
            event = await self._event_queue.get()
            if event is None:
                break
            yield event

    def abort(self) -> None:
        self._stopped = True

    # ── Nodes ────────────────────────────────────────────────────────────────

    async def _intake_node(self, state: TaskState) -> TaskState:
        """Parse goal, set initial status, emit thinking event."""
        self._emit(self._event(
            EventType.thinking,
            {"message": f"Understanding goal: {state.goal[:100]}"},
        ))
        state.status = TaskStatus.planning
        state.updated_at = datetime.utcnow()
        return state

    async def _plan_node(self, state: TaskState) -> TaskState:
        """Generate a plan using the planner service."""
        self._emit(self._event(
            EventType.thinking,
            {"message": "Creating execution plan..."},
        ))

        steps = await planner_service.create_plan(
            goal=state.goal,
            constraints=state.constraints,
        )

        state.plan = steps
        state.currentStep = 0
        state.status = TaskStatus.running
        state.updated_at = datetime.utcnow()

        self._emit(self._event(
            EventType.plan_created,
            {
                "steps": [
                    {
                        "id": s.id,
                        "description": s.description,
                        "tool": s.tool_used,
                        "requires_approval": s.requires_approval,
                    }
                    for s in steps
                ],
                "total_steps": len(steps),
            },
        ))

        return state

    async def _execute_node(self, state: TaskState) -> TaskState:
        """Execute the current step via ExecutorService."""
        executor = ExecutorService(emit=self._emit, task_id=self._task_id)
        step = state.plan[state.currentStep]
        updated_step = await executor.execute_step(step, state)
        state.plan[state.currentStep] = updated_step

        # Accumulate cost
        state.total_cost_usd += updated_step.cost_usd
        if updated_step.model_used:
            state.model_used = updated_step.model_used

        self._emit(self._event(
            EventType.cost_update,
            {
                "step_id": updated_step.id,
                "step_cost": updated_step.cost_usd,
                "total_cost": state.total_cost_usd,
            },
        ))

        state.updated_at = datetime.utcnow()
        return state

    async def _verify_node(self, state: TaskState) -> TaskState:
        """Light verification – check if the step result is plausible."""
        step = state.plan[state.currentStep]
        if step.status != StepStatus.completed:
            return state

        # Only verify if result is non-trivial
        if not step.result:
            return state

        try:
            result_preview = str(step.result)[:500]
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a quality checker. Respond with a single word: "
                        "'PASS' if the result addresses the step, "
                        "'FAIL' otherwise."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Step: {step.description}\n"
                        f"Result: {result_preview}\n\n"
                        "Does the result address the step? PASS or FAIL?"
                    ),
                },
            ]
            verdict, _, _ = await openrouter_client.chat_completion(
                messages=messages,
                task_type="general",
                force_free=True,
                max_tokens=10,
            )
            if "FAIL" in verdict.upper():
                logger.info("Verify node: step '%s' flagged as FAIL", step.description[:50])
                # Don't override – just log for now
        except Exception as exc:
            logger.debug("verify_node error (non-fatal): %s", exc)

        return state

    async def _retry_node(self, state: TaskState, step: TaskStep) -> TaskState:
        """Handle retry bookkeeping (actual retry logic is in executor)."""
        step.retry_count += 1
        step.status = StepStatus.pending
        state.updated_at = datetime.utcnow()
        return state

    async def _replan_node(self, state: TaskState) -> TaskState:
        """Replan remaining steps after a persistent failure."""
        failed_step = state.plan[state.currentStep]
        completed = [s for s in state.plan[:state.currentStep] if s.status == StepStatus.completed]

        self._emit(self._event(
            EventType.replan,
            {
                "failed_step": failed_step.description,
                "error": failed_step.error,
            },
        ))

        new_steps = await planner_service.replan(
            goal=state.goal,
            completed_steps=completed,
            failed_step=failed_step,
            error=failed_step.error or "unknown error",
            constraints=state.constraints,
        )

        if new_steps:
            state.plan = completed + new_steps
            state.currentStep = len(completed)

        state.updated_at = datetime.utcnow()
        return state

    async def _approval_node(self, state: TaskState, step: TaskStep) -> TaskState:
        """Pause and wait for human approval."""
        request = ApprovalRequest(
            taskId=self._task_id,
            stepId=step.id,
            action=step.tool_used or "execute",
            description=step.description,
            risk_level=RiskLevel.medium,
        )
        state.status = TaskStatus.waiting_approval
        state.pending_approval = request
        state.updated_at = datetime.utcnow()

        self._emit(self._event(
            EventType.approval_required,
            {
                "step_id": step.id,
                "description": step.description,
                "tool": step.tool_used,
                "risk_level": request.risk_level,
            },
        ))

        # Poll Redis for approval decision
        elapsed = 0.0
        while elapsed < APPROVAL_TIMEOUT:
            decision = await session_memory.get_approval(self._task_id)
            if decision is not None:
                await session_memory.clear_approval(self._task_id)
                state.pending_approval = None
                state.status = TaskStatus.running

                if decision:
                    self._emit(self._event(
                        EventType.approval_granted,
                        {"step_id": step.id},
                    ))
                else:
                    self._emit(self._event(
                        EventType.approval_denied,
                        {"step_id": step.id},
                    ))
                    step.status = StepStatus.skipped

                return state

            await asyncio.sleep(APPROVAL_POLL_INTERVAL)
            elapsed += APPROVAL_POLL_INTERVAL

        # Timed out: auto-deny
        logger.warning("Approval timed out for step %s", step.id)
        step.status = StepStatus.skipped
        state.pending_approval = None
        state.status = TaskStatus.running
        return state

    async def _deliver_node(self, state: TaskState) -> TaskState:
        """Compile the final answer and mark task complete."""
        completed = [s for s in state.plan if s.status == StepStatus.completed]
        failed = [s for s in state.plan if s.status == StepStatus.failed]

        if not completed and failed:
            state.status = TaskStatus.failed
            state.error = "All steps failed"
            self._emit(self._event(
                EventType.task_failed,
                {"error": state.error, "total_cost": state.total_cost_usd},
            ))
            return state

        # Synthesize final answer
        try:
            summary = self._summarize_results(completed, state.goal)
            state.result = summary
        except Exception as exc:
            logger.warning("deliver_node summary failed: %s", exc)
            state.result = {
                "completed_steps": len(completed),
                "failed_steps": len(failed),
                "results": [
                    {"step": s.description, "result": str(s.result)[:200]}
                    for s in completed
                ],
            }

        state.status = TaskStatus.completed
        state.updated_at = datetime.utcnow()

        self._emit(self._event(
            EventType.task_completed,
            {
                "result_preview": str(state.result)[:500],
                "total_cost_usd": state.total_cost_usd,
                "steps_completed": len(completed),
                "steps_failed": len(failed),
                "model_used": state.model_used,
            },
        ))

        return state

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _summarize_results(self, steps: List[TaskStep], goal: str) -> str:
        parts = [f"Task: {goal}\n"]
        for i, step in enumerate(steps, 1):
            result_str = str(step.result)[:300] if step.result else "(no output)"
            parts.append(f"Step {i}: {step.description}\nResult: {result_str}\n")
        return "\n".join(parts)

    def _emit(self, event: AgentEvent) -> None:
        self._event_queue.put_nowait(event)
        # Also persist event asynchronously
        asyncio.create_task(session_memory.save_event(event))

    def _event(
        self,
        event_type: EventType,
        payload: Optional[Dict[str, Any]] = None,
        model_used: Optional[str] = None,
        cost_usd: float = 0.0,
    ) -> AgentEvent:
        return AgentEvent(
            taskId=self._task_id,
            eventType=event_type,
            payload=payload or {},
            model_used=model_used,
            cost_usd=cost_usd,
        )

    async def _save(self, state: TaskState) -> None:
        await session_memory.save_state(state)
