from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo. Returns titles, URLs, and snippets."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (1-20)",
                "default": 5,
            },
            "region": {
                "type": "string",
                "description": "Region code for results (e.g. 'us-en')",
                "default": "us-en",
            },
        },
        "required": ["query"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        query: str = input.get("query", "").strip()
        max_results: int = min(int(input.get("max_results", 5)), 20)
        region: str = input.get("region", "us-en")

        if not query:
            return {"success": False, "result": None, "error": "query is required"}

        try:
            results = await self._search(query, max_results, region)
            return {
                "success": True,
                "result": {
                    "query": query,
                    "results": results,
                    "count": len(results),
                },
                "error": None,
            }
        except Exception as exc:
            logger.exception("WebSearchTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc)}

    async def _search(
        self, query: str, max_results: int, region: str
    ) -> List[Dict[str, Any]]:
        """Run DuckDuckGo search synchronously in a thread pool."""
        import asyncio
        import functools

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(self._sync_search, query, max_results, region),
        )

    def _sync_search(
        self, query: str, max_results: int, region: str
    ) -> List[Dict[str, Any]]:
        from duckduckgo_search import DDGS

        results: List[Dict[str, Any]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                region=region,
                safesearch="moderate",
                max_results=max_results,
            ):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        return results
