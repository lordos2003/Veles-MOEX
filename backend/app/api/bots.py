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

from app.api.deps import get_bot_repository, get_bot_runtime_manager
from app.bots.repository import BotRepository
from app.bots.schemas import BotResponse
from app.models.bot import Bot
from app.trading.bot_lifecycle import BotRuntimeManager, BotStartRejected, BotStateError

router = APIRouter(tags=["bots"])

_RUNTIME_UNAVAILABLE = (
    "live bot runtime is unavailable; bot lifecycle mutations require a running "
    "live execution service"
)


def _to_response(bot: Bot) -> BotResponse:
    return BotResponse(
        id=bot.id,
        name=bot.name,
        status=bot.status,
        strategy_version_id=bot.strategy_version_id,
        account_id=bot.account_id,
        instrument_id=bot.instrument_id,
        started_at=bot.started_at,
        stopped_at=bot.stopped_at,
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
    except BotStateError as exc:
        await _persist_current_state(repo, bot, runtime)
        raise HTTPException(
            status_code=409, detail=f"invalid bot lifecycle transition: {exc}"
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
) -> BotResponse:
    bot = await _load_bot(bot_id, repo)
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
