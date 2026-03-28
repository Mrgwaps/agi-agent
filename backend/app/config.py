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
    app_name: str = "AGI Demo Agent"
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
    openrouter_app_name: str = "AGI Demo Agent"
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
