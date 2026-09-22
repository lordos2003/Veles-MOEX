"""BrokerAdapter abstraction.

The Strategy/Trading Engine must depend only on this interface, never on
T-Invest specifics. Live uses TInvestAdapter; Backtest uses BacktestBroker,
which also implements this interface. This keeps Live and Backtest on the same
Strategy/Trading Engine (Architecture & Product Specification section 11).

This layer hands out broker-agnostic DTOs (accounts, positions, orders, deals,
instruments) and the internal domain market-data models (``Candle``,
``LastPrice``, ``Timeframe``), so higher layers never see broker (T-Invest)
objects. All money/quantity values use ``Decimal``; timestamps are timezone-aware
UTC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.instrument import InstrumentType, TradingStatus
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType


@dataclass
class BrokerOrderRequest:
    """Broker-agnostic order request sent by the Order Manager.

    ``quantity`` and ``price`` are measured in the canonical domain units: the
    number of instrument units (pieces/shares) and the price per one unit. The
    broker adapter converts to the broker's native representation (e.g. lots /
    ``Quotation``) and must not leak that conversion outside the adapter.
    """

    instrument_figi: str
    side: OrderSide
    quantity: Decimal
    type: OrderType
    price: Decimal | None = None
    account_id: str | None = None
    idempotency_key: str = ""


@dataclass
class BrokerAccount:
    """Broker-agnostic account summary.

    For the account list, ``name``/``status``/``account_type`` are populated;
    for a single account request, cash/equity are populated from the portfolio.
    """

    account_id: str
    broker: str = "tinvest"
    currency: str = "RUB"
    available_cash: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    currencies: list[str] = field(default_factory=list)
    name: str | None = None
    account_type: str | None = None
    status: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None


@dataclass
class BrokerPosition:
    """Broker-agnostic open position."""

    account_id: str
    instrument_figi: str
    ticker: str | None = None
    instrument_type: str | None = None
    quantity: Decimal = Decimal("0")
    average_price: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")
    current_value: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    currency: str | None = None
    timestamp: datetime | None = None


@dataclass
class BrokerOrder:
    """Broker-agnostic order (read-only).

    ``requested_quantity`` / ``executed_quantity`` are expressed in the
    broker's native unit (lots for T-Invest); live fill/position accounting
    uses the canonical unit (units) via fill/position events instead.
    """

    order_id: str
    status: OrderStatus
    account_id: str | None = None
    instrument_figi: str | None = None
    ticker: str | None = None
    type: OrderType | None = None
    side: OrderSide | None = None
    requested_quantity: Decimal = Decimal("0")
    executed_quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    idempotency_key: str | None = None
    currency: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reject_info: str | None = None


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
    """Broker-agnostic settled deal/execution."""

    deal_id: str
    instrument_figi: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    account_id: str | None = None
    order_id: str | None = None
    commission: Decimal = Decimal("0")
    currency: str | None = None
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

    # --- Read-only broker data ---

    @abstractmethod
    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        """Return currently open positions (optionally for an account)."""

    @abstractmethod
    async def get_orders(self, account_id: str | None = None) -> list[BrokerOrder]:
        """Return existing orders (optionally for an account)."""

    @abstractmethod
    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        """Return settled deals/executions (optionally for an account)."""

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

    # --- Trading ---

    @abstractmethod
    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        """Place an order and return the broker order."""

    @abstractmethod
    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None:
        """Cancel an order by broker order id.

        ``account_id`` is required by brokers that scope orders per account.
        """

    @abstractmethod
    async def get_order(self, order_id: str, account_id: str | None = None) -> BrokerOrder:
        """Fetch a single order by broker order id.

        ``account_id`` is required by brokers that scope orders per account.
        """
