"""API dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers import BrokerAdapter, TInvestAdapter
from app.core.db import get_session
from app.services.instruments import InstrumentService
from app.services.market_data import MarketDataService


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
