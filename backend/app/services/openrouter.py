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

    def _pick_model(
        self,
        task_type: str,
        force_free: bool = False,
        max_budget: Optional[float] = None,
    ) -> str:
        prefer_free = force_free or settings.openrouter_prefer_free
        if prefer_free:
            return TASK_MODEL_MAP.get(task_type, FREE_MODELS[1])

        # If budget is tight, use free model
        remaining = (max_budget or settings.openrouter_max_budget_usd) - self._session_cost
        if remaining <= 0.01:
            logger.info("Budget nearly exhausted (%.4f remaining), using free model", remaining)
            return TASK_MODEL_MAP.get(task_type, FREE_MODELS[1])

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
        return await self._call(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            fallback_to_free=True,
        )

    # ── Internal ────────────────────────────────────────────────────────────

    async def _call(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        fallback_to_free: bool = True,
    ) -> Tuple[str, str, float]:
        if not self._api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. "
                "Please set the environment variable."
            )

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "OpenRouter %s returned %d for model %s: %s",
                exc.request.url,
                exc.response.status_code,
                model,
                exc.response.text[:200],
            )
            if fallback_to_free and model not in FREE_MODELS:
                fallback = FREE_MODELS[1]
                logger.info("Falling back to free model: %s", fallback)
                return await self._call(
                    messages=messages,
                    model=fallback,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    fallback_to_free=False,
                )
            raise
        except Exception:
            if fallback_to_free and model not in FREE_MODELS:
                fallback = FREE_MODELS[1]
                logger.info("OpenRouter error – falling back to free model: %s", fallback)
                return await self._call(
                    messages=messages,
                    model=fallback,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    fallback_to_free=False,
                )
            raise

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Parse response
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""

        # Cost tracking
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        actual_model = data.get("model", model)
        cost = self.estimate_cost(actual_model, input_tokens, output_tokens)
        self._session_cost += cost

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
