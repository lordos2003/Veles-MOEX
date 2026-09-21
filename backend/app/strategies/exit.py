"""Full Exit Engine (Veles-compatible, MVP-5).

The Exit Engine is a first-class subsystem (Product specification section 6). It
is broker-agnostic: it produces |ExitPlan| limit orders and market
|ExitDecision| objects; it never submits broker orders itself, so Backtest and
(future) Live use the same logic.

Components implemented here:
- FixedPercentageTP (Простой)
- MultiTakeTP with TakeItem (Свой)
- SignalTP (Сигнал) with Minimum P&L
- BreakEvenConfig (Стоп-лосс в безубыток; NOT the ordinary Stop Loss)
- SimpleStopLossConfig (Стоп-лосс, percent)
- SignalStopLossConfig (Стоп-лосс, signal)

Trailing exit is intentionally not implemented (explicitly post-MVP-5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.models.enums import OrderSide
from app.strategies.config import (
    BreakEvenConfig,
    Direction,
    ExitConfig,
    ExitMode,
    FixedPercentageTP,
    MultiTakeTP,
    SignalStopLossConfig,
    SignalTP,
    StopLossConfig,
    StopLossReference,
)
from app.strategies.domain import ExitPlan


class ExitType(StrEnum):
    FIXED_TP = "fixed_tp"
    TAKE = "take"
    SIGNAL_TP = "signal_tp"
    BREAK_EVEN = "breakeven"
    STOP_LOSS = "stop_loss"
    SIGNAL_STOP = "signal_stop"


class ExitExecution(StrEnum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class ExitDecision:
    """A deterministic exit decision produced by the Exit Engine."""

    exit_type: ExitType
    reason: str
    execution: ExitExecution
    quantity: Decimal
    side: OrderSide
    trigger_price: Decimal | None = None
    trigger_time: datetime | None = None
    order_price: Decimal | None = None
    config_kind: str = ""


@dataclass
class ExitState:
    """Mutable state of an active position's exit configuration."""

    mode: ExitMode
    direction: Direction
    executed_takes: list[int] = field(default_factory=list)
    breakeven_active: bool = False
    breakeven_level: Decimal | None = None
    last_take_price: Decimal | None = None
    average_price: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")


_PRIORITY = {
    ExitType.SIGNAL_STOP: 1,
    ExitType.STOP_LOSS: 2,
    ExitType.BREAK_EVEN: 3,
    ExitType.SIGNAL_TP: 4,
}


