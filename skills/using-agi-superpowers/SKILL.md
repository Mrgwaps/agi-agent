---
name: using-agi-superpowers
description: Use when working with the AGI Agent platform to discover and apply elite agent skills - activates the master skill library for revenue generation, automation, and complex task completion
---

# AGI Agent Superpowers

The AGI Agent has a continuously-growing master skills library (SQLite + SKILL.md format, inspired by obra/superpowers) that is autonomously researched and updated every 2 hours using free LLM models and DuckDuckGo search.

## Skill Categories

| Category | Description | Revenue Potential |
|---|---|---|
| `revenue` | Fiverr gigs, Upwork proposals, digital products, cold email, SEO | High–Very High |
| `automation` | Web scraping, API integration, workflow automation | High–Very High |
| `research` | Market research, competitive analysis, intelligence reports | High |
| `writing` | Content creation, SEO articles, social media, copy | Medium–High |
| `coding` | Software development, scripts, automation pipelines | High |
| `communication` | Email outreach, agent-to-agent, platform signups | Medium |
| `data` | Data extraction, analysis, visualization | Medium–High |

## How to Use the Skills Library

### Browse Available Skills
```
GET /api/skills                          # all skills
GET /api/skills?category=revenue         # filter by category
GET /api/skills?revenue_potential=high   # filter by revenue
GET /api/skills/stats                    # dashboard summary
GET /api/skills/recent                   # latest discoveries
```

### Trigger a Research Cycle
```
POST /api/skills/research/trigger        # discover new skills now
GET  /api/skills/research/status         # check cycle status
```

### Apply a Skill to an Agent Task
When creating a task, reference the skill's `system_prompt` field to prime the agent:
1. Fetch the skill: `GET /api/skills/{name}`
2. Use `skill.system_prompt` as the agent's system prompt
3. Combine with the task goal in the user message

## Mandatory Skill-Checking Protocol

Before executing any revenue-generating task, the agent MUST:
1. Check `/api/skills?category=revenue` for applicable skills
2. Select the skill with highest `revenue_potential` and `success_rate` for the task type
3. Apply the skill's `system_prompt` as context
4. Record the outcome via `POST /api/skills/{id}/run` to improve success rates

## Skill Discovery Loop

The `SkillResearcherService` runs perpetually:
- **Interval**: every 2 hours
- **Method**: DuckDuckGo search (free) → deepseek-r1:free analysis (free) → structured extraction
- **Topics**: 25 rotating queries covering income generation, automation, complex tasks
- **Stale purge**: deactivates skills with < 30% success rate after 3+ runs
- **Heartbeat integration**: new skills appear in the 30-min revenue intelligence brief

## Key Files

| File | Purpose |
|---|---|
| `backend/app/services/skills_db.py` | SQLite master store, seed skills, SKILL.md export |
| `backend/app/services/skill_researcher.py` | Perpetual background researcher |
| `backend/app/api/skills.py` | REST API for skill CRUD |
| `skills/` | SKILL.md files (superpowers format, auto-generated) |
| `frontend/src/components/SkillsPanel.tsx` | Dashboard UI panel |

## Revenue-Focused Seed Skills

The following skills are pre-loaded at startup:

1. **fiverr_gig_creation** — Craft optimized Fiverr gigs that convert (revenue: high)
2. **upwork_proposal_writer** — Write winning Upwork proposals with 98% JSS framing (revenue: high)
3. **digital_product_ideation** — Validate digital products against market demand (revenue: very_high)
4. **seo_content_strategy** — Keyword research + full SEO article pipeline (revenue: high)
5. **cold_email_outreach** — 5-email sequences with 35%+ reply rate patterns (revenue: very_high)
6. **ai_prompt_marketplace** — Engineer + sell prompts on PromptBase/Etsy (revenue: medium)
7. **web_scraping_data_extraction** — Build production scrapers for monetizable data (revenue: high)
8. **api_integration_automation** — Connect APIs into 24/7 revenue workflows (revenue: very_high)
9. **market_research_report** — Professional research reports for consulting revenue (revenue: high)
10. **social_media_content_engine** — 30-day content calendars from a single topic (revenue: medium)
