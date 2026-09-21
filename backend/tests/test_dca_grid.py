"""Deterministic DCA / Grid engine (MVP-4) tests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest import BacktestBroker, BacktestConfig, BacktestEngine
from app.domain.marketdata import Candle, Timeframe
from app.models.enums import OrderSide
from app.strategies import (
    CustomLevel,
    DCAGridConfig,
    DCAGridEngine,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    LevelStatus,
    SignalOffsetReference,
    StrategyConfig,
    TradingMode,
)
from app.strategies.dca_grid import GridState
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading.engine import TradingEngine
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"
ENG = DCAGridEngine()


def D(value) -> Decimal:
    return Decimal(str(value))


def _build(config: DCAGridConfig, ref: str, direction, base="100") -> GridState:
    return ENG.build(config, D(ref), direction, base_nominal=D(base))


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


def _bt_cfg(candles, dca, tp_percent=10.0, quantity="1", initial="10000") -> BacktestConfig:
    return BacktestConfig(
        strategy=StrategyConfig(
            direction=Direction.LONG,
            entry=EntryConfig(),
            exit=ExitConfig(take_profit=FixedPercentageTP(percent=tp_percent)),
            dca_grid=dca,
        ),
        instrument_figi=FIGI,
        timeframe=Timeframe.MIN_5,
        candles=candles,
        initial_capital=D(initial),
        quantity=D(quantity),
        account_id="backtest",
    )


def _prices(state):
    return [round(lvl.price, 4) for lvl in state.levels]


# --- SIMPLE LONG / SHORT / coverage / levels ---


def test_simple_long_grid():
    state = _build(DCAGridConfig(levels=5, overlap_percent=40.0), "100", Direction.LONG)
    assert _prices(state) == [D("100"), D("90"), D("80"), D("70"), D("60")]
    assert all(lvl.side == OrderSide.BUY for lvl in state.levels)
    assert state.levels[0].is_market is True


def test_simple_short_grid():
    state = _build(DCAGridConfig(levels=5, overlap_percent=40.0), "100", Direction.SHORT)
    assert _prices(state) == [D("100"), D("110"), D("120"), D("130"), D("140")]
    assert all(lvl.side == OrderSide.SELL for lvl in state.levels)


def test_first_order_offset():
    state = _build(
        DCAGridConfig(levels=3, overlap_percent=20.0, first_order_offset_percent=5.0),
        "100",
        Direction.LONG,
    )
    assert state.levels[0].price == D("95")
    assert state.levels[0].is_market is False
    state_s = _build(
        DCAGridConfig(levels=3, overlap_percent=20.0, first_order_offset_percent=5.0),
        "100",
        Direction.SHORT,
    )
    assert state_s.levels[0].price == D("105")


def test_zero_offset_market_first():
    state = _build(
        DCAGridConfig(levels=3, overlap_percent=20.0, first_order_offset_percent=0.0),
        "100",
        Direction.LONG,
    )
    assert state.levels[0].is_market is True
    assert state.levels[0].price == D("100")


def test_total_price_coverage():
    state = _build(DCAGridConfig(levels=3, overlap_percent=30.0), "100", Direction.LONG)
    assert state.levels[-1].price == D("70")


def test_number_of_levels():
    for n in (1, 3, 8):
        state = _build(DCAGridConfig(levels=n, overlap_percent=30.0), "100", Direction.LONG)
        assert len(state.levels) == n


def test_linear_spacing():
    state = _build(DCAGridConfig(levels=5, overlap_percent=40.0), "100", Direction.LONG)
    gaps = [state.levels[i + 1].price - state.levels[i].price for i in range(4)]
    assert gaps == [D("-10")] * 4


# --- logarithmic distribution ---


def test_log_coeff_one_is_linear():
    state = _build(
        DCAGridConfig(levels=5, overlap_percent=40.0, logarithmic_factor=1.0),
        "100",
        Direction.LONG,
    )
    assert _prices(state) == [D("100"), D("90"), D("80"), D("70"), D("60")]


def test_log_greater_one_denser_near_reference():
    state = _build(
        DCAGridConfig(levels=5, overlap_percent=40.0, logarithmic_factor=2.0),
        "100",
        Direction.LONG,
    )
    prices = [lvl.price for lvl in state.levels]
    assert abs(prices[1] - prices[0]) < abs(prices[-1] - prices[-2])


def test_log_less_one_denser_far():
    state = _build(
        DCAGridConfig(levels=5, overlap_percent=40.0, logarithmic_factor=0.5),
        "100",
        Direction.LONG,
    )
    prices = [lvl.price for lvl in state.levels]
    assert abs(prices[1] - prices[0]) > abs(prices[-1] - prices[-2])


# --- martingale ---


def test_martingale_nominal_sizing():
    state = _build(DCAGridConfig(levels=3, martingale_percent=100.0), "100", Direction.LONG)
    nominals = [lvl.nominal for lvl in state.levels]
    assert nominals == [D("100"), D("200"), D("400")]


def test_martingale_long_quantity():
    state = _build(
        DCAGridConfig(levels=3, overlap_percent=20.0, martingale_percent=100.0),
        "100",
        Direction.LONG,
    )
    qty = [lvl.quantity for lvl in state.levels]
    assert qty[0] == D("1")
    assert qty[0] < qty[1] < qty[2]


def test_martingale_short_quantity_can_decrease():
    state = _build(
        DCAGridConfig(levels=3, overlap_percent=20.0, martingale_percent=0.0),
        "100",
        Direction.SHORT,
    )
    qty = [lvl.quantity for lvl in state.levels]
    assert qty[0] > qty[1] > qty[2]
    assert state.levels[0].nominal == state.levels[1].nominal == D("100")


# --- CUSTOM ---


def test_custom_grid():
    cfg = DCAGridConfig(
        mode=TradingMode.CUSTOM,
        custom_levels=[
            CustomLevel(offset_percent=5, nominal_percent=50),
            CustomLevel(offset_percent=10, nominal_percent=50),
        ],
    )
    state = _build(cfg, "100", Direction.LONG)
    assert [round(lvl.price, 4) for lvl in state.levels] == [D("95"), D("90")]
    assert [lvl.nominal for lvl in state.levels] == [D("50"), D("50")]


def test_custom_single_order():
    cfg = DCAGridConfig(
        mode=TradingMode.CUSTOM,
        custom_levels=[CustomLevel(offset_percent=3, nominal_percent=100)],
    )
    state = _build(cfg, "100", Direction.LONG)
    assert len(state.levels) == 1
    assert state.levels[0].nominal == D("100")


def test_custom_invalid_offsets():
    cfg = DCAGridConfig(
        mode=TradingMode.CUSTOM,
        custom_levels=[
            CustomLevel(offset_percent=10, nominal_percent=50),
            CustomLevel(offset_percent=5, nominal_percent=50),
        ],
    )
    with pytest.raises(ValueError):
        _build(cfg, "100", Direction.LONG)


# --- partial grid ---


def test_partial_grid_submission():
    state = _build(
        DCAGridConfig(levels=5, overlap_percent=20.0, active_limit=3), "100", Direction.LONG
    )
    assert len(state.active_orders()) == 3
    assert len(state.waiting_orders()) == 2


def test_next_waiting_level_activated_after_fill():
    state = _build(
        DCAGridConfig(levels=5, overlap_percent=20.0, active_limit=3), "100", Direction.LONG
    )
    ENG.on_fill(state, 0)
    assert 0 in state.filled
    assert [p.level_index for p in state.active_orders()] == [1, 2, 3]
    assert [p.level_index for p in state.waiting_orders()] == [4]


# --- pull-up ---


def test_pullup_long():
    cfg = DCAGridConfig(
        levels=3, overlap_percent=20.0, first_order_offset_percent=5.0, pull_up_percent=2.0
    )
    state = _build(cfg, "100", Direction.LONG)
    assert ENG.evaluate_pullup(cfg, state, D("100"), D("97")) is True
    assert ENG.evaluate_pullup(cfg, state, D("100"), D("96")) is False


def test_pullup_short():
    cfg = DCAGridConfig(
        levels=3, overlap_percent=20.0, first_order_offset_percent=5.0, pull_up_percent=2.0
    )
    state = _build(cfg, "100", Direction.SHORT)
    assert ENG.evaluate_pullup(cfg, state, D("100"), D("103")) is True
    assert ENG.evaluate_pullup(cfg, state, D("100"), D("104")) is False


def test_pullup_ignored_for_market_first():
    cfg = DCAGridConfig(
        levels=3, overlap_percent=20.0, first_order_offset_percent=0.0, pull_up_percent=2.0
    )
    state = _build(cfg, "100", Direction.LONG)
    assert ENG.evaluate_pullup(cfg, state, D("100"), D("200")) is False


# --- SIGNAL mode ---


def test_signal_first_market_order():
    cfg = DCAGridConfig(mode=TradingMode.SIGNAL, first_order_offset_percent=0.0)
    state = _build(cfg, "100", Direction.LONG)
    assert state.levels[0].is_market is True
    assert state.levels[0].price == D("100")


def test_signal_first_limit_order():
    cfg = DCAGridConfig(mode=TradingMode.SIGNAL, first_order_offset_percent=5.0)
    state = _build(cfg, "100", Direction.LONG)
    assert state.levels[0].is_market is False
    assert state.levels[0].price == D("95")


def test_signal_requires_signal_and_min_offset():
    cfg = DCAGridConfig(
        mode=TradingMode.SIGNAL,
        first_order_offset_percent=0.0,
        signal_min_offset_percent=5.0,
        signal_offset_type=SignalOffsetReference.REFERENCE,
    )
    state = _build(cfg, "100", Direction.LONG)
    assert ENG.signal_dca_order(cfg, state, signal_fired=False, current_price=D("94")) is None
    assert ENG.signal_dca_order(cfg, state, signal_fired=True, current_price=D("96")) is None
    order = ENG.signal_dca_order(cfg, state, signal_fired=True, current_price=D("94"))
    assert order is not None and order.is_market is True


def test_signal_offset_from_previous_order():
    cfg = DCAGridConfig(
        mode=TradingMode.SIGNAL,
        first_order_offset_percent=0.0,
        signal_min_offset_percent=5.0,
        signal_offset_type=SignalOffsetReference.PREVIOUS_ORDER,
    )
    state = _build(cfg, "100", Direction.LONG)
    state.last_order_price = D("100")
    assert ENG.signal_dca_order(cfg, state, signal_fired=True, current_price=D("94")) is not None
    assert ENG.signal_dca_order(cfg, state, signal_fired=True, current_price=D("96")) is None


def test_signal_offset_from_reference():
    cfg = DCAGridConfig(
        mode=TradingMode.SIGNAL,
        first_order_offset_percent=0.0,
        signal_min_offset_percent=5.0,
        signal_offset_type=SignalOffsetReference.REFERENCE,
    )
    state = _build(cfg, "100", Direction.LONG)
    assert ENG.signal_dca_order(cfg, state, signal_fired=True, current_price=D("94")) is not None


# --- averaging / grid state / backtest DCA ---


def test_weighted_average_price_after_dca():
    state = _build(DCAGridConfig(levels=2, overlap_percent=10.0), "100", Direction.LONG)
    ENG.on_fill(state, 0)
    state.average_price = D("100")
    q1 = state.levels[1].quantity
    avg = ENG.apply_average(state, q1, D("90"))
    expected = (D("100") * D("1") + D("90") * q1) / (D("1") + q1)
    assert avg == expected
    assert avg < D("100")


def test_grid_state_after_dca_fill():
    state = _build(
        DCAGridConfig(levels=4, overlap_percent=20.0, active_limit=2), "100", Direction.LONG
    )
    assert [p.level_index for p in state.active_orders()] == [0, 1]
    ENG.on_fill(state, 1)
    assert 1 in state.filled
    assert [p.level_index for p in state.active_orders()] == [0, 2]
    assert state.levels[1].status == LevelStatus.FILLED


def test_backtest_dca_average_and_repeatable():
    candles = [
        _candle(0, 100, 100.5, 99.5, 100),
        _candle(1, 100, 100.5, 99.5, 100),
        _candle(2, 99, 100, 88, 95),
        _candle(3, 95, 110, 94, 108),
    ]
    dca = DCAGridConfig(levels=2, overlap_percent=10.0, martingale_percent=0.0)
    engine = _make_engine()
    cfg = _bt_cfg(candles, dca, tp_percent=10.0)
    r1 = engine.run(cfg)
    r2 = engine.run(cfg)
    assert asdict(r1) == asdict(r2)
    assert len(r1.deals) == 1
    deal = r1.deals[0]
    q1 = D("100") / D("90")
    expected_avg = (D("100") * D("1") + D("90") * q1) / (D("1") + q1)
    assert deal.entry_price == pytest.approx(expected_avg)
    assert deal.quantity == pytest.approx(D("1") + q1)