class ExitEngine:
    """Builds and evaluates the full set of exits for a position."""

    def resolve_mode(self, config: ExitConfig) -> ExitMode:
        tp = config.take_profit
        if isinstance(tp, FixedPercentageTP):
            return ExitMode.SIMPLE
        if isinstance(tp, MultiTakeTP):
            return ExitMode.CUSTOM
        if isinstance(tp, SignalTP):
            return ExitMode.SIGNAL
        raise NotImplementedError("Trailing take-profit is not implemented at MVP-5")

    def build_exit_orders(
        self, config: ExitConfig, direction: Direction, entry_price: Decimal, position_qty: float
    ) -> list[ExitPlan]:
        """Build the limit exit plans (Fixed TP / Multi-Take) for a position."""
        tp = config.take_profit
        qty = Decimal(str(position_qty))
        if isinstance(tp, FixedPercentageTP):
            return self._fixed_plan(direction, entry_price, qty, tp.percent)
        if isinstance(tp, MultiTakeTP):
            return [
                self._take_plan(
                    direction, entry_price, qty, take.offset_percent, take.volume_percent, i
                )
                for i, take in enumerate(tp.takes)
            ]
        if isinstance(tp, SignalTP):
            return []
        raise NotImplementedError("Trailing take-profit is not implemented at MVP-5")

    def on_average(
        self,
        config: ExitConfig,
        direction: Direction,
        average_price: float,
        position_qty: float,
        old_exits: list[ExitPlan],
    ) -> list[ExitPlan]:
        """Recalculate the remaining limit exits from a new average price.

        Executed (previously filled) takes are left immutable; only the remaining
        ``position_qty`` is re-priced against the new average.
        """
        avg = Decimal(str(average_price))
        return self.build_exit_orders(config, direction, avg, position_qty)

    def build_remaining_take_plans(
        self,
        config: ExitConfig,
        direction: Direction,
        avg_price: Decimal,
        total_qty: Decimal,
        executed_takes: list[int],
    ) -> list[ExitPlan]:
        """Re-price only the unexecuted Multi-Take levels against a new average."""
        tp = config.take_profit
        if not isinstance(tp, MultiTakeTP):
            return self.build_exit_orders(config, direction, avg_price, float(total_qty))
        plans = []
        for i, take in enumerate(tp.takes):
            if i in executed_takes:
                continue
            plans.append(
                self._take_plan(
                    direction, avg_price, total_qty, take.offset_percent, take.volume_percent, i
                )
            )
        return plans

    def on_take_executed(
        self, state: ExitState, config: ExitConfig, take_index: int, take_price: Decimal
    ) -> None:
        """Record an executed take and (for Multi-Take with break-even) arm protection."""
        state.executed_takes.append(take_index)
        state.last_take_price = take_price
        tp = config.take_profit
        if isinstance(tp, MultiTakeTP) and tp.breakeven is not None and state.executed_takes:
            state.breakeven_active = True
            state.breakeven_level = breakeven_level(
                tp.breakeven, state.direction, state.average_price, state.last_take_price
            )

    # --- limit plan builders -----------------------------------------------------

    @staticmethod
    def _fixed_plan(direction, avg, qty, percent) -> list[ExitPlan]:
        price = _tp_price(avg, direction, percent)
        return [
            ExitPlan(
                side=_exit_side(direction),
                quantity=float(qty),
                price=price,
                offset_percent=percent,
            )
        ]

    @staticmethod
    def _take_plan(direction, avg, total_qty, offset, volume, index) -> ExitPlan:
        price = _tp_price(avg, direction, offset)
        return ExitPlan(
            side=_exit_side(direction),
            quantity=float(total_qty * Decimal(str(volume)) / Decimal("100")),
            price=price,
            offset_percent=offset,
        )

    # --- decision methods --------------------------------------------------------

    def signal_tp_decision(
        self,
        config: ExitConfig,
        direction: Direction,
        avg_price: Decimal,
        position_qty: Decimal,
        current_price: Decimal,
        signal_fired: bool,
        now: datetime | None = None,
    ) -> ExitDecision | None:
        tp = config.take_profit
        if not isinstance(tp, SignalTP) or not signal_fired:
            return None
        pnl = pnl_percent(direction, avg_price, current_price)
        if tp.min_pnl_percent is not None and pnl < tp.min_pnl_percent:
            return None
        return ExitDecision(
            exit_type=ExitType.SIGNAL_TP,
            reason="signal_tp",
            execution=ExitExecution.MARKET,
            quantity=position_qty,
            side=_exit_side(direction),
            trigger_price=current_price,
            trigger_time=now,
            config_kind="signal",
        )

    def simple_stop_decision(
        self,
        config: ExitConfig,
        direction: Direction,
        reference_price: Decimal,
        current_price: Decimal,
        position_qty: Decimal,
        now: datetime | None = None,
    ) -> ExitDecision | None:
        sl = config.stop_loss
        if not isinstance(sl, StopLossConfig):
            return None
        level = simple_stop_level(reference_price, direction, sl.percent)
        if direction == Direction.LONG and current_price <= level:
            return self._stop_decision(direction, level, current_price, position_qty, now)
        if direction == Direction.SHORT and current_price >= level:
            return self._stop_decision(direction, level, current_price, position_qty, now)
        return None

    def signal_stop_decision(
        self,
        config: ExitConfig,
        direction: Direction,
        signal_fired: bool,
        avg_price: Decimal,
        last_order_price: Decimal | None,
        current_price: Decimal,
        position_qty: Decimal,
        grid_assembled: bool,
        now: datetime | None = None,
    ) -> ExitDecision | None:
        sl = config.signal_stop
        if not isinstance(sl, SignalStopLossConfig) or not signal_fired:
            return None
        if sl.offset_enabled:
            if sl.reference == StopLossReference.LAST_ORDER and not grid_assembled:
                return None
            ref = avg_price if sl.reference == StopLossReference.AVERAGE_PRICE else last_order_price
            if ref is None:
                return None
            if not _offset_satisfied(direction, ref, current_price, sl.min_offset_percent):
                return None
        return self._stop_decision(
            direction, None, current_price, position_qty, now, ExitType.SIGNAL_STOP
        )

    def breakeven_decision(
        self,
        config: ExitConfig,
        state: ExitState,
        avg_price: Decimal,
        previous_take_price: Decimal | None,
        current_price: Decimal,
        position_qty: Decimal,
        now: datetime | None = None,
    ) -> ExitDecision | None:
        tp = config.take_profit
        if (
            not isinstance(tp, MultiTakeTP)
            or tp.breakeven is None
            or not state.breakeven_active
        ):
            return None
        level = breakeven_level(tp.breakeven, state.direction, avg_price, previous_take_price)
        state.breakeven_level = level
        if state.direction == Direction.LONG and current_price <= level:
            return self._stop_decision(
                state.direction, level, current_price, position_qty, now, ExitType.BREAK_EVEN
            )
        if state.direction == Direction.SHORT and current_price >= level:
            return self._stop_decision(
                state.direction, level, current_price, position_qty, now, ExitType.BREAK_EVEN
            )
        return None

    def _stop_decision(
        self, direction, level, current_price, position_qty, now, exit_type=ExitType.STOP_LOSS
    ) -> ExitDecision:
        return ExitDecision(
            exit_type=exit_type,
            reason=exit_type.value,
            execution=ExitExecution.MARKET,
            quantity=position_qty,
            side=_exit_side(direction),
            trigger_price=level or current_price,
            trigger_time=now,
            config_kind=exit_type.value,
        )

    # --- priority -----------------------------------------------------------------

    def select(self, decisions: list[ExitDecision]) -> ExitDecision | None:
        """Deterministic selection among simultaneous exits.

        Protective exits (signal stop, stop loss, break-even) take precedence
        over signal take-profit. Ties are kept in list order.
        """
        if not decisions:
            return None
        return min(
            decisions,
            key=lambda d: (_PRIORITY.get(d.exit_type, 99), decisions.index(d)),
        )


