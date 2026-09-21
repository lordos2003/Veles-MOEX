"""Engine interface import and contract tests.

These verify the architectural frame exists and that trading methods are not
implemented yet (they raise NotImplementedError). No fake trading results.
"""

from __future__ import annotations

import asyncio

import pytest

from app.backtest import BacktestBroker, BacktestEngine
from app.brokers import BrokerOrderRequest, TInvestAdapter
from app.models.enums import OrderSide, OrderType
from app.strategies import (
    DCAGridConfig,
    DCAGridEngine,
    Direction,
    EntryConfig,
    EntryEngine,
    ExitConfig,
    ExitEngine,
    FixedPercentageTP,
    MarketContext,
    StrategyConfig,
    StrategyEngine,
)
from app.trading import OrderManager, PositionManager, RiskManager, TradingEngine


def test_strategy_engine_constructs() -> None:
    entry = EntryEngine()
    dca = DCAGridEngine()
    exit_engine = ExitEngine()
    se = StrategyEngine(entry, dca, exit_engine)
    assert se.entry is entry
    assert se.dca_grid is dca
    assert se.exit_engine is exit_engine


def test_trading_engine_constructs() -> None:
    broker = TInvestAdapter()
    order_manager = OrderManager(broker)
    position_manager = PositionManager()
    risk_manager = RiskManager()
    strategy_engine = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    te = TradingEngine(broker, strategy_engine, order_manager, position_manager, risk_manager)
    assert te.broker is broker


def test_backtest_engine_constructs_with_trading_engine() -> None:
    broker = BacktestBroker()
    order_manager = OrderManager(broker)
    te = TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        order_manager,
        PositionManager(),
        RiskManager(),
    )
    be = BacktestEngine(te)
    assert be.trading_engine is te


def test_strategy_methods_not_implemented() -> None:
    entry = EntryEngine()
    dca = DCAGridEngine()
    exit_engine = ExitEngine()
    se = StrategyEngine(entry, dca, exit_engine)
    cfg = ExitConfig(take_profit=FixedPercentageTP(percent=2.0))

    # Entry without market snapshot -> no signal (not a NotImplementedError).
    assert entry.evaluate(EntryConfig(), Direction.LONG, MarketContext()) is None

    # DCA/Grid (MVP-4) builds a deterministic grid state.
    from decimal import Decimal

    state = dca.build(DCAGridConfig(), Decimal("100"), Direction.LONG)
    assert state is not None and len(state.levels) == 1
    assert state.active_orders()

    # Exit recalculation after averaging is a later stage.
    with pytest.raises(NotImplementedError):
        exit_engine.on_average(cfg, average_price=100.0, position_qty=10.0, old_exits=[])

    # Strategy without market snapshot -> no entry signal.
    plan = se.evaluate(StrategyConfig(exit=cfg), MarketContext())
    assert plan.entry is None


def test_async_trading_methods_not_implemented() -> None:
    broker = TInvestAdapter()
    order_manager = OrderManager(broker)

    async def _run() -> None:
        request = BrokerOrderRequest(
            instrument_figi="BBG004730N88",
            side=OrderSide.BUY,
            quantity=1,
            type=OrderType.MARKET,
        )
        await order_manager.create(request)

    with pytest.raises(NotImplementedError):
        asyncio.run(_run())
