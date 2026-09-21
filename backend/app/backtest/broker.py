"""BacktestBroker.

Implements the same |BrokerAdapter| interface so the Backtest engine can reuse
the exact same Strategy Engine as Live (Architecture & Product Specification
section 11). It models market/limit execution over historical candles, order
states, fills/deals, account balance and position accounting, with configurable
maker/taker commissions and slippage.

Fills are deterministic:
- market order -> fills immediately at the given/current price (+ slippage);
- limit order -> fills when a bar's low/high crosses the limit (OHLC rule, no
  intra-bar ordering, maker commission).

Partial fills are deferred by design; the interface supports them later.
T-Invest is not referenced anywhere here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.brokers.base import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerInstrument,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from app.domain.instrument import TradingStatus
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType


class BacktestBroker(BrokerAdapter):
    """BrokerAdapter implementation backed by historical data."""

    def __init__(
        self,
        *,
        account_id: str = "backtest",
        initial_capital: Decimal = Decimal("0"),
        maker_fee: Decimal = Decimal("0"),
        taker_fee: Decimal = Decimal("0"),
        slippage: Decimal = Decimal("0"),
        figi: str | None = None,
        candles: list[Candle] | None = None,
    ) -> None:
        self._account_id = account_id
        self._figi = figi
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._maker_fee = maker_fee
        self._taker_fee = taker_fee
        self._slippage = slippage
        self._candles = candles or []

        self._quantity: Decimal = Decimal("0")  # signed: +long / -short
        self._avg_price: Decimal = Decimal("0")
        self._opened_at: datetime | None = None
        self._closed_at: datetime | None = None
        self._realized_gross: Decimal = Decimal("0")
        self._fees_total: Decimal = Decimal("0")
        self._last_price: Decimal = Decimal("0")

        self._orders: dict[str, BrokerOrder] = {}
        self._deals: list[BrokerDeal] = []
        self._order_seq = 0
        self._deal_seq = 0
        self._last_time: datetime | None = None

    # --- position / account helpers -------------------------------------------------

    def is_open(self) -> bool:
        return self._quantity != 0

    def set_price(self, price: Decimal) -> None:
        self._last_price = price

    def set_figi(self, figi: str) -> None:
        self._figi = figi

    def average_price(self) -> Decimal:
        return self._avg_price

    def position_quantity(self) -> Decimal:
        return self._quantity

    def opened_at(self) -> datetime | None:
        return self._opened_at

    def closed_at(self) -> datetime | None:
        return self._closed_at

    def fees_total(self) -> Decimal:
        return self._fees_total

    def realized_gross_pnl(self) -> Decimal:
        return self._realized_gross

    def unrealized_pnl(self) -> Decimal:
        if self._quantity == 0:
            return Decimal("0")
        if self._quantity > 0:
            return (self._last_price - self._avg_price) * self._quantity
        return (self._avg_price - self._last_price) * abs(self._quantity)

    def equity(self) -> Decimal:
        return self._cash + self._quantity * self._last_price

    def deals(self) -> list[BrokerDeal]:
        return list(self._deals)

    def orders(self) -> list[BrokerOrder]:
        return list(self._orders.values())

    # --- execution ------------------------------------------------------------------

    def execute_market(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal | None = None,
        timestamp: datetime | None = None,
    ) -> BrokerOrder:
        fill_price = self._fill_market_price(side, price or self._last_price)
        fee = fill_price * quantity * self._taker_fee
        self._apply_fill(side, quantity, fill_price, fee, timestamp)

        order_id = self._next_order_id("mkt")
        order = BrokerOrder(
            order_id=order_id,
            status=OrderStatus.FILLED,
            account_id=self._account_id,
            instrument_figi=self._figi,
            type=OrderType.MARKET,
            side=side,
            requested_quantity=quantity,
            executed_quantity=quantity,
            price=fill_price,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._orders[order_id] = order
        self._record_deal(order, fill_price, quantity, fee, timestamp)
        return order

    def place_limit(
        self, side: OrderSide, quantity: Decimal, price: Decimal, timestamp: datetime | None = None
    ) -> BrokerOrder:
        order_id = self._next_order_id("lmt")
        order = BrokerOrder(
            order_id=order_id,
            status=OrderStatus.SUBMITTED,
            account_id=self._account_id,
            instrument_figi=self._figi,
            type=OrderType.LIMIT,
            side=side,
            requested_quantity=quantity,
            executed_quantity=Decimal("0"),
            price=price,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._orders[order_id] = order
        return order

    def on_bar(self, bar: Candle) -> list[BrokerDeal]:
        """Attempt to fill pending limit orders using one OHLC bar."""
        filled: list[BrokerDeal] = []
        self._last_time = bar.timestamp
        for order in list(self._orders.values()):
            if order.type != OrderType.LIMIT or order.status not in (
                OrderStatus.SUBMITTED,
                OrderStatus.NEW,
            ):
                continue
            if order.price is None or not self._limit_hit(order.side, order.price, bar):
                continue
            fee = order.price * Decimal(order.requested_quantity) * self._maker_fee
            self._apply_fill(order.side, order.requested_quantity, order.price, fee, bar.timestamp)
            order.status = OrderStatus.FILLED
            order.executed_quantity = order.requested_quantity
            order.updated_at = bar.timestamp
            deal = self._record_deal(
                order, order.price, order.requested_quantity, fee, bar.timestamp
            )
            filled.append(deal)
        return filled

    def cancel(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        order.status = OrderStatus.CANCELLED
        order.updated_at = self._last_time
        return True

    # --- internals ------------------------------------------------------------------

    def _fill_market_price(self, side: OrderSide, ref: Decimal) -> Decimal:
        if self._slippage == 0:
            return ref
        if side == OrderSide.BUY:
            return ref * (Decimal("1") + self._slippage)
        return ref * (Decimal("1") - self._slippage)

    @staticmethod
    def _limit_hit(side: OrderSide, price: Decimal | None, bar: Candle) -> bool:
        if price is None:
            return False
        if side == OrderSide.BUY:
            return Decimal(bar.low) <= price
        return Decimal(bar.high) >= price

    def _apply_fill(
        self,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        timestamp: datetime | None,
    ) -> None:
        self._fees_total += fee
        prev_qty = self._quantity

        if side == OrderSide.BUY:
            self._cash -= quantity * price + fee
            if self._quantity >= 0:
                new_q = self._quantity + quantity
                self._avg_price = (self._quantity * self._avg_price + quantity * price) / new_q
                self._quantity = new_q
            else:
                closed = min(quantity, -self._quantity)
                self._realized_gross += (self._avg_price - price) * closed
                self._quantity = self._quantity + closed
                if self._quantity == 0:
                    self._avg_price = Decimal("0")
        else:  # SELL
            self._cash += quantity * price - fee
            if self._quantity <= 0:
                new_q = self._quantity - quantity
                self._avg_price = (
                    abs(self._quantity) * self._avg_price + quantity * price
                ) / abs(new_q)
                self._quantity = new_q
            else:
                closed = min(quantity, self._quantity)
                self._realized_gross += (price - self._avg_price) * closed
                self._quantity = self._quantity - closed
                if self._quantity == 0:
                    self._avg_price = Decimal("0")

        if prev_qty == 0 and self._quantity != 0:
            self._opened_at = timestamp
        if prev_qty != 0 and self._quantity == 0:
            self._closed_at = timestamp

    def _record_deal(
        self,
        order: BrokerOrder,
        price: Decimal,
        quantity: Decimal,
        fee: Decimal,
        timestamp: datetime | None,
    ) -> BrokerDeal:
        self._deal_seq += 1
        deal = BrokerDeal(
            deal_id=f"deal-{self._deal_seq}",
            instrument_figi=self._figi or "",
            side=order.side,
            quantity=quantity,
            price=price,
            account_id=self._account_id,
            order_id=order.order_id,
            commission=fee,
            happened_at=timestamp,
        )
        self._deals.append(deal)
        return deal

    def _next_order_id(self, prefix: str) -> str:
        self._order_seq += 1
        return f"{prefix}-{self._order_seq}"

    # --- BrokerAdapter interface ----------------------------------------------------

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _account(self) -> BrokerAccount:
        return BrokerAccount(
            account_id=self._account_id,
            broker="backtest",
            currency="RUB",
            available_cash=self._cash,
            equity=self.equity(),
        )

    def _position(self) -> BrokerPosition:
        return BrokerPosition(
            account_id=self._account_id,
            instrument_figi=self._figi or "",
            quantity=abs(self._quantity),
            average_price=self._avg_price,
            current_price=self._last_price,
            current_value=abs(self._quantity) * self._last_price,
            unrealized_pnl=self.unrealized_pnl(),
            timestamp=self._closed_at or self._opened_at,
        )

    async def get_accounts(self) -> list[BrokerAccount]:
        return [self._account()]

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        return self._account()

    async def get_instruments(self, kind: str | None = None) -> list[BrokerInstrument]:
        if self._figi is None:
            return []
        return [
            BrokerInstrument(
                figi=self._figi,
                instrument_type=None,
                trading_status=TradingStatus.TRADING_AVAILABLE,
                is_active=True,
            )
        ]

    async def get_instrument(self, figi: str) -> BrokerInstrument:
        return BrokerInstrument(
            figi=figi,
            instrument_type=None,
            trading_status=TradingStatus.TRADING_AVAILABLE,
            is_active=True,
        )

    async def get_last_price(self, figi: str) -> LastPrice:
        return LastPrice(figi=figi, price=self._last_price)

    async def get_candles(
        self,
        figi: str,
        timeframe: Timeframe,
        from_: datetime,
        to: datetime,
        limit: int | None = None,
    ) -> list[Candle]:
        candles = [c for c in self._candles if from_ <= c.timestamp <= to]
        if limit is not None:
            candles = candles[:limit]
        return candles

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        qty = Decimal(str(request.quantity))
        price = Decimal(str(request.price)) if request.price is not None else None
        if request.type == OrderType.MARKET:
            return self.execute_market(request.side, qty, price=price)
        return self.place_limit(
            request.side, qty, price if price is not None else Decimal("0")
        )

    async def cancel_order(self, order_id: str) -> None:
        self.cancel(order_id)

    async def get_order(self, order_id: str) -> BrokerOrder:
        return self._orders[order_id]

    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        return [self._position()] if self.is_open() else []

    async def get_orders(self, account_id: str | None = None) -> list[BrokerOrder]:
        return list(self._orders.values())

    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        return list(self._deals)
