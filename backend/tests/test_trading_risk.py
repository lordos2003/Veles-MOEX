"""MVP-6 integration: RiskManager / TradingEngine / live path (deterministic).

These tests never place real-money orders and use only broker-neutral fakes.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from app.brokers.base import BrokerAccount, BrokerOrder
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.trading import (
    LiveExecutionBlocked,
    LiveExecutionService,
    OrderManager,
    RiskLimits,
    RiskManager,
    RiskRejected,
    TradingEngine,
)
from app.trading.domain import ExecutionIntent
from app.trading.state import InMemoryLiveStateStore


class FakeBroker:
    """Duck-typed broker for the live/risk tests."""

    def __init__(self, orders=None, positions=None) -> None:
        self._orders = orders or []
        self._positions = positions or []
        self.place_calls = 0

    async def get_orders(self, account_id: str | None = None) -> list:
        return self._orders

    async def get_open_positions(self, account_id: str | None = None) -> list:
        return self._positions

    async def get_deals(self, account_id: str | None = None) -> list:
        return []

    async def get_accounts(self) -> list:
        return [BrokerAccount(account_id="acc-1")]

    async def place_order(self, request) -> BrokerOrder:
        self.place_calls += 1
        return BrokerOrder(
            order_id=request.idempotency_key or "broker-1",
            status=OrderStatus.SUBMITTED,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=request.quantity,
        )


def _intent(om: OrderManager, quantity="5", instrument_figi="BBG000") -> ExecutionIntent:
    return om.create_intent(
        intent_id="i-int",
        trade_id="bot-1",
        instrument_figi=instrument_figi,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        account_id="acc-1",
        idempotency_key="idem-int",
    )


async def _service(risk_manager: RiskManager) -> tuple[LiveExecutionService, FakeBroker]:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    store = InMemoryLiveStateStore()
    service = LiveExecutionService(
        broker, store, om, pm, "acc-1", risk_manager=risk_manager
    )
    result = await service.start()
    assert result.safe is True
    return service, broker


async def test_emergency_stop_blocks_submit() -> None:
    risk = RiskManager(limits=RiskLimits(emergency_stop=True))
    service, broker = await _service(risk)
    with pytest.raises(RiskRejected):
        await service.submit(_intent(service._order_manager))
    assert broker.place_calls == 0


async def test_position_size_limit_blocks_submit() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill("BBG000", OrderSide.BUY, Decimal("8"), Decimal("100"))
    risk = RiskManager(
        limits=RiskLimits(max_position_size=Decimal("10")), position_manager=pm
    )
    service, _ = await _service(risk)
    with pytest.raises(RiskRejected):
        await service.submit(_intent(service._order_manager, quantity="5"))
    assert broker.place_calls == 0


async def test_allowed_intent_reaches_order_manager() -> None:
    service, broker = await _service(RiskManager())
    order = await service.submit(_intent(service._order_manager, quantity="5"))
    assert order is not None
    assert order.broker_order_id is not None
    assert broker.place_calls == 1


async def test_live_execution_cannot_bypass_risk_manager() -> None:
    # Even with a SAFE recovery, a risk violation must not reach the broker.
    risk = RiskManager(limits=RiskLimits(emergency_stop=True))
    service, broker = await _service(risk)
    with pytest.raises(RiskRejected):
        await service.submit(_intent(service._order_manager))
    assert broker.place_calls == 0


async def test_safe_blocked_recovery_gate_still_blocks() -> None:
    # BLOCKED recovery gate must block submit even when risk would allow it.
    broker = FakeBroker(orders=[], positions=[])
    om = OrderManager(broker)
    pm = om.positions()
    store = InMemoryLiveStateStore()
    service = LiveExecutionService(
        broker, store, om, pm, "acc-1",
        risk_manager=RiskManager(),
    )
    # Force a blocked recovery: an unresolved active order in the snapshot.
    from app.trading import LiveStateSnapshot
    from app.trading.domain import InternalOrder, OrderState

    await store.save_snapshot(
        LiveStateSnapshot(
            orders=[
                InternalOrder(
                    order_id="order-1",
                    intent_id="i-1",
                    instrument_figi="BBG000",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("5"),
                    idempotency_key="key-1",
                    broker_order_id="broker-1",
                    status=OrderState.SUBMITTED,
                )
            ]
        )
    )
    result = await service.start()
    assert result.safe is False
    with pytest.raises(LiveExecutionBlocked):
        await service.submit(_intent(service._order_manager))


def test_trading_engine_does_not_import_tinvest() -> None:
    from app.trading import engine as engine_module

    src = inspect.getsource(engine_module)
    # The engine must not import T-Invest (only the broker-neutral interface).
    assert "from app.brokers.tinvest" not in src
    assert "import tinvest" not in src
    assert "from app.brokers import" in src


async def test_trading_engine_process_routes_through_risk() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    risk = RiskManager(limits=RiskLimits(emergency_stop=True))

    class _SE:
        def evaluate(self, config, context):
            from app.strategies.domain import EntrySignal, Plan

            return Plan(entry=EntrySignal(action="enter", direction=OrderSide.BUY))

    def intent_factory(_plan, _context):
        return _intent(om)

    te = TradingEngine(
        broker,
        _SE(),
        om,
        pm,
        risk,
        strategy_config=object(),
        intent_factory=intent_factory,
    )
    await te.start()
    with pytest.raises(RiskRejected):
        await te.process(None)
    assert broker.place_calls == 0


async def test_process_requires_strategy_engine_and_config() -> None:
    """process() must not be invoked with a missing strategy engine/config."""
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    te = TradingEngine(broker, None, om, pm, RiskManager())
    await te.start()
    with pytest.raises(RuntimeError):
        await te.process(None)
