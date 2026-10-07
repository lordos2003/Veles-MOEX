"""Strategies REST endpoints (MVP-7.0 R4).

A strategy is configuration/data. The configuration is validated through the
existing ``StrategyConfig`` model; invalid configs fail with HTTP 422 (FastAPI
validation details). Updating the configuration appends an immutable new
version; existing versions are never mutated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_strategy_service
from app.strategies.config import StrategyConfig
from app.strategies.indicators import INDICATOR_CATALOG
from app.strategies.schemas import (
    IndicatorParamResponse,
    IndicatorResponse,
    LiveDealValidation,
    StrategyCreate,
    StrategyResponse,
    StrategyUpdate,
    StrategyValidateResponse,
    StrategyVersionResponse,
)
from app.strategies.service import StrategyNotFoundError, StrategyService
from app.trading.deal import DealConfigUnsupported, validate_live_deal_config

router = APIRouter(tags=["strategies"])


@router.post("/strategies", response_model=StrategyResponse, status_code=201)
async def create_strategy(
    payload: StrategyCreate,
    service: Annotated[StrategyService, Depends(get_strategy_service)],
) -> StrategyResponse:
    """Create a strategy with its initial immutable version (v1)."""
    strategy = await service.create(payload.name, payload.config, payload.description)
    return await _to_response(service, strategy.id)


@router.get("/strategies", response_model=list[StrategyResponse])
async def list_strategies(
    service: Annotated[StrategyService, Depends(get_strategy_service)],
) -> list[StrategyResponse]:
    """List strategies (with their latest configuration version)."""
    strategies = await service.list()
    return [await _to_response(service, strategy.id) for strategy in strategies]


@router.get("/strategies/schema")
async def strategies_schema() -> dict:
    """Return the pydantic JSON Schema of ``StrategyConfig``.

    ``title``/``description``/``enum`` metadata of the config model is exposed
    to the frontend; no defaults are invented by this endpoint.
    """
    return StrategyConfig.model_json_schema()


@router.post("/strategies/validate", response_model=StrategyValidateResponse)
async def validate_strategy(config: StrategyConfig) -> StrategyValidateResponse:
    """Validate a strategy configuration and report live-deal scope support.

    Invalid configurations fail with HTTP 422 (FastAPI validation). The live
    ``validate_live_deal_config`` result is returned as ``live_deal``: a config
    outside the D1/E3/E4 scope reports ``supported=false`` with a reason but is
    still valid as a configuration (the rejection happens at bot START).
    """
    try:
        validate_live_deal_config(config)
        live = LiveDealValidation(supported=True)
    except DealConfigUnsupported as exc:
        live = LiveDealValidation(supported=False, reason=str(exc))
    return StrategyValidateResponse(valid=True, live_deal=live)


@router.get("/strategies/indicators", response_model=list[IndicatorResponse])
async def list_indicators() -> list[IndicatorResponse]:
    """Return the catalog of indicators the calculation engine supports (U3).

    The catalog is driven by the same registry as ``indicator_series`` (see
    ``app.strategies.indicators``): a name that the engine cannot compute is
    never listed, and a listed entry is always computable. No default values
    are exposed (AGENTS.md §2).
    """
    return [
        IndicatorResponse(
            name=entry.name,
            series=list(entry.series),
            params=[
                IndicatorParamResponse(name=param.name, type=param.type, required=param.required)
                for param in entry.params
            ],
            uses_period=entry.uses_period,
            uses_method=entry.uses_method,
            uses_series=entry.uses_series,
            uses_params=entry.uses_params,
        )
        for entry in INDICATOR_CATALOG
    ]


@router.get("/strategies/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: int,
    service: Annotated[StrategyService, Depends(get_strategy_service)],
) -> StrategyResponse:
    """Return a strategy with its latest configuration version."""
    try:
        return await _to_response(service, strategy_id)
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/strategies/{strategy_id}/versions", response_model=list[StrategyVersionResponse])
async def list_versions(
    strategy_id: int,
    service: Annotated[StrategyService, Depends(get_strategy_service)],
) -> list[StrategyVersionResponse]:
    """Return all immutable versions of a strategy (newest first)."""
    strategy = await service.get(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"strategy {strategy_id} not found")
    versions = await service.versions(strategy_id)
    return [
        StrategyVersionResponse(
            id=version.id,
            strategy_id=version.strategy_id,
            version=version.version,
            config=version.config,
            created_at=version.created_at,
        )
        for version in versions
    ]


@router.put("/strategies/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    service: Annotated[StrategyService, Depends(get_strategy_service)],
) -> StrategyResponse:
    """Update strategy metadata; a new config appends the next immutable version."""
    try:
        await service.update(
            strategy_id,
            name=payload.name,
            description=payload.description,
            config=payload.config,
        )
        return await _to_response(service, strategy_id)
    except StrategyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _to_response(service: StrategyService, strategy_id: int) -> StrategyResponse:
    """Build the API response for a strategy (latest version as ``config``)."""
    strategy = await service.get(strategy_id)
    if strategy is None:
        raise StrategyNotFoundError(f"strategy {strategy_id} not found")
    versions = await service.versions(strategy_id)
    latest = versions[0] if versions else None
    return StrategyResponse(
        id=strategy.id,
        name=strategy.name,
        description=strategy.description,
        is_active=strategy.is_active,
        config=latest.config if latest is not None else strategy.config,
        versions=len(versions),
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
    )
