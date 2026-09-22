"""T-Invest stream manager (MVP-6.2) tests.

Covers stream decoding into broker-neutral events, partial fills, deduplication
of trades arriving from both OrderStateStream and TradesStream, manager
dispatch, reconnect and unary recovery. No real network is used.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.brokers.base import BrokerOrder, BrokerPosition
from app.brokers.tinvest_streams import (
    TInvestStreamManager,
    TInvestStreamTransport,
    _decode_order_state,
    _decode_position,
    _decode_trades,
)
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.trading import OrderManager, OrderState, PositionManager

FIGI = "BBG004730N88"
_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"


def D(v) -> Decimal:
    return Decimal(str(v))


class PlaceBroker:
    """Minimal BrokerAdapter stand-in used to submit an order."""

    def __init__(self, status: OrderStatus = OrderStatus.SUBMITTED, order_id: str = "broker-1"):
        self._order_id = order_id
        self._status = status

    async def place_order(self, request) -> BrokerOrder:
        return BrokerOrder(
            order_id=self._order_id,
            status=self._status,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=D(str(request.quantity)),
        )


class RecoveryAdapter:
    """BrokerAdapter stand-in used by the stream manager for unary recovery."""

    def __init__(
        self,
        orders: list[BrokerOrder] | None = None,
        positions: list[BrokerPosition] | None = None,
    ):
        self.orders = orders or []
        self.positions = positions or []

    async def get_orders(self, account_id: str | None = None) -> list[BrokerOrder]:
        return self.orders

    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        return self.positions


class FakeStreamTransport(TInvestStreamTransport):
    """Scripted stream transport: yields batches, optionally failing initial calls."""

    def __init__(self, batches: list[dict], fail_calls: int = 0):
        self.batches = batches
        self.fail_calls = fail_calls
        self.connections = 0
        self.messages_calls = 0
        self.closed = 0

    async def connect(self, accounts: list[str]) -> None:
        self.connections += 1

    async def messages(self):
        self.messages_calls += 1
        if self.messages_calls <= self.fail_calls:
            raise ConnectionError("stream dropped")
        for message in self.batches:
            yield message

    async def close(self) -> None:
        self.closed += 1


def make_intent(
    om: OrderManager,
    quantity="25",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    account_id="acc-1",
):
    return om.create_intent(
        intent_id="i-1",
        trade_id="bot-1",
        instrument_figi=FIGI,
        side=side,
        order_type=order_type,
        quantity=D(quantity),
        limit_price=D("105") if order_type == OrderType.LIMIT else None,
        account_id=account_id,
        idempotency_key="8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
    )


async def submit(om: OrderManager, **kw):
    order = await om.submit(make_intent(om, **kw))
    return order


# --- Decoding ---


def test_decode_order_state_produces_update_and_fills() -> None:
    msg = {
        "order_id": "broker-1",
        "order_request_id": "8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
        "execution_report_status": "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
        "trades": [
            {
                "trade_id": "t1",
                "price": {"units": "100", "nano": 0},
                "quantity": 10,
                "date_time": "2025-01-01T10:00:00Z",
            },
        ],
    }
    events = _decode_order_state(msg)
    update = next(e for e in events if hasattr(e, "status"))
    assert update.status == OrderState.PARTIALLY_FILLED
    assert update.idempotency_key == "8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1"
    fills = [e for e in events if hasattr(e, "execution_id")]
    assert fills[0].execution_id == "t1"
    assert fills[0].quantity == Decimal("10")
    assert fills[0].price == Decimal("100")


def test_decode_trades_produces_fills() -> None:
    msg = {
        "order_id": "broker-1",
        "trades": [
            {"trade_id": "t1", "price": {"units": "101", "nano": 0}, "quantity": 15},
            {"trade_id": "t2", "price": {"units": "102", "nano": 0}, "quantity": 10},
        ],
    }
    fills = _decode_trades(msg)
    assert [f.execution_id for f in fills] == ["t1", "t2"]
    assert fills[0].quantity == Decimal("15")


def test_decode_position() -> None:
    msg = {"date": "2025-01-01T10:00:00Z", "securities": [{"figi": FIGI, "balance": 25}]}
    pos = _decode_position(msg)
    assert pos is not None
    assert pos.quantity == Decimal("25")
    assert pos.average_price is None


# --- Partial fills / dedup across streams ---


async def test_partial_fills_build_position() -> None:
    om = OrderManager(PlaceBroker(), PositionManager())
    order = await submit(om, quantity="25")
    om.on_trade_fill(_trade("t1", order.broker_order_id, 10, "100"))
    om.on_trade_fill(_trade("t2", order.broker_order_id, 15, "101"))
    assert order.filled_quantity == D("25")
    assert order.status == OrderState.FILLED
    assert om.positions().get(FIGI).quantity == D("25")


async def test_same_trade_from_two_streams_applied_once() -> None:
    om = OrderManager(PlaceBroker(), PositionManager())
    order = await submit(om, quantity="25")
    # The same trade_id arrives via TradesStream and OrderStateStream.trades.
    om.on_trade_fill(_trade("t1", order.broker_order_id, 10, "100"))
    om.on_trade_fill(_trade("t1", order.broker_order_id, 10, "100"))
    assert order.filled_quantity == D("10")
    assert om.positions().get(FIGI).quantity == D("10")


def _trade(execution_id, broker_order_id, qty, price):
    from app.trading import TradeFill

    return TradeFill(
        execution_id=execution_id,
        broker_order_id=broker_order_id,
        quantity=D(qty),
        price=D(price),
    )


# --- Stream manager dispatch ---


async def test_stream_manager_dispatches_order_state_and_trades() -> None:
    om = OrderManager(PlaceBroker(), PositionManager())
    order = await submit(om, quantity="25")
    transport = FakeStreamTransport(
        batches=[
            {
                "order_state": {
                    "order_id": order.broker_order_id,
                    "execution_report_status": "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
                    "trades": [
                        {"trade_id": "t1", "price": {"units": "100", "nano": 0}, "quantity": 10},
                    ],
                }
            },
            {
                "order_trades": {
                    "order_id": order.broker_order_id,
                    "trades": [
                        {"trade_id": "t2", "price": {"units": "102", "nano": 0}, "quantity": 15},
                    ],
                }
            },
        ]
    )
    mgr = TInvestStreamManager(RecoveryAdapter(), transport, om, "acc-1")
    await mgr._run_session()

    assert order.status == OrderState.FILLED
    assert order.filled_quantity == D("25")
    assert om.positions().get(FIGI).quantity == D("25")


# --- Recovery after reconnect ---


async def test_recovery_pushes_unary_order_and_position_state() -> None:
    om = OrderManager(PlaceBroker(), PositionManager())
    order = await submit(om, quantity="25")
    adapter = RecoveryAdapter(
        orders=[
            BrokerOrder(
                order_id=order.broker_order_id,
                status=OrderStatus.PARTIALLY_FILLED,
                account_id="acc-1",
                instrument_figi=FIGI,
                requested_quantity=D("25"),
            )
        ],
        positions=[
            BrokerPosition(
                account_id="acc-1",
                instrument_figi=FIGI,
                quantity=D("25"),
                average_price=D("100"),
                current_price=D("101"),
            )
        ],
    )
    transport = FakeStreamTransport(batches=[])
    mgr = TInvestStreamManager(adapter, transport, om, "acc-1")
    await mgr._recover()

    assert order.status == OrderState.PARTIALLY_FILLED
    pos = om.positions().get(FIGI)
    assert pos is not None
    assert pos.quantity == D("25")
    assert pos.average_price == D("100")


async def test_reconnect_after_disconnect() -> None:
    om = OrderManager(PlaceBroker(), PositionManager())
    adapter = RecoveryAdapter()
    transport = FakeStreamTransport(batches=[], fail_calls=1)
    mgr = TInvestStreamManager(adapter, transport, om, "acc-1", backoff=(0.0,))
    task = asyncio.create_task(mgr.run())
    await asyncio.sleep(0.05)
    mgr.stop()
    await task
    assert transport.connections >= 2
    assert transport.closed >= 2
