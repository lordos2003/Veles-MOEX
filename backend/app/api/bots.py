"""Bot lifecycle REST endpoints (broker-neutral).

These endpoints drive the bot lifecycle and persist bot state through the
``BotRepository``. GET endpoints are read-only and work without a live runtime.
Mutating endpoints (start/stop/emergency-stop) require the real application
``BotRuntimeManager`` wired into the live execution service; when it is absent
the mutation is rejected with an explicit error and no bot state is changed.
No disconnected fallback runtime is created.

No authentication/authorization subsystem is added in MVP-6.5.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_account_service,
    get_bot_repository,
    get_bot_runtime_manager,
    get_broker_adapter,
    get_deal_store,
    get_instrument_service,
    get_live_deal_manager,
    get_live_scheduler,
    get_strategy_service,
)
from app.bots.repository import BotRepository
from app.bots.schemas import (
    BotCreate,
    BotResponse,
    BotUpdate,
    DealLevelResponse,
    DealResponse,
)
from app.bots.strategy import StrategyLoadError, load_bot_strategy
from app.brokers import BrokerAdapter
from app.core.db import get_session
from app.models.bot import Bot
from app.persistence.deal_store import SqlAlchemyDealStore
from app.services.accounts import AccountService
from app.services.instruments import InstrumentService
from app.strategies.service import StrategyService
from app.trading.bot_lifecycle import BotRuntimeManager, BotStartRejected, BotStateError
from app.trading.deal import Deal, DealConfigUnsupported
from app.trading.deal_manager import DealManager
from app.trading.scheduler import LiveCycleScheduler

router = APIRouter(tags=["bots"])

_RUNTIME_UNAVAILABLE = (
    "live bot runtime is unavailable; bot lifecycle mutations require a running "
    "live execution service"
)


def _to_response(
    bot: Bot,
    deal_error: str | None = None,
    last_error: str | None = None,
    last_skip_reason: str | None = None,
) -> BotResponse:
    return BotResponse(
        id=bot.id,
        name=bot.name,
        status=bot.status,
        strategy_version_id=bot.strategy_version_id,
        account_id=bot.account_id,
        instrument_id=bot.instrument_id,
        deposit=bot.deposit,
        started_at=bot.started_at,
        stopped_at=bot.stopped_at,
        stop_reason=bot.stop_reason,
        deal_error=deal_error,
        last_error=last_error,
        last_skip_reason=last_skip_reason,
    )


def _deal_to_schema(deal: Deal) -> DealResponse:
    return DealResponse(
        id=deal.id,
        bot_id=deal.bot_id,
        instrument_figi=deal.instrument_figi,
        direction=deal.direction.value,
        status=deal.status.value,
        deposit=deal.deposit,
        base_nominal=deal.base_nominal,
        reference_price=deal.reference_price,
        lot_size=deal.lot_size,
        tick_size=deal.tick_size,
        tp_percent=deal.tp_percent,
        average_price=deal.average_price,
        position_quantity=sum(
            (level.filled_quantity for level in deal.levels), Decimal("0")
        ),
        tp_price=deal.tp_price,
        tp_quantity=deal.tp_quantity,
        sl_percent=deal.sl_percent,
        p0_price=deal.p0_price,
        sl_quantity=deal.sl_quantity,
        sl_price=deal.sl_price,
        sl_order_id=deal.sl_order_id,
        sl_active=None if deal.sl_percent is None else deal.sl_order_id is not None,
        close_reason=deal.close_reason,
        stop_bot_after=deal.stop_bot_after,
        levels=[
            DealLevelResponse(
                index=level.index,
                side=level.side.value,
                price=level.price,
                nominal=level.nominal,
                quantity=level.quantity,
                offset_percent=level.offset_percent,
                status=level.status.value,
                is_market=level.is_market,
                filled_quantity=level.filled_quantity,
                order_id=level.order_id,
                broker_order_id=level.broker_order_id,
            )
            for level in deal.levels
        ],
        created_at=deal.created_at,
        updated_at=deal.updated_at,
        closed_at=deal.closed_at,
    )


async def _load_bot(bot_id: int, repo: BotRepository) -> Bot:
    bot = await repo.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"bot not found: {bot_id}")
    return bot


async def _enforce_version_change_rule(
    bot: Bot, deal_store: SqlAlchemyDealStore
) -> None:
    """R5: a strategy-version change requires STOPPED state and no unclosed deal."""
    if bot.status != "STOPPED":
        raise HTTPException(
            status_code=409,
            detail=(
                "strategy version can only be changed while the bot is STOPPED; "
                f"current status: {bot.status}"
            ),
        )
    open_deal = await deal_store.get_open_for_bot(bot.id)
    if open_deal is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "strategy version cannot be changed while the bot has an "
                f"unclosed deal (deal {open_deal.id})"
            ),
        )


async def _persist_current_state(
    repo: BotRepository, bot: Bot, runtime: BotRuntimeManager
) -> None:
    """Persist the bot's actual lifecycle state so DB and runtime agree."""
    bot_runtime = runtime.get(bot.id)
    if bot_runtime is not None:
        await repo.update_state(bot, bot_runtime.state)


