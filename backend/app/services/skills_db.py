"""
Master Skills Database — persistent SQLite store for agent superpowers.

Inspired by the obra/superpowers framework: each skill is a named, tested
capability that an agent can invoke.  Skills are discovered by the
SkillResearcherService, validated, and stored here.

Schema is designed to be compatible with the superpowers framework concept:
  - name              : unique slug (e.g. "fiverr_gig_creation")
  - title             : human-readable name
  - category          : revenue | automation | research | writing | coding | communication
  - description       : what the skill does
  - system_prompt     : the prompt template that activates the skill
  - tool_hints        : comma-separated tool names the skill leverages
  - revenue_potential : none | low | medium | high | very_high
  - complexity        : beginner | intermediate | advanced
  - tags              : comma-separated keywords
  - source_url        : where this skill was discovered
  - tested_at         : last validation timestamp
  - success_rate      : 0.0–1.0 (1.0 = always works)
  - use_count         : times this skill has been used
  - is_active         : whether the skill is currently enabled
  - created_at        : first discovery
  - updated_at        : last update
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Use system temp dir — works on Windows, Linux, macOS
_DB_PATH = Path(tempfile.gettempdir()) / "agi_skills.db"
_lock = asyncio.Lock()

# Directory where SKILL.md files are written (superpowers-compatible format)
# __file__ = backend/app/services/skills_db.py → parents[3] = project root
_SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
_SKILLS_DIR.mkdir(exist_ok=True)


def _write_skill_md(skill: Dict[str, Any]) -> None:
    """
    Write (or overwrite) a SKILL.md file for a skill in the superpowers format.

    Directory: skills/{name}/SKILL.md
    Format:
        ---
        name: <slug>
        description: Use when <description> - activates <title>
        ---
        # <title>
        ...full markdown content...
    """
    name = skill.get("name", "")
    if not name:
        return
    skill_dir = _SKILLS_DIR / name
    skill_dir.mkdir(exist_ok=True)
    skill_file = skill_dir / "SKILL.md"

    title = skill.get("title", name.replace("_", " ").title())
    description = skill.get("description", "")
    system_prompt = skill.get("system_prompt", "")
    category = skill.get("category", "general")
    revenue = skill.get("revenue_potential", "none")
    complexity = skill.get("complexity", "intermediate")
    tags = skill.get("tags", "")
    tool_hints = skill.get("tool_hints", "")
    source_url = skill.get("source_url", "")

    # Superpowers frontmatter: description triggers skill activation
    frontmatter_desc = f"Use when performing {category} tasks or needing {title.lower()} - {description[:120]}"

    content = f"""---
name: {name}
description: {frontmatter_desc}
---

# {title}

> **Category:** {category} | **Revenue Potential:** {revenue.replace('_', ' ').title()} | **Complexity:** {complexity.title()}

## What This Skill Does

{description}

## System Prompt (Activates This Skill)

```
{system_prompt}
```

## When to Use

- Task involves {category} work
- Revenue potential is {revenue.replace('_', ' ')}
- Tags: {tags}
{"- Recommended tools: " + tool_hints if tool_hints else ""}

## Usage

Apply this skill by using the system prompt above as your agent's system context.
The prompt is designed to prime the LLM for elite-level execution of {title.lower()} tasks.
{"" if not source_url else chr(10) + "## Source" + chr(10) + chr(10) + source_url}
"""
    try:
        skill_file.write_text(content.strip(), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write SKILL.md for '%s': %s", name, exc)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT UNIQUE NOT NULL,
                title            TEXT NOT NULL,
                category         TEXT NOT NULL DEFAULT 'general',
                description      TEXT NOT NULL,
                system_prompt    TEXT NOT NULL DEFAULT '',
                tool_hints       TEXT NOT NULL DEFAULT '',
                revenue_potential TEXT NOT NULL DEFAULT 'none',
                complexity       TEXT NOT NULL DEFAULT 'intermediate',
                tags             TEXT NOT NULL DEFAULT '',
                source_url       TEXT NOT NULL DEFAULT '',
                tested_at        REAL,
                success_rate     REAL NOT NULL DEFAULT 0.0,
                use_count        INTEGER NOT NULL DEFAULT 0,
                is_active        INTEGER NOT NULL DEFAULT 1,
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS skills_category_idx ON skills(category);
            CREATE INDEX IF NOT EXISTS skills_revenue_idx  ON skills(revenue_potential);
            CREATE INDEX IF NOT EXISTS skills_active_idx   ON skills(is_active);

            CREATE TABLE IF NOT EXISTS skill_runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id   INTEGER REFERENCES skills(id) ON DELETE CASCADE,
                task_id    TEXT,
                success    INTEGER NOT NULL DEFAULT 1,
                notes      TEXT,
                ran_at     REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                query        TEXT NOT NULL,
                skills_found INTEGER NOT NULL DEFAULT 0,
                skills_added INTEGER NOT NULL DEFAULT 0,
                skills_updated INTEGER NOT NULL DEFAULT 0,
                model_used   TEXT NOT NULL DEFAULT '',
                ran_at       REAL NOT NULL
            );
        """)


