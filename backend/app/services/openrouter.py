from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

FREE_MODELS: List[str] = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

# Cost per 1 million tokens (input, output) in USD
MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    "openai/gpt-4o": (5.0, 15.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-3.5-turbo": (0.50, 1.50),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "google/gemini-pro-1.5": (1.25, 5.00),
    "mistralai/mixtral-8x7b-instruct": (0.27, 0.27),
    "meta-llama/llama-3.1-8b-instruct": (0.055, 0.055),
    "meta-llama/llama-3.1-70b-instruct": (0.52, 0.75),
    # Free models have zero cost
    **{m: (0.0, 0.0) for m in FREE_MODELS},
}

# Task type → preferred model
TASK_MODEL_MAP: Dict[str, str] = {
    "planning": "google/gemma-3-27b-it:free",
    "web": "meta-llama/llama-3.3-70b-instruct:free",
    "code": "deepseek/deepseek-r1:free",
    "analysis": "qwen/qwen-2.5-72b-instruct:free",
    "general": "meta-llama/llama-3.3-70b-instruct:free",
    "structured": "mistralai/mistral-7b-instruct:free",
}

# 429 backoff: first retry waits this many seconds, doubling each time
_429_BASE_WAIT = 8.0
_429_MAX_WAIT = 90.0
# Minimum gap between API calls (ms) to avoid burst rate limits
_MIN_CALL_INTERVAL_MS = 500


class OpenRouterClient:
    """Async OpenRouter API client with intelligent model routing and cost tracking."""

    def __init__(self) -> None:
        self._session_cost: float = 0.0
        self._base_url = settings.openrouter_base_url
        self._api_key = settings.openrouter_api_key
        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        # Per-model rate-limit backoff: model → earliest_retry_time (monotonic)
        self._model_backoff: Dict[str, float] = {}
        # Serialize all outbound requests to avoid burst 429s
        self._request_lock = asyncio.Lock()
        self._last_call_time: float = 0.0

    # ── Public helpers ──────────────────────────────────────────────────────

    def get_free_models(self) -> List[str]:
        return list(FREE_MODELS)

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        costs = MODEL_COSTS.get(model, (0.001, 0.001))
        return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000

    @property
    def session_cost(self) -> float:
        return self._session_cost

    def _available_free_models(self) -> List[str]:
        """Return free models ordered by earliest availability."""
        now = time.monotonic()
        available = [m for m in FREE_MODELS if self._model_backoff.get(m, 0) <= now]
        if available:
            return available
        # All rate-limited – return the one with the soonest retry time
        return sorted(FREE_MODELS, key=lambda m: self._model_backoff.get(m, 0))

    def _pick_model(
        self,
        task_type: str,
        force_free: bool = False,
        max_budget: Optional[float] = None,
    ) -> str:
        prefer_free = force_free or settings.openrouter_prefer_free
        if prefer_free:
            preferred = TASK_MODEL_MAP.get(task_type, FREE_MODELS[1])
            now = time.monotonic()
            if self._model_backoff.get(preferred, 0) <= now:
                return preferred
            # Preferred model is rate-limited; pick another available free model
            available = self._available_free_models()
            return available[0]

        # If budget is tight, use free model
        remaining = (max_budget or settings.openrouter_max_budget_usd) - self._session_cost
        if remaining <= 0.01:
            logger.info("Budget nearly exhausted (%.4f remaining), using free model", remaining)
            available = self._available_free_models()
            return available[0]

        return TASK_MODEL_MAP.get(task_type, settings.openrouter_default_model)

    # ── Core completion ─────────────────────────────────────────────────────

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        task_type: str = "general",
        force_free: bool = False,
        max_budget: Optional[float] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> Tuple[str, str, float]:
        """
        Call the OpenRouter chat completion endpoint.

        Returns:
            (response_text, model_used, cost_usd)
        """
        model = self._pick_model(task_type, force_free, max_budget)
        return await self._call_with_rotation(
            messages=messages,
            preferred_model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    # ── Internal ────────────────────────────────────────────────────────────

    async def _call_with_rotation(
        self,
        messages: List[Dict[str, Any]],
        preferred_model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """
        Try the preferred model first, then rotate through all free models on 429.
        Each 429 triggers a per-model backoff so future calls skip that model.
        """
        if not self._api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. "
                "Please set the environment variable."
            )

        # Build ordered candidate list: preferred first, then other free models
        candidates: List[str] = [preferred_model]
        for m in FREE_MODELS:
            if m != preferred_model:
                candidates.append(m)

        last_exc: Exception = RuntimeError("No models available")

        for attempt_idx, model in enumerate(candidates):
            # Wait out any existing backoff for this model
            now = time.monotonic()
            backoff_until = self._model_backoff.get(model, 0)
            if backoff_until > now:
                wait_secs = backoff_until - now
                logger.info(
                    "Model %s is rate-limited, waiting %.1fs before trying", model, wait_secs
                )
                await asyncio.sleep(wait_secs)

            try:
                return await self._single_call(model, messages, temperature, max_tokens, json_mode)

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code

                if status == 429:
                    # Parse Retry-After header if present
                    retry_after_raw = exc.response.headers.get("Retry-After", "")
                    try:
                        retry_after = float(retry_after_raw)
                    except (ValueError, TypeError):
                        retry_after = min(_429_BASE_WAIT * (2 ** attempt_idx), _429_MAX_WAIT)

                    self._model_backoff[model] = time.monotonic() + retry_after
                    logger.warning(
                        "429 rate-limit on model %s — backoff %.1fs, rotating to next model",
                        model,
                        retry_after,
                    )
                    last_exc = exc
                    continue  # try next model

                # Non-429 HTTP error: try next free model only if not already tried all
                logger.warning("HTTP %d from model %s: %s", status, model, exc.response.text[:200])
                last_exc = exc
                if attempt_idx < len(candidates) - 1:
                    continue
                raise

            except Exception as exc:
                logger.warning("Error calling model %s: %s", model, exc)
                last_exc = exc
                if attempt_idx < len(candidates) - 1:
                    continue
                raise

        raise last_exc

    async def _single_call(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """Execute one HTTP call, serialized and rate-gap enforced."""
        async with self._request_lock:
            # Enforce minimum interval between requests
            now = time.monotonic()
            gap = _MIN_CALL_INTERVAL_MS / 1000.0
            elapsed_since_last = now - self._last_call_time
            if elapsed_since_last < gap:
                await asyncio.sleep(gap - elapsed_since_last)

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

            self._last_call_time = time.monotonic()
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

        # Clear any backoff for a successfully responding model
        self._model_backoff.pop(actual_model, None)

        logger.debug(
            "OpenRouter [%s] tokens=%d+%d cost=$%.6f latency=%dms",
            actual_model,
            input_tokens,
            output_tokens,
            cost,
            elapsed_ms,
        )

        return text, actual_model, cost

    async def reset_session_cost(self) -> None:
        self._session_cost = 0.0


# Singleton
openrouter_client = OpenRouterClient()
