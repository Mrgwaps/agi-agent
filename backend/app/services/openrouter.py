"""
OpenRouter client — Claude models as primary, free models as fallback.

Primary models (paid via OpenRouter, reliable, fast):
  FREE tier     → anthropic/claude-haiku-4-5      cheap + fast
  BALANCED tier → anthropic/claude-sonnet-4-6     capable
  PREMIUM tier  → anthropic/claude-opus-4-6       most capable

Free fallback models (used when Claude fails with 4xx/5xx):
  google/gemini-2.0-flash-exp:free
  meta-llama/llama-3.3-70b-instruct:free
  google/gemma-3-27b-it:free
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ModelQuality(str, Enum):
    FREE     = "free"
    BALANCED = "balanced"
    PREMIUM  = "premium"


# ── Claude models (OpenRouter paid) ────────────────────────────────────────
CLAUDE_HAIKU  = "anthropic/claude-haiku-4-5"
CLAUDE_SONNET = "anthropic/claude-sonnet-4-6"
CLAUDE_OPUS   = "anthropic/claude-opus-4-6"

# ── Free fallback models ────────────────────────────────────────────────────
FREE_MODELS: List[str] = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

# ── Cost per 1M tokens (input, output) ────────────────────────────────────
MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    CLAUDE_HAIKU:  (1.00,  5.00),
    CLAUDE_SONNET: (3.00, 15.00),
    CLAUDE_OPUS:   (5.00, 25.00),
    **{m: (0.0, 0.0) for m in FREE_MODELS},
}

# task_type → (primary model, premium model)
TASK_MODEL_MAP: Dict[str, Tuple[str, str]] = {
    "planning":   (CLAUDE_HAIKU,  CLAUDE_SONNET),
    "structured": (CLAUDE_HAIKU,  CLAUDE_HAIKU),
    "general":    (CLAUDE_HAIKU,  CLAUDE_SONNET),
    "analysis":   (CLAUDE_SONNET, CLAUDE_SONNET),
    "web":        (CLAUDE_HAIKU,  CLAUDE_SONNET),
    "code":       (CLAUDE_SONNET, CLAUDE_OPUS),
    "writing":    (CLAUDE_SONNET, CLAUDE_OPUS),
    "synthesis":  (CLAUDE_SONNET, CLAUDE_OPUS),
    "delivery":   (CLAUDE_SONNET, CLAUDE_OPUS),
}

# Rate-limit retry config
_RETRY_WAIT_1  = 15.0   # wait before retry on same model
_RETRY_WAIT_2  = 30.0   # wait before second retry
_FALLBACK_WAIT =  5.0   # wait before trying free fallback
_MAX_TOTAL_WAIT = 120.0
_JITTER_RANGE  =   3.0
_GLOBAL_MIN_INTERVAL = 0.5  # seconds between calls (Claude has generous RPM)


def _jitter(base: float, cap: float = 60.0) -> float:
    return min(base + random.uniform(0, _JITTER_RANGE), cap)


def infer_quality(
    step_description: str,
    goal: str = "",
    is_final_step: bool = False,
    task_type: str = "general",
    has_budget: bool = False,
) -> ModelQuality:
    """Return model quality tier for a step."""
    desc_lower = step_description.lower()

    _premium_kw = frozenset({
        "write", "draft", "compose", "ebook", "guide", "report",
        "article", "chapter", "essay", "synthesize", "deliver",
        "final answer", "comprehensive", "professional",
    })
    _writing_goal_kw = frozenset({
        "write", "ebook", "book", "guide", "report", "article",
        "document", "essay",
    })

    if task_type in ("writing", "synthesis", "delivery"):
        return ModelQuality.PREMIUM

    if is_final_step and any(k in desc_lower for k in (
        "deliver", "final", "synthesize", "compile", "write",
        "produce", "generate", "compose", "draft", "complete",
    )):
        return ModelQuality.PREMIUM

    if any(k in desc_lower for k in _premium_kw):
        return ModelQuality.PREMIUM

    if any(k in goal.lower() for k in _writing_goal_kw):
        return ModelQuality.BALANCED

    return ModelQuality.FREE


class OpenRouterClient:
    """
    Async OpenRouter client that routes to Claude models by default.

    Strategy:
    1. Try the appropriate Claude model (Haiku/Sonnet/Opus).
    2. On 429 → wait briefly, retry same model.
    3. On persistent 429 or 5xx → try a free fallback model.
    4. Free fallback models rotate on failure.
    """

    def __init__(self, max_concurrent: int = 3) -> None:
        self._session_cost: float = 0.0
        self._base_url = settings.openrouter_base_url
        self._api_key = settings.openrouter_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        self._model_backoff: Dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_call_time: float = 0.0
        self._call_lock = asyncio.Lock()

    @property
    def session_cost(self) -> float:
        return self._session_cost

    def get_free_models(self) -> List[str]:
        return list(FREE_MODELS)

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, (0.001, 0.001))
        return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000

    def _pick_claude_model(self, task_type: str, quality: ModelQuality) -> str:
        primary, premium = TASK_MODEL_MAP.get(task_type, TASK_MODEL_MAP["general"])
        if quality == ModelQuality.PREMIUM:
            return premium
        if quality == ModelQuality.BALANCED:
            # Use Sonnet for balanced tasks
            return CLAUDE_SONNET
        return primary  # Haiku for FREE/general

    def _available_free_models(self) -> List[str]:
        now = time.monotonic()
        available = [m for m in FREE_MODELS if self._model_backoff.get(m, 0) <= now]
        if available:
            random.shuffle(available)
            return available
        return list(FREE_MODELS)

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        task_type: str = "general",
        quality: ModelQuality = ModelQuality.FREE,
        force_free: bool = False,
        max_budget: Optional[float] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> Tuple[str, str, float]:
        if force_free:
            quality = ModelQuality.FREE

        return await self._call_with_fallback(
            messages=messages,
            task_type=task_type,
            quality=quality,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    async def _call_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        task_type: str,
        quality: ModelQuality,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")

        claude_model = self._pick_claude_model(task_type, quality)
        last_exc: Exception = RuntimeError("No models available")
        total_waited = 0.0

        # ── Try Claude model (primary) ──────────────────────────────────────
        # Attempt 1: immediate
        # Attempt 2: after short wait (15s)
        # Attempt 3: after another wait (30s)
        claude_schedule = [
            (claude_model, 0.0),
            (claude_model, _RETRY_WAIT_1),
            (claude_model, _RETRY_WAIT_2),
        ]

        for model, pre_wait in claude_schedule:
            if pre_wait > 0:
                wait = _jitter(pre_wait)
                logger.info(
                    "Claude rate-limited — waiting %.0fs before retry (model=%s)",
                    wait, model,
                )
                await asyncio.sleep(wait)
                total_waited += wait

            now = time.monotonic()
            remaining = self._model_backoff.get(model, 0) - now
            if remaining > 0 and pre_wait == 0:
                # Model is in backoff from a previous request — skip to free fallback
                logger.info("Claude model %s in backoff (%.0fs) — trying free fallback", model, remaining)
                break

            try:
                result = await self._single_call(model, messages, temperature, max_tokens, json_mode)
                return result
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    retry_after_raw = exc.response.headers.get("Retry-After", "")
                    try:
                        hint = float(retry_after_raw)
                    except (ValueError, TypeError):
                        hint = 30.0
                    self._model_backoff[model] = time.monotonic() + hint
                    logger.warning("429 on Claude %s (Retry-After=%.0fs)", model, hint)
                    last_exc = exc
                    continue
                elif status in (401, 402, 403):
                    logger.warning("HTTP %d on Claude model %s — falling back to free", status, model)
                    last_exc = exc
                    break  # don't retry paid model on auth/billing errors
                logger.warning("HTTP %d from %s: %s", status, model, exc.response.text[:200])
                last_exc = exc
            except Exception as exc:
                logger.warning("Error on Claude model %s: %s", model, exc)
                last_exc = exc

        # ── Fallback to free models ────────────────────────────────────────
        logger.info("Falling back to free models after Claude failure")
        await asyncio.sleep(_jitter(_FALLBACK_WAIT))

        for free_model in self._available_free_models()[:3]:
            try:
                result = await self._single_call(free_model, messages, temperature, max_tokens, json_mode)
                logger.info("Free model %s succeeded as fallback", free_model)
                return result
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    self._model_backoff[free_model] = time.monotonic() + 60.0
                logger.warning("Free model %s failed (HTTP %d)", free_model, status)
                last_exc = exc
            except Exception as exc:
                logger.warning("Free model %s error: %s", free_model, exc)
                last_exc = exc

        raise last_exc

    async def _single_call(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        async with self._semaphore:
            async with self._call_lock:
                now = time.monotonic()
                gap = _GLOBAL_MIN_INTERVAL - (now - self._last_call_time)
                if gap > 0:
                    await asyncio.sleep(gap)
                self._last_call_time = time.monotonic()

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            )
        resp.raise_for_status()

        data = resp.json()
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        choice = data["choices"][0]
        text = choice["message"]["content"] or ""

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        actual_model = data.get("model", model)
        cost = self.estimate_cost(actual_model, input_tokens, output_tokens)
        self._session_cost += cost

        self._model_backoff.pop(actual_model, None)

        logger.info(
            "OpenRouter [%s] tokens=%d+%d cost=$%.6f latency=%dms",
            actual_model, input_tokens, output_tokens, cost, elapsed_ms,
        )
        return text, actual_model, cost

    async def reset_session_cost(self) -> None:
        self._session_cost = 0.0


# ── Singletons ──────────────────────────────────────────────────────────────
# Main client — higher concurrency since Claude has better rate limits
openrouter_client = OpenRouterClient(max_concurrent=3)

# Background client for skill researcher / heartbeat
background_openrouter_client = OpenRouterClient(max_concurrent=1)