async def _apply(
    repo: BotRepository,
    bot: Bot,
    runtime: BotRuntimeManager,
    operation: str,
) -> None:
    """Run a lifecycle operation and persist the resulting state.

    On any failure the actual runtime state is persisted so the DB never lags
    behind the lifecycle (e.g. a rejected START is persisted as ERROR, never
    left as RUNNING or stale STOPPED).
    """
    try:
        if operation == "start":
            await runtime.start(bot.id)
        elif operation == "stop":
            await runtime.stop(bot.id)
        else:
            await runtime.emergency_stop(bot.id)
    except BotStartRejected as exc:
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=409, detail=f"bot start rejected by risk manager: {exc}"
        ) from exc
    except StrategyLoadError as exc:
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=409,
            detail=f"bot start failed: strategy could not be loaded/validated: {exc}",
        ) from exc
    except BotStateError as exc:
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=409, detail=f"invalid bot lifecycle transition: {exc}"
        ) from exc
    except DealConfigUnsupported as exc:
        # MVP-6.12 D1: the bot config does not qualify for live deal
        # continuation (grid mode / TP kind / SL presence / pull-up). The
        # rejection is explicit at START and surfaces as a client error.
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=409,
            detail=(
                "bot start failed: config not supported for live deal "
                f"continuation: {exc}"
            ),
        ) from exc
    except Exception as exc:
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=503, detail=f"bot lifecycle operation failed: {exc}"
        ) from exc
    await _persist_current_state(repo, bot, runtime)


@router.get("/bots", response_model=list[BotResponse])
async def list_bots(
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
) -> list[BotResponse]:
    bots = await repo.list()
    return [_to_response(bot) for bot in bots]


