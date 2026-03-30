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

# ---------------------------------------------------------------------------
# Model quality tiers
# ---------------------------------------------------------------------------

class ModelQuality(str, Enum):
    FREE     = "free"       # Routing, tool-input building, lightweight checks
    BALANCED = "balanced"   # Research, analysis, intermediate reasoning
    PREMIUM  = "premium"    # Writing, synthesis, final delivery, complex code


# Free models — zero cost, rotated on 429
FREE_MODELS: List[str] = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

# Premium models — best output quality for deliverables
PREMIUM_MODELS: List[str] = [
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku",
    "google/gemini-flash-1.5",
]

# Cost per 1 million tokens (input, output) in USD
MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    "openai/gpt-4o":                    (5.00,  15.00),
    "openai/gpt-4o-mini":               (0.15,   0.60),
    "openai/gpt-3.5-turbo":             (0.50,   1.50),
    "anthropic/claude-3.5-sonnet":      (3.00,  15.00),
    "anthropic/claude-3-haiku":         (0.25,   1.25),
    "google/gemini-pro-1.5":            (1.25,   5.00),
    "google/gemini-flash-1.5":          (0.075,  0.30),
    "mistralai/mixtral-8x7b-instruct":  (0.27,   0.27),
    "meta-llama/llama-3.1-8b-instruct": (0.055,  0.055),
    "meta-llama/llama-3.1-70b-instruct":(0.52,   0.75),
    **{m: (0.0, 0.0) for m in FREE_MODELS},
}

# Task type → (free model, premium model)
TASK_MODEL_MAP: Dict[str, Tuple[str, str]] = {
    "planning":   ("google/gemma-3-27b-it:free",              "anthropic/claude-3.5-sonnet"),
    "web":        ("meta-llama/llama-3.3-70b-instruct:free",  "openai/gpt-4o-mini"),
    "code":       ("deepseek/deepseek-r1:free",               "anthropic/claude-3.5-sonnet"),
    "analysis":   ("qwen/qwen-2.5-72b-instruct:free",         "openai/gpt-4o-mini"),
    "writing":    ("meta-llama/llama-3.3-70b-instruct:free",  "anthropic/claude-3.5-sonnet"),
    "synthesis":  ("qwen/qwen-2.5-72b-instruct:free",         "anthropic/claude-3.5-sonnet"),
    "delivery":   ("meta-llama/llama-3.3-70b-instruct:free",  "anthropic/claude-3.5-sonnet"),
    "general":    ("meta-llama/llama-3.3-70b-instruct:free",  "openai/gpt-4o-mini"),
    "structured": ("mistralai/mistral-7b-instruct:free",      "openai/gpt-4o-mini"),
}

# Keywords that signal premium-quality output is needed
_PREMIUM_KEYWORDS = frozenset({
    "write", "writing", "written", "author", "compose", "composing",
    "draft", "drafting", "create content", "generate content",
    "ebook", "e-book", "book", "guide", "manual", "tutorial",
    "report", "article", "chapter", "document", "essay",
    "synthesize", "synthesis", "compile", "assemble", "finalize",
    "deliver", "final answer", "final result", "complete guide",
    "professional", "comprehensive", "detailed analysis",
    "sell", "product", "publish",
})

_PREMIUM_GOAL_KEYWORDS = frozenset({
    "write", "ebook", "e-book", "book", "guide", "report", "article",
    "document", "essay", "paper", "whitepaper", "course", "curriculum",
    "sell", "publish", "professional",
})

# Rate-limit constants
_429_BASE_WAIT    = 10.0    # base seconds for first 429
_429_MAX_WAIT     = 120.0   # hard cap per backoff
_MAX_TOTAL_WAIT   = 300.0   # if we've waited this long total, give up
_JITTER_RANGE     = 3.0     # ±seconds of random jitter added to every backoff
# Max concurrent LLM calls across the system — prevents thundering-herd 429s
_MAX_CONCURRENT   = 3


def _jitter(base: float, max_val: float = _429_MAX_WAIT) -> float:
    """Apply capped exponential value + random jitter."""
    return min(base + random.uniform(0, _JITTER_RANGE), max_val)


