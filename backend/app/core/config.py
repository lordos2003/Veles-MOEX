"""Application configuration via environment variables.

Secrets must never be hardcoded in source. They are supplied through the
environment (or a local ``.env`` file that is git-ignored). This module only
declares typed fields and defaults, and loads them through pydantic-settings.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    # Comma-separated list in env, or JSON array (see _parse_list_fields).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

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
    # When True the app runs live-execution recovery at startup and gates live
    # execution on it (reconciliation must be SAFE before new orders).
    live_trading_enabled: bool = False

    # --- Risk (execution gate limits, MVP-6.6) ---
    # Typed boundary for the RiskManager limits, separate from strategy
    # parameters. All optional: unset (None / empty) keeps the corresponding
    # check disabled. No financial defaults are invented.
    risk_max_position_size: float | None = None
    risk_daily_loss_limit: float | None = None
    risk_max_concurrent_bots: int | None = None
    risk_blocked_instruments: Annotated[list[str], NoDecode] = []

    # --- Live cycle scheduler (MVP-6.13 S2/S4) ---
    # Owner-approved operational timing/threshold parameters for tick timing
    # and the transient-failure policy. Ops values only, not financial ones.
    scheduler_bar_close_delay_seconds: float = 5.0
    scheduler_bar_close_retry_seconds: float = 5.0
    scheduler_bar_close_max_wait_seconds: float = 60.0
    scheduler_max_consecutive_failures: int = 3

    # --- Market snapshot (MVP-6.15 L2) ---
    # Operational search-depth limits for the backward fill of
    # ``get_snapshot``: the service searches at least this many calendar days
    # and at least ``snapshot_search_factor x lookback_bars x bar width``
    # back from "now" for real existing candles when the current window does
    # not contain ``lookback_bars`` candles. Ops parameters, not financial.
    snapshot_min_search_days: int = 14
    snapshot_search_factor: int = 4

    # --- Backtest (MVP-7.0 R7) ---
    # Ops limit for one API backtest run: the maximum number of candles a single
    # request may fetch. A search cap, not a financial value.
    backtest_max_candles: int = 10000

    @field_validator("cors_origins", "risk_blocked_instruments", mode="before")
    @classmethod
    def _parse_list_fields(cls, value: Any) -> Any:
        """Accept a comma-separated string or a JSON array (P3, MVP-7.3).

        Without ``NoDecode`` pydantic-settings insists that a list-typed env
        value is valid JSON and raises SettingsError on the .env.example value
        ``CORS_ORIGINS=http://localhost:5173``. With this validator the raw
        string is split on commas; JSON arrays and Python lists pass through.
        An empty/blank string means an empty list (so an unset or blank
        CORS/risk value never breaks startup).
        """
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list):
                    raise ValueError("expected a JSON array")
                return parsed
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
