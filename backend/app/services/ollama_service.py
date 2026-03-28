from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OllamaService:
    """Async client for the local Ollama inference server."""

    def __init__(self) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._timeout = settings.ollama_timeout

    # ── Public API ──────────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        """Return True if the Ollama server is reachable."""
        if not settings.ollama_enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        """Return list of locally available model names."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as exc:
            logger.warning("Failed to list Ollama models: %s", exc)
            return []

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Tuple[str, str]:
        """
        Send a chat request to Ollama.

        Returns:
            (response_text, model_used)
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            text: str = data.get("message", {}).get("content", "")
            actual_model: str = data.get("model", model)
            return text, actual_model

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama HTTP error %d: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise
        except Exception as exc:
            logger.error("Ollama chat error: %s", exc)
            raise

    async def generate(
        self,
        prompt: str,
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Tuple[str, str]:
        """
        Generate a completion via the /api/generate endpoint.

        Returns:
            (response_text, model_used)
        """
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("response", ""), data.get("model", model)


# Singleton
ollama_service = OllamaService()
