"""
Settings API — lets the frontend push runtime configuration to the backend.
Keys are applied to the in-memory `settings` singleton immediately.
They are NOT written to .env (restart reverts to .env values).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    hyperbrowser_api_key: Optional[str] = None
    wavespeed_api_key: Optional[str] = None
    google_maps_api_key: Optional[str] = None
    huggingface_api_key: Optional[str] = None
    serp_api_key: Optional[str] = None
    fal_api_key: Optional[str] = None
    heygen_api_key: Optional[str] = None
    agentmail_api_key: Optional[str] = None
    ghost_database_url: Optional[str] = None
    stripe_secret_key: Optional[str] = None
    stripe_publishable_key: Optional[str] = None
    stripe_webhook_secret: Optional[str] = None


@router.post("")
async def update_settings(body: SettingsUpdate) -> dict:
    """Apply runtime settings overrides (in-memory only)."""
    updated: list[str] = []

    if body.openrouter_api_key is not None:
        settings.openrouter_api_key = body.openrouter_api_key
        # Keep the openrouter client in sync
        try:
            from app.services.openrouter import openrouter_client
            openrouter_client._api_key = body.openrouter_api_key
        except Exception:
            pass
        updated.append("openrouter_api_key")

    if body.hyperbrowser_api_key is not None:
        settings.hyperbrowser_api_key = body.hyperbrowser_api_key
        updated.append("hyperbrowser_api_key")

    if body.wavespeed_api_key is not None:
        settings.wavespeed_api_key = body.wavespeed_api_key
        updated.append("wavespeed_api_key")

    if body.google_maps_api_key is not None:
        settings.google_maps_api_key = body.google_maps_api_key
        updated.append("google_maps_api_key")

    if body.huggingface_api_key is not None:
        settings.huggingface_api_key = body.huggingface_api_key
        updated.append("huggingface_api_key")

    if body.serp_api_key is not None:
        settings.serp_api_key = body.serp_api_key
        updated.append("serp_api_key")

    if body.fal_api_key is not None:
        settings.fal_api_key = body.fal_api_key
        updated.append("fal_api_key")

    if body.heygen_api_key is not None:
        settings.heygen_api_key = body.heygen_api_key
        updated.append("heygen_api_key")

    if body.agentmail_api_key is not None:
        settings.agentmail_api_key = body.agentmail_api_key
        try:
            from app.services.agentmail_service import agentmail_service
            agentmail_service._api_key = body.agentmail_api_key
        except Exception:
            pass
        updated.append("agentmail_api_key")

    if body.ghost_database_url is not None:
        settings.ghost_database_url = body.ghost_database_url
        updated.append("ghost_database_url")

    if body.stripe_secret_key is not None:
        settings.stripe_secret_key = body.stripe_secret_key
        updated.append("stripe_secret_key")

    if body.stripe_publishable_key is not None:
        settings.stripe_publishable_key = body.stripe_publishable_key
        updated.append("stripe_publishable_key")

    if body.stripe_webhook_secret is not None:
        settings.stripe_webhook_secret = body.stripe_webhook_secret
        updated.append("stripe_webhook_secret")

    return {"ok": True, "updated": updated}


@router.get("")
async def get_settings_status() -> dict:
    """Return which API keys are configured (boolean only — never expose values)."""
    return {
        "openrouter": bool(settings.openrouter_api_key),
        "hyperbrowser": bool(settings.hyperbrowser_api_key),
        "wavespeed": bool(settings.wavespeed_api_key),
        "google_maps": bool(settings.google_maps_api_key),
        "huggingface": bool(settings.huggingface_api_key),
        "serp_api": bool(settings.serp_api_key),
        "fal": bool(settings.fal_api_key),
        "heygen": bool(settings.heygen_api_key),
        "agentmail": bool(settings.agentmail_api_key),
        "ghost_db": bool(settings.ghost_database_url),
        "stripe": bool(settings.stripe_secret_key),
    }
