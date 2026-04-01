"""
Direct Anthropic / Claude API client.

When ANTHROPIC_API_KEY is set this is the primary LLM provider — it is
faster, more reliable, and has no free-tier rate-limit grinding.

Model tier mapping (cheapest → most capable):
  FREE  → claude-haiku-4-5    ($1/$5  per 1M tokens)  — routing, JSON, quick Q&A
  BALANCED → claude-sonnet-4-6 ($3/$15 per 1M tokens)  — research, analysis
  PREMIUM  → claude-opus-4-6  ($5/$25 per 1M tokens)   — writing, synthesis, code

All calls use adaptive thinking on Opus/Sonnet and streaming is used for
max_tokens > 4096 to avoid HTTP timeouts.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

# Model IDs
HAIKU  = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"
OPUS   = "claude-opus-4-6"

# Per 1M tokens (input, output) in USD
_COSTS: Dict[str, Tuple[float, float]] = {
    HAIKU:  (1.00,  5.00),
    SONNET: (3.00, 15.00),
    OPUS:   (5.00, 25.00),
}

# task_type → (free model, premium model)
_TASK_MAP: Dict[str, Tuple[str, str]] = {
    "planning":   (HAIKU,  SONNET),
    "structured": (HAIKU,  HAIKU),
    "general":    (HAIKU,  SONNET),
    "analysis":   (SONNET, SONNET),
    "web":        (HAIKU,  SONNET),
    "code":       (SONNET, OPUS),
    "writing":    (SONNET, OPUS),
    "synthesis":  (SONNET, OPUS),
    "delivery":   (SONNET, OPUS),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COSTS.get(model, (0.001, 0.001))
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


class ClaudeClient:
    """Async Claude client backed by the official Anthropic SDK."""

    def __init__(self) -> None:
        self._api_key = settings.anthropic_api_key
        self._client: Any = None  # lazy-init so import errors don't crash startup
        self._session_cost: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # local import so missing SDK doesn't kill the app
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise RuntimeError(
                    "anthropic package is not installed. "
                    "Run: pip install anthropic>=0.39.0"
                )
        return self._client

    def _pick_model(
        self,
        task_type: str,
        use_premium: bool,
        has_budget: bool,
    ) -> str:
        free_model, premium_model = _TASK_MAP.get(task_type, _TASK_MAP["general"])
        if use_premium and has_budget:
            return premium_model
        return free_model

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        task_type: str = "general",
        use_premium: bool = False,
        has_budget: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> Tuple[str, str, float]:
        """
        Call Claude and return (text, model_id, cost_usd).

        System prompt can be embedded in the first message or passed separately.
        """
        client = self._get_client()
        model = self._pick_model(task_type, use_premium, has_budget)

        # Separate system prompt from messages
        api_messages = []
        api_system = system

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                # Merge multiple system messages
                if api_system:
                    api_system = api_system + "\n\n" + content
                else:
                    api_system = content
            else:
                api_messages.append({"role": role, "content": content})

        if not api_messages:
            # Ensure there's at least one user message
            api_messages = [{"role": "user", "content": "Continue."}]

        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }
        if api_system:
            kwargs["system"] = api_system

        # Use adaptive thinking on Opus/Sonnet for complex tasks
        if model in (OPUS, SONNET) and task_type in (
            "code", "analysis", "synthesis", "writing", "delivery"
        ):
            kwargs["thinking"] = {"type": "adaptive"}

        logger.info(
            "Claude [%s] task=%s tokens_max=%d",
            model, task_type, max_tokens,
        )

        t0 = time.monotonic()

        # Use streaming for large outputs to avoid HTTP timeouts
        if max_tokens > 4096:
            text = await self._stream_call(client, kwargs)
        else:
            resp = await client.messages.create(**kwargs)
            text = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    text += block.text
            usage = resp.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cost = _estimate_cost(model, input_tokens, output_tokens)
            self._session_cost += cost
            latency = int((time.monotonic() - t0) * 1000)
            logger.info(
                "Claude [%s] tokens=%d+%d cost=$%.6f latency=%dms",
                model, input_tokens, output_tokens, cost, latency,
            )
            return text, model, cost

        # For streaming path, cost is estimated from tokens counted in _stream_call
        latency = int((time.monotonic() - t0) * 1000)
        # Rough estimate: 4 chars ≈ 1 token
        est_input = sum(len(str(m.get("content", ""))) for m in api_messages) // 4
        est_output = len(text) // 4
        cost = _estimate_cost(model, est_input, est_output)
        self._session_cost += cost
        logger.info(
            "Claude [%s] stream latency=%dms est_cost=$%.6f",
            model, latency, cost,
        )
        return text, model, cost

    async def _stream_call(self, client: Any, kwargs: Dict[str, Any]) -> str:
        """Stream a Claude response and return the concatenated text."""
        text_parts: List[str] = []
        async with client.messages.stream(**kwargs) as stream:
            async for chunk in stream.text_stream:
                text_parts.append(chunk)
        return "".join(text_parts)

    @property
    def session_cost(self) -> float:
        return self._session_cost


# Singleton
claude_client = ClaudeClient()
