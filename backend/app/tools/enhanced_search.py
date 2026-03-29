"""
EnhancedSearchTool — SerpAPI-backed search with DuckDuckGo fallback.

Automatically uses the free DDG route first, escalates to SerpAPI
when richer structured results are needed.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class EnhancedSearchTool(BaseTool):
    name = "enhanced_search"
    description = (
        "Search the web for current information using SerpAPI (Google results) "
        "with automatic DuckDuckGo fallback. Returns rich structured results "
        "including titles, URLs, and snippets. Best for quick fact lookups, "
        "current events, and finding specific pages. Use web_researcher for "
        "deep multi-source research tasks."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default 10, max 20)",
                "default": 10,
            },
            "engine": {
                "type": "string",
                "enum": ["google", "bing", "duckduckgo"],
                "description": "Search engine to use (default: google)",
                "default": "google",
            },
            "force_premium": {
                "type": "boolean",
                "description": "Skip DuckDuckGo and use SerpAPI directly for highest quality",
                "default": False,
            },
        },
        "required": ["query"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.serp_service import serp_service

        query: str = input.get("query", "").strip()
        num_results: int = min(int(input.get("num_results", 10)), 20)
        engine: str = input.get("engine", "google")
        force_premium: bool = bool(input.get("force_premium", False))

        if not query:
            return {"success": False, "result": None, "error": "query is required"}

        result = await serp_service.search(
            query,
            num_results=num_results,
            engine=engine,
            force_premium=force_premium,
        )

        if result["success"]:
            results = result.get("results", [])
            source = result.get("source", "unknown")

            # Format as readable text
            lines = [f"Search results for: {query} (via {source})\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title', 'Untitled')}")
                lines.append(f"   URL: {r.get('url', '')}")
                lines.append(f"   {r.get('snippet', '')[:200]}")
                lines.append("")

            return {
                "success": True,
                "result": "\n".join(lines),
                "raw_results": results,
                "source": source,
                "error": None,
            }

        return {
            "success": False,
            "result": None,
            "error": result.get("error", "Search failed"),
        }
