from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class JsonGeneratorTool(BaseTool):
    name = "json_generator"
    description = (
        "Generate valid JSON or CSV from a schema description and input data. "
        "Uses the LLM to intelligently structure and format the data."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "schema_description": {
                "type": "string",
                "description": "Natural language description of the desired output schema",
            },
            "data": {
                "description": "Input data to structure (string, dict, or list)",
            },
            "output_format": {
                "type": "string",
                "enum": ["json", "csv", "jsonl"],
                "default": "json",
            },
            "instructions": {
                "type": "string",
                "description": "Additional formatting/transformation instructions",
            },
        },
        "required": ["schema_description", "data"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        schema_desc: str = input.get("schema_description", "")
        data: Any = input.get("data", "")
        output_format: str = input.get("output_format", "json")
        instructions: str = input.get("instructions", "")

        if not schema_desc:
            return {
                "success": False,
                "result": None,
                "error": "schema_description is required",
            }

        try:
            result = await self._generate(
                schema_desc, data, output_format, instructions
            )
            return {"success": True, "result": result, "error": None}
        except Exception as exc:
            logger.exception("JsonGeneratorTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc)}

    async def _generate(
        self,
        schema_desc: str,
        data: Any,
        output_format: str,
        instructions: str,
    ) -> Dict[str, Any]:
        from app.services.openrouter import openrouter_client

        # Serialise input data
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data, indent=2)
        else:
            data_str = str(data)

        extra = f"\n\nAdditional instructions: {instructions}" if instructions else ""

        system_prompt = (
            "You are a data transformation expert. "
            "Given input data and a schema description, produce a well-formed output. "
            "Return ONLY the structured data with no explanation or markdown fences."
        )

        if output_format == "json":
            user_msg = (
                f"Schema description: {schema_desc}\n\n"
                f"Input data:\n{data_str}{extra}\n\n"
                "Return valid JSON only."
            )
        elif output_format == "csv":
            user_msg = (
                f"Schema description: {schema_desc}\n\n"
                f"Input data:\n{data_str}{extra}\n\n"
                "Return valid CSV (with header row) only."
            )
        elif output_format == "jsonl":
            user_msg = (
                f"Schema description: {schema_desc}\n\n"
                f"Input data:\n{data_str}{extra}\n\n"
                "Return JSONL (one JSON object per line) only."
            )
        else:
            user_msg = (
                f"Schema description: {schema_desc}\n\n"
                f"Input data:\n{data_str}{extra}\n\n"
                "Return the structured data."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        text, model, cost = await openrouter_client.chat_completion(
            messages=messages,
            task_type="structured",
            force_free=True,
            max_tokens=4096,
        )

        # Strip markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        parsed: Optional[Any] = None
        if output_format == "json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass

        return {
            "output": text,
            "parsed": parsed,
            "format": output_format,
            "model_used": model,
            "cost_usd": cost,
        }
