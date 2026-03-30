"""
Skill Researcher — perpetual background service that autonomously discovers,
validates, and catalogues elite agent skills with a focus on revenue generation.

Inspired by https://github.com/obra/superpowers — every discovered skill becomes
a named "superpower" the AGI agents can invoke.

Architecture
────────────
• Runs as an asyncio background task started in FastAPI lifespan.
• Uses its own dedicated `background_openrouter_client` (max_concurrent=1) so
  it NEVER competes with active user task execution.
• Uses deepseek/deepseek-r1:free + llama-3.3-70b-instruct:free by default
  (powerful, zero cost).
• Searches the web with DuckDuckGo (no API key required).
• Interval: 2 hours between full research cycles.
• Each cycle:
    1. Pick a research topic (revenue skills, automation, elite agent tasks…)
    2. DuckDuckGo search → collect URLs + snippets
    3. LLM analysis → extract structured skill definitions
    4. Upsert skills into SQLite master Skills DB
    5. Purge stale / consistently-failing skills
    6. Update heartbeat report cache so new skills appear in the 30-min brief
• Leverages superpowers framework concept: skills = named system-prompt
  templates that activate specific agent capabilities.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional

from app.services.openrouter import ModelQuality, background_openrouter_client
from app.services.skills_db import skills_db, seed_initial_skills

logger = logging.getLogger(__name__)

# ── Research configuration ─────────────────────────────────────────────────────

RESEARCH_INTERVAL = 2 * 60 * 60   # 2 hours between cycles
INITIAL_DELAY     = 90             # seconds after startup before first run

# Topic rotation — broad and specific queries to build a diverse skills library
_RESEARCH_TOPICS: List[str] = [
    # Revenue / income generation
    "AI agent skills for earning money online 2024 2025",
    "best freelancing skills for AI agents automation income",
    "how to make money with AI agents autonomous income strategies",
    "AI agent gig economy fiverr upwork revenue generation skills",
    "passive income strategies using AI automation agents",
    "AI agent affiliate marketing content generation revenue",
    "selling AI-generated digital products prompts templates",
    "AI agent dropshipping product research automation skills",
    "lead generation automation AI agent cold outreach skills",
    "content creation monetization strategy AI agent",
    # Complex task skills
    "elite AI agent skills complex task completion 2024",
    "advanced agent capabilities autonomous problem solving",
    "AI agent web scraping data extraction monetization",
    "AI agent API integration workflow automation skills",
    "AI agent market research competitive analysis skills",
    "AI agent SEO content strategy ranking skills",
    # Superpowers / frameworks
    "AI agent superpowers capabilities framework skills",
    "autonomous agent skill building revenue generation",
    "agentic AI task skills best practices techniques",
    "multi-step AI agent complex workflow completion",
    # Specialized revenue
    "AI agent social media marketing income skills",
    "AI agent email marketing automation revenue skills",
    "AI agent software development freelance income",
    "AI agent consulting report writing skills revenue",
    "AI agent e-commerce automation product listing skills",
]

# LLM model preference for research (cheap + powerful)
_RESEARCH_MODEL_PREFERENCE = "deepseek/deepseek-r1:free"

# The skill extraction prompt — produces structured JSON skill definitions
_EXTRACTION_SYSTEM_PROMPT = """You are an elite agent skill analyst building a master library of AI agent superpowers.

Your job: analyze web search results and extract actionable SKILL DEFINITIONS that AI agents can use to:
1. Generate real revenue (freelancing, digital products, automation services)
2. Complete complex tasks autonomously
3. Solve real-world problems efficiently

