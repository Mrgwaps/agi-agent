"""
Multi-provider LLM client — OpenRouter + HuggingFace in parallel.

Tier strategy:
  FREE     → Race top OR free models + HF fast models simultaneously.
             First response wins; totally separate rate-limit quotas.
  BALANCED → Claude Haiku (paid, reliable). Falls back to parallel race.
  PREMIUM  → Claude Sonnet (paid). Falls back to HF 70B models.

With both providers racing, 429s on one don't stall the pipeline —
the other provider's response arrives in seconds.
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


# ── OpenRouter paid models ──────────────────────────────────────────────────
CLAUDE_HAIKU  = "anthropic/claude-haiku-4-5"
CLAUDE_SONNET = "anthropic/claude-sonnet-4-6"
CLAUDE_OPUS   = "anthropic/claude-opus-4-6"

# ── OpenRouter free models (priority order) ─────────────────────────────────
OR_FREE_MODELS: List[str] = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

# ── HuggingFace serverless inference models ─────────────────────────────────
# Fast models for FREE tier — race these against OpenRouter free models.
HF_BASE_URL = "https://router.huggingface.co/v1"

HF_FREE_MODELS: List[str] = [
    "meta-llama/Meta-Llama-3.1-8B-Instruct",   # fast, reliable
    "Qwen/Qwen2.5-7B-Instruct",                 # fast, efficient
    "microsoft/Phi-3.5-mini-instruct",           # very fast small model
    "mistralai/Mistral-7B-Instruct-v0.3",        # solid fallback
]

# Capable HF models for BALANCED/PREMIUM fallback
HF_BALANCED_MODELS: List[str] = [
    "meta-llama/Llama-3.3-70B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
]

# ── Cost tracking ────────────────────────────────────────────────────────────
MODEL_COSTS: Dict[str, Tuple[float, float]] = {
    CLAUDE_HAIKU:  (1.00,  5.00),
    CLAUDE_SONNET: (3.00, 15.00),
    CLAUDE_OPUS:   (5.00, 25.00),
    **{m: (0.0, 0.0) for m in OR_FREE_MODELS},
    **{m: (0.0, 0.0) for m in HF_FREE_MODELS},
    **{m: (0.0, 0.0) for m in HF_BALANCED_MODELS},
}

# ── Backoff config ───────────────────────────────────────────────────────────
_RETRY_WAIT_1      = 10.0   # wait before first retry on paid model
_RETRY_WAIT_2      = 20.0   # wait before second retry on paid model
_FREE_BACKOFF      = 60.0   # per-model backoff after free model 429
_GLOBAL_MIN_INTERVAL = 0.2  # min gap between call initiations
_RACE_TIMEOUT      = 25.0   # max seconds to wait for any single race call


def _jitter(base: float) -> float:
    return base + random.uniform(0, 2.0)


def infer_quality(
    step_description: str,
    goal: str = "",
    is_final_step: bool = False,
    task_type: str = "general",
    has_budget: bool = False,
) -> ModelQuality:
    """Route a step to the appropriate model quality tier."""
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


class MultiProviderClient:
    """
    Agentic LLM client that races OpenRouter and HuggingFace in parallel.

    For FREE-tier calls, up to 4 models (mix of OR + HF) are launched
    simultaneously. The first successful response is used; the rest are
    cancelled. This gives:
      - Speed: fastest provider wins (usually 1-3s)
      - Resilience: 429 on one provider doesn't stall; the other responds
      - No waiting: never sits idle waiting for a backed-off model
    """

    def __init__(self, max_concurrent: int = 6) -> None:
        self._session_cost: float = 0.0

        # OpenRouter config
        self._or_base_url  = settings.openrouter_base_url
        self._or_api_key   = settings.openrouter_api_key
        self._or_headers   = {
            "Authorization": f"Bearer {self._or_api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title":      settings.openrouter_app_name,
            "Content-Type": "application/json",
        }

        # HuggingFace config
        self._hf_api_key  = settings.huggingface_api_key
        self._hf_headers  = {
            "Authorization": f"Bearer {self._hf_api_key}",
            "Content-Type": "application/json",
        }

        self._or_backoff:  Dict[str, float] = {}
        self._hf_backoff:  Dict[str, float] = {}

        self._semaphore    = asyncio.Semaphore(max_concurrent)
        self._last_call_ts: float = 0.0
        self._rate_lock    = asyncio.Lock()

    # ── Public ───────────────────────────────────────────────────────────────

    @property
    def session_cost(self) -> float:
        return self._session_cost

    def get_free_models(self) -> List[str]:
        return list(OR_FREE_MODELS)

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS.get(model, (0.001, 0.001))
        return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000

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
        return await self._route(messages, quality, temperature, max_tokens, json_mode)

    # ── Routing ──────────────────────────────────────────────────────────────

    async def _route(
        self,
        messages: List[Dict[str, Any]],
        quality: ModelQuality,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        if not self._or_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set in backend/.env")

        if quality == ModelQuality.FREE:
            return await self._race_free(messages, temperature, max_tokens, json_mode)

        # BALANCED: Claude Haiku first, then race on failure
        # PREMIUM:  Claude Sonnet first, then race HF balanced on failure
        paid = CLAUDE_HAIKU if quality == ModelQuality.BALANCED else CLAUDE_SONNET

        now = time.monotonic()
        if self._or_backoff.get(paid, 0) <= now:
            for pre_wait in [0.0, _RETRY_WAIT_1, _RETRY_WAIT_2]:
                if pre_wait:
                    await asyncio.sleep(_jitter(pre_wait))
                try:
                    return await self._call_or(paid, messages, temperature, max_tokens, json_mode)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        try:
                            hint = float(exc.response.headers.get("Retry-After", "20"))
                        except (ValueError, TypeError):
                            hint = 20.0
                        self._or_backoff[paid] = time.monotonic() + hint
                        logger.warning("429 on %s (backoff=%.0fs)", paid, hint)
                        if pre_wait == _RETRY_WAIT_2:
                            break  # exhausted retries
                        continue
                    elif exc.response.status_code in (401, 402, 403):
                        logger.warning("HTTP %d on %s — skipping paid", exc.response.status_code, paid)
                        break
                    raise
                except Exception as exc:
                    logger.warning("%s error: %s", paid, exc)
                    break

        # Paid model failed — race free/balanced models from both providers
        logger.info("%s unavailable, racing fallback models", paid)
        if quality == ModelQuality.PREMIUM:
            return await self._race_balanced_fallback(messages, temperature, max_tokens, json_mode)
        return await self._race_free(messages, temperature, max_tokens, json_mode)

    # ── Race engine ──────────────────────────────────────────────────────────

    async def _race_free(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """
        Launch up to 2 OR free models + up to 2 HF free models in parallel.
        First success wins; losers are cancelled. Falls back to Claude Haiku
        if every model fails.
        """
        now = time.monotonic()
        or_ready  = [m for m in OR_FREE_MODELS  if self._or_backoff.get(m, 0) <= now][:2]
        hf_ready  = (
            [m for m in HF_FREE_MODELS if self._hf_backoff.get(m, 0) <= now][:2]
            if self._hf_api_key else []
        )

        candidates = []
        # Interleave OR and HF so we always start one from each provider
        for or_m, hf_m in zip(or_ready, hf_ready):
            candidates.extend([("or", or_m), ("hf", hf_m)])
        # Add any leftover from the longer list
        for m in or_ready[len(hf_ready):]:
            candidates.append(("or", m))
        for m in hf_ready[len(or_ready):]:
            candidates.append(("hf", m))

        if not candidates:
            # Nothing ready — Claude Haiku as immediate fallback
            logger.info("All free models in backoff — using Claude Haiku")
            return await self._call_or(CLAUDE_HAIKU, messages, temperature, max_tokens, json_mode)

        result = await self._race(candidates, messages, temperature, max_tokens, json_mode)
        if result is not None:
            return result

        # Everything failed — Claude Haiku
        logger.info("All race candidates failed — falling back to Claude Haiku")
        return await self._call_or(CLAUDE_HAIKU, messages, temperature, max_tokens, json_mode)

    async def _race_balanced_fallback(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """Race HF 70B models + Claude Haiku when Sonnet is unavailable."""
        now = time.monotonic()
        hf_ready = (
            [m for m in HF_BALANCED_MODELS if self._hf_backoff.get(m, 0) <= now]
            if self._hf_api_key else []
        )
        candidates = [("hf", m) for m in hf_ready[:2]] + [("or", CLAUDE_HAIKU)]
        result = await self._race(candidates, messages, temperature, max_tokens, json_mode)
        if result is not None:
            return result
        raise RuntimeError("All PREMIUM fallback models failed")

    async def _race(
        self,
        candidates: List[Tuple[str, str]],  # [("or"|"hf", model_id), ...]
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Optional[Tuple[str, str, float]]:
        """
        Launch all candidates in parallel. Return first success, cancel the rest.
        Returns None if all fail.
        """
        async def _guarded(provider: str, model: str) -> Tuple[str, str, float]:
            try:
                if provider == "hf":
                    return await asyncio.wait_for(
                        self._call_hf(model, messages, temperature, max_tokens, json_mode),
                        timeout=_RACE_TIMEOUT,
                    )
                else:
                    return await asyncio.wait_for(
                        self._call_or(model, messages, temperature, max_tokens, json_mode),
                        timeout=_RACE_TIMEOUT,
                    )
            except asyncio.TimeoutError:
                logger.warning("%s/%s timed out after %.0fs", provider, model, _RACE_TIMEOUT)
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    try:
                        hint = float(exc.response.headers.get("Retry-After", str(_FREE_BACKOFF)))
                    except (ValueError, TypeError):
                        hint = _FREE_BACKOFF
                    if provider == "hf":
                        self._hf_backoff[model] = time.monotonic() + hint
                    else:
                        self._or_backoff[model] = time.monotonic() + hint
                    logger.debug("%s/%s 429 — backoff %.0fs", provider, model, hint)
                raise

        tasks: Dict[asyncio.Task, Tuple[str, str]] = {
            asyncio.create_task(_guarded(p, m)): (p, m)
            for p, m in candidates
        }

        pending = set(tasks)
        winner  = None

        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    p, m = tasks[task]
                    if task.exception() is None:
                        winner = task.result()
                        logger.info("Race won by %s/%s", p, m)
                        return winner
                    else:
                        logger.debug("Race candidate %s/%s failed: %s", p, m, task.exception())
        finally:
            for t in pending:
                t.cancel()
            # Let cancelled tasks finish cleanly
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        return None  # all failed

    # ── Provider-specific calls ───────────────────────────────────────────────

    async def _call_or(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """Single call to OpenRouter."""
        await self._throttle()
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._or_base_url}/chat/completions",
                headers=self._or_headers,
                json=payload,
            )
        resp.raise_for_status()
        return self._parse_response(resp.json(), model, t0, "OR")

    async def _call_hf(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> Tuple[str, str, float]:
        """Single call to HuggingFace serverless inference."""
        if not self._hf_api_key:
            raise RuntimeError("HF_API_KEY not configured")

        await self._throttle()
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # HF doesn't support json_mode the same way — skip it

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{HF_BASE_URL}/chat/completions",
                headers=self._hf_headers,
                json=payload,
            )
        resp.raise_for_status()
        return self._parse_response(resp.json(), model, t0, "HF")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _throttle(self) -> None:
        """Enforce a minimum interval between call initiations."""
        async with self._semaphore:
            async with self._rate_lock:
                now = time.monotonic()
                gap = _GLOBAL_MIN_INTERVAL - (now - self._last_call_ts)
                if gap > 0:
                    await asyncio.sleep(gap)
                self._last_call_ts = time.monotonic()

    def _parse_response(
        self,
        data: Dict[str, Any],
        model: str,
        t0: float,
        provider: str,
    ) -> Tuple[str, str, float]:
        elapsed_ms   = int((time.monotonic() - t0) * 1000)
        choice       = data["choices"][0]
        text         = choice["message"]["content"] or ""
        usage        = data.get("usage", {})
        in_tok       = usage.get("prompt_tokens", 0)
        out_tok      = usage.get("completion_tokens", 0)
        actual_model = data.get("model", model)
        cost         = self.estimate_cost(actual_model, in_tok, out_tok)
        self._session_cost += cost
        # Clear any backoff on success
        self._or_backoff.pop(actual_model, None)
        self._hf_backoff.pop(actual_model, None)
        logger.info(
            "[%s/%s] tokens=%d+%d cost=$%.6f latency=%dms",
            provider, actual_model, in_tok, out_tok, cost, elapsed_ms,
        )
        return text, actual_model, cost

    async def reset_session_cost(self) -> None:
        self._session_cost = 0.0


# ── Backwards-compat alias so existing code that imports OpenRouterClient works
OpenRouterClient = MultiProviderClient


# ── Singletons ────────────────────────────────────────────────────────────────
openrouter_client            = MultiProviderClient(max_concurrent=6)
background_openrouter_client = MultiProviderClient(max_concurrent=2)
