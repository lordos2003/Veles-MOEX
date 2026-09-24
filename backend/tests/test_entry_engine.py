"""Tests for the EntryEngine and basic Exit / StrategyEngine (Strategy Engine MVP-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.marketdata import Timeframe
from app.models.enums import OrderSide
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext
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

UTC = UTC
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def _series(closes: list[float]) -> BarSeries:
    bars = [
        Bar(
            timestamp=T0 + timedelta(minutes=i),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=1.0,
            is_complete=True,
        )
        for i, c in enumerate(closes)
    ]
    return BarSeries(timeframe=Timeframe.MIN_5, bars=bars)


def _snapshot(closes: list[float]) -> Snapshot:
    s = _series(closes)
    return Snapshot(series={s.timeframe: s})


def _entry_gt(threshold: float) -> EntryConfig:
    cond = FilterCondition(
        arg1=CandleSpec(timeframe=Timeframe.MIN_5, series="close"),
        operator=Operator.GREATER_THAN,
        arg2=ConstantValue(value=threshold),
    )
    return EntryConfig(groups=[FilterGroup(conditions=[cond])])


def test_entry_long_buys() -> None:
    ev = EntryEngine()
    context = MarketContext(snapshot=_snapshot([90, 95, 105]), timestamp=T0 + timedelta(minutes=2))
    signal = ev.evaluate(_entry_gt(100), Direction.LONG, context)
    assert signal is not None
    assert signal.direction == OrderSide.BUY
    assert signal.action == "enter"


def test_entry_short_sells() -> None:
    ev = EntryEngine()
    context = MarketContext(snapshot=_snapshot([90, 95, 105]), timestamp=T0 + timedelta(minutes=2))
    signal = ev.evaluate(_entry_gt(100), Direction.SHORT, context)
    assert signal is not None
    assert signal.direction == OrderSide.SELL


def test_entry_no_signal_without_snapshot() -> None:
    ev = EntryEngine()
    assert ev.evaluate(_entry_gt(100), Direction.LONG, MarketContext()) is None


def test_entry_unconditional_fires() -> None:
    ev = EntryEngine()
    context = MarketContext(snapshot=_snapshot([100]), timestamp=T0)
    signal = ev.evaluate(EntryConfig(), Direction.LONG, context)
    assert signal is not None
    assert signal.direction == OrderSide.BUY


def test_fixed_percentage_tp_long_target() -> None:
    te = ExitEngine()
    cfg = ExitConfig(take_profit=FixedPercentageTP(percent=10.0))
    plans = te.build_exit_orders(cfg, Direction.LONG, entry_price=Decimal("100"), position_qty=3)
    assert len(plans) == 1
    assert plans[0].price == Decimal("110")
    assert plans[0].side == OrderSide.SELL
    assert plans[0].quantity == 3


def test_fixed_percentage_tp_short_target() -> None:
    te = ExitEngine()
    cfg = ExitConfig(take_profit=FixedPercentageTP(percent=10.0))
    plans = te.build_exit_orders(cfg, Direction.SHORT, entry_price=Decimal("100"), position_qty=2)
    assert len(plans) == 1
    assert plans[0].price == Decimal("90")
    assert plans[0].side == OrderSide.BUY


def test_strategy_engine_plan_entry_and_exit() -> None:
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    cfg = StrategyConfig(
        direction=Direction.LONG,
        entry=_entry_gt(100),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
    )
    context = MarketContext(
        snapshot=_snapshot([90, 95, 105]),
        timestamp=T0 + timedelta(minutes=2),
        price=105.0,
    )
    plan = se.evaluate(cfg, context, position_qty=Decimal("2"))
    assert plan.entry is not None
    assert plan.entry.direction == OrderSide.BUY
    assert len(plan.exits) == 1
    assert plan.exits[0].price == Decimal("115.5")  # 105 * 1.10
    assert plan.exits[0].quantity == 2.0