def infer_quality(
    step_description: str,
    goal: str = "",
    is_final_step: bool = False,
    task_type: str = "general",
) -> ModelQuality:
    desc_lower = step_description.lower()
    goal_lower = goal.lower()

    if task_type in ("writing", "synthesis", "delivery"):
        return ModelQuality.PREMIUM

    if is_final_step and any(k in desc_lower for k in (
        "deliver", "final", "synthesize", "compile", "write", "create",
        "produce", "generate", "compose", "draft", "complete",
    )):
        return ModelQuality.PREMIUM

    if any(k in desc_lower for k in _PREMIUM_KEYWORDS):
        return ModelQuality.PREMIUM

    if any(k in goal_lower for k in _PREMIUM_GOAL_KEYWORDS):
        return ModelQuality.BALANCED

    return ModelQuality.FREE


class OpenRouterClient:
    """
    Async OpenRouter API client with quality-tier routing and robust 429 handling.

    Key improvements over naïve retry:
    - Global semaphore caps concurrent in-flight requests (prevents pile-ups)
    - Per-model backoff dictionary tracks each model's cooldown independently
    - When ALL models are rate-limited, waits for the soonest-available one
      instead of raising immediately after N attempts
    - Exponential backoff + jitter prevents thundering-herd re-429s
    - Background service clients can be created as separate instances so they
      don't compete with main task execution
    """

    def __init__(self, max_concurrent: int = _MAX_CONCURRENT) -> None:
        self._session_cost: float = 0.0
        self._base_url = settings.openrouter_base_url
        self._api_key = settings.openrouter_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        # Per-model: monotonic timestamp when backoff expires
        self._model_backoff: Dict[str, float] = {}
        # Global concurrency gate — prevents thundering-herd 429s
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # Per-model last-call time (for minimum spacing)
        self._model_last_call: Dict[str, float] = {}
        # Minimum ms between calls to the same model
        self._min_model_interval = 0.8  # seconds

    # ── Public helpers ──────────────────────────────────────────────────────

    def get_free_models(self) -> List[str]:
        return list(FREE_MODELS)

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, (0.001, 0.001))
        return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000

    @property
    def session_cost(self) -> float:
        return self._session_cost

    def _soonest_available_free(self) -> Tuple[str, float]:
        """Return (model, wait_seconds) for the free model available soonest."""
        now = time.monotonic()
        best_model = FREE_MODELS[0]
        best_wait = max(0.0, self._model_backoff.get(FREE_MODELS[0], 0) - now)
        for m in FREE_MODELS[1:]:
            w = max(0.0, self._model_backoff.get(m, 0) - now)
            if w < best_wait:
                best_wait, best_model = w, m
        return best_model, best_wait

    def _available_free_models(self) -> List[str]:
        now = time.monotonic()
        available = [m for m in FREE_MODELS if self._model_backoff.get(m, 0) <= now]
        if available:
            # Shuffle to distribute load
            random.shuffle(available)
            return available
        # All rate-limited: return sorted by soonest available
        return sorted(FREE_MODELS, key=lambda m: self._model_backoff.get(m, 0))

    def _pick_model(self, task_type: str, quality: ModelQuality, max_budget: Optional[float] = None) -> str:
        remaining = (max_budget or settings.openrouter_max_budget_usd) - self._session_cost
        budget_tight = remaining <= 0.05

        free_model, premium_model = TASK_MODEL_MAP.get(task_type, TASK_MODEL_MAP["general"])

        if quality == ModelQuality.FREE or budget_tight:
            now = time.monotonic()
            if self._model_backoff.get(free_model, 0) <= now:
                return free_model
            return self._available_free_models()[0]

        if quality == ModelQuality.BALANCED:
            best_free = "meta-llama/llama-3.3-70b-instruct:free"
            now = time.monotonic()
            if self._model_backoff.get(best_free, 0) <= now:
                return best_free
            return self._available_free_models()[0]

        # PREMIUM
        if not self._api_key:
            logger.warning("No API key; falling back to free model for premium task")
            return self._available_free_models()[0]
        return premium_model

    # ── Core completion ─────────────────────────────────────────────────────

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

        model = self._pick_model(task_type, quality, max_budget)
        logger.info("Model selected: %s (quality=%s, task=%s)", model, quality.value, task_type)

        return await self._call_with_rotation(
            messages=messages,
            preferred_model=model,
            quality=quality,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    # ── Internal ────────────────────────────────────────────────────────────

    async def _call_with_rotation(
        self,
        messages: List[Dict[str, Any]],
        preferred_model: str,
        quality: ModelQuality,
        task_type: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        if not self._api_key:
            raise ValueError("OPENROUTER_API_KEY is not set.")

        # Build ordered candidate list
        if quality == ModelQuality.PREMIUM:
            _, premium_model = TASK_MODEL_MAP.get(task_type, TASK_MODEL_MAP["general"])
            candidates = [preferred_model]
            for m in PREMIUM_MODELS:
                if m != preferred_model:
                    candidates.append(m)
            candidates.extend(self._available_free_models())
        else:
            # Free/balanced: rotate through all free models
            candidates = [preferred_model] + [m for m in FREE_MODELS if m != preferred_model]

        last_exc: Exception = RuntimeError("No models available")
        total_waited = 0.0

        for attempt_idx, model in enumerate(candidates):
            # Check / honour per-model backoff
            now = time.monotonic()
            backoff_until = self._model_backoff.get(model, 0)
            if backoff_until > now:
                wait_secs = _jitter(backoff_until - now)
                if total_waited + wait_secs > _MAX_TOTAL_WAIT:
                    # Skip this model — too long to wait, try the next
                    logger.debug("Skipping %s (backoff too long: %.1fs)", model, wait_secs)
                    continue
                logger.info("Model %s cooling down, waiting %.1fs (attempt %d)", model, wait_secs, attempt_idx + 1)
                await asyncio.sleep(wait_secs)
                total_waited += wait_secs

            try:
                result = await self._single_call(model, messages, temperature, max_tokens, json_mode)
                if quality == ModelQuality.PREMIUM and model in FREE_MODELS:
                    logger.warning("Premium task used free model %s (premium unavailable)", model)
                return result

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429:
                    retry_after_raw = exc.response.headers.get("Retry-After", "")
                    try:
                        retry_after = float(retry_after_raw)
                    except (ValueError, TypeError):
                        retry_after = min(_429_BASE_WAIT * (2 ** attempt_idx), _429_MAX_WAIT)

                    backoff = _jitter(retry_after)
                    self._model_backoff[model] = time.monotonic() + backoff
                    logger.warning("429 on %s → backoff %.1fs, rotating to next model", model, backoff)
                    last_exc = exc
                    continue

                elif status in (401, 402, 403):
                    logger.warning("HTTP %d on %s → skip (auth/billing)", status, model)
                    last_exc = exc
                    continue

                logger.warning("HTTP %d from %s: %s", status, model, exc.response.text[:200])
                last_exc = exc
                if attempt_idx < len(candidates) - 1:
                    continue
                raise

            except Exception as exc:
                logger.warning("Error calling %s: %s", model, exc)
                last_exc = exc
                if attempt_idx < len(candidates) - 1:
                    continue
                raise

        # All candidates exhausted — wait for soonest available free model and retry once
        soonest_model, soonest_wait = self._soonest_available_free()
        if soonest_wait > 0 and total_waited + soonest_wait <= _MAX_TOTAL_WAIT:
            wait_with_jitter = _jitter(soonest_wait)
            logger.info(
                "All models rate-limited. Waiting %.1fs for %s to recover…",
                wait_with_jitter, soonest_model,
            )
            await asyncio.sleep(wait_with_jitter)
            # Single final attempt
            try:
                return await self._single_call(soonest_model, messages, temperature, max_tokens, json_mode)
            except Exception as exc:
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
        """Make a single HTTP call to OpenRouter, gated by the global semaphore."""
        async with self._semaphore:
            # Enforce per-model minimum interval
            now = time.monotonic()
            last = self._model_last_call.get(model, 0)
            gap = self._min_model_interval - (now - last)
            if gap > 0:
                await asyncio.sleep(gap)

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
            self._model_last_call[model] = time.monotonic()
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

        # Clear backoff on success
        self._model_backoff.pop(actual_model, None)

        logger.info(
            "OpenRouter [%s] tokens=%d+%d cost=$%.6f latency=%dms",
            actual_model, input_tokens, output_tokens, cost, elapsed_ms,
        )
        return text, actual_model, cost

    async def reset_session_cost(self) -> None:
        self._session_cost = 0.0


# ── Singletons ──────────────────────────────────────────────────────────────

# Main client used by task executor
openrouter_client = OpenRouterClient(max_concurrent=3)

# Dedicated low-priority client for background services (skill researcher, heartbeat).
# Separate instance = separate semaphore = never competes with task execution.
background_openrouter_client = OpenRouterClient(max_concurrent=1)
