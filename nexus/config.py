"""Centralized configuration loaded from environment variables.

Uses pydantic-settings to validate and type-check all config at startup.
All secrets come from environment / .env — never hardcoded.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application-wide settings. Loaded once at startup via get_settings()."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime ──────────────────────────────────────────────
    env: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    payment_enabled: bool = False

    # ── Database ─────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nexus"
    db_user: str = "nexus"
    db_password: str = "changeme"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync connection string for Alembic migrations."""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── Redis ────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── LLM ──────────────────────────────────────────────────
    ollama_url: str = "http://localhost:11434"
    anthropic_api_key: str = ""
    hf_token: str = ""

    # ── Integrations ─────────────────────────────────────────
    sap_base_url: str = ""
    salesforce_url: str = ""
    slack_bot_token: str = ""
    smtp_host: str = "localhost"
    smtp_user: str = ""
    smtp_password: str = ""
    docusign_api_key: str = ""
    docusign_staging_key: str = ""

    # ── n8n ──────────────────────────────────────────────────
    n8n_user: str = "admin"
    n8n_password: str = ""

    # ── Grafana ──────────────────────────────────────────────
    grafana_password: str = ""

    # ── Computed helpers ─────────────────────────────────────
    @property
    def is_staging(self) -> bool:
        return self.env == Environment.STAGING

    @property
    def is_production(self) -> bool:
        return self.env == Environment.PRODUCTION

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance — cached after first call."""
    return Settings()
