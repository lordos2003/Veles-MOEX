"""MVP-6.3 deterministic tests: durable state, reconciliation and recovery.

These tests never place real-money orders; broker interactions are faked and
the SQLAlchemy persistence is exercised against an in-memory SQLite store.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.brokers.base import BrokerOrder, BrokerPosition
from app.models import Base
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.persistence.execution_state import SqlAlchemyLiveStateStore
from app.trading import (
    LiveRecoveryCoordinator,
    LiveStateSnapshot,
    OrderManager,
    RecoveryStatus,
)
from app.trading.domain import Fill, InternalOrder, OrderState, TradeFill
from app.trading.position_manager import Position, PositionManager


def _make_order(
    order_id: str = "order-1",
    *,
    status: OrderState = OrderState.SUBMITTED,
    broker_order_id: str | None = "broker-1",
    filled: str = "0",
    avg: str = "0",
    idempotency_key: str = "key-1",
    quantity: str = "10",
) -> InternalOrder:
    return InternalOrder(
        order_id=order_id,
        intent_id="intent-1",
        instrument_figi="BBG000",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        requested_quantity=Decimal(quantity),
        limit_price=Decimal("100"),
        idempotency_key=idempotency_key,
        account_id="acc-1",
        broker_order_id=broker_order_id,
        filled_quantity=Decimal(filled),
        average_fill_price=Decimal(avg),
        status=status,
    )


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    from app.models.live_execution import LiveFill, LiveIntent, LiveOrder, LivePosition

    live_tables = [
        LiveIntent.__table__,
        LiveOrder.__table__,
        LiveFill.__table__,
        LivePosition.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=live_tables))
    session = AsyncSession(engine, expire_on_commit=False)
    yield SqlAlchemyLiveStateStore(session)
    await session.close()
    await engine.dispose()


class FakeBroker:
    """Duck-typed broker used by the recovery coordinator."""

    def __init__(self, orders=None, positions=None, get_order=None) -> None:
        self._orders = orders or []
        self._positions = positions or []
        self._get_order = get_order

    async def get_orders(self, account_id: str | None = None) -> list:
        return self._orders

    async def get_open_positions(self, account_id: str | None = None) -> list:
        return self._positions

    async def get_order(self, order_id: str, account_id: str | None = None) -> BrokerOrder:
        if self._get_order is not None:
            return self._get_order(order_id, account_id)
        for order in self._orders:
            if order.order_id == order_id:
                return order
        raise LookupError(order_id)


def _broker_order(order_id: str, status: OrderStatus, *, idempotency_key=None) -> BrokerOrder:
    return BrokerOrder(
        order_id=order_id,
        status=status,
        idempotency_key=idempotency_key,
        reject_info=None,
    )


# --- persistence -------------------------------------------------------------


async def test_persist_and_reload_active_order(store):
    order = _make_order(status=OrderState.SUBMITTED, filled="2", avg="100")
    await store.save_snapshot(LiveStateSnapshot(orders=[order]))
    reloaded = await store.load_snapshot()
    assert len(reloaded.orders) == 1
    o = reloaded.orders[0]
    assert o.order_id == order.order_id
    assert o.status == OrderState.SUBMITTED
    assert o.broker_order_id == "broker-1"
    assert o.filled_quantity == Decimal("2")
    assert o.average_fill_price == Decimal("100")
    assert o.idempotency_key == "key-1"


async def test_persist_and_reload_fills(store):
    fill = Fill(
        fill_id="fill-1",
        internal_order_id="order-1",
        quantity=Decimal("2"),
        price=Decimal("100"),
        fee=Decimal("1"),
        broker_execution_id="t-1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await store.save_snapshot(LiveStateSnapshot(fills=[fill]))
    reloaded = await store.load_snapshot()
    assert len(reloaded.fills) == 1
    assert reloaded.fills[0].fill_id == "fill-1"
    assert reloaded.fills[0].quantity == Decimal("2")
    assert reloaded.fills[0].fee == Decimal("1")


async def test_recovered_dca_position_keeps_weighted_average(store):
    pm = PositionManager()
    pm.apply_fill("BBG000", OrderSide.BUY, Decimal("1"), Decimal("100"))
    pm.apply_fill("BBG000", OrderSide.BUY, Decimal("2"), Decimal("130"))
    pos = pm.get("BBG000")
    expected = (Decimal("1") * Decimal("100") + Decimal("2") * Decimal("130")) / Decimal("3")
    assert pos.average_price == expected
    await store.save_snapshot(LiveStateSnapshot(positions=[pos]))
    reloaded = await store.load_snapshot()
    assert reloaded.positions[0].quantity == Decimal("3")
    assert reloaded.positions[0].average_price == pos.average_price


# --- reconciliation / recovery ------------------------------------------------


async def test_restart_recovery_reconciles_order_and_position_to_broker(store):
    await store.save_snapshot(LiveStateSnapshot(orders=[_make_order()]))

    broker = FakeBroker(
        orders=[_broker_order("broker-1", OrderStatus.FILLED, idempotency_key="key-1")],
        positions=[
            BrokerPosition(
                account_id="acc-1",
                instrument_figi="BBG000",
                quantity=Decimal("10"),
                average_price=Decimal("100"),
            )
        ],
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")

    assert result.safe is True
    order = om.get_order("order-1")
    assert order.status == OrderState.FILLED
    assert om.positions().get("BBG000").quantity == Decimal("10")


async def test_broker_order_differs_from_stale_local(store):
    await store.save_snapshot(
        LiveStateSnapshot(orders=[_make_order(status=OrderState.SUBMITTED)])
    )
    broker = FakeBroker(
        orders=[_broker_order("broker-1", OrderStatus.FILLED, idempotency_key="key-1")]
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is True
    assert om.get_order("order-1").status == OrderState.FILLED


async def test_broker_position_differs_from_stale_local(store):
    await store.save_snapshot(
        LiveStateSnapshot(
            positions=[
                Position(
                    instrument_figi="BBG000",
                    quantity=Decimal("5"),
                    average_price=Decimal("50"),
                )
            ]
        )
    )
    broker = FakeBroker(
        positions=[
            BrokerPosition(
                account_id="acc-1",
                instrument_figi="BBG000",
                quantity=Decimal("8"),
                average_price=Decimal("90"),
            )
        ]
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is True
    pos = om.positions().get("BBG000")
    assert pos.quantity == Decimal("8")
    assert pos.average_price == Decimal("90")


async def test_duplicate_trade_applied_exactly_once():
    broker = FakeBroker()
    om = OrderManager(broker=broker)
    om.load_snapshot(LiveStateSnapshot(orders=[_make_order()]))
    trade = TradeFill(
        execution_id="trade-1",
        broker_order_id="broker-1",
        quantity=Decimal("2"),
        price=Decimal("100"),
        internal_order_id="order-1",
    )
    om.on_trade_fill(trade)
    om.on_trade_fill(trade)
    assert len(om.list_fills()) == 1
    assert om.positions().get("BBG000").quantity == Decimal("2")


async def test_lost_response_resolved_through_broker_query(store):
    await store.save_snapshot(
        LiveStateSnapshot(
            orders=[
                _make_order(
                    status=OrderState.UNKNOWN,
                    broker_order_id=None,
                    idempotency_key="key-9",
                )
            ]
        )
    )
    broker = FakeBroker(
        orders=[_broker_order("broker-9", OrderStatus.FILLED, idempotency_key="key-9")]
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is True
    order = om.get_order("order-1")
    assert order.status == OrderState.FILLED
    assert order.broker_order_id == "broker-9"


async def test_unresolved_order_remains_unknown_and_blocks(store):
    await store.save_snapshot(LiveStateSnapshot(orders=[_make_order(status=OrderState.SUBMITTED)]))

    def _missing(order_id, account_id):
        raise LookupError(order_id)

    broker = FakeBroker(orders=[], get_order=_missing)
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is False
    assert result.status == RecoveryStatus.BLOCKED
    assert om.get_order("order-1").status == OrderState.UNKNOWN


async def test_successful_reconciliation_allows_resume(store):
    await store.save_snapshot(
        LiveStateSnapshot(orders=[_make_order(status=OrderState.SUBMITTED)])
    )
    broker = FakeBroker(
        orders=[
            _broker_order(
                "broker-1", OrderStatus.PARTIALLY_FILLED, idempotency_key="key-1"
            )
        ]
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is True
    assert om.get_order("order-1").status == OrderState.PARTIALLY_FILLED


async def test_failed_reconciliation_blocks_new_execution(store):
    await store.save_snapshot(
        LiveStateSnapshot(orders=[_make_order(status=OrderState.WORKING)])
    )
    broker = FakeBroker(
        orders=[], get_order=lambda oid, acc: (_ for _ in ()).throw(LookupError(oid))
    )
    om = OrderManager(broker=broker)
    coordinator = LiveRecoveryCoordinator(store, om, om.positions(), broker)
    result = await coordinator.recover("acc-1")
    assert result.safe is False
    assert result.reason is not None


# --- broker-neutral guarantees ------------------------------------------------


def test_persistence_does_not_leak_broker_specific_objects():
    store_src = inspect.getsource(SqlAlchemyLiveStateStore)
    assert "tinvest" not in store_src.lower()

    from app.trading import domain, position_manager, state

    for module in (domain, position_manager, state):
        assert "import sqlalchemy" not in inspect.getsource(module)


def test_persistence_reloads_into_domain_types():
    from app.persistence import execution_state as persistence_mod

    store_src = inspect.getsource(persistence_mod)
    # The store maps ORM rows -> broker-neutral domain types, never broker DTOs.
    assert "InternalOrder" in store_src
    assert "Position" in store_src
    assert "BrokerOrder" not in store_src
