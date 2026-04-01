"""
OpenRouter client — tiered model routing.

FREE tier     → Gemini Flash / Gemma free models (no credits needed, fast)
BALANCED tier → Claude Haiku (cheap paid, reliable)
PREMIUM tier  → Claude Sonnet (capable paid)

Free models are tried in priority order; each gets its own backoff so a
429 on one model doesn't block the others.
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

# ── Free models — priority order (fastest/most capable first) ──────────────
# These are used for FREE tier AND as fallback when paid models fail.
FREE_MODELS: List[str] = [
    "google/gemini-2.0-flash-exp:free",       # fast, high quality, best first
    "google/gemma-3-27b-it:free",             # capable Gemma
    "google/gemma-3-12b-it:free",             # smaller Gemma, faster
    "meta-llama/llama-3.3-70b-instruct:free", # strong Llama
    "qwen/qwen-2.5-72b-instruct:free",        # strong Qwen
    "meta-llama/llama-3.1-8b-instruct:free",  # fast small model
    "mistralai/mistral-7b-instruct:free",     # lightweight fallback
]

# ── Cost per 1M tokens (input, output) ────────────────────────────────────
MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    CLAUDE_HAIKU:  (1.00,  5.00),
    CLAUDE_SONNET: (3.00, 15.00),
    CLAUDE_OPUS:   (5.00, 25.00),
    **{m: (0.0, 0.0) for m in FREE_MODELS},
}

# ── Tier → (balanced model, premium model) ────────────────────────────────
# FREE quality never uses paid models — goes straight to free models.
# BALANCED uses Claude Haiku (cheap). PREMIUM uses Claude Sonnet.
PAID_MODEL_MAP: Dict[str, Tuple[str, str]] = {
    # quality → (balanced, premium)
    "balanced": (CLAUDE_HAIKU,  CLAUDE_HAIKU),
    "premium":  (CLAUDE_HAIKU,  CLAUDE_SONNET),
}

# Rate-limit retry config
_RETRY_WAIT_1  = 15.0   # wait before retry on same paid model
_RETRY_WAIT_2  = 30.0   # wait before second paid retry
_FREE_BACKOFF  = 65.0   # per-model backoff after free model 429
_JITTER_RANGE  =  3.0
_GLOBAL_MIN_INTERVAL = 0.3  # seconds between calls


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

    if task_type in ("code", "analysis"):
        return ModelQuality.BALANCED

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

    def _pick_paid_model(self, quality: ModelQuality) -> str:
        if quality == ModelQuality.PREMIUM:
            return PAID_MODEL_MAP["premium"][1]   # Claude Sonnet
        return PAID_MODEL_MAP["balanced"][0]       # Claude Haiku

    def _available_free_models(self) -> List[str]:
        """Return free models not currently in backoff, preserving priority order."""
        now = time.monotonic()
        available = [m for m in FREE_MODELS if self._model_backoff.get(m, 0) <= now]
        if available:
            return available
        # All in backoff — find the one whose backoff expires soonest
        return [min(FREE_MODELS, key=lambda m: self._model_backoff.get(m, 0))]

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
            quality=quality,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    async def _call_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        quality: ModelQuality,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")

        last_exc: Exception = RuntimeError("No models available")

        # ── FREE quality: go straight to free models, no paid credits used ──
        if quality == ModelQuality.FREE:
            return await self._try_free_models(messages, temperature, max_tokens, json_mode)

        # ── BALANCED / PREMIUM: try paid Claude first ─────────────────────
        paid_model = self._pick_paid_model(quality)

        for attempt, pre_wait in enumerate([0.0, _RETRY_WAIT_1, _RETRY_WAIT_2]):
            if pre_wait > 0:
                wait = _jitter(pre_wait)
                logger.info("Claude rate-limited — waiting %.0fs (model=%s)", wait, paid_model)
                await asyncio.sleep(wait)

            now = time.monotonic()
            if self._model_backoff.get(paid_model, 0) > now and attempt == 0:
                logger.info("Claude %s in backoff — trying free models first", paid_model)
                break

            try:
                return await self._single_call(paid_model, messages, temperature, max_tokens, json_mode)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    try:
                        hint = float(exc.response.headers.get("Retry-After", "30"))
                    except (ValueError, TypeError):
                        hint = 30.0
                    self._model_backoff[paid_model] = time.monotonic() + hint
                    logger.warning("429 on Claude %s (Retry-After=%.0fs)", paid_model, hint)
                    last_exc = exc
                    continue
                elif status in (401, 402, 403):
                    logger.warning("HTTP %d on Claude %s — falling back to free", status, paid_model)
                    last_exc = exc
                    break
                logger.warning("HTTP %d from %s: %s", status, paid_model, exc.response.text[:200])
                last_exc = exc
            except Exception as exc:
                logger.warning("Claude %s error: %s", paid_model, exc)
                last_exc = exc

        # Claude failed — fall back to free models
        logger.info("Claude failed (%s), falling back to free models", last_exc)
        try:
            return await self._try_free_models(messages, temperature, max_tokens, json_mode)
        except Exception as exc:
            raise last_exc from exc

    async def _try_free_models(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """
        Try each free model in priority order. On 429, mark that model as
        backed off and immediately try the next one — no sleeping between models.
        """
        last_exc: Exception = RuntimeError("All free models failed")

        candidates = self._available_free_models()
        for model in candidates:
            # If model is in backoff, wait until it clears (or skip if another is available)
            now = time.monotonic()
            wait_until = self._model_backoff.get(model, 0)
            if wait_until > now:
                remaining = wait_until - now
                other_available = [m for m in FREE_MODELS
                                   if m != model and self._model_backoff.get(m, 0) <= now]
                if other_available:
                    continue  # skip, another model is ready
                logger.info("All free models in backoff; waiting %.0fs for %s", remaining, model)
                await asyncio.sleep(min(remaining, _FREE_BACKOFF) + _jitter(0))

            try:
                result = await self._single_call(model, messages, temperature, max_tokens, json_mode)
                logger.info("Free model %s succeeded", model)
                return result
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    try:
                        hint = float(exc.response.headers.get("Retry-After", str(_FREE_BACKOFF)))
                    except (ValueError, TypeError):
                        hint = _FREE_BACKOFF
                    self._model_backoff[model] = time.monotonic() + hint
                    logger.warning("Free model %s 429 (backoff=%.0fs) — trying next", model, hint)
                else:
                    logger.warning("Free model %s HTTP %d", model, status)
                last_exc = exc
            except Exception as exc:
                logger.warning("Free model %s error: %s", model, exc)
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
