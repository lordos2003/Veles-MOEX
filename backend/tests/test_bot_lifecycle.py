"""VIP-6.5 Bot lifecycle tests (deterministic).

These tests use only broker-neutral fakes and never place real orders. They
cover the bot state machine, the RiskManager start guard, the execution gate and
the recovery SAFE/BLOCKED gate.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.models.enums import BotState, OrderSide, OrderStatus, OrderType
from app.trading import (
    BotRuntime,
    BotRuntimeManager,
    BotStartRejected,
    BotStateError,
    InMemoryLiveStateStore,
    LiveExecutionBlocked,
    LiveExecutionService,
    OrderManager,
    RiskLimits,
    RiskManager,
    TradingEngine,
)
from app.trading.bot_lifecycle import can_transition
from app.trading.domain import ExecutionIntent, InternalOrder


class FakeBroker:
    """Duck-typed broker for lifecycle tests."""

    def __init__(self, orders=None, positions=None) -> None:
        self._orders = orders or []
        self._positions = positions or []
        self.place_calls = 0
        self.cancel_calls: list[tuple[str, str]] = []
        self.cancelled: set[str] = set()

    async def get_orders(self, account_id: str | None = None) -> list:
        return self._orders

    async def get_open_positions(self, account_id: str | None = None) -> list:
        return self._positions

    async def get_deals(self, account_id: str | None = None) -> list:
        return []

    async def get_accounts(self) -> list:
        from app.brokers.base import BrokerAccount

        return [BrokerAccount(account_id="acc-1")]

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self.place_calls += 1
        order_id = f"broker-{self.place_calls}"
        if getattr(request, "idempotency_key", None):
            order_id = request.idempotency_key
        return BrokerOrder(
            order_id=order_id,
            status=OrderStatus.SUBMITTED,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=request.quantity,
        )

    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None:
        self.cancel_calls.append((order_id, account_id or ""))
        self.cancelled.add(order_id)


def _intent(om: OrderManager, bot_id: int = 1, quantity="5") -> ExecutionIntent:
    return om.create_intent(
        intent_id=f"i-{bot_id}-{om.list_intents().__len__()}",
        trade_id=f"trade-{bot_id}",
        instrument_figi="BBG000",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        account_id="acc-1",
        idempotency_key=f"idem-{bot_id}",
        bot_id=bot_id,
    )


def _runtime(risk: RiskManager, submit_cb=None, om: OrderManager | None = None) -> BotRuntime:
    return BotRuntime(1, risk, submit_cb=submit_cb, order_manager=om)


async def test_valid_start_transition_to_running() -> None:
    rt = _runtime(RiskManager())
    assert rt.state is BotState.STOPPED
    rt.start()
    assert rt.state is BotState.RUNNING
    assert rt.can_submit() is True


async def test_check_start_blocks_start() -> None:
    # max_concurrent_bots == 0 => the risk manager denies every START.
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=0))
    rt = _runtime(risk)
    with pytest.raises(BotStartRejected):
        rt.start()
    assert rt.state is BotState.ERROR


async def test_successful_start_registers_active_bot() -> None:
    # max_concurrent_bots == 1: the first bot can start, a second cannot.
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    first = _runtime(risk)
    first.start()
    assert first.state is BotState.RUNNING
    second = BotRuntime(2, risk)
    with pytest.raises(BotStartRejected):
        second.start()
    # Stopping frees the slot.
    await first.stop()
    second.start()
    assert second.state is BotState.RUNNING


async def test_stop_blocks_new_intents() -> None:
    calls: list[int] = []

    async def _submit(intent: ExecutionIntent) -> InternalOrder:
        calls.append(1)
        return InternalOrder(
            order_id="o-1",
            intent_id=intent.intent_id,
            instrument_figi="BBG000",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=intent.quantity,
        )

    rt = _runtime(RiskManager(), submit_cb=_submit)
    rt.start()
    await rt.stop()
    assert rt.state is BotState.STOPPED
    with pytest.raises(BotStateError):
        await rt.submit_intent(_intent(OrderManager(FakeBroker())))
    assert calls == []


async def test_normal_stop_does_not_close_position() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    # Seed a real (filled) position that must survive a normal stop.
    om.positions().apply_fill("BBG000", OrderSide.BUY, Decimal("5"), Decimal("100"))
    risk = RiskManager(position_manager=om.positions())
    rt = BotRuntime(1, risk, submit_cb=om.submit, order_manager=om)
    rt.start()
    await rt.stop()
    assert rt.state is BotState.STOPPED
    position = om.positions().get("BBG000")
    assert position is not None
    assert position.quantity == Decimal("5")


async def test_emergency_stop_blocks_new_intents() -> None:
    calls: list[int] = []

    async def _submit(intent: ExecutionIntent) -> InternalOrder:
        calls.append(1)
        return InternalOrder(
            order_id="o-1",
            intent_id=intent.intent_id,
            instrument_figi="BBG000",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=intent.quantity,
        )

    rt = _runtime(RiskManager(), submit_cb=_submit)
    rt.start()
    await rt.emergency_stop()
    assert rt.state is BotState.EMERGENCY_STOP
    with pytest.raises(BotStateError):
        await rt.submit_intent(_intent(OrderManager(FakeBroker())))
    assert calls == []


async def test_emergency_stop_cancels_active_orders() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager()
    rt = BotRuntime(1, risk, submit_cb=om.submit, order_manager=om)
    rt.start()
    order = await om.submit(_intent(om))
    await rt.emergency_stop()
    assert broker.cancel_calls == [(order.broker_order_id, "acc-1")]


async def test_invalid_state_transitions_are_rejected() -> None:
    rt = _runtime(RiskManager())
    # RUNNING -> STARTING is not allowed.
    rt.start()
    with pytest.raises(BotStateError):
        rt.start()
    assert rt.state is BotState.RUNNING


async def test_transition_table() -> None:
    assert can_transition(BotState.STOPPED, BotState.STARTING)
    assert can_transition(BotState.STARTING, BotState.RUNNING)
    assert can_transition(BotState.RUNNING, BotState.EMERGENCY_STOP)
    assert not can_transition(BotState.STOPPED, BotState.RUNNING)
    assert not can_transition(BotState.EMERGENCY_STOP, BotState.RUNNING)


def test_bot_lifecycle_and_engine_do_not_import_tinvest() -> None:
    from app.trading import bot_lifecycle as module

    src = inspect.getsource(module)
    assert "from app.brokers.tinvest" not in src
    assert "import tinvest" not in src


async def test_safe_blocked_recovery_gate_still_blocks_with_bot_gate() -> None:
    from app.trading import LiveStateSnapshot
    from app.trading.domain import OrderState

    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    store = InMemoryLiveStateStore()
    risk = RiskManager()
    engine = TradingEngine(broker, None, om, pm, risk)
    runtime_manager = BotRuntimeManager(risk)
    service = LiveExecutionService(
        broker,
        store,
        om,
        pm,
        "acc-1",
        risk_manager=risk,
        trading_engine=engine,
        bot_runtime_manager=runtime_manager,
    )
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
        await service.submit(_intent(om))
