"""Pydantic schemas for the strategies REST API (MVP-7.0 R4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.strategies.config import StrategyConfig


class StrategyCreate(BaseModel):
    """Create a strategy with an initial immutable version (v1)."""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    config: StrategyConfig


class StrategyUpdate(BaseModel):
    """Update strategy metadata and/or the configuration.

    A new configuration creates a new immutable version (version + 1);
    existing versions are never mutated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    config: StrategyConfig | None = None


class StrategyVersionResponse(BaseModel):
    """An immutable snapshot of a strategy configuration."""

    id: int
    strategy_id: int
    version: int
    config: dict[str, Any]
    created_at: datetime


class StrategyResponse(BaseModel):
    """A strategy with its latest configuration version."""

    id: int
    name: str
    description: str | None = None
    is_active: bool = True
    config: dict[str, Any]
    versions: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LiveDealValidation(BaseModel):
    """Result of ``validate_live_deal_config`` for the given configuration."""

    supported: bool
    reason: str | None = None


class StrategyValidateResponse(BaseModel):
    """Result of the config validation endpoint.

    ``schema_valid`` is always true when the response is returned (invalid
    configs fail with HTTP 422 before this point); ``live_deal`` reports the
    D1/E3/E4 live-deal-scope validation result.
    """

    valid: bool = True
    live_deal: LiveDealValidation


class IndicatorParamResponse(BaseModel):
    """One configurable parameter of an indicator from the catalog (U3).

    ``default`` is the single source of truth value the form pre-fills (I2);
    ``default_source`` says whether the value is documented by Veles
    (``veles``) or an owner-approved project choice (``project``).
    """

    name: str
    type: str
    required: bool
    default: int | float
    default_source: Literal["veles", "project"]


class IndicatorResponse(BaseModel):
    """Catalog entry: an indicator the calculation engine can compute (U3).

    ``series`` are the selectable output series (``IndicatorSpec.series``);
    ``uses_*`` report which ``IndicatorSpec`` fields the calculation consumes.
    ``period_default`` / ``period_default_source`` declare the explicit default
    for ``IndicatorSpec.period`` (None when the indicator does not use period).
    """

    name: str
    series: list[str]
    params: list[IndicatorParamResponse]
    uses_period: bool
    uses_method: bool
    uses_series: bool
    uses_params: bool
    period_default: int | None = None
    period_default_source: Literal["veles", "project"] | None = None
