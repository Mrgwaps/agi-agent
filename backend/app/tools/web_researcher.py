"""
WebResearcherTool — multi-query deep research synthesizer.

Implements patterns from:
  - alirezarezvani/claude-skills: market-research, competitive-intelligence, customer-insights
  - trailofbits/skills: audit-context-building (gather full context before acting)
  - obra/superpowers: brainstorming (explore widely before converging)

This tool issues multiple targeted searches, extracts key information from
top results, and synthesizes findings into a structured research brief.
More intelligent than a single web_search call because it:
  1. Generates multiple complementary queries covering different angles
  2. Fetches and reads actual page content (not just snippets)
  3. Cross-references findings across sources
  4. Returns a structured, citation-backed research brief
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_MAX_QUERIES = 5
_MAX_RESULTS_PER_QUERY = 4
_PAGE_FETCH_TIMEOUT = 15


class WebResearcherTool(BaseTool):
    name = "web_researcher"
    description = (
        "Conduct deep multi-source research on any topic. Issues multiple targeted "
        "search queries, reads top sources, and synthesizes findings into a structured "
        "research brief with key findings, statistics, insights, and citations. "
        "Use this for research tasks, market analysis, topic exploration, fact-finding, "
        "and background research for writing projects."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "research_question": {
                "type": "string",
                "description": "The main research question or topic to investigate",
            },
            "subtopics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific subtopics or angles to research (optional; auto-generated if omitted)",
            },
            "context": {
                "type": "string",
                "description": "Additional context about what you're trying to accomplish with this research",
            },
            "depth": {
                "type": "string",
                "enum": ["quick", "standard", "deep"],
                "description": "Research depth: quick (2 queries), standard (3-4 queries), deep (5 queries)",
                "default": "standard",
            },
        },
        "required": ["research_question"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.openrouter import ModelQuality, openrouter_client

        research_question: str = input.get("research_question", "").strip()
        subtopics: List[str] = input.get("subtopics", [])
        context: str = input.get("context", "")
        depth: str = input.get("depth", "standard")

        if not research_question:
            return {"success": False, "result": None, "error": "research_question is required"}

        depth_map = {"quick": 2, "standard": 3, "deep": _MAX_QUERIES}
        num_queries = depth_map.get(depth, 3)

        try:
            # Step 1: Generate research queries
            queries = await self._generate_queries(
                research_question, subtopics, context, num_queries, openrouter_client
            )
            logger.info("WebResearcherTool: running %d queries for '%s'", len(queries), research_question[:60])

            # Step 2: Execute searches in parallel
            search_results = await self._run_searches(queries)

            # Step 3: Fetch top page content for richer context
            page_contents = await self._fetch_top_pages(search_results)

            # Step 4: Synthesize into structured research brief
            brief = await self._synthesize(
                research_question, queries, search_results, page_contents, openrouter_client
            )

            return {
                "success": True,
                "result": brief,
                "metadata": {
                    "queries_run": queries,
                    "sources_found": sum(len(r) for r in search_results.values()),
                    "pages_read": len(page_contents),
                },
                "error": None,
            }

        except Exception as exc:
            logger.exception("WebResearcherTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc)}

    async def _generate_queries(
        self,
        question: str,
        subtopics: List[str],
        context: str,
        num_queries: int,
        client: Any,
    ) -> List[str]:
        """Use LLM to generate diverse, targeted search queries."""
        if subtopics:
            # Build queries directly from provided subtopics
            queries = [question] + [f"{question} {t}" for t in subtopics[:num_queries - 1]]
            return queries[:num_queries]

        prompt_parts = [
            f"Research question: {question}",
            f"Generate exactly {num_queries} different search queries that together will give comprehensive coverage of this topic.",
            "Rules:",
            "- First query: broad overview",
            "- Remaining queries: specific angles, statistics, expert opinions, practical examples",
            "- Each query should find DIFFERENT information from the others",
            "- Use natural search language, not questions",
            f"Context: {context}" if context else "",
            "\nReturn ONLY a JSON array of query strings, nothing else.",
            'Example: ["query one", "query two", "query three"]',
        ]

        try:
            text, _, _ = await client.chat_completion(
                messages=[{"role": "user", "content": "\n".join(p for p in prompt_parts if p)}],
                task_type="structured",
                quality=ModelQuality.FREE,
                max_tokens=256,
                temperature=0.3,
            )
            import json, re
            text = text.strip()
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                queries = json.loads(match.group())
                if isinstance(queries, list) and queries:
                    return [str(q) for q in queries[:num_queries]]
        except Exception as exc:
            logger.warning("Query generation failed, using fallback: %s", exc)

        # Fallback: simple variations
        return [question, f"{question} guide", f"{question} best practices"][:num_queries]

    async def _run_searches(self, queries: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Run all queries in parallel using DuckDuckGo."""
        async def _single_search(query: str) -> tuple[str, List[Dict[str, Any]]]:
            try:
                import asyncio, functools
                from duckduckgo_search import DDGS

                def _sync():
                    results = []
                    with DDGS() as ddgs:
                        for r in ddgs.text(query, max_results=_MAX_RESULTS_PER_QUERY):
                            results.append({
                                "title": r.get("title", ""),
                                "url": r.get("href", ""),
                                "snippet": r.get("body", ""),
                            })
                    return results

                loop = asyncio.get_running_loop()
                results = await loop.run_in_executor(None, _sync)
                return query, results
            except Exception as exc:
                logger.warning("Search failed for '%s': %s", query[:50], exc)
                return query, []

        tasks = [_single_search(q) for q in queries]
        pairs = await asyncio.gather(*tasks)
        return {q: r for q, r in pairs}

    async def _fetch_top_pages(
        self, search_results: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, str]]:
        """Fetch content from the top unique URLs across all search results."""
        import httpx

        # Collect unique URLs, prioritising first result per query
        seen_urls: set[str] = set()
        urls_to_fetch: List[str] = []
        for results in search_results.values():
            for r in results[:2]:  # top 2 per query
                url = r.get("url", "")
                if url and url not in seen_urls and len(urls_to_fetch) < 6:
                    seen_urls.add(url)
                    urls_to_fetch.append(url)

        async def _fetch(url: str) -> Dict[str, str]:
            try:
                async with httpx.AsyncClient(
                    timeout=_PAGE_FETCH_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AGIAgent/1.0)"},
                ) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        return {"url": url, "content": ""}
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                        tag.decompose()
                    text = " ".join(soup.get_text(separator=" ").split())
                    return {"url": url, "content": text[:3000]}  # cap per page
            except Exception:
                return {"url": url, "content": ""}

        pages = await asyncio.gather(*[_fetch(u) for u in urls_to_fetch])
        return [p for p in pages if p["content"]]

    async def _synthesize(
        self,
        question: str,
        queries: List[str],
        search_results: Dict[str, List[Dict[str, Any]]],
        pages: List[Dict[str, str]],
        client: Any,
    ) -> str:
        """Synthesize all gathered data into a structured research brief."""
        from app.services.openrouter import ModelQuality

        # Build context for synthesis
        snippets_text = "\n\n".join(
            f"Query: {q}\n"
            + "\n".join(
                f"  [{i+1}] {r['title']}\n  URL: {r['url']}\n  {r['snippet'][:300]}"
                for i, r in enumerate(results[:3])
            )
            for q, results in search_results.items()
            if results
        )

        pages_text = "\n\n---\n\n".join(
            f"Source: {p['url']}\n{p['content'][:1500]}"
            for p in pages[:4]
        )

        synthesis_prompt = f"""Research question: {question}

Search results:
{snippets_text[:3000]}

Page content from top sources:
{pages_text[:4000]}

---
Synthesize all of the above into a structured research brief with these sections:

## Executive Summary
(3-5 bullet points covering the most critical findings)

## Key Findings
(Organized by theme. For each finding: state it clearly, cite the source, note confidence level)

## Statistics & Data Points
(Any specific numbers, percentages, metrics found — with sources)

## Expert Insights & Perspectives
(Notable quotes, expert opinions, industry viewpoints)

## Gaps & Limitations
(What the research didn't find or couldn't confirm)

## Sources
(Numbered list of URLs cited above)

Be specific, accurate, and cite sources. Do not add information not found in the sources."""

        text, _, _ = await client.chat_completion(
            messages=[{"role": "user", "content": synthesis_prompt}],
            task_type="analysis",
            quality=ModelQuality.BALANCED,
            max_tokens=3000,
            temperature=0.3,
        )
        return text
