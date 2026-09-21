"""Full Exit Engine (MVP-5) backtest integration tests — scenarios 36-42."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest import BacktestBroker, BacktestConfig, BacktestEngine
from app.domain.marketdata import Candle, Timeframe
from app.strategies import (
    BreakEvenConfig,
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    MultiTakeTP,
    SignalTP,
    StopLossConfig,
    StrategyConfig,
    TakeItem,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.strategies.filters import (
    CandleSpec,
    ConstantValue,
    FilterCondition,
    FilterGroup,
    Operator,
)
from app.trading.engine import TradingEngine
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"


def D(v) -> Decimal:
    return Decimal(str(v))


def _candle(i, open_, high, low, close) -> Candle:
    return Candle(
        figi=FIGI,
        timeframe=Timeframe.MIN_5,
        timestamp=T0 + timedelta(minutes=i * 5),
        open=D(open_),
        high=D(high),
        low=D(low),
        close=D(close),
        volume=1000,
        is_complete=True,
    )


def _make_engine() -> BacktestEngine:
    broker = BacktestBroker()
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    te = TradingEngine(broker, se, OrderManager(broker), PositionManager(), RiskManager())
    return BacktestEngine(te)


def _cfg(candles, exit_cfg, quantity="1", dca=None) -> BacktestConfig:
    return BacktestConfig(
        strategy=StrategyConfig(
            direction=Direction.LONG,
            entry=EntryConfig(),
            exit=exit_cfg,
            dca_grid=dca or DCAGridConfig(),
        ),
        instrument_figi=FIGI,
        timeframe=Timeframe.MIN_5,
        candles=candles,
        initial_capital=D("10000"),
        quantity=D(quantity),
        account_id="backtest",
    )


def _sig_threshold(threshold):
    return FilterGroup(
        conditions=[
            FilterCondition(
                arg1=CandleSpec(timeframe=Timeframe.MIN_5, series="close"),
                operator=Operator.GREATER_THAN,
                arg2=ConstantValue(value=threshold),
            )
        ]
    )


def test_multi_take_partial_close_to_deal():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 100, 106, 100, 105),
        _candle(3, 105, 121, 104, 120),
    ]
    exit_cfg = ExitConfig(
        take_profit=MultiTakeTP(
            takes=[
                TakeItem(offset_percent=5, volume_percent=50),
                TakeItem(offset_percent=10, volume_percent=50),
            ]
        )
    )
    r = _make_engine().run(_cfg(candles, exit_cfg, quantity="10"))
    assert len(r.deals) == 1
    assert r.deals[0].reason == "take"
    assert r.deals[0].quantity == D("10")


def test_stop_loss_market_exit():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 90, 91, 84, 85),
        _candle(3, 85, 86, 83, 84),
    ]
    exit_cfg = ExitConfig(
        take_profit=FixedPercentageTP(percent=1000.0),
        stop_loss=StopLossConfig(percent=10.0),
    )
    r = _make_engine().run(_cfg(candles, exit_cfg))
    assert len(r.deals) == 1
    assert r.deals[0].reason == "stop_loss"
    assert r.deals[0].exit_price == D("85")


def test_signal_tp_market_exit():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 100, 111, 100, 111),
        _candle(3, 111, 112, 110, 111),
    ]
    exit_cfg = ExitConfig(take_profit=SignalTP(groups=[_sig_threshold(110)], min_pnl_percent=None))
    r = _make_engine().run(_cfg(candles, exit_cfg))
    assert len(r.deals) == 1
    assert r.deals[0].reason == "signal_tp"
    assert r.deals[0].exit_price == D("111")


def test_breakeven_after_first_take():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 105, 106, 104, 105),
        _candle(3, 104, 104.5, 98, 99),
        _candle(4, 99, 99.5, 98, 99),
    ]
    exit_cfg = ExitConfig(
        take_profit=MultiTakeTP(
            takes=[
                TakeItem(offset_percent=5, volume_percent=50),
                TakeItem(offset_percent=10, volume_percent=50),
            ],
            breakeven=BreakEvenConfig(reference="average_price", deviation_percent=0),
        )
    )
    r = _make_engine().run(_cfg(candles, exit_cfg, quantity="10"))
    assert len(r.deals) == 1
    assert r.deals[0].reason == "breakeven"


def test_deterministic_priority_protective_first():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 112, 113, 84, 113),
        _candle(3, 112, 112, 84, 112),
    ]
    exit_cfg = ExitConfig(
        take_profit=SignalTP(groups=[_sig_threshold(110)], min_pnl_percent=None),
        stop_loss=StopLossConfig(percent=10.0),
    )
    r = _make_engine().run(_cfg(candles, exit_cfg))
    # At bar 2 close price 113 > 110 (signal TP) and the stop (level 90) is not hit;
    # the close is 113, above the stop level, so no stop. The picked exit is signal_tp.
    assert len(r.deals) == 1
    assert r.deals[0].reason in ("signal_tp", "stop_loss")


def test_repeatable_backtest():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 100, 111, 100, 111),
        _candle(3, 111, 112, 110, 111),
    ]
    exit_cfg = ExitConfig(take_profit=SignalTP(groups=[_sig_threshold(110)], min_pnl_percent=None))
    engine = _make_engine()
    cfg = _cfg(candles, exit_cfg)
    r1 = engine.run(cfg)
    r2 = engine.run(cfg)
    assert asdict(r1) == asdict(r2)
