"""Full Exit Engine (MVP-5) tests — scenarios 1-35."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import OrderSide
from app.strategies import (
    BreakEvenConfig,
    Direction,
    ExitConfig,
    ExitEngine,
    ExitExecution,
    ExitMode,
    ExitState,
    ExitType,
    FilterGroup,
    FixedPercentageTP,
    MultiTakeTP,
    SignalStopLossConfig,
    SignalTP,
    StopLossConfig,
    TakeItem,
)

ENG = ExitEngine()

_TWO = [
    {"offset_percent": 5, "volume_percent": 50},
    {"offset_percent": 10, "volume_percent": 50},
]
_ONE = [{"offset_percent": 5, "volume_percent": 100}]
_TWOTWENTY = [
    {"offset_percent": 5, "volume_percent": 40},
    {"offset_percent": 10, "volume_percent": 40},
]
_ORDER_INVALID = [
    {"offset_percent": 10, "volume_percent": 50},
    {"offset_percent": 5, "volume_percent": 50},
]
_VOL_INVALID = [
    {"offset_percent": 5, "volume_percent": 60},
    {"offset_percent": 10, "volume_percent": 60},
]


def D(v) -> Decimal:
    return Decimal(str(v))


def _exit(tp, *, stop=None, signal_stop=None) -> ExitConfig:
    return ExitConfig(take_profit=tp, stop_loss=stop, signal_stop=signal_stop)


def _mt(takes, breakeven=None):
    return MultiTakeTP(takes=[TakeItem(**t) for t in takes], breakeven=breakeven)


def _be(ref="average_price", dev=0.0):
    return BreakEvenConfig(reference=ref, deviation_percent=dev)


def _be_exit(dev=0.0, ref="average_price", takes=None):
    return _exit(_mt(takes or _TWO, _be(ref=ref, dev=dev)))


def _plans(tp, direction, avg, qty, *, stop=None, signal_stop=None):
    return ENG.build_exit_orders(
        _exit(tp, stop=stop, signal_stop=signal_stop), direction, D(avg), qty
    )


def _st(direction, avg, current, *, signal=True, min_pnl=None):
    cfg = _exit(SignalTP(groups=[], min_pnl_percent=min_pnl))
    return ENG.signal_tp_decision(cfg, direction, D(avg), D("10"), D(current), signal)


def _ss(reference="average_price", min_offset=0.0, enabled=True):
    return SignalStopLossConfig(
        groups=[], reference=reference, min_offset_percent=min_offset, offset_enabled=enabled
    )


def _sl_cfg(**ss_kwargs):
    return _exit(FixedPercentageTP(percent=10.0), signal_stop=_ss(**ss_kwargs))


def _sigstop(cfg, direction, avg, price, *, last_order=None, signal=True, grid=True):
    return ENG.signal_stop_decision(
        cfg, direction, signal, D(avg),
        D(last_order) if last_order is not None else None,
        D(price), D("5"), grid,
    )


def _state(active=False, avg="100"):
    return ExitState(
        mode=ExitMode.CUSTOM, direction=Direction.LONG,
        average_price=D(avg), breakeven_active=active,
    )


def _be_dec(cfg, avg="100", last=None, current="100", active=True, qty="5"):
    state = _state(active=active, avg=avg)
    return ENG.breakeven_decision(
        cfg, state, D(avg), D(last) if last else None, D(current), D(qty)
    )


# --- Fixed TP (1-5) ---


def test_fixed_tp_long():
    plans = _plans(FixedPercentageTP(percent=10.0), Direction.LONG, 100, 3)
    assert len(plans) == 1
    assert plans[0].price == D("110")
    assert plans[0].side == OrderSide.SELL
    assert plans[0].quantity == 3


def test_fixed_tp_short():
    plans = _plans(FixedPercentageTP(percent=10.0), Direction.SHORT, 100, 2)
    assert plans[0].price == D("90")
    assert plans[0].side == OrderSide.BUY


def test_tp_from_average_price():
    plans = _plans(FixedPercentageTP(percent=5.0), Direction.LONG, 80, 1)
    assert plans[0].price == D("84")


def test_tp_recalculated_after_dca():
    cfg = _exit(FixedPercentageTP(percent=10.0))
    plans = ENG.on_average(cfg, Direction.LONG, 90.0, 5, old_exits=[])
    assert plans[0].price == D("99")


def test_tp_volume_follows_remaining():
    plans = _plans(FixedPercentageTP(percent=10.0), Direction.LONG, 100, 7)
    assert plans[0].quantity == 7


# --- Multi-Take (6-13) ---


def test_two_takes():
    plans = _plans(_mt(_TWO), Direction.LONG, 100, 10)
    assert [p.price for p in plans] == [D("105"), D("110")]
    assert [p.quantity for p in plans] == [5, 5]


def test_three_takes():
    takes = [
        {"offset_percent": 5, "volume_percent": 30},
        {"offset_percent": 10, "volume_percent": 30},
        {"offset_percent": 15, "volume_percent": 40},
    ]
    plans = _plans(_mt(takes), Direction.LONG, 100, 10)
    assert len(plans) == 3
    assert [p.quantity for p in plans] == [3, 3, 4]


def test_partial_position_closure():
    plans = _plans(_mt(_TWOTWENTY), Direction.LONG, 100, 10)
    assert sum(p.quantity for p in plans) == 8


def test_remaining_volume():
    plans = _plans(_mt(_TWOTWENTY), Direction.LONG, 100, 10)
    assert 10 - sum(p.quantity for p in plans) == 2


def test_takes_recalculated_after_dca():
    cfg = _exit(_mt(_TWO))
    plans = ENG.on_average(cfg, Direction.LONG, 90.0, 8, old_exits=[])
    assert [p.price for p in plans] == [D("94.5"), D("99")]


def test_executed_takes_immutable():
    cfg = _exit(_mt(_TWO))
    remaining = ENG.build_remaining_take_plans(cfg, Direction.LONG, D("100"), D("10"), [0])
    assert [p.price for p in remaining] == [D("110")]
    assert remaining[0].quantity == 5


def test_invalid_take_ordering_rejected():
    with pytest.raises(ValueError):
        _mt(_ORDER_INVALID)


def test_invalid_total_volume_rejected():
    with pytest.raises(ValueError):
        _mt(_VOL_INVALID)


# --- Signal TP (14-17) ---


def test_signal_tp_market_exit():
    decision = _st(Direction.LONG, 100, 110)
    assert decision is not None
    assert decision.exit_type == ExitType.SIGNAL_TP
    assert decision.execution == ExitExecution.MARKET
    assert decision.quantity == D("10")


def test_signal_tp_blocked_below_min_pnl():
    assert _st(Direction.LONG, 100, 100, min_pnl=10.0) is None


def test_signal_tp_close_when_min_met():
    assert _st(Direction.LONG, 100, 112, min_pnl=10.0) is not None


def test_signal_tp_reuses_filters():
    cfg = _exit(SignalTP(groups=[FilterGroup(conditions=[])], min_pnl_percent=None))
    assert cfg.take_profit.groups == [FilterGroup(conditions=[])]


# --- Break-Even (18-25) ---


def test_breakeven_rejected_with_fewer_than_two_takes():
    with pytest.raises(ValueError):
        _mt(_ONE, breakeven=BreakEvenConfig())


def test_breakeven_activation_after_first_take():
    cfg = _be_exit()
    state = _state()
    ENG.on_take_executed(state, cfg, 0, D("105"))
    assert state.breakeven_active is True
    assert state.executed_takes == [0]


def test_breakeven_reference_average():
    cfg = _be_exit(dev=0)
    decision = ENG.breakeven_decision(cfg, _state(active=True), D("100"), None, D("100"), D("5"))
    assert decision is not None and decision.exit_type == ExitType.BREAK_EVEN


def test_breakeven_reference_previous_take():
    cfg = _be_exit(ref="previous_take", dev=0)
    assert _be_dec(cfg, last=105, current=106) is None
    assert _be_dec(cfg, last=105, current=105) is not None


def test_breakeven_positive_deviation():
    cfg = _be_exit(dev=2)
    assert _be_dec(cfg, current=101.5) is not None
    assert _be_dec(cfg, current=103) is None


def test_breakeven_zero_deviation():
    cfg = _be_exit(dev=0)
    assert _be_dec(cfg) is not None


def test_breakeven_negative_deviation():
    cfg = _be_exit(dev=-1)
    assert _be_dec(cfg, current=99) is not None


# --- Simple Stop Loss (26-28) ---


def test_simple_stop_long():
    cfg = _exit(FixedPercentageTP(percent=10.0), stop=StopLossConfig(percent=5.0))
    decision = ENG.simple_stop_decision(cfg, Direction.LONG, D("100"), D("94"), D("5"))
    assert decision is not None
    assert decision.exit_type == ExitType.STOP_LOSS
    assert decision.execution == ExitExecution.MARKET


def test_simple_stop_short():
    cfg = _exit(FixedPercentageTP(percent=10.0), stop=StopLossConfig(percent=5.0))
    assert ENG.simple_stop_decision(cfg, Direction.SHORT, D("100"), D("106"), D("5")) is not None


def test_simple_stop_activation_semantics():
    cfg = _exit(FixedPercentageTP(percent=10.0), stop=StopLossConfig(percent=5.0))
    assert ENG.simple_stop_decision(cfg, Direction.LONG, D("100"), D("96"), D("5")) is None
    assert ENG.simple_stop_decision(cfg, Direction.LONG, D("100"), D("95"), D("5")) is not None


# --- Signal Stop Loss (29-35) ---


def test_signal_stop_requires_signal_and_offset():
    cfg = _sl_cfg(min_offset=5.0)
    assert _sigstop(cfg, Direction.LONG, 100, 98) is None
    assert _sigstop(cfg, Direction.LONG, 100, 94) is not None


def test_signal_stop_reference_average():
    cfg = _sl_cfg(reference="average_price", min_offset=3.0)
    assert _sigstop(cfg, Direction.LONG, 100, 96, grid=False) is not None


def test_signal_stop_reference_last_order_needs_grid():
    cfg = _sl_cfg(reference="last_order", min_offset=3.0)
    assert _sigstop(cfg, Direction.LONG, 100, 87, last_order=90, grid=False) is None
    assert _sigstop(cfg, Direction.LONG, 100, 87, last_order=90, grid=True) is not None


def test_signal_stop_disabled_offset():
    cfg = _sl_cfg(reference="average_price", enabled=False)
    assert _sigstop(cfg, Direction.LONG, 100, 99) is not None


def test_signal_stop_positive_offset_can_be_profitable():
    cfg = _sl_cfg(reference="average_price", min_offset=5.0)
    assert _sigstop(cfg, Direction.SHORT, 100, 106) is not None


def test_signal_stop_activates_before_full_grid_when_avg_ref():
    cfg = _sl_cfg(reference="average_price", min_offset=5.0)
    assert _sigstop(cfg, Direction.LONG, 100, 94, grid=False) is not None


def test_simple_and_signal_stop_independent():
    cfg = _exit(
        FixedPercentageTP(percent=10.0),
        stop=StopLossConfig(percent=5.0),
        signal_stop=_ss(reference="average_price", min_offset=5.0),
    )
    simple = ENG.simple_stop_decision(cfg, Direction.LONG, D("100"), D("94"), D("5"))
    signal = _sigstop(cfg, Direction.LONG, 100, 94)
    assert simple is not None and signal is not None


def test_priority_prefers_protective_exit():
    stop = ENG.simple_stop_decision(
        _exit(FixedPercentageTP(percent=10.0), stop=StopLossConfig(percent=5.0)),
        Direction.LONG, D("100"), D("94"), D("5"),
    )
    tp = _st(Direction.LONG, 100, 110)
    chosen = ENG.select([tp, stop])
    assert chosen is not None and chosen.exit_type == ExitType.STOP_LOSS
