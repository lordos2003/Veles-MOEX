"""MVP-6.9 Position State & authoritative quantity tests.

The PositionManager is the only authoritative source of live execution quantity.
These focused tests cover: valid/missing/zero/negative positions, the real
quantity reaching ExitPlan and ExecutionIntent, no live exit order without a
valid position, no fabricated/default quantity, and unchanged Backtest/DCA
behavior. Deterministic and broker-neutral.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.domain.marketdata import Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading import (
    InvalidPositionQuantity,
    OrderManager,
    PositionManager,
    PositionSizing,
    PositionUnavailable,
    RiskManager,
    TradingEngine,
)
from app.trading.plan_intent import plan_to_intents

T0 = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"


class FakeBroker:
    def __init__(self) -> None:
        self.place_calls = 0

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self.place_calls += 1
        return BrokerOrder(
            order_id=f"broker-{self.place_calls}",
            status=OrderStatus.SUBMITTED,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=request.quantity,
        )


def _strategy() -> StrategyConfig:
    # MVP-6.10: live per-bot engines require the bot's own configured
    # timeframe in the strategy config (no implicit default).
    return StrategyConfig(
        direction=Direction.LONG,
        timeframe=Timeframe.MIN_5,
        entry=EntryConfig(),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )


def _context() -> Snapshot:
    return Snapshot(
        series={
            Timeframe.MIN_5: BarSeries(
                timeframe=Timeframe.MIN_5,
                bars=[Bar(T0, 100.0, 101.0, 99.0, 100.0, 1000.0)],
            )
        }
    )


# --- 1-4: PositionManager authoritative quantity -----------------------------


def test_valid_real_position_resolves_quantity() -> None:
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    assert pm.resolve_quantity(FIGI, Direction.LONG) == Decimal("10")


def test_missing_position_raises_unavailable() -> None:
    pm = PositionManager()
    with pytest.raises(PositionUnavailable):
        pm.resolve_quantity(FIGI, Direction.LONG)


def test_zero_quantity_is_invalid() -> None:
    pm = PositionManager()
    pm.apply_position_update(
        _update(FIGI, quantity=Decimal("0"), average_price=Decimal("100"))
    )
    with pytest.raises(InvalidPositionQuantity):
        pm.resolve_quantity(FIGI, Direction.LONG)


def test_negative_quantity_invalid_for_direction() -> None:
    pm = PositionManager()
    # A short position (signed negative) is inconsistent with a LONG strategy.
    pm.apply_fill(FIGI, OrderSide.SELL, Decimal("5"), Decimal("100"))
    with pytest.raises(InvalidPositionQuantity):
        pm.resolve_quantity(FIGI, Direction.LONG)
    # A SHORT strategy on the same position is valid (magnitude 5).
    assert pm.resolve_quantity(FIGI, Direction.SHORT) == Decimal("5")


# --- 5-6: real quantity reaches ExitPlan / ExecutionIntent -------------------


def test_real_quantity_reaches_exit_plan() -> None:
    pm = PositionManager()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    qty = pm.resolve_quantity(FIGI, Direction.LONG)
    plan = se.evaluate(_strategy(), _market_context(), position_qty=qty)
    exits = plan.exits
    assert len(exits) == 1
    assert exits[0].side is OrderSide.SELL
    assert exits[0].quantity == 10.0
    assert exits[0].price == Decimal("110")  # 100 * 1.10


async def test_real_quantity_reaches_execution_intent() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )
    await engine.start()
    await engine.process(_market_context())
    sell = [o for o in om.list_orders() if o.side is OrderSide.SELL]
    assert len(sell) == 1
    assert sell[0].requested_quantity == Decimal("10")
    assert sell[0].order_type is OrderType.LIMIT
    assert sell[0].limit_price == Decimal("110")


# --- 7-8: no order without a valid position; no fallback ---------------------


async def test_no_live_order_when_position_absent() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()  # empty

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )
    await engine.start()
    await engine.process(_market_context())
    # No position => no live order at all for this cycle.
    assert om.list_orders() == []


async def test_no_live_order_when_zero_quantity() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_position_update(
        _update(FIGI, quantity=Decimal("0"), average_price=Decimal("100"))
    )

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )
    await engine.start()
    await engine.process(_market_context())
    # Zero position quantity => no live order at all for this cycle.
    assert om.list_orders() == []


async def test_no_live_order_when_sign_mismatched() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    # A short position is sign-inconsistent with the LONG strategy.
    pm.apply_fill(FIGI, OrderSide.SELL, Decimal("5"), Decimal("100"))

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )
    await engine.start()
    await engine.process(_market_context())
    # Sign-inconsistent position => no live order at all for this cycle.
    assert om.list_orders() == []


async def test_no_fallback_quantity() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )
    await engine.start()
    await engine.process(_market_context())
    sell = [o for o in om.list_orders() if o.side is OrderSide.SELL]
    assert [o for o in sell if o.requested_quantity == Decimal("1.0")] == []
    assert sell[0].requested_quantity == Decimal("10")  # real position quantity


# --- 9-10: Backtest / DCA unchanged ------------------------------------------


def test_backtest_style_evaluate_unchanged() -> None:
    # The Backtest engine calls evaluate(config, context) without a position
    # quantity (it keeps its own broker position state), so exits are simply not
    # planned there and the call must not error.
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    plan = se.evaluate(_strategy(), _market_context())
    assert plan.entry is not None
    assert plan.exits == []


def test_dca_grid_unchanged() -> None:
    # DCA/Grid still builds from an explicit base nominal (MVP-6.8).
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    plan = se.evaluate(_strategy(), _market_context(), base_nominal=Decimal("5000"))
    assert len(plan.grid) == 1
    assert plan.grid[0].quantity == pytest.approx(50.0)  # 5000 / 100


def _market_context():
    from app.strategies.domain import MarketContext

    return MarketContext(price=100.0, timestamp=T0, snapshot=_context())


def _update(figi, *, quantity, average_price):
    from app.trading.domain import PositionUpdate

    return PositionUpdate(
        instrument_figi=figi,
        quantity=quantity,
        average_price=average_price,
        timestamp=T0,
    )
