"""BrokerAdapter abstraction.

The Strategy/Trading Engine must depend only on this interface, never on
T-Invest specifics. Live uses TInvestAdapter; Backtest uses BacktestBroker,
which also implements this interface. This keeps Live and Backtest on the same
Strategy/Trading Engine (Architecture & Product Specification section 11).

This layer hands out broker-agnostic DTOs (accounts, instruments) and the
internal domain market-data models (``Candle``, ``LastPrice``, ``Timeframe``),
so higher layers never see broker (T-Invest) objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.instrument import InstrumentType, TradingStatus
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType


@dataclass
class BrokerOrderRequest:
    """Broker-agnostic order request sent by the Order Manager."""

    instrument_figi: str
    side: OrderSide
    quantity: float
    type: OrderType
    price: float | None = None
    account_id: str | None = None


@dataclass
class BrokerOrder:
    """Broker-agnostic order representation."""

    order_id: str
    status: OrderStatus
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    created_at: datetime | None = None


@dataclass
class BrokerPosition:
    """Broker-agnostic open position."""

    instrument_figi: str
    quantity: float
    average_price: float
    unrealized_pnl: float = 0.0


@dataclass
class BrokerAccount:
    """Broker-agnostic account summary.

    For the account list, ``name``/``status``/``account_type`` are populated;
    for a single account request, cash/equity are populated from the portfolio.
    """

    account_id: str
    currency: str = "RUB"
    available_cash: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    name: str | None = None
    account_type: str | None = None
    status: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None


@dataclass
class BrokerInstrument:
    """Broker-agnostic instrument metadata (normalized to domain types)."""

    figi: str
    ticker: str | None = None
    name: str | None = None
    instrument_type: InstrumentType | None = None
    currency: str | None = None
    lot_size: int | None = None
    tick_size: Decimal | None = None
    trading_status: TradingStatus = TradingStatus.TRADING_AVAILABLE
    exchange: str | None = None
    is_active: bool = True


@dataclass
class BrokerDeal:
    """Broker-agnostic settled deal/execution record."""

    deal_id: str
    instrument_figi: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    happened_at: datetime | None = None


class BrokerAdapter(ABC):
    """Interface implemented by concrete broker adapters.

    The high-level trading components (`OrderManager`, `PositionManager`,
    `TradingEngine`) talk to this interface only. It is intentionally narrow
    and marked as the integration seam for a broker.
    """

    # --- Connection ---

    @abstractmethod
    async def connect(self) -> None:
        """Establish and validate the broker connection."""

    @abstractmethod
    async def close(self) -> None:
        """Close the broker connection."""

    # --- Accounts ---

    @abstractmethod
    async def get_accounts(self) -> list[BrokerAccount]:
        """Return all available broker accounts."""

    @abstractmethod
    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        """Return account summary (cash/equity)."""

    # --- Instruments / market data (read-only) ---

    @abstractmethod
    async def get_instruments(self, kind: str | None = None) -> list[BrokerInstrument]:
        """Return a list of instruments, optionally filtered by kind."""

    @abstractmethod
    async def get_instrument(self, figi: str) -> BrokerInstrument:
        """Return a single instrument by FIGI."""

    @abstractmethod
    async def get_last_price(self, figi: str) -> LastPrice:
        """Return the last trade price for an instrument."""

    @abstractmethod
    async def get_candles(
        self,
        figi: str,
        timeframe: Timeframe,
        from_: datetime,
        to: datetime,
        limit: int | None = None,
    ) -> list[Candle]:
        """Return historical OHLCV candles for an instrument and timeframe."""

    # --- Trading (not implemented in this phase) ---

    @abstractmethod
    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        """Place an order and return the broker order."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        """Cancel an order by broker order id."""

    @abstractmethod
    async def get_order(self, order_id: str) -> BrokerOrder:
        """Fetch a single order by broker order id."""

    @abstractmethod
    async def get_open_positions(self) -> list[BrokerPosition]:
        """Return currently open positions from the broker."""

    @abstractmethod
    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        """Return settled deals/executions."""
