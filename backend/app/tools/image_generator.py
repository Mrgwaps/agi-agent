"""
ImageGeneratorTool — generate images and videos via WaveSpeed AI.

Uses the free Flux-Schnell model by default, escalates to Flux-Dev
for premium quality requests. Falls back to a vivid text description
if the API key is absent.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ImageGeneratorTool(BaseTool):
    name = "image_generator"
    description = (
        "Generate high-quality images or short video clips from text prompts. "
        "Uses WaveSpeed AI (Flux models) for images, with intelligent quality "
        "routing: fast/free tier for quick visuals, premium tier for detailed artwork. "
        "Provide a detailed prompt for best results. Optionally specify size and quality."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed text description of the image or video to generate",
            },
            "media_type": {
                "type": "string",
                "enum": ["image", "video"],
                "description": "Type of media to generate (default: image)",
                "default": "image",
            },
            "quality": {
                "type": "string",
                "enum": ["standard", "premium"],
                "description": "standard = fast/free Flux-Schnell; premium = Flux-Dev (higher detail)",
                "default": "standard",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Elements to avoid in the generation (optional)",
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels (default 1024)",
                "default": 1024,
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels (default 1024)",
                "default": 1024,
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.wavespeed_service import wavespeed_service

        prompt: str = input.get("prompt", "").strip()
        media_type: str = input.get("media_type", "image")
        quality: str = input.get("quality", "standard")
        negative_prompt: str = input.get("negative_prompt", "")
        width: int = int(input.get("width", 1024))
        height: int = int(input.get("height", 1024))

        if not prompt:
            return {"success": False, "result": None, "error": "prompt is required"}

        if media_type == "video":
            result = await wavespeed_service.generate_video(
                prompt,
                negative_prompt=negative_prompt,
            )
        else:
            result = await wavespeed_service.generate_image(
                prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                quality=quality,
            )

        if result["success"]:
            url = result.get("url")
            description = result.get("description")
            model = result.get("model", "unknown")

            if url:
                summary = f"Generated {media_type} using {model}.\nURL: {url}"
            else:
                summary = f"WaveSpeed unavailable — visual description:\n\n{description}"

            return {
                "success": True,
                "result": summary,
                "url": url,
                "model": model,
                "error": result.get("error"),
            }

        return {
            "success": False,
            "result": None,
            "error": result.get("error", "Image generation failed"),
        }
