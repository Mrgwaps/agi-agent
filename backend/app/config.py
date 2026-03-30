from __future__ import annotations

import os
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "AGI Agent"
    debug: bool = False
    log_level: str = "INFO"

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: List[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_name: str = "AGI Agent"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_default_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_planning_model: str = "google/gemma-3-27b-it:free"
    openrouter_code_model: str = "deepseek/deepseek-r1:free"
    openrouter_web_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_prefer_free: bool = True
    openrouter_max_budget_usd: float = 1.0

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_enabled: bool = True
    ollama_default_model: str = "llama3.2"
    ollama_timeout: int = 120

    # ── Hyperbrowser ─────────────────────────────────────────────────────────
    hyperbrowser_api_key: str = Field(default="", alias="HYPERBROWSER_API_KEY")
    hyperbrowser_base_url: str = "https://api.hyperbrowser.ai"

    # ── WaveSpeed AI (image / video generation) ───────────────────────────────
    wavespeed_api_key: str = Field(default="", alias="WAVESPEED_API_KEY")
    wavespeed_base_url: str = "https://api.wavespeed.ai/api/v2"

    # ── Google Maps ───────────────────────────────────────────────────────────
    google_maps_api_key: str = Field(default="", alias="GOOGLE_MAPS_API_KEY")

    # ── Hugging Face ──────────────────────────────────────────────────────────
    huggingface_api_key: str = Field(default="", alias="HUGGINGFACE_API_KEY")
    huggingface_base_url: str = "https://api-inference.huggingface.co"

    # ── SerpAPI ───────────────────────────────────────────────────────────────
    serp_api_key: str = Field(default="", alias="SERP_API_KEY")

    # ── fal.ai (Kokoro TTS, image generation) ────────────────────────────────
    fal_api_key: str = Field(default="", alias="FAL_API_KEY")

    # ── HeyGen (Interactive Avatar) ───────────────────────────────────────────
    heygen_api_key: str = Field(default="", alias="HEYGEN_API_KEY")

    # ── AgentMail (agent email inboxes) ──────────────────────────────────────
    agentmail_api_key: str = Field(default="", alias="AGENTMAIL_API_KEY")

    # ── Ghost.build (forkable managed Postgres for agents) ────────────────────
    # Set GHOST_DATABASE_URL to the postgres:// connection string from `ghost database create`
    ghost_database_url: str = Field(default="", alias="GHOST_DATABASE_URL")

    # ── Stripe ────────────────────────────────────────────────────────────────
    stripe_secret_key: str = Field(default="", alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str = Field(default="", alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: str = Field(default="", alias="STRIPE_WEBHOOK_SECRET")

    # ── Database ──────────────────────────────────────────────────────────────
    postgres_url: str = Field(
        default="postgresql://agi:agi@localhost:5432/agi_agent",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
    )

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "agi_agent_memory"
    chroma_persist_directory: str = "/tmp/chroma_data"

    # ── Workspace ────────────────────────────────────────────────────────────
    workspace_root: str = "/tmp/agi_workspace"

    # ── Telemetry ────────────────────────────────────────────────────────────
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "agi-agent-backend"

    # ── Task defaults ─────────────────────────────────────────────────────────
    task_max_steps: int = 20
    task_max_retries: int = 3
    task_step_timeout: int = 120


settings = Settings()
