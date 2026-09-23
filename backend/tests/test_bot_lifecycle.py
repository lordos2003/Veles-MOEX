"""MVP-6.5 Bot lifecycle tests (deterministic).

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


# --- correction #1: lifecycle consistency -------------------------------------


class FakeBotRepo:
    """In-memory stand-in for BotRepository."""

    def __init__(self, bots: list) -> None:
        self._bots = bots
        self.saved: list[tuple[int, str]] = []

    async def get(self, bot_id: int):
        for bot in self._bots:
            if bot.id == bot_id:
                return bot
        return None

    async def list(self) -> list:
        return list(self._bots)

    async def update_state(self, bot, state: BotState):
        self.saved.append((bot.id, state.value))
        bot.status = state.value
        return bot


def _persisted_bot(bot_id: int, status: str = "STOPPED"):
    from app.models.bot import Bot

    return Bot(
        id=bot_id,
        name=f"bot-{bot_id}",
        strategy_version_id=1,
        account_id=1,
        instrument_id=1,
        status=status,
    )


def _manager(risk: RiskManager, om: OrderManager | None = None, submit_cb=None):
    def _factory(bot_id: int, state: BotState = BotState.STOPPED) -> BotRuntime:
        return BotRuntime(bot_id, risk, submit_cb=submit_cb, order_manager=om, state=state)

    return BotRuntimeManager(risk, runtime_factory=_factory)


async def test_mutating_api_rejects_without_live_runtime() -> None:
    from fastapi import HTTPException

    from app.api import bots as bots_api

    repo = FakeBotRepo([_persisted_bot(1)])
    for endpoint in (bots_api.start_bot, bots_api.stop_bot, bots_api.emergency_stop_bot):
        with pytest.raises(HTTPException) as ei:
            await endpoint(1, repo, None)
        assert ei.value.status_code == 503
    assert repo.saved == []  # no bot state changed
    assert _persisted_state(repo, 1) == "STOPPED"


def _persisted_state(repo: FakeBotRepo, bot_id: int) -> str:
    for bot in repo._bots:
        if bot.id == bot_id:
            return bot.status
    raise AssertionError(f"bot {bot_id} not in repo")


async def test_get_bot_endpoints_work_without_live_runtime() -> None:
    from fastapi import HTTPException

    from app.api import bots as bots_api

    repo = FakeBotRepo([_persisted_bot(1)])
    assert [b.id for b in await bots_api.list_bots(repo)] == [1]
    assert (await bots_api.get_bot(1, repo)).id == 1
    with pytest.raises(HTTPException) as ei:
        await bots_api.get_bot(2, repo)
    assert ei.value.status_code == 404


async def test_persisted_running_bot_not_executable_after_restart() -> None:
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    om = OrderManager(FakeBroker())
    manager = _manager(risk, om=om, submit_cb=om.submit)
    repo = FakeBotRepo([_persisted_bot(1, status=BotState.RUNNING.value)])
    await manager.restore_persisted_states(repo)
    runtime = manager.get(1)
    assert runtime is not None
    # Restarted RUNNING is blocked until an explicit START.
    assert runtime.state is BotState.ERROR
    assert repo.saved == [(1, BotState.ERROR.value)]
    # Risk slot is not implicitly occupied after restart.
    assert risk.check_start(1) is True
    # And the bot cannot submit.
    with pytest.raises(BotStateError):
        await runtime.submit_intent(_intent(om))
    # An explicit START works again.
    await manager.start(1)
    assert manager.get(1).state is BotState.RUNNING


async def test_stop_holds_risk_slot_during_cancellation() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    observations: list[bool] = []
    original_cancel = broker.cancel_order

    async def spy_cancel(order_id: str, account_id: str | None = None) -> None:
        observations.append(risk.check_start(1))
        await original_cancel(order_id, account_id)

    broker.cancel_order = spy_cancel
    rt = BotRuntime(1, risk, submit_cb=om.submit, order_manager=om)
    rt.start()
    await om.submit(_intent(om))
    await rt.stop()
    # Slot occupied while cancellation was in progress, released afterwards.
    assert observations == [False]
    assert risk.check_start(1) is True
    assert rt.state is BotState.STOPPED


async def test_cancellation_failure_leaves_error_and_releases_slot() -> None:
    from app.trading.domain import OrderState

    class FailingOrderManager:
        def list_orders(self) -> list:
            return [
                InternalOrder(
                    order_id="o-1",
                    intent_id="i-1",
                    instrument_figi="BBG000",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    requested_quantity=Decimal("1"),
                    status=OrderState.WORKING,
                    bot_id=1,
                )
            ]

        async def cancel(self, order_id: str) -> None:
            raise RuntimeError("broker unavailable")

    om = FailingOrderManager()
    risk = RiskManager()
    rt = BotRuntime(1, risk, submit_cb=None, order_manager=om)
    rt.start()
    with pytest.raises(RuntimeError):
        await rt.stop()
    assert rt.state is BotState.ERROR
    # Risk state released after the lifecycle transition finished.
    assert risk.check_start(1) is True


async def test_rejected_start_persists_error_and_returns_api_error() -> None:
    from fastapi import HTTPException

    from app.api import bots as bots_api

    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=0))
    om = OrderManager(FakeBroker())
    manager = _manager(risk, om=om, submit_cb=om.submit)
    bot = _persisted_bot(1)
    repo = FakeBotRepo([bot])
    with pytest.raises(HTTPException) as ei:
        await bots_api.start_bot(1, repo, manager)
    assert ei.value.status_code == 409
    assert repo.saved == [(1, BotState.ERROR.value)]
    assert bot.status == BotState.ERROR.value


def test_no_disconnected_fallback_runtime_manager_created() -> None:
    from types import SimpleNamespace

    from app.api.deps import get_bot_runtime_manager

    no_service = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert get_bot_runtime_manager(no_service) is None
    manager = BotRuntimeManager(RiskManager())
    with_runtime = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(live_execution=SimpleNamespace(bot_runtime=manager)))
    )
    assert get_bot_runtime_manager(with_runtime) is manager


async def test_emergency_stop_releases_risk_slot() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    rt = BotRuntime(1, risk, submit_cb=om.submit, order_manager=om)
    rt.start()
    await om.submit(_intent(om))
    await rt.emergency_stop()
    assert rt.state is BotState.EMERGENCY_STOP
    assert risk.check_start(1) is True
    with pytest.raises(BotStateError):
        await rt.submit_intent(_intent(om))
