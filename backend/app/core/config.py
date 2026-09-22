"""Application configuration via environment variables.

Secrets must never be hardcoded in source. They are supplied through the
environment (or a local ``.env`` file that is git-ignored). This module only
declares typed fields and defaults, and loads them through pydantic-settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables (prefix ``VELES_`` optional)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "Veles-MOEX"
    environment: str = "development"
    api_v1_prefix: str = "/api"

    # --- Infrastructure ---
    # SQLAlchemy async URL. Default targets local docker-compose PostgreSQL.
    database_url: str = "postgresql+asyncpg://veles:veles@localhost:5432/veles_moex"
    redis_url: str = "redis://localhost:6379/0"

    # --- CORS ---
    # Comma-separated list in env, or JSON array. Parsed by pydantic-settings.
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- T-Invest ---
    # API token. Must come from the environment, never from source. If empty the
    # integration is reported as "not_configured" rather than failing startup.
    tinvest_token: str | None = None
    # Official prod REST endpoint. Sandbox is available for testing.
    tinvest_base_url: str = "https://invest-public-api.tbank.ru/rest"
    # When True the adapter targets the T-Invest sandbox (no real money).
    tinvest_sandbox: bool = False
    # Optional WebSocket stream endpoint. Defaults to wss://.../ws derived from
    # the REST base url when unset.
    tinvest_stream_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
