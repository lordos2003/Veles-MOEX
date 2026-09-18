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
    with pytest.raises(NotImplementedError):
        entry.evaluate(EntryConfig(), MarketContext())

    dca = DCAGridEngine()
    with pytest.raises(NotImplementedError):
        dca.build_grid(DCAGridConfig(), 100.0)

    exit_engine = ExitEngine()
    cfg = ExitConfig(take_profit=FixedPercentageTP(percent=2.0))
    with pytest.raises(NotImplementedError):
        exit_engine.build_exit_orders(cfg, average_price=100.0, position_qty=10.0)

    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    with pytest.raises(NotImplementedError):
        se.evaluate(StrategyConfig(exit=cfg), MarketContext())


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
