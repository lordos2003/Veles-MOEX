"""BrokerAdapter abstraction.

The Strategy/Trading Engine must depend only on this interface, never on
T-Invest specifics. Live uses TInvestAdapter; Backtest uses BacktestBroker,
which also implements this interface. This keeps Live and Backtest on the same
Strategy/Trading Engine (Architecture & Product Specification section 11).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

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
    """Broker-agnostic account summary."""

    account_id: str
    currency: str = "RUB"
    available_cash: float = 0.0
    equity: float = 0.0


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

    @abstractmethod
    async def connect(self) -> None:
        """Establish and validate the broker connection."""

    @abstractmethod
    async def close(self) -> None:
        """Close the broker connection."""

    @abstractmethod
    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        """Return account summary (cash/equity)."""

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
