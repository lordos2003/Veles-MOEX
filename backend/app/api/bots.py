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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_bot_repository, get_bot_runtime_manager, get_live_deal_manager
from app.bots.repository import BotRepository
from app.bots.schemas import BotDepositUpdate, BotResponse
from app.bots.strategy import StrategyLoadError
from app.models.bot import Bot
from app.trading.bot_lifecycle import BotRuntimeManager, BotStartRejected, BotStateError
from app.trading.deal import DealConfigUnsupported
from app.trading.deal_manager import DealManager

router = APIRouter(tags=["bots"])

_RUNTIME_UNAVAILABLE = (
    "live bot runtime is unavailable; bot lifecycle mutations require a running "
    "live execution service"
)


def _to_response(bot: Bot, deal_error: str | None = None) -> BotResponse:
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
        deal_error=deal_error,
    )


async def _load_bot(bot_id: int, repo: BotRepository) -> Bot:
    bot = await repo.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"bot not found: {bot_id}")
    return bot


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


@router.get("/bots/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    deal_manager: Annotated[DealManager | None, Depends(get_live_deal_manager)] = None,
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    # B2: surface the last Deal-layer failure (if any) as a read-only field —
    # the bot may be in ERROR because of a deal failure and the API must show
    # why (no opaque ERROR state).
    deal_error = (
        deal_manager.last_error_for(bot_id) if deal_manager is not None else None
    )
    return _to_response(bot, deal_error=deal_error)


@router.patch("/bots/{bot_id}", response_model=BotResponse)
async def update_bot_deposit(
    bot_id: int,
    payload: BotDepositUpdate,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
) -> BotResponse:
    """Set or clear the bot deposit (MVP-6.11 C5).

    ``deposit`` must be positive (or ``null`` to clear it); a non-positive
    value is rejected by schema validation (422) and no default is invented.
    """
    bot = await _load_bot(bot_id, repo)
    await repo.update_deposit(bot, payload.deposit)
    return _to_response(bot)


@router.post("/bots/{bot_id}/start", response_model=BotResponse)
async def start_bot(
    bot_id: int,
    repo: Annotated[BotRepository, Depends(get_bot_repository)],
    runtime: Annotated[BotRuntimeManager | None, Depends(get_bot_runtime_manager)],
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
    if runtime is None:
        raise HTTPException(status_code=503, detail=_RUNTIME_UNAVAILABLE)
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
