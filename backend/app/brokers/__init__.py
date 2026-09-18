"""Broker abstraction package."""

from __future__ import annotations

from app.brokers.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerInstrument,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from app.brokers.tinvest import TInvestAdapter
from app.brokers.tinvest_client import TInvestClient
from app.brokers.tinvest_errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerApiError,
    BrokerConnectionError,
    InstrumentNotFoundError,
    InvalidRequestError,
    MarketDataError,
    RateLimitError,
    ResourceNotFoundError,
    TInvestError,
)
from app.domain.instrument import InstrumentType, TradingStatus
from app.domain.marketdata import Candle, LastPrice, Timeframe

__all__ = [
    "BrokerAdapter",
    "BrokerAccount",
    "BrokerDeal",
    "BrokerInstrument",
    "BrokerOrder",
    "BrokerOrderRequest",
    "BrokerPosition",
    "TInvestAdapter",
    "TInvestClient",
    "TInvestError",
    "AuthenticationError",
    "BrokerApiError",
    "BrokerConnectionError",
    "InvalidRequestError",
    "InstrumentNotFoundError",
    "AccountNotFoundError",
    "MarketDataError",
    "RateLimitError",
    "ResourceNotFoundError",
    "InstrumentType",
    "TradingStatus",
    "Candle",
    "LastPrice",
    "Timeframe",
]
