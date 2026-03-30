"""
Heartbeat API — 30-minute intelligence insights.

The heartbeat loop runs as a background asyncio task, periodically
analyzing task history and generating revenue-focused insights using
free LLM models (no cost).

Endpoints:
  GET /heartbeat/insights   — latest intelligence brief
  POST /heartbeat/trigger   — manually trigger a run (dev/testing)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])

# Module-level state (singleton, in-memory)
_latest_insight: Dict[str, Any] = {
    "text": None,
    "timestamp": None,
    "tasks_analyzed": 0,
    "model_used": None,
    "next_run_in_seconds": 1800,
    "new_skills": [],
    "total_skills": 0,
}
_last_run_time: Optional[float] = None
_INTERVAL = 1800  # 30 minutes

# Free LLM model ladder for heartbeat
_FREE_MODELS = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

_SYSTEM_PROMPT = (
    "You are a strategic AI business advisor helping an entrepreneur maximize revenue "
    "from their AI agent platform. Be specific, practical, and direct. "
    "Avoid vague advice. Focus on concrete actions that can be started today."
)

_USER_PROMPT_TEMPLATE = """Here are the AI agent tasks recently completed:

{task_list}

Based on these tasks and their outcomes, provide exactly 3 revenue opportunities.

Format your response as:
## Revenue Intelligence Brief

**Opportunity 1: [Title]**
[2-3 specific sentences: what to do, who to sell it to, estimated earnings]

**Opportunity 2: [Title]**
[2-3 specific sentences]

**Opportunity 3: [Title]**
[2-3 specific sentences]

**Quick Win (do today):**
[One immediate action the user can take in the next hour]"""


# ── Background task ───────────────────────────────────────────────────────────

async def _heartbeat_loop() -> None:
    """
    Runs forever as a background task. Waits 60s on startup to let
    the server fully initialize, then runs every 30 minutes.
    """
    logger.info("Heartbeat loop starting (first run in 60s)")
    await asyncio.sleep(60)  # Initial delay

    while True:
        try:
            await _run_heartbeat()
        except asyncio.CancelledError:
            logger.info("Heartbeat loop cancelled")
            break
        except Exception as exc:
            logger.warning("Heartbeat run failed (non-fatal): %s", exc)
        await asyncio.sleep(_INTERVAL)


async def _run_heartbeat() -> None:
    """Execute one heartbeat cycle."""
    import time
    global _latest_insight, _last_run_time

    logger.info("Running heartbeat intelligence analysis…")
    t0 = time.monotonic()

    # 1. Load recent task history
    task_context = await _build_task_context()

    if not task_context:
        logger.info("Heartbeat: no tasks found, skipping LLM call")
        return

    # 2. Call free LLM with model ladder
    text, model_used = await _call_free_llm(task_context)

    elapsed = time.monotonic() - t0
    now = datetime.now(timezone.utc)

    # Enrich with skills data
    new_skills: list = []
    total_skills = 0
    try:
        from app.services.skills_db import skills_db as _skills_db
        new_skills = await _skills_db.get_recent_skills(limit=5)
        stats = await _skills_db.get_stats()
        total_skills = stats.get("active_skills", 0)
    except Exception:
        pass

    _latest_insight = {
        "text": text,
        "timestamp": now.isoformat(),
        "tasks_analyzed": task_context["count"],
        "model_used": model_used,
        "next_run_in_seconds": _INTERVAL,
        "new_skills": new_skills,
        "total_skills": total_skills,
    }
    _last_run_time = now.timestamp()

    logger.info(
        "Heartbeat complete in %.1fs — analyzed %d tasks via %s",
        elapsed,
        task_context["count"],
        model_used,
    )


async def _build_task_context() -> Optional[Dict[str, Any]]:
    """Load recent tasks from session memory."""
    try:
        from app.memory.session import session_memory

        # session_memory stores task states; try to get recent task IDs
        # The session memory stores tasks by their IDs — we'll scan Redis keys
        client = await session_memory._get_client()
        keys = await client.keys("task:*:state")

        task_summaries = []
        for key in keys[-20:]:  # Last 20 tasks max
            try:
                raw = await client.get(key)
                if not raw:
                    continue
                import json
                state = json.loads(raw)
                goal = state.get("goal", "")[:120]
                status = state.get("status", "unknown")
                cost = state.get("total_cost_usd", 0)
                task_summaries.append(f"- [{status}] {goal} (cost: ${cost:.4f})")
            except Exception:
                continue

        if not task_summaries:
            return None

        return {
            "count": len(task_summaries),
            "list_text": "\n".join(task_summaries),
        }
    except Exception as exc:
        logger.debug("Heartbeat: could not load tasks: %s", exc)
        # Return a generic context when memory is unavailable
        return {
            "count": 1,
            "list_text": "- [unknown] No task data available (agent running in demo mode)",
        }


async def _call_free_llm(task_context: Dict[str, Any]) -> tuple[str, str]:
    """Try free LLM models (OpenRouter background client → HuggingFace → static)."""
    from app.services.openrouter import ModelQuality, background_openrouter_client as openrouter_client

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        task_list=task_context["list_text"]
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    # Use the background client (separate semaphore — never competes with tasks)
    from app.services.openrouter import background_openrouter_client
    try:
        text, model_used, _ = await background_openrouter_client.chat_completion(
            messages=messages,
            task_type="analysis",
            quality=ModelQuality.FREE,
            max_tokens=600,
            temperature=0.7,
        )
        if text and len(text) > 100:
            return text, model_used
    except Exception as exc:
        logger.debug("Heartbeat: OpenRouter FREE failed: %s", exc)

    # HuggingFace serverless fallback
    try:
        from app.services.huggingface_service import huggingface_service
        result = await huggingface_service.text_generation(
            f"{_SYSTEM_PROMPT}\n\n{user_prompt}",
            max_tokens=500,
            quality="free",
        )
        if result["success"] and result.get("text"):
            return result["text"], f"huggingface/{result['model']}"
    except Exception as exc:
        logger.debug("Heartbeat: HuggingFace fallback failed: %s", exc)

    # Absolute fallback — static insight
    return _static_insight(), "static"


def _static_insight() -> str:
    return """## Revenue Intelligence Brief

