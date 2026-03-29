"""
HFInferenceTool — Hugging Face Inference API for open-source model tasks.

Supports: text generation, zero-shot classification, summarization,
and sentence embeddings. Uses free serverless inference first,
escalates to paid tier with API key.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class HFInferenceTool(BaseTool):
    name = "hf_inference"
    description = (
        "Run open-source AI models via Hugging Face Inference API. "
        "Capabilities: text generation (Mistral, Zephyr, Llama), "
        "zero-shot text classification, document summarization, and "
        "sentence embeddings for similarity tasks. "
        "Use for specialized model tasks or when OpenRouter is rate-limited."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "enum": ["text_generation", "classify", "summarize", "embeddings"],
                "description": "Which HF inference task to run",
            },
            "input": {
                "type": "string",
                "description": "Input text for the model",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate labels for zero-shot classification",
            },
            "model": {
                "type": "string",
                "description": "Specific HuggingFace model ID to use (optional, auto-selected if omitted)",
            },
            "quality": {
                "type": "string",
                "enum": ["free", "paid"],
                "description": "Model tier: free (smaller, fast) or paid (larger, better)",
                "default": "free",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Max tokens to generate (default 512)",
                "default": 512,
            },
        },
        "required": ["task", "input"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.huggingface_service import huggingface_service

        task: str = input.get("task", "text_generation")
        text: str = input.get("input", "").strip()
        model: str = input.get("model", "")
        quality: str = input.get("quality", "free")
        max_tokens: int = int(input.get("max_tokens", 512))

        if not text:
            return {"success": False, "result": None, "error": "input is required"}

        if task == "text_generation":
            result = await huggingface_service.text_generation(
                text,
                max_tokens=max_tokens,
                model=model or None,
                quality=quality,
            )
            return {
                "success": result["success"],
                "result": result.get("text"),
                "model": result.get("model"),
                "error": result.get("error"),
            }

        elif task == "classify":
            labels = input.get("labels", [])
            if not labels:
                return {"success": False, "result": None, "error": "labels required for classify task"}
            result = await huggingface_service.classify(text, labels, model=model or "facebook/bart-large-mnli")
            return {
                "success": result["success"],
                "result": result.get("result"),
                "model": result.get("model"),
                "error": result.get("error"),
            }

        elif task == "summarize":
            result = await huggingface_service.summarize(text, model=model or "facebook/bart-large-cnn")
            return {
                "success": result["success"],
                "result": result.get("summary"),
                "model": result.get("model"),
                "error": result.get("error"),
            }

        elif task == "embeddings":
            result = await huggingface_service.embeddings(text)
            if result["success"]:
                emb = result.get("embeddings")
                return {
                    "success": True,
                    "result": f"Computed embeddings with shape {len(emb)} x {len(emb[0]) if emb and isinstance(emb[0], list) else 'N/A'}",
                    "embeddings": emb,
                    "model": result.get("model"),
                    "error": None,
                }
            return {"success": False, "result": None, "error": result.get("error")}

        return {"success": False, "result": None, "error": f"Unknown task: {task}"}
