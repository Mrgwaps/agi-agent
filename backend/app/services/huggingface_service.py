"""
Hugging Face Inference API service.

Ladder strategy (text generation):
  1. Free serverless inference (no key, rate limited) — small public models
  2. HF Inference API with key — larger models, higher limits
  3. OpenRouter fallback — when HF is unavailable

Supports: text-generation, text-classification, question-answering,
          summarization, translation, sentence-similarity, embeddings
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api-inference.huggingface.co/models"
_TIMEOUT = 60

# Free models to try in order (no key needed, but rate-limited)
_FREE_TEXT_MODELS = [
    "HuggingFaceH4/zephyr-7b-beta",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "microsoft/phi-2",
]

# Models available with a paid key
_PAID_TEXT_MODELS = [
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "HuggingFaceH4/zephyr-7b-beta",
]

_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_CLASSIFICATION_MODEL = "facebook/bart-large-mnli"
_SUMMARIZATION_MODEL = "facebook/bart-large-cnn"


class HuggingFaceService:
    """
    Async client for Hugging Face Inference API with automatic tier escalation.
    """

    def __init__(self) -> None:
        self._api_key: str = settings.huggingface_api_key or os.getenv("HUGGINGFACE_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    # ── Public ────────────────────────────────────────────────────────────────

    async def text_generation(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.7,
        model: Optional[str] = None,
        quality: str = "free",  # "free" | "paid"
    ) -> Dict[str, Any]:
        """Generate text using HF inference."""
        candidates = [model] if model else (
            _PAID_TEXT_MODELS if (quality == "paid" and self.available) else _FREE_TEXT_MODELS
        )

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "return_full_text": False,
            },
        }

        for candidate in candidates:
            try:
                result = await self._call(candidate, payload)
                if isinstance(result, list) and result:
                    text = result[0].get("generated_text", "")
                    return {"success": True, "text": text, "model": candidate, "error": None}
            except Exception as exc:
                if "is currently loading" in str(exc):
                    logger.info("HF model %s loading, retrying in 20s…", candidate)
                    await asyncio.sleep(20)
                    try:
                        result = await self._call(candidate, payload)
                        if isinstance(result, list) and result:
                            text = result[0].get("generated_text", "")
                            return {"success": True, "text": text, "model": candidate, "error": None}
                    except Exception:
                        pass
                logger.debug("HF model %s failed: %s", candidate, exc)
                continue

        # All HF models failed — OpenRouter fallback
        return await self._openrouter_fallback(prompt, max_tokens, temperature)

    async def embeddings(
        self,
        texts: Union[str, List[str]],
        *,
        model: str = _EMBEDDING_MODEL,
    ) -> Dict[str, Any]:
        """Compute sentence embeddings."""
        payload = {"inputs": texts if isinstance(texts, list) else [texts]}
        try:
            result = await self._call(model, payload)
            return {"success": True, "embeddings": result, "model": model, "error": None}
        except Exception as exc:
            logger.warning("HF embeddings failed: %s", exc)
            return {"success": False, "embeddings": None, "model": model, "error": str(exc)}

    async def classify(
        self,
        text: str,
        candidate_labels: List[str],
        *,
        model: str = _CLASSIFICATION_MODEL,
    ) -> Dict[str, Any]:
        """Zero-shot text classification."""
        payload = {
            "inputs": text,
            "parameters": {"candidate_labels": candidate_labels},
        }
        try:
            result = await self._call(model, payload)
            return {"success": True, "result": result, "model": model, "error": None}
        except Exception as exc:
            logger.warning("HF classification failed: %s", exc)
            return {"success": False, "result": None, "model": model, "error": str(exc)}

    async def summarize(
        self,
        text: str,
        *,
        max_length: int = 200,
        min_length: int = 50,
        model: str = _SUMMARIZATION_MODEL,
    ) -> Dict[str, Any]:
        """Summarize long text."""
        payload = {
            "inputs": text[:4000],
            "parameters": {"max_length": max_length, "min_length": min_length},
        }
        try:
            result = await self._call(model, payload)
            if isinstance(result, list) and result:
                summary = result[0].get("summary_text", "")
                return {"success": True, "summary": summary, "model": model, "error": None}
        except Exception as exc:
            logger.warning("HF summarization failed: %s", exc)
        return {"success": False, "summary": None, "model": model, "error": "HF summarization failed"}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _call(self, model: str, payload: Dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_BASE_URL}/{model}",
                json=payload,
                headers=self._headers(),
            )
            if resp.status_code == 503:
                body = resp.json()
                if "is currently loading" in body.get("error", ""):
                    raise RuntimeError(f"HF model {model} is currently loading")
            resp.raise_for_status()
            return resp.json()

    async def _openrouter_fallback(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> Dict[str, Any]:
        """All HF options exhausted — delegate to OpenRouter."""
        try:
            from app.services.openrouter import ModelQuality, openrouter_client

            text, model, _ = await openrouter_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                task_type="general",
                quality=ModelQuality.FREE,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return {"success": True, "text": text, "model": f"openrouter/{model}", "error": None}
        except Exception as exc:
            return {"success": False, "text": None, "model": None, "error": str(exc)}


huggingface_service = HuggingFaceService()