@router.post("/bots", response_model=BotResponse, status_code=201)
async def create_bot(
    payload: BotCreate,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    strategy_service: Annotated[StrategyService, Depends(get_strategy_service)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
    instrument_service: Annotated[InstrumentService, Depends(get_instrument_service)],
) -> BotResponse:
    """Create a bot in state STOPPED (R5).

    All referenced entities (strategy version, account, instrument) must exist;
    otherwise an explicit HTTP 404 is returned. A bot starts only through
    ``POST /bots/{id}/start``.
    """
    if await strategy_service.get_version(payload.strategy_version_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"strategy version not found: {payload.strategy_version_id}",
        )
    if await account_service.get_by_id(payload.account_id) is None:
        raise HTTPException(
            status_code=404, detail=f"account not found: {payload.account_id}"
        )
    if await instrument_service.get_by_id(payload.instrument_id) is None:
        raise HTTPException(
            status_code=404, detail=f"instrument not found: {payload.instrument_id}"
        )
    bot = await repo.create(
        name=payload.name,
        strategy_version_id=payload.strategy_version_id,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        deposit=payload.deposit,
    )
    return _to_response(bot)


@router.get("/bots/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_manager: Annotated[DealManager | None, Depends(get_live_deal_manager)] = None,
    scheduler: Annotated[LiveCycleScheduler | None, Depends(get_live_scheduler)] = None,
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    # B2: surface the last Deal-layer failure (if any) as a read-only field —
    # the bot may be in ERROR because of a deal failure and the API must show
    # why (no opaque ERROR state).
    deal_error = (
        deal_manager.last_error_for(bot_id) if deal_manager is not None else None
    )
    # MVP-6.13 S4: the scheduler records the last cycle failure reason (skipped
    # transients, timeout, or the terminal error that moved the bot to ERROR).
    last_error = (
        scheduler.last_error_for(bot_id) if scheduler is not None else None
    )
    # MVP-6.14 N1: the last proven no-trade skip reason (a skip is neither a
    # failure nor a success, so it is observable separately from last_error).
    last_skip_reason = (
        scheduler.last_skip_reason_for(bot_id) if scheduler is not None else None
    )
    return _to_response(
        bot,
        deal_error=deal_error,
        last_error=last_error,
        last_skip_reason=last_skip_reason,
    )


@router.get("/bots/{bot_id}/deal", response_model=DealResponse | None)
async def get_open_deal(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_store: Annotated[SqlAlchemyDealStore, Depends(get_deal_store)],
) -> DealResponse | None:
    """Return the current unclosed deal of a bot, or ``null`` when none (R6).

    The source is the Deal store (MVP-6.12): no recomputation is performed.
    """
    await _load_bot(bot_id, repo)
    deal = await deal_store.get_open_for_bot(bot_id)
    return _deal_to_schema(deal) if deal is not None else None


@router.get("/bots/{bot_id}/deals", response_model=list[DealResponse])
async def list_bot_deals(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_store: Annotated[SqlAlchemyDealStore, Depends(get_deal_store)],
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[DealResponse]:
    """Return closed deals of a bot, newest first (history, R6).

    ``close_reason`` is included per deal; ``limit`` caps the result when set.
    """
    await _load_bot(bot_id, repo)
    deals = await deal_store.list_closed_for_bot(bot_id, limit=limit)
    return [_deal_to_schema(deal) for deal in deals]


@router.patch("/bots/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: int,
    payload: BotUpdate,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_store: Annotated[SqlAlchemyDealStore, Depends(get_deal_store)] = None,
    strategy_service: Annotated[StrategyService, Depends(get_strategy_service)] = None,
) -> BotResponse:
    """Update bot deposit and/or strategy version (R5).

    ``deposit`` follows the MVP-6.11 C5 rules (positive or explicit ``null``;
    an empty PATCH is rejected with 422). A ``strategy_version_id`` change is
    allowed only while the bot is STOPPED and has no unclosed deal (HTTP 409
    otherwise) and only to an existing version (HTTP 404 otherwise).
    """
    bot = await _load_bot(bot_id, repo)
    fields = payload.model_fields_set
    if "deposit" in fields:
        await repo.update_deposit(bot, payload.deposit)
    if "strategy_version_id" in fields:
        if payload.strategy_version_id is None:
            raise HTTPException(
                status_code=422, detail="strategy_version_id must not be null"
            )
        await _enforce_version_change_rule(bot, deal_store)
        if await strategy_service.get_version(payload.strategy_version_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"strategy version not found: {payload.strategy_version_id}",
            )
        await repo.update_strategy_version(bot, payload.strategy_version_id)
    return _to_response(bot)


@router.delete("/bots/{bot_id}", response_model=BotResponse)
async def delete_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_store: Annotated[SqlAlchemyDealStore, Depends(get_deal_store)] = None,
) -> BotResponse:
    """Delete a bot (R5): only while STOPPED and without an unclosed deal."""
    bot = await _load_bot(bot_id, repo)
    await _enforce_version_change_rule(bot, deal_store)
    await repo.delete(bot)
    return _to_response(bot)


@router.post("/bots/{bot_id}/start", response_model=BotResponse)
async def start_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    runtime: Annotated[BotRuntimeManager | None, Depends(get_bot_runtime_manager)],
    session: Annotated[AsyncSession, Depends(get_session)],
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    if runtime is None:
        raise HTTPException(status_code=503, detail=_RUNTIME_UNAVAILABLE)
    # R3: a stop-loss bot cannot run on a connection that does not support
    # stop orders (T-Invest sandbox has no StopOrdersService). The failure is
    # explicit at START instead of failing mid-run.
    try:
        bot_strategy = await load_bot_strategy(session, bot)
    except StrategyLoadError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"bot start failed: strategy could not be loaded/validated: {exc}",
        ) from exc
    if bot_strategy.config.exit.stop_loss is not None and not broker.supports_stop_orders:
        raise HTTPException(
            status_code=409,
            detail=(
                "bot start failed: stop-loss requires stop-order support, which "
                "the current broker connection does not provide (sandbox)"
            ),
        )
    await _apply(repo, bot, runtime, "start")
    return _to_response(bot)


@router.post("/bots/{bot_id}/stop", response_model=BotResponse)
async def stop_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    runtime: Annotated[BotRuntimeManager | None, Depends(get_bot_runtime_manager)],
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    if runtime is None:
        raise HTTPException(status_code=503, detail=_RUNTIME_UNAVAILABLE)
    await _apply(repo, bot, runtime, "stop")
    return _to_response(bot)


@router.post("/bots/{bot_id}/emergency-stop", response_model=BotResponse)
async def emergency_stop_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    runtime: Annotated[BotRuntimeManager | None, Depends(get_bot_runtime_manager)],
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    if runtime is None:
        raise HTTPException(status_code=503, detail=_RUNTIME_UNAVAILABLE)
    await _apply(repo, bot, runtime, "emergency-stop")
    return _to_response(bot)