# Ensure schema on module load
_ensure_schema()


class SkillsDB:
    """Thread-safe async wrapper around the SQLite skills store."""

    # ── Write ──────────────────────────────────────────────────────────────────

    async def upsert_skill(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert or update a skill.  If a skill with the same `name` exists,
        update its fields (preserving use_count and success_rate unless supplied).

        Returns {action: 'created'|'updated', skill_id}.
        """
        now = time.time()
        async with _lock:
            with _get_conn() as conn:
                existing = conn.execute(
                    "SELECT id, success_rate, use_count FROM skills WHERE name = ?",
                    (skill["name"],),
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE skills SET
                            title             = ?,
                            category          = ?,
                            description       = ?,
                            system_prompt     = ?,
                            tool_hints        = ?,
                            revenue_potential = ?,
                            complexity        = ?,
                            tags              = ?,
                            source_url        = ?,
                            tested_at         = ?,
                            success_rate      = ?,
                            is_active         = 1,
                            updated_at        = ?
                        WHERE name = ?
                    """, (
                        skill.get("title", skill["name"]),
                        skill.get("category", "general"),
                        skill.get("description", ""),
                        skill.get("system_prompt", ""),
                        skill.get("tool_hints", ""),
                        skill.get("revenue_potential", "none"),
                        skill.get("complexity", "intermediate"),
                        skill.get("tags", ""),
                        skill.get("source_url", ""),
                        skill.get("tested_at", now),
                        skill.get("success_rate", existing["success_rate"]),
                        now,
                        skill["name"],
                    ))
                    _write_skill_md(skill)
                    return {"action": "updated", "skill_id": existing["id"]}
                else:
                    cur = conn.execute("""
                        INSERT INTO skills
                            (name, title, category, description, system_prompt,
                             tool_hints, revenue_potential, complexity, tags,
                             source_url, tested_at, success_rate, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        skill["name"],
                        skill.get("title", skill["name"]),
                        skill.get("category", "general"),
                        skill.get("description", ""),
                        skill.get("system_prompt", ""),
                        skill.get("tool_hints", ""),
                        skill.get("revenue_potential", "none"),
                        skill.get("complexity", "intermediate"),
                        skill.get("tags", ""),
                        skill.get("source_url", ""),
                        skill.get("tested_at", now),
                        skill.get("success_rate", 0.8),
                        now,
                        now,
                    ))
                    _write_skill_md(skill)
                    return {"action": "created", "skill_id": cur.lastrowid}

    async def record_run(self, skill_id: int, success: bool, task_id: str = "", notes: str = "") -> None:
        """Record a skill execution and update its success_rate."""
        async with _lock:
            with _get_conn() as conn:
                conn.execute("""
                    INSERT INTO skill_runs (skill_id, task_id, success, notes, ran_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (skill_id, task_id, int(success), notes, time.time()))

                # Recalculate rolling success rate (last 20 runs)
                rows = conn.execute("""
                    SELECT AVG(success) as rate FROM (
                        SELECT success FROM skill_runs
                        WHERE skill_id = ?
                        ORDER BY ran_at DESC LIMIT 20
                    )
                """, (skill_id,)).fetchone()
                if rows and rows["rate"] is not None:
                    conn.execute("""
                        UPDATE skills SET
                            success_rate = ?,
                            use_count    = use_count + 1,
                            updated_at   = ?
                        WHERE id = ?
                    """, (rows["rate"], time.time(), skill_id))

    async def deactivate_skill(self, skill_id: int, reason: str = "") -> None:
        async with _lock:
            with _get_conn() as conn:
                row = conn.execute("SELECT name FROM skills WHERE id = ?", (skill_id,)).fetchone()
                conn.execute(
                    "UPDATE skills SET is_active = 0, updated_at = ? WHERE id = ?",
                    (time.time(), skill_id),
                )
                # Remove SKILL.md so it disappears from the superpowers directory
                if row:
                    skill_file = _SKILLS_DIR / row["name"] / "SKILL.md"
                    try:
                        skill_file.unlink(missing_ok=True)
                    except Exception:
                        pass
        logger.info("Skill %d deactivated: %s", skill_id, reason)

    async def purge_stale_skills(self, min_success_rate: float = 0.3, min_runs: int = 3) -> int:
        """
        Deactivate skills with poor success rates after enough test runs.
        Returns number of skills deactivated.
        """
        async with _lock:
            with _get_conn() as conn:
                rows = conn.execute("""
                    SELECT s.id, s.name, s.success_rate, COUNT(r.id) as run_count
                    FROM skills s
                    LEFT JOIN skill_runs r ON r.skill_id = s.id
                    WHERE s.is_active = 1
                    GROUP BY s.id
                    HAVING run_count >= ? AND s.success_rate < ?
                """, (min_runs, min_success_rate)).fetchall()

                for row in rows:
                    conn.execute(
                        "UPDATE skills SET is_active = 0, updated_at = ? WHERE id = ?",
                        (time.time(), row["id"]),
                    )
                    logger.info(
                        "Purged stale skill '%s' (success_rate=%.0f%%, runs=%d)",
                        row["name"], row["success_rate"] * 100, row["run_count"],
                    )
                return len(rows)

    async def record_research_session(
        self, query: str, found: int, added: int, updated: int, model: str
    ) -> None:
        async with _lock:
            with _get_conn() as conn:
                conn.execute("""
                    INSERT INTO research_sessions
                        (query, skills_found, skills_added, skills_updated, model_used, ran_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (query, found, added, updated, model, time.time()))

    # ── Read ───────────────────────────────────────────────────────────────────

    async def list_skills(
        self,
        category: Optional[str] = None,
        revenue_potential: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        async with _lock:
            with _get_conn() as conn:
                where_clauses = []
                params: List[Any] = []
                if active_only:
                    where_clauses.append("is_active = 1")
                if category:
                    where_clauses.append("category = ?")
                    params.append(category)
                if revenue_potential:
                    where_clauses.append("revenue_potential = ?")
                    params.append(revenue_potential)
                where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
                params.append(limit)
                rows = conn.execute(
                    f"SELECT * FROM skills {where} ORDER BY revenue_potential DESC, success_rate DESC LIMIT ?",
                    params,
                ).fetchall()
                return [dict(r) for r in rows]

    async def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        async with _lock:
            with _get_conn() as conn:
                row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
                return dict(row) if row else None

    async def get_stats(self) -> Dict[str, Any]:
        async with _lock:
            with _get_conn() as conn:
                total = conn.execute("SELECT COUNT(*) as n FROM skills").fetchone()["n"]
                active = conn.execute("SELECT COUNT(*) as n FROM skills WHERE is_active = 1").fetchone()["n"]
                by_cat = conn.execute("""
                    SELECT category, COUNT(*) as n FROM skills WHERE is_active = 1
                    GROUP BY category ORDER BY n DESC
                """).fetchall()
                by_rev = conn.execute("""
                    SELECT revenue_potential, COUNT(*) as n FROM skills WHERE is_active = 1
                    GROUP BY revenue_potential ORDER BY n DESC
                """).fetchall()
                top = conn.execute("""
                    SELECT name, title, revenue_potential, success_rate
                    FROM skills WHERE is_active = 1
                    ORDER BY success_rate DESC, use_count DESC LIMIT 5
                """).fetchall()
                last_session = conn.execute("""
                    SELECT * FROM research_sessions ORDER BY ran_at DESC LIMIT 1
                """).fetchone()
                return {
                    "total_skills": total,
                    "active_skills": active,
                    "by_category": {r["category"]: r["n"] for r in by_cat},
                    "by_revenue_potential": {r["revenue_potential"]: r["n"] for r in by_rev},
                    "top_skills": [dict(r) for r in top],
                    "last_research_session": dict(last_session) if last_session else None,
                }

    async def get_recent_skills(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recently added/updated active skills."""
        async with _lock:
            with _get_conn() as conn:
                rows = conn.execute("""
                    SELECT name, title, category, revenue_potential, description, updated_at
                    FROM skills WHERE is_active = 1
                    ORDER BY updated_at DESC LIMIT ?
                """, (limit,)).fetchall()
                return [dict(r) for r in rows]


# Singleton
skills_db = SkillsDB()


# ── Seed with foundational superpowers-style skills ────────────────────────────

SEED_SKILLS: List[Dict[str, Any]] = [
    {
        "name": "fiverr_gig_creation",
        "title": "Fiverr Gig Creation & Optimization",
        "category": "revenue",
        "description": "Research top-performing Fiverr gigs in a niche, craft a compelling title/description/tags, set competitive pricing, and generate a gig creation checklist.",
        "system_prompt": "You are an elite Fiverr marketplace expert. Analyze the niche, identify top-performing gig patterns, and produce optimized gig content that converts browsers into buyers. Focus on: keyword-rich titles, benefit-driven descriptions, clear deliverables, competitive pricing tiers, and upsell opportunities.",
        "tool_hints": "enhanced_search,content_writer",
        "revenue_potential": "high",
        "complexity": "beginner",
        "tags": "freelancing,fiverr,gig,marketplace,income",
        "source_url": "https://fiverr.com",
        "success_rate": 0.85,
    },
    {
        "name": "upwork_proposal_writer",
        "title": "Upwork Winning Proposal Writer",
        "category": "revenue",
        "description": "Analyze a job posting and generate a high-converting Upwork proposal that speaks directly to client pain points, demonstrates expertise, and includes a tailored action plan.",
        "system_prompt": "You are a top-rated Upwork freelancer with a 98% job success score. Write proposals that win. Your proposals: open with a hook that proves you read the job, address the client's core problem immediately, demonstrate relevant experience with specifics, propose a clear solution, and end with a confident call to action. Keep proposals under 200 words.",
        "tool_hints": "content_writer",
        "revenue_potential": "high",
        "complexity": "intermediate",
        "tags": "freelancing,upwork,proposal,client,income",
        "source_url": "https://upwork.com",
        "success_rate": 0.80,
    },
    {
        "name": "digital_product_ideation",
        "title": "Digital Product Ideation & Validation",
        "category": "revenue",
        "description": "Research market demand for digital products (ebooks, templates, courses, SaaS), validate with search trends and competitor analysis, and produce a ranked opportunity list.",
        "system_prompt": "You are a digital product strategist who specializes in identifying under-served market gaps. For any niche, you: (1) identify the top 5 pain points via search intent analysis, (2) map those to monetizable digital products, (3) estimate market size and competition, (4) rank opportunities by effort-to-revenue ratio. Output a prioritized product roadmap.",
        "tool_hints": "enhanced_search,web_researcher",
        "revenue_potential": "very_high",
        "complexity": "intermediate",
        "tags": "digital products,ebook,course,saas,passive income",
        "source_url": "https://gumroad.com",
        "success_rate": 0.82,
    },
    {
        "name": "seo_content_strategy",
        "title": "SEO Content Strategy & Article Writing",
        "category": "revenue",
        "description": "Identify low-competition, high-intent keywords, create an SEO content plan, and write fully optimized articles that rank and generate affiliate/ad revenue.",
        "system_prompt": "You are an expert SEO strategist and content writer. Your articles rank on page 1 because you: target long-tail keywords with buying intent, structure content with clear H2/H3 hierarchy, answer the search query within the first 100 words, use internal linking strategy, and include a compelling CTA. Output: keyword analysis, outline, and full article draft.",
        "tool_hints": "enhanced_search,content_writer,web_researcher",
        "revenue_potential": "high",
        "complexity": "intermediate",
        "tags": "seo,content,blogging,affiliate,passive income",
        "source_url": "https://ahrefs.com/blog",
        "success_rate": 0.78,
    },
    {
        "name": "cold_email_outreach",
        "title": "Cold Email Outreach Campaign",
        "category": "revenue",
        "description": "Research target prospects, craft personalized cold email sequences, and generate a follow-up cadence that books calls and generates leads.",
        "system_prompt": "You are a B2B sales expert with a 35%+ reply rate on cold emails. Your emails are: hyper-personalized (reference specific company details), value-first (lead with insight not pitch), ultra-concise (under 75 words), and have a single clear ask. Generate a 5-email sequence with subject lines, preview text, and timing recommendations.",
        "tool_hints": "email,enhanced_search,content_writer",
        "revenue_potential": "very_high",
        "complexity": "intermediate",
        "tags": "sales,outreach,email,leads,b2b",
        "source_url": "https://close.com/blog",
        "success_rate": 0.75,
    },
    {
        "name": "ai_prompt_marketplace",
        "title": "AI Prompt Engineering & Marketplace Sales",
        "category": "revenue",
        "description": "Design high-value prompt templates for specific use cases, package them for sale on PromptBase/Etsy, and write compelling marketplace listings.",
        "system_prompt": "You are an elite prompt engineer who sells prompts on PromptBase. You create prompts that: solve a specific, recurring problem, produce consistently high-quality outputs, have clear instructions and examples, and are priced based on the value they deliver. Output: the prompt itself, a marketplace title, description, and pricing recommendation.",
        "tool_hints": "content_writer",
        "revenue_potential": "medium",
        "complexity": "beginner",
        "tags": "prompts,promptbase,ai,passive income,marketplace",
        "source_url": "https://promptbase.com",
        "success_rate": 0.90,
    },
    {
        "name": "web_scraping_data_extraction",
        "title": "Web Scraping & Data Extraction Pipeline",
        "category": "automation",
        "description": "Build automated web scrapers to extract structured data from websites, clean it, and deliver it in usable formats (CSV, JSON, database).",
        "system_prompt": "You are a data engineering expert specializing in web scraping. You: identify the most efficient scraping approach for a target site, handle pagination/dynamic content, implement rate limiting and error handling, clean and normalize extracted data, and output production-ready Python code using httpx/BeautifulSoup/playwright.",
        "tool_hints": "code_executor,hyperbrowser",
        "revenue_potential": "high",
        "complexity": "advanced",
        "tags": "scraping,data,automation,python,pipeline",
        "source_url": "https://github.com/obra/superpowers",
        "success_rate": 0.80,
    },
    {
        "name": "api_integration_automation",
        "title": "API Integration & Workflow Automation",
        "category": "automation",
        "description": "Connect disparate APIs and build automated workflows that replace manual tasks, trigger on events, and operate 24/7 without human intervention.",
        "system_prompt": "You are an automation architect. For any workflow automation request, you: map the trigger → action → output flow, identify the optimal APIs/tools, handle authentication securely, implement retry and error handling, and produce working code with documentation. Favor webhook-driven architectures over polling.",
        "tool_hints": "code_executor,email",
        "revenue_potential": "very_high",
        "complexity": "advanced",
        "tags": "api,automation,workflow,integration,zapier",
        "source_url": "https://n8n.io",
        "success_rate": 0.85,
    },
    {
        "name": "market_research_report",
        "title": "Market Research & Competitive Analysis Report",
        "category": "research",
        "description": "Conduct deep market research on any industry or niche, analyze competitors, identify opportunities, and deliver a professional report with actionable insights.",
        "system_prompt": "You are a market research analyst at a top consultancy. Your reports are data-driven and actionable. Structure: Executive Summary → Market Size & Growth → Key Players & Competitive Landscape → Customer Pain Points → Opportunities & Gaps → Recommendations. Use specific numbers, cite sources, and highlight the top 3 actionable opportunities.",
        "tool_hints": "web_researcher,enhanced_search,content_writer",
        "revenue_potential": "high",
        "complexity": "intermediate",
        "tags": "research,market analysis,consulting,report,business intelligence",
        "source_url": "https://statista.com",
        "success_rate": 0.88,
    },
    {
        "name": "social_media_content_engine",
        "title": "Social Media Content Engine",
        "category": "revenue",
        "description": "Generate a month's worth of platform-optimized social media content (Twitter/X threads, LinkedIn posts, Instagram captions) from a single topic brief.",
        "system_prompt": "You are a social media strategist with 1M+ followers across platforms. You know that: Twitter/X thrives on contrarian takes and thread storytelling, LinkedIn rewards professional vulnerability and insights, Instagram needs visual hooks and hashtag strategy. From a single topic, generate a 30-day content calendar with platform-specific copy, optimal posting times, and engagement prompts.",
        "tool_hints": "content_writer",
        "revenue_potential": "medium",
        "complexity": "beginner",
        "tags": "social media,content,twitter,linkedin,marketing",
        "source_url": "https://buffer.com",
        "success_rate": 0.90,
    },
]


async def seed_initial_skills() -> None:
    """Insert foundational skills on first run (skips existing)."""
    added = 0
    for skill in SEED_SKILLS:
        result = await skills_db.upsert_skill(skill)
        if result["action"] == "created":
            added += 1
    if added:
        logger.info("Skills DB seeded with %d foundational skills", added)
