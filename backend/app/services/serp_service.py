"""
Search service — SerpAPI with intelligent DuckDuckGo fallback.

Ladder strategy:
  1. DuckDuckGo (free, no key) — always tried first
  2. SerpAPI    (paid, richer results) — used when DDG returns <3 results
     OR when explicitly requested for premium quality

SerpAPI docs: https://serpapi.com/search-api
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SERPAPI_URL = "https://serpapi.com/search"
_TIMEOUT = 20


class SerpService:
    """
    Intelligent search that auto-ladders from free DDG to paid SerpAPI.
    """

    def __init__(self) -> None:
        self._api_key: str = settings.serp_api_key or os.getenv("SERP_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    # ── Public ────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        engine: str = "google",
        force_premium: bool = False,
    ) -> Dict[str, Any]:
        """
        Search and return structured results.

        Returns:
          {
            "success": bool,
            "source": "duckduckgo" | "serpapi",
            "results": [{"title", "url", "snippet"}, ...],
            "error": str | None,
          }
        """
        # Always try DDG first unless premium is forced and key exists
        if not force_premium:
            ddg_result = await self._search_ddg(query, num_results)
            if ddg_result["success"] and len(ddg_result["results"]) >= 3:
                return ddg_result
            logger.info("DDG returned %d results for '%s', escalating to SerpAPI",
                        len(ddg_result.get("results", [])), query[:60])

        if self.available:
            return await self._search_serp(query, num_results, engine)

        # No SerpAPI key — return whatever DDG gave us
        return await self._search_ddg(query, num_results)

    async def get_answer_box(self, query: str) -> Optional[Dict[str, Any]]:
        """Fetch a direct answer box (knowledge graph / featured snippet) via SerpAPI."""
        if not self.available:
            return None
        try:
            result = await self._search_serp(query, num_results=5, engine="google")
            raw = result.get("_raw", {})
            return raw.get("answer_box") or raw.get("knowledge_graph")
        except Exception as exc:
            logger.debug("SerpAPI answer_box failed: %s", exc)
            return None

    # ── Backends ─────────────────────────────────────────────────────────────

    async def _search_ddg(self, query: str, num_results: int) -> Dict[str, Any]:
        try:
            import functools
            from duckduckgo_search import DDGS

            def _sync():
                results = []
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=num_results):
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        })
                return results

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, _sync)
            return {"success": True, "source": "duckduckgo", "results": results, "error": None}
        except Exception as exc:
            logger.warning("DuckDuckGo search failed for '%s': %s", query[:60], exc)
            return {"success": False, "source": "duckduckgo", "results": [], "error": str(exc)}

    async def _search_serp(
        self, query: str, num_results: int, engine: str
    ) -> Dict[str, Any]:
        params = {
            "q": query,
            "api_key": self._api_key,
            "engine": engine,
            "num": num_results,
            "output": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_SERPAPI_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            results: List[Dict[str, Any]] = []
            for r in data.get("organic_results", [])[:num_results]:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                    "position": r.get("position"),
                })

            return {
                "success": True,
                "source": "serpapi",
                "results": results,
                "_raw": data,
                "error": None,
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.error("SerpAPI auth failed — falling back to DDG")
                return await self._search_ddg(query, num_results)
            raise
        except Exception as exc:
            logger.warning("SerpAPI search failed: %s", exc)
            return await self._search_ddg(query, num_results)


serp_service = SerpService()
