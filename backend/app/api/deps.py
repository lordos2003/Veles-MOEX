"""API dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.bots.repository import BotRepository
from app.brokers import BrokerAdapter, TInvestAdapter
from app.core.db import get_session
from app.services.broker_data import BrokerDataService
from app.services.instruments import InstrumentService
from app.services.market_data import MarketDataService
from app.trading.bot_lifecycle import BotRuntimeManager
from app.trading.deal_manager import DealManager
from app.trading.scheduler import LiveCycleScheduler


def get_broker_adapter() -> BrokerAdapter:
    """Return a configured BrokerAdapter (T-Invest) for the current request.

    The endpoint layer depends only on the BrokerAdapter abstraction, so T-Invest
    specifics never leak into the API/domain layer.
    """
    return TInvestAdapter()


def get_instrument_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InstrumentService:
    """Return an InstrumentService bound to the request session."""
    return InstrumentService(session)


def get_market_data_service(
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> MarketDataService:
    """Return a MarketDataService bound to the request broker adapter."""
    return MarketDataService(broker)


def get_broker_data_service(
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> BrokerDataService:
    """Return a BrokerDataService bound to the request broker adapter."""
    return BrokerDataService(broker)


def get_bot_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BotRepository:
    """Return a BotRepository bound to the request session."""
    return BotRepository(session)


def get_bot_runtime_manager(request: Request) -> BotRuntimeManager | None:
    """Return the application bot runtime manager, or ``None`` if not running.

    Mutating bot endpoints require the real application manager that is wired
    to the live execution service. No disconnected fallback manager is created.
    Read-only (GET) bot endpoints do not require it.
    """
    service = getattr(request.app.state, "live_execution", None)
    if service is not None:
        return service.bot_runtime
    return None


def get_live_deal_manager(request: Request) -> DealManager | None:
    """Return the application DealManager, or ``None`` when unavailable.

    Read-only (B2): the deal-failure reason of a bot is exposed through
    ``last_error_for`` so ``GET /bots/{id}`` can surface it. No fallback
    manager is created; when the live execution service is not running the
    field is simply absent.
    """
    service = getattr(request.app.state, "live_execution", None)
    if service is not None:
        return service.deal_manager
    return None


def get_live_scheduler(request: Request) -> LiveCycleScheduler | None:
    """Return the application LiveCycleScheduler, or ``None`` when unavailable.

    Read-only (MVP-6.13 S4): the per-bot last cycle failure is exposed through
    ``last_error_for`` so ``GET /bots/{id}`` can surface it. No fallback
    scheduler is created; when the live execution service is not running the
    field is simply absent.
    """
    service = getattr(request.app.state, "live_execution", None)
    if service is not None:
        return service.scheduler
    return None