**Opportunity 1: AI Research-as-a-Service**
Offer research reports generated by your AGI agent to businesses. Charge $50-$200 per deep research report on market trends, competitors, or industry analysis. Target founders and consultants who need fast, reliable research.

**Opportunity 2: Content Automation Retainer**
Sell monthly retainers ($500-$2,000/mo) to businesses needing recurring content — blog posts, social copy, email sequences — all generated and refined by your agent. Emphasize speed and cost vs. human writers.

**Opportunity 3: Agent-as-a-Service for SMBs**
Package your agent for specific verticals (e-commerce product descriptions, real estate listings, legal summaries). White-label it and charge per-task or per-seat. Low CAC with high LTV.

**Quick Win (do today):**
Post one example of a completed agent task on LinkedIn/Twitter with "DM me if you want this done for your business" — this is the fastest path to your first paid customer."""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/insights")
async def get_insights():
    """
    Return the latest intelligence brief.

    text is null until the first heartbeat runs (60s after startup).
    """
    import time
    if _last_run_time is not None:
        elapsed_since_run = time.time() - _last_run_time
        next_run = max(0, int(_INTERVAL - elapsed_since_run))
    else:
        next_run = 60  # First run coming up

    return {
        **_latest_insight,
        "next_run_in_seconds": next_run,
        "available": _latest_insight.get("text") is not None,
    }


@router.post("/trigger")
async def trigger_heartbeat():
    """Manually trigger a heartbeat run (useful for testing)."""
    asyncio.create_task(_run_heartbeat())
    return {"message": "Heartbeat triggered", "status": "running"}


# Export the loop function for main.py to start
heartbeat_loop = _heartbeat_loop
