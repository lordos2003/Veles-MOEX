"""Live execution domain (MVP-6.1) tests.

Covers order lifecycle, idempotency, position accounting, integration of
OrderManager with BrokerAdapter / PositionManager, and Decimal precision.
All broker interaction uses a duck-typed fake BrokerAdapter (no T-Invest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers.base import BrokerDeal, BrokerOrder
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.trading import (
    ExecutionIntent,
    Fill,
    OrderManager,
    OrderState,
    OrderUpdate,
    PositionManager,
)


def D(v) -> Decimal:
    return Decimal(str(v))


FIGI = "BBG004730N88"


class FakeExecutionBroker:
    """Duck-typed BrokerAdapter stand-in for execution tests."""

    def __init__(self) -> None:
        self.orders: dict[str, BrokerOrder] = {}
        self.deals: list[BrokerDeal] = []
        self._seq = 0
        self.place_result: OrderStatus = OrderStatus.SUBMITTED
        self.raise_on_place: Exception | None = None
        self.raise_on_cancel: Exception | None = None
        self.called_place = 0

    async def place_order(self, request):
        self.called_place += 1
        if self.raise_on_place is not None:
            raise self.raise_on_place
        self._seq += 1
        oid = f"broker-{self._seq}"
        order = BrokerOrder(
            order_id=oid,
            status=self.place_result,
            account_id="acc",
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=D(str(request.quantity)),
            executed_quantity=D("0"),
            price=D(str(request.price)) if request.price is not None else None,
        )
        self.orders[oid] = order
        return order

    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None:
        if self.raise_on_cancel is not None:
            raise self.raise_on_cancel
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED

    async def get_order(self, order_id: str, account_id: str | None = None) -> BrokerOrder:
        return self.orders[order_id]

    async def get_deals(self) -> list[BrokerDeal]:
        return list(self.deals)

    async def get_orders(self) -> list[BrokerOrder]:
        return list(self.orders.values())

    async def get_open_positions(self) -> list:
        return []


def make_intent(
    om, order_type=OrderType.MARKET, quantity="100", figi=FIGI, intent_id="i-1", idem="k-1"
):
    return om.create_intent(
        intent_id=intent_id,
        trade_id="bot-1",
        instrument_figi=figi,
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=D(quantity),
        limit_price=D("105") if order_type == OrderType.LIMIT else None,
        idempotency_key=idem,
    )


def _fill(order_id, qty, price, fill_id="f"):
    return Fill(fill_id=fill_id, internal_order_id=order_id, quantity=D(qty), price=D(price))


def _upd(broker_id, status, order_id=None):
    return OrderUpdate(broker_order_id=broker_id, status=status, internal_order_id=order_id)


# --- Order lifecycle (1-9) ---


async def test_create_intent():
    om = OrderManager(FakeExecutionBroker())
    intent = make_intent(om)
    assert isinstance(intent, ExecutionIntent)
    assert intent.intent_id == "i-1"
    assert intent.quantity == D("100")


async def test_submit_to_submitted():
    broker = FakeExecutionBroker()
    broker.place_result = OrderStatus.SUBMITTED
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    assert order.status == OrderState.SUBMITTED
    assert order.broker_order_id == "broker-1"
    assert order.remaining_quantity == D("100")


async def test_working():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    om.on_order_update(_upd(order.broker_order_id, OrderState.WORKING, order.order_id))
    assert order.status == OrderState.WORKING


async def test_partial_fill():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    om.apply_fill(_fill(order.order_id, 30, 100, "f1"))
    assert order.status == OrderState.PARTIALLY_FILLED
    assert order.filled_quantity == D("30")
    assert order.remaining_quantity == D("70")


async def test_second_partial_fill():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    om.apply_fill(_fill(order.order_id, 30, 100, "f1"))
    om.apply_fill(_fill(order.order_id, 40, 100, "f2"))
    assert order.filled_quantity == D("70")
    assert order.remaining_quantity == D("30")
    assert order.status == OrderState.PARTIALLY_FILLED


async def test_full_fill():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    om.apply_fill(_fill(order.order_id, 30, 100, "f1"))
    om.apply_fill(_fill(order.order_id, 40, 100, "f2"))
    om.apply_fill(_fill(order.order_id, 30, 100, "f3"))
    assert order.filled_quantity == D("100")
    assert order.remaining_quantity == D("0")
    assert order.status == OrderState.FILLED


async def test_cancellation():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    cancelled = await om.cancel(order.order_id)
    assert cancelled.status == OrderState.CANCELLED


async def test_rejection():
    broker = FakeExecutionBroker()
    broker.place_result = OrderStatus.REJECTED
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    assert order.status == OrderState.REJECTED


async def test_unknown_on_lost_response():
    broker = FakeExecutionBroker()
    broker.raise_on_place = Exception("transport timeout")
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    assert order.status == OrderState.UNKNOWN


# --- Idempotency (10-12) ---


async def test_duplicate_intent_returns_same_order():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    intent = make_intent(om)
    a = await om.submit(intent)
    b = await om.submit(intent)
    assert a.order_id == b.order_id
    assert broker.called_place == 1


async def test_duplicate_idempotency_key_blocked():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    a = await om.submit(make_intent(om, intent_id="i-1", idem="same"))
    b = await om.submit(make_intent(om, intent_id="i-2", idem="same"))
    assert a.order_id == b.order_id
    assert broker.called_place == 1


async def test_duplicate_fill_event_ignored():
    broker = FakeExecutionBroker()
    om = OrderManager(broker, PositionManager())
    order = await om.submit(make_intent(om))
    om.apply_fill(_fill(order.order_id, 30, 100, "f1"))
    om.apply_fill(_fill(order.order_id, 30, 100, "f1"))
    assert order.filled_quantity == D("30")
    assert om.positions().get(FIGI).quantity == D("30")


# --- Position (13-17) ---


async def test_first_fill_creates_position():
    om = OrderManager(FakeExecutionBroker(), PositionManager())
    order = await om.submit(make_intent(om, quantity="10"))
    om.apply_fill(_fill(order.order_id, 10, 100, "f1"))
    pos = om.positions().get(FIGI)
    assert pos is not None and pos.quantity == D("10")


async def test_weighted_average_multiple_fills():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("100"), D("100"))
    pm.apply_fill(FIGI, OrderSide.BUY, D("50"), D("110"))
    pos = pm.get(FIGI)
    assert pos.average_price == D("103.3333333333333333333333333")
    assert pos.quantity == D("150")


async def test_partial_closing():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("100"), D("100"))
    pm.apply_fill(FIGI, OrderSide.SELL, D("40"), D("110"))
    pos = pm.get(FIGI)
    assert pos.quantity == D("60")
    assert pos.average_price == D("100")
    assert pos.realized_pnl == D("400")


async def test_full_closing():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("10"), D("100"))
    pm.apply_fill(FIGI, OrderSide.SELL, D("10"), D("120"))
    pos = pm.get(FIGI)
    assert pos.quantity == D("0")
    assert pos.realized_pnl == D("200")
    assert pos.average_price == D("0")


async def test_opposite_side_fill_reverses_position():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("100"), D("100"))
    pm.apply_fill(FIGI, OrderSide.SELL, D("150"), D("120"))
    pos = pm.get(FIGI)
    assert pos.quantity == D("-50")
    assert pos.average_price == D("120")
    assert pos.realized_pnl == D("2000")


# --- Integration (18-21) ---


async def test_order_manager_calls_broker():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    await om.submit(make_intent(om))
    assert broker.called_place == 1


async def test_order_manager_forwards_fills_to_position_manager():
    broker = FakeExecutionBroker()
    om = OrderManager(broker, PositionManager())
    order = await om.submit(make_intent(om, quantity="100"))
    om.apply_fill(_fill(order.order_id, 30, 80, "f1"))
    om.apply_fill(_fill(order.order_id, 70, 90, "f2"))
    pos = om.positions().get(FIGI)
    assert pos.quantity == D("100")
    assert pos.average_price == D("87")


async def test_broker_failure_creates_no_false_position():
    broker = FakeExecutionBroker()
    broker.raise_on_place = Exception("timeout")
    om = OrderManager(broker, PositionManager())
    order = await om.submit(make_intent(om))
    assert order.status == OrderState.UNKNOWN
    assert om.positions().get(FIGI) is None


async def test_submission_alone_does_not_change_position():
    broker = FakeExecutionBroker()
    broker.place_result = OrderStatus.SUBMITTED
    om = OrderManager(broker, PositionManager())
    await om.submit(make_intent(om, quantity="100"))
    assert om.positions().get(FIGI) is None


# --- Precision (22-25) ---


async def test_decimal_price_quantity_fee():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("0.5"), D("123.45"), fee=D("0.01"))
    pos = pm.get(FIGI)
    assert pos.quantity == D("0.5")
    assert pos.average_price == D("123.45")
    assert pos.fees == D("0.01")


async def test_weighted_average_no_float_error():
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, D("3"), D("0.1"))
    pm.apply_fill(FIGI, OrderSide.BUY, D("7"), D("0.2"))
    pos = pm.get(FIGI)
    expected = (D("3") * D("0.1") + D("7") * D("0.2")) / D("10")
    assert pos.average_price == expected
    assert pos.average_price == D("0.17")


async def test_fill_immutable():
    fill = Fill(fill_id="f", internal_order_id="o", quantity=D("1"), price=D("1"))
    with pytest.raises(AttributeError):
        fill.quantity = D("2")  # type: ignore[misc]


async def test_order_update_idempotent():
    broker = FakeExecutionBroker()
    om = OrderManager(broker)
    order = await om.submit(make_intent(om))
    om.on_order_update(_upd(order.broker_order_id, OrderState.WORKING, order.order_id))
    om.on_order_update(_upd(order.broker_order_id, OrderState.WORKING, order.order_id))
    assert order.status == OrderState.WORKING
