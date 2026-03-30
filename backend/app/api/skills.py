"""
Skills API — expose the master Skills DB to the frontend and other services.

Routes:
  GET  /skills                  — list skills (filter by category, revenue_potential)
  GET  /skills/stats            — summary stats for dashboard
  GET  /skills/recent           — recently added/updated skills
  GET  /skills/{name}           — get a specific skill
  POST /skills                  — manually add a skill
  POST /skills/research/trigger — trigger an immediate research cycle
  GET  /skills/research/status  — last research cycle report
  DELETE /skills/{name}         — deactivate a skill
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.skills_db import skills_db
from app.services.skill_researcher import skill_researcher

router = APIRouter(prefix="/skills", tags=["skills"])


# ── Request models ─────────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str
    title: str
    category: str = "general"
    description: str
    system_prompt: str = ""
    tool_hints: str = ""
    revenue_potential: str = "none"
    complexity: str = "intermediate"
    tags: str = ""
    source_url: str = ""
    success_rate: float = 0.8


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_skills(
    category: Optional[str] = None,
    revenue_potential: Optional[str] = None,
    active_only: bool = True,
    limit: int = 100,
):
    """List skills with optional filters."""
    skills = await skills_db.list_skills(
        category=category,
        revenue_potential=revenue_potential,
        active_only=active_only,
        limit=limit,
    )
    return {"success": True, "skills": skills, "count": len(skills)}


@router.get("/stats")
async def skills_stats():
    """Dashboard summary: total skills, by-category, top earners, last research session."""
    return await skills_db.get_stats()


@router.get("/recent")
async def recent_skills(limit: int = 10):
    """Most recently discovered or updated skills."""
    skills = await skills_db.get_recent_skills(limit=limit)
    return {"success": True, "skills": skills}


@router.get("/research/status")
async def research_status():
    """Status of the last skill research cycle."""
    report = skill_researcher.get_last_report()
    stats = await skills_db.get_stats()
    return {
        "running": skill_researcher._running,
        "cycles_completed": skill_researcher._cycle_count,
        "last_cycle": report,
        "db_stats": stats,
    }


@router.post("/research/trigger")
async def trigger_research(background_tasks: BackgroundTasks):
    """Manually trigger an immediate research cycle (runs in background)."""
    async def _run():
        try:
            await skill_researcher._research_cycle()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Manual research cycle failed: %s", exc)

    background_tasks.add_task(_run)
    return {"success": True, "message": "Research cycle triggered in background"}


@router.get("/{name}")
async def get_skill(name: str):
    skill = await skills_db.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {"success": True, "skill": skill}


@router.post("")
async def create_skill(req: SkillCreate):
    """Manually add or update a skill in the master DB."""
    result = await skills_db.upsert_skill(req.model_dump())
    return {"success": True, **result}


@router.delete("/{name}")
async def deactivate_skill(name: str):
    """Deactivate a skill (soft delete)."""
    skill = await skills_db.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    await skills_db.deactivate_skill(skill["id"], reason="manual deactivation via API")
    return {"success": True, "message": f"Skill '{name}' deactivated"}
