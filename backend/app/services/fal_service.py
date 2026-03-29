"""
fal.ai service — Kokoro TTS (text-to-speech).

Kokoro is a high-quality, natural-sounding TTS model available via fal.ai.
The API is fast (<1s for short text) and produces MP3 audio.

Docs: https://fal.ai/models/fal-ai/kokoro
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://fal.run/fal-ai/kokoro"
_TIMEOUT = 30

# Kokoro voice IDs
VOICES = {
    "af_sky": "American Female — Sky (warm, conversational)",
    "af_bella": "American Female — Bella (bright, energetic)",
    "af_sarah": "American Female — Sarah (clear, professional)",
    "am_michael": "American Male — Michael (deep, authoritative)",
    "am_adam": "American Male — Adam (friendly, casual)",
    "bf_emma": "British Female — Emma (crisp, formal)",
    "bm_george": "British Male — George (refined, measured)",
}

DEFAULT_VOICE = "af_sky"


class FalService:
    """
    Async client for fal.ai APIs.

    Current features:
    - Kokoro TTS: converts text to natural speech (MP3 URL)
    """

    def __init__(self) -> None:
        self._api_key: str = settings.fal_api_key or os.getenv("FAL_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

    # ── Public ────────────────────────────────────────────────────────────────

    async def kokoro_tts(
        self,
        text: str,
        *,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Convert text to speech using Kokoro TTS.

        Returns:
            {
                "success": bool,
                "audio_url": str | None,
                "duration_seconds": float,
                "voice": str,
                "error": str | None,
            }
        """
        if not self.available:
            return {
                "success": False,
                "audio_url": None,
                "duration_seconds": 0.0,
                "voice": voice,
                "error": "fal.ai API key not configured. Add FAL_API_KEY to settings.",
            }

        if not text or not text.strip():
            return {
                "success": False,
                "audio_url": None,
                "duration_seconds": 0.0,
                "voice": voice,
                "error": "Empty text",
            }

        # Truncate very long text (Kokoro handles up to ~1000 chars well)
        text_to_speak = text.strip()[:1200]

        payload = {
            "text": text_to_speak,
            "voice": voice if voice in VOICES else DEFAULT_VOICE,
            "speed": speed,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _BASE_URL,
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            # fal.ai returns: {"audio": {"url": "...", "duration": 4.2}, ...}
            audio = data.get("audio") or data.get("audio_file") or {}
            if isinstance(audio, str):
                audio_url = audio
                duration = 0.0
            else:
                audio_url = audio.get("url") or data.get("audio_url")
                duration = float(audio.get("duration", 0.0))

            if not audio_url:
                raise ValueError(f"No audio URL in fal.ai response: {data}")

            return {
                "success": True,
                "audio_url": audio_url,
                "duration_seconds": duration,
                "voice": voice,
                "error": None,
            }

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                logger.error("fal.ai TTS: authentication failed — check FAL_API_KEY")
                error = "Invalid fal.ai API key"
            elif status == 429:
                logger.warning("fal.ai TTS: rate limited")
                error = "fal.ai rate limit exceeded — try again shortly"
            else:
                error = f"fal.ai HTTP {status}"
            return {"success": False, "audio_url": None, "duration_seconds": 0.0, "voice": voice, "error": error}

        except asyncio.TimeoutError:
            logger.warning("fal.ai TTS timed out after %ds", _TIMEOUT)
            return {"success": False, "audio_url": None, "duration_seconds": 0.0, "voice": voice, "error": "TTS request timed out"}

        except Exception as exc:
            logger.warning("fal.ai TTS failed: %s", exc)
            return {"success": False, "audio_url": None, "duration_seconds": 0.0, "voice": voice, "error": str(exc)}

    def list_voices(self) -> Dict[str, str]:
        """Return all available voice IDs and descriptions."""
        return dict(VOICES)


fal_service = FalService()
