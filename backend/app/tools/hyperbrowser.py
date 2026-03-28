from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class HyperbrowserTool(BaseTool):
    name = "hyperbrowser"
    description = (
        "Browse web pages, take screenshots, and extract structured data using "
        "Hyperbrowser. Falls back to plain HTTP scraping if API key not set."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["scrape_url", "take_screenshot", "extract_structured_data"],
            },
            "url": {"type": "string", "description": "URL to browse"},
            "schema_description": {
                "type": "string",
                "description": "For extract_structured_data: describe what fields to extract",
            },
            "wait_for_selector": {
                "type": "string",
                "description": "CSS selector to wait for before scraping",
            },
        },
        "required": ["action", "url"],
    }

    # ── Main entry ──────────────────────────────────────────────────────────

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        action = input.get("action", "scrape_url")
        url = input.get("url", "").strip()

        if not url:
            return {"success": False, "result": None, "error": "url is required"}

        try:
            if action == "scrape_url":
                result = await self._scrape(url, input.get("wait_for_selector"))
            elif action == "take_screenshot":
                result = await self._screenshot(url)
            elif action == "extract_structured_data":
                schema_desc = input.get("schema_description", "Extract all relevant data")
                result = await self._extract(url, schema_desc)
            else:
                return {"success": False, "result": None, "error": f"Unknown action: {action}"}

            return {"success": True, "result": result, "error": None}
        except Exception as exc:
            logger.exception("HyperbrowserTool error for %s: %s", url, exc)
            return {"success": False, "result": None, "error": str(exc)}

    # ── Actions ─────────────────────────────────────────────────────────────

    async def _scrape(
        self, url: str, wait_for_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        if settings.hyperbrowser_api_key:
            return await self._hyperbrowser_scrape(url, wait_for_selector)
        return await self._fallback_scrape(url)

    async def _screenshot(self, url: str) -> Dict[str, Any]:
        if not settings.hyperbrowser_api_key:
            return {
                "url": url,
                "screenshot": None,
                "error": "Hyperbrowser API key required for screenshots",
            }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.hyperbrowser_base_url}/api/screenshot",
                headers={
                    "x-api-key": settings.hyperbrowser_api_key,
                    "Content-Type": "application/json",
                },
                json={"url": url},
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "url": url,
            "screenshot_url": data.get("screenshotUrl") or data.get("url"),
            "data": data,
        }

    async def _extract(self, url: str, schema_desc: str) -> Dict[str, Any]:
        if settings.hyperbrowser_api_key:
            return await self._hyperbrowser_extract(url, schema_desc)

        # Fallback: scrape and return raw text for LLM processing
        scraped = await self._fallback_scrape(url)
        return {**scraped, "schema_description": schema_desc, "raw_only": True}

    # ── Hyperbrowser API calls ───────────────────────────────────────────────

    async def _hyperbrowser_scrape(
        self, url: str, wait_for_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "url": url,
            "scrapeOptions": {"formats": ["markdown", "html"]},
        }
        if wait_for_selector:
            payload["waitForSelector"] = wait_for_selector

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.hyperbrowser_base_url}/api/scrape",
                headers={
                    "x-api-key": settings.hyperbrowser_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content_md = data.get("data", {}).get("markdown", "")
        content_html = data.get("data", {}).get("html", "")
        metadata = data.get("data", {}).get("metadata", {})

        return {
            "url": url,
            "title": metadata.get("title", ""),
            "content": content_md or content_html,
            "links": self._extract_links_from_html(content_html),
            "metadata": metadata,
            "source": "hyperbrowser",
        }

    async def _hyperbrowser_extract(
        self, url: str, schema_desc: str
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.hyperbrowser_base_url}/api/scrape",
                headers={
                    "x-api-key": settings.hyperbrowser_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "scrapeOptions": {
                        "formats": ["markdown"],
                        "prompt": schema_desc,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "url": url,
            "extracted": data.get("data", {}),
            "source": "hyperbrowser",
        }

    # ── Fallback HTTP scraping ───────────────────────────────────────────────

    async def _fallback_scrape(self, url: str) -> Dict[str, Any]:
        """Simple scrape using httpx + BeautifulSoup."""
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; AGIAgent/1.0; "
                "+https://github.com/agi-agent)"
            )
        }

        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        # Remove script/style noise
        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()

        title = soup.title.get_text(strip=True) if soup.title else ""
        content = soup.get_text(separator="\n", strip=True)

        # Limit content length
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]"

        links = self._extract_links_from_soup(soup, url)

        return {
            "url": url,
            "title": title,
            "content": content,
            "links": links[:20],
            "source": "fallback_http",
        }

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _extract_links_from_html(self, html: str) -> List[Dict[str, str]]:
        if not html:
            return []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            return self._extract_links_from_soup(soup, "")
        except Exception:
            return []

    def _extract_links_from_soup(
        self, soup: Any, base_url: str
    ) -> List[Dict[str, str]]:
        links = []
        for a in soup.find_all("a", href=True)[:50]:
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if href and not href.startswith(("javascript:", "mailto:", "#")):
                links.append({"text": text, "href": href})
        return links