For each skill you identify, output a JSON object with EXACTLY these fields:
{
  "name": "snake_case_slug_max_40_chars",
  "title": "Human Readable Title (5-8 words)",
  "category": "revenue|automation|research|writing|coding|communication|data",
  "description": "One sentence: what the skill does and its primary value.",
  "system_prompt": "The complete system prompt that activates this skill. 3-6 sentences. Be specific and actionable.",
  "tool_hints": "comma,separated,tool,names from: enhanced_search,web_researcher,code_executor,content_writer,email,filesystem,location,hf_inference,image_generator",
  "revenue_potential": "none|low|medium|high|very_high",
  "complexity": "beginner|intermediate|advanced",
  "tags": "comma,separated,keywords,max,8,tags",
  "source_url": "most relevant URL from the search results"
}

Rules:
- Focus HEAVILY on revenue-generating skills (revenue_potential: high or very_high)
- Each skill must be genuinely actionable by an autonomous AI agent
- system_prompt must be a real, usable prompt template (not just a description)
- Only include skills that are unique and add value to the library
- Output ONLY a JSON array, no other text
- Include 3-8 skills per analysis. Quality over quantity."""


class SkillResearcherService:
    """
    Perpetual background skill researcher.

    Call `start()` once in the FastAPI lifespan — it creates an asyncio task
    that runs indefinitely, sleeping between research cycles.
    """

    def __init__(self) -> None:
        self._running = False
        self._cycle_count = 0
        self._topic_index = 0
        self._last_report: Optional[Dict[str, Any]] = None

    def get_last_report(self) -> Optional[Dict[str, Any]]:
        return self._last_report

    async def start(self) -> None:
        """Entry point — call once from lifespan."""
        if self._running:
            return
        self._running = True
        logger.info("SkillResearcher: seeding foundational skills…")
        await seed_initial_skills()
        logger.info("SkillResearcher: starting perpetual research loop (interval=%dh)", RESEARCH_INTERVAL // 3600)
        await self._loop()

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        await asyncio.sleep(INITIAL_DELAY)
        while self._running:
            try:
                await self._research_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("SkillResearcher cycle failed: %s", exc, exc_info=True)
            # Sleep until next cycle (with small jitter so it doesn't always land
            # at the exact same time as other background services)
            jitter = random.uniform(-300, 300)
            await asyncio.sleep(RESEARCH_INTERVAL + jitter)

    # ── Single research cycle ──────────────────────────────────────────────────

    async def _research_cycle(self) -> None:
        self._cycle_count += 1
        topic = self._next_topic()
        logger.info("SkillResearcher cycle #%d: '%s'", self._cycle_count, topic)
        t0 = time.monotonic()

        # 1. Web search
        snippets = await self._search(topic)
        if not snippets:
            logger.warning("SkillResearcher: no search results for '%s'", topic)
            return

        # 2. LLM extraction
        raw_skills, model_used = await self._extract_skills(topic, snippets)
        logger.info("SkillResearcher: extracted %d skills from '%s'", len(raw_skills), topic)

        if not raw_skills:
            return

        # 3. Upsert into DB
        added = updated = 0
        for skill_data in raw_skills:
            try:
                result = await skills_db.upsert_skill(skill_data)
                if result["action"] == "created":
                    added += 1
                else:
                    updated += 1
            except Exception as exc:
                logger.warning("SkillResearcher: failed to upsert skill '%s': %s", skill_data.get("name", "?"), exc)

        # 4. Purge stale skills every 3 cycles
        purged = 0
        if self._cycle_count % 3 == 0:
            purged = await skills_db.purge_stale_skills(min_success_rate=0.3, min_runs=3)

        # 5. Record session
        await skills_db.record_research_session(topic, len(raw_skills), added, updated, model_used)

        elapsed = int(time.monotonic() - t0)
        self._last_report = {
            "cycle": self._cycle_count,
            "topic": topic,
            "skills_found": len(raw_skills),
            "skills_added": added,
            "skills_updated": updated,
            "skills_purged": purged,
            "model_used": model_used,
            "elapsed_seconds": elapsed,
            "timestamp": time.time(),
        }
        logger.info(
            "SkillResearcher cycle #%d done: +%d added, ~%d updated, -%d purged (%ds)",
            self._cycle_count, added, updated, purged, elapsed,
        )

    # ── Web search ─────────────────────────────────────────────────────────────

    async def _search(self, query: str, max_results: int = 8) -> List[Dict[str, Any]]:
        """Search with DuckDuckGo (free, no API key required)."""
        try:
            from duckduckgo_search import AsyncDDGS
            async with AsyncDDGS() as ddgs:
                results = await ddgs.atext(query, max_results=max_results)
                return [{"title": r.get("title",""), "snippet": r.get("body",""), "url": r.get("href","")} for r in results]
        except Exception as exc:
            logger.warning("SkillResearcher DDG search failed: %s", exc)
            # Fallback: try synchronous API
            try:
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=max_results))
                    return [{"title": r.get("title",""), "snippet": r.get("body",""), "url": r.get("href","")} for r in results]
            except Exception as exc2:
                logger.error("SkillResearcher search completely failed: %s", exc2)
                return []

    # ── LLM extraction ─────────────────────────────────────────────────────────

    async def _extract_skills(
        self, topic: str, snippets: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], str]:
        """Use LLM to extract structured skill definitions from search snippets."""
        snippets_text = "\n\n".join(
            f"[{i+1}] {s['title']}\nURL: {s['url']}\n{s['snippet']}"
            for i, s in enumerate(snippets)
        )

        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Research topic: {topic}\n\n"
                    f"Search results to analyze:\n{snippets_text}\n\n"
                    "Extract skill definitions as a JSON array. "
                    "Focus on revenue-generating and complex-task skills. "
                    "Return ONLY the JSON array, no preamble."
                ),
            },
        ]

        try:
            text, model, _ = await background_openrouter_client.chat_completion(
                messages=messages,
                task_type="analysis",
                quality=ModelQuality.FREE,
                max_tokens=3000,
                temperature=0.3,  # low temp for structured output
            )
            skills = self._parse_skill_json(text)
            return skills, model
        except Exception as exc:
            logger.error("SkillResearcher LLM extraction failed: %s", exc)
            return [], "failed"

    def _parse_skill_json(self, text: str) -> List[Dict[str, Any]]:
        """Parse the LLM output as a JSON array of skill objects."""
        text = text.strip()

        # Strip markdown fences
        if "```" in text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()

        # Find the JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            # Maybe a single object?
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    obj = json.loads(text[start:end+1])
                    return [obj] if isinstance(obj, dict) else []
                except Exception:
                    return []
            return []

        try:
            raw = json.loads(text[start:end+1])
            if not isinstance(raw, list):
                return []
            validated = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                if not item.get("name") or not item.get("description"):
                    continue
                # Sanitize name to snake_case slug
                item["name"] = re.sub(r"[^a-z0-9_]", "_", item["name"].lower())[:40].strip("_")
                # Validate enum fields
                item["category"] = item.get("category", "general") if item.get("category") in (
                    "revenue", "automation", "research", "writing", "coding", "communication", "data", "general"
                ) else "general"
                item["revenue_potential"] = item.get("revenue_potential", "none") if item.get("revenue_potential") in (
                    "none", "low", "medium", "high", "very_high"
                ) else "none"
                item["complexity"] = item.get("complexity", "intermediate") if item.get("complexity") in (
                    "beginner", "intermediate", "advanced"
                ) else "intermediate"
                validated.append(item)
            return validated
        except json.JSONDecodeError as exc:
            logger.warning("SkillResearcher JSON parse failed: %s | text[:200]=%s", exc, text[:200])
            return []

    # ── Topic rotation ─────────────────────────────────────────────────────────

    def _next_topic(self) -> str:
        topic = _RESEARCH_TOPICS[self._topic_index % len(_RESEARCH_TOPICS)]
        self._topic_index += 1
        return topic

    def stop(self) -> None:
        self._running = False


# Singleton
skill_researcher = SkillResearcherService()


async def skill_researcher_loop() -> None:
    """Top-level coroutine wired into FastAPI lifespan."""
    await skill_researcher.start()