# --- helpers ----------------------------------------------------------------------


def _tp_price(avg: Decimal, direction: Direction, offset_percent: float) -> Decimal:
    factor = Decimal("1") + Decimal(str(offset_percent)) / Decimal("100")
    if direction == Direction.SHORT:
        factor = Decimal("1") - Decimal(str(offset_percent)) / Decimal("100")
    return avg * factor


def _exit_side(direction: Direction) -> OrderSide:
    return OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY


def pnl_percent(direction: Direction, avg: Decimal, current: Decimal) -> float:
    if avg == 0:
        return 0.0
    if direction == Direction.SHORT:
        value = (avg - current) / avg * Decimal("100")
    else:
        value = (current - avg) / avg * Decimal("100")
    return float(value)


def simple_stop_level(reference_price: Decimal, direction: Direction, percent: float) -> Decimal:
    sign = Decimal("-1") if direction == Direction.LONG else Decimal("1")
    return reference_price * (Decimal("1") + sign * Decimal(str(percent)) / Decimal("100"))


def breakeven_level(
    cfg: BreakEvenConfig,
    direction: Direction,
    avg_price: Decimal,
    previous_take_price: Decimal | None,
) -> Decimal:
    base = avg_price if cfg.reference == "average_price" else previous_take_price
    if base is None:
        base = avg_price
    dev = Decimal(str(cfg.deviation_percent)) / Decimal("100") * base
    if direction == Direction.LONG:
        return base + dev
    return base - dev


def _offset_satisfied(
    direction: Direction, ref: Decimal, current: Decimal, min_offset_percent: float
) -> bool:
    min_off = Decimal(str(min_offset_percent)) / Decimal("100")
    if direction == Direction.LONG:
        return current <= ref * (Decimal("1") - min_off)
    return current >= ref * (Decimal("1") + min_off)
