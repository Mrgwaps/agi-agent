"""
WaveSpeed AI service — image and video generation.

Ladder strategy:
  1. WaveSpeed free-tier / low-cost models (flux-schnell, SDXL)
  2. WaveSpeed premium models (flux-dev, video)
  3. Fallback: describe the image using LLM (text-only)

Docs: https://docs.wavespeed.ai
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 120  # image generation can be slow


class WaveSpeedService:
    """
    Async client for WaveSpeed AI image / video generation.

    Free route  → wavespeed-ai/flux-schnell (ultra-fast, free-tier)
    Premium     → wavespeed-ai/flux-dev (higher quality, paid)
    Video       → wavespeed-ai/wan-t2v-720p (text-to-video)
    """

    def __init__(self) -> None:
        self._api_key: str = settings.wavespeed_api_key or os.getenv("WAVESPEED_API_KEY", "")
        self._base_url: str = settings.wavespeed_base_url

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    # ── Public ────────────────────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        quality: str = "standard",   # "standard" | "premium"
    ) -> Dict[str, Any]:
        """
        Generate an image. Returns a dict with 'url', 'model', 'success'.
        Falls back to an LLM description if the key is absent.
        """
        if not self.available:
            return await self._llm_fallback(prompt, "image")

        model = "wavespeed-ai/flux-dev" if quality == "premium" else "wavespeed-ai/flux-schnell"

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "size": f"{width}*{height}",
            "num_inference_steps": steps,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            result = await self._submit_and_poll(model, payload)
            return {"success": True, "url": result, "model": model, "error": None}
        except Exception as exc:
            logger.warning("WaveSpeed image generation failed (%s): %s", model, exc)
            # Retry with schnell on dev failure
            if quality == "premium":
                try:
                    fallback_model = "wavespeed-ai/flux-schnell"
                    result = await self._submit_and_poll(fallback_model, payload)
                    return {"success": True, "url": result, "model": fallback_model, "error": None}
                except Exception as exc2:
                    logger.warning("WaveSpeed fallback also failed: %s", exc2)
            return {"success": False, "url": None, "model": model, "error": str(exc)}

    async def generate_video(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        duration: int = 5,
    ) -> Dict[str, Any]:
        """Generate a short video clip."""
        if not self.available:
            return await self._llm_fallback(prompt, "video")

        model = "wavespeed-ai/wan-t2v-720p"
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "duration": duration,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            result = await self._submit_and_poll(model, payload)
            return {"success": True, "url": result, "model": model, "error": None}
        except Exception as exc:
            logger.warning("WaveSpeed video generation failed: %s", exc)
            return {"success": False, "url": None, "model": model, "error": str(exc)}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _submit_and_poll(self, model: str, payload: Dict[str, Any]) -> str:
        """Submit a generation job and poll until done. Returns the result URL."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Submit job
            resp = await client.post(
                f"{self._base_url}/{model}/run",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            # Some models return result immediately
            outputs = data.get("data", {}).get("outputs", [])
            if outputs:
                return outputs[0] if isinstance(outputs[0], str) else str(outputs[0])

            # Poll for async jobs
            request_id = data.get("data", {}).get("id") or data.get("id")
            if not request_id:
                raise RuntimeError(f"No request_id in WaveSpeed response: {data}")

            for _ in range(60):  # up to 60 polls × 2s = 2 min
                await asyncio.sleep(2)
                poll = await client.get(
                    f"{self._base_url}/results/{request_id}",
                    headers=headers,
                )
                poll.raise_for_status()
                poll_data = poll.json()
                status = poll_data.get("data", {}).get("status", "")
                if status == "completed":
                    outputs = poll_data.get("data", {}).get("outputs", [])
                    if outputs:
                        return outputs[0] if isinstance(outputs[0], str) else str(outputs[0])
                    raise RuntimeError("Completed but no outputs")
                if status in ("failed", "canceled"):
                    raise RuntimeError(f"Job {request_id} {status}: {poll_data}")

            raise TimeoutError(f"WaveSpeed job {request_id} timed out after 2 minutes")

    async def _llm_fallback(self, prompt: str, media_type: str) -> Dict[str, Any]:
        """When no API key: describe what the image/video would look like."""
        from app.services.openrouter import ModelQuality, openrouter_client

        text, model, _ = await openrouter_client.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Describe in vivid detail what a {media_type} would look like "
                        f"if generated from this prompt: {prompt}\n\n"
                        "Write a rich, detailed visual description as if you were seeing it."
                    ),
                }
            ],
            task_type="general",
            quality=ModelQuality.FREE,
            max_tokens=512,
        )
        return {
            "success": True,
            "url": None,
            "description": text,
            "model": model,
            "error": "WaveSpeed API key not configured — returned text description instead",
        }


wavespeed_service = WaveSpeedService()
