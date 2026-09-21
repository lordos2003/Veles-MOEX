"""DCA / Grid Engine (Veles functional model).

The engine is broker-agnostic: it works from a |DCAGridConfig|, a reference
price, a Direction and a base nominal (currency) and produces a |GridState| of
planned order levels. It never touches T-Invest; the Backtest and (future) Live
execution layers consume |GridOrderPlan|/|DCAOrder| and feed fills back in.

Veles model reproduced here:
- TradingMode: SIMPLE / CUSTOM / SIGNAL.
- SIMPLE: overlap (price range between first and last order), grid order count,
  first-order offset, martingale (nominal sizing), logarithmic distribution,
  partial grid (active limit), pull-up threshold.
- CUSTOM: explicit ordered offsets + nominals.
- SIGNAL: first order (market at offset 0, else limit); subsequent averaging
  orders are market and require a signal plus a minimum offset.

The mathematical mapping behind price distribution is isolated in
``GridPriceDistribution`` so it can be swapped if precise Veles details appear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.models.enums import OrderSide
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    SignalOffsetReference,
    TradingMode,
)


class LevelStatus(StrEnum):
    WAITING = "waiting"
    ACTIVE = "active"
    FILLED = "filled"


@dataclass
class GridLevel:
    """One planned order level of a grid."""

    index: int
    side: OrderSide
    price: Decimal
    nominal: Decimal
    quantity: Decimal
    offset_percent: float
    status: LevelStatus = LevelStatus.WAITING
    is_market: bool = False
    filled_quantity: Decimal = Decimal("0")


@dataclass
class GridOrderPlan:
    """An order plan ready for submission to an execution layer."""

    level_index: int
    side: OrderSide
    price: Decimal | None
    nominal: Decimal
    quantity: Decimal
    is_market: bool
    offset_percent: float


@dataclass
class DCAOrder:
    """An executed/planned averaging order (SIGNAL mode / on fill)."""

    level_index: int
    side: OrderSide
    price: Decimal | None
    quantity: Decimal
    nominal: Decimal
    offset_percent: float
    is_market: bool
    timestamp: datetime | None = None


@dataclass
class GridState:
    """The current, mutable grid plus averaging bookkeeping."""

    mode: TradingMode
    direction: Direction
    reference_price: Decimal
    base_nominal: Decimal
    levels: list[GridLevel]
    active_limit: int | None = None
    filled: list[int] = field(default_factory=list)
    average_price: Decimal = Decimal("0")
    last_order_price: Decimal | None = None

    def unfilled(self) -> list[GridLevel]:
        return [lvl for lvl in self.levels if lvl.status != LevelStatus.FILLED]

    def active_orders(self) -> list[GridOrderPlan]:
        """The eligible (nearest, not filled) orders, capped by active_limit."""
        limit = self.active_limit if self.active_limit is not None else len(self.levels)
        return [_plan(lvl) for lvl in self.unfilled()[:limit]]

    def waiting_orders(self) -> list[GridOrderPlan]:
        """The remaining planned orders not yet eligible for submission."""
        limit = self.active_limit if self.active_limit is not None else len(self.levels)
        return [_plan(lvl) for lvl in self.unfilled()[limit:]]

    def filled_levels(self) -> list[GridLevel]:
        return [lvl for lvl in self.levels if lvl.status == LevelStatus.FILLED]


def _plan(lvl: GridLevel) -> GridOrderPlan:
    return GridOrderPlan(
        level_index=lvl.index,
        side=lvl.side,
        price=None if lvl.is_market else lvl.price,
        nominal=lvl.nominal,
        quantity=lvl.quantity,
        is_market=lvl.is_market,
        offset_percent=lvl.offset_percent,
    )


class GridPriceDistribution:
    """Deterministic price-level generator (isolated mathematical mapping)."""

    @staticmethod
    def _price_at(ref: Decimal, offset_percent: float, direction: Direction) -> Decimal:
        sign = Decimal("-1") if direction == Direction.LONG else Decimal("1")
        offset = Decimal(str(offset_percent)) / Decimal("100")
        return ref * (Decimal("1") + offset * sign)

    @staticmethod
    def first_order_price(ref: Decimal, offset_percent: float, direction: Direction) -> Decimal:
        return GridPriceDistribution._price_at(ref, offset_percent, direction)

    @staticmethod
    def simple_prices(config: DCAGridConfig, ref: Decimal, direction: Direction) -> list[Decimal]:
        n = config.levels
        if n == 1:
            return [
                GridPriceDistribution.first_order_price(
                    ref, config.first_order_offset_percent, direction
                )
            ]
        sign = Decimal("-1") if direction == Direction.LONG else Decimal("1")
        first = GridPriceDistribution.first_order_price(
            ref, config.first_order_offset_percent, direction
        )
        overlap = ref * (Decimal(str(config.overlap_percent)) / Decimal("100"))
        last = first + (sign * overlap)
        total_range = last - first

        coeff = config.logarithmic_factor
        if coeff <= 0:
            coeff = 1.0
        gaps = [coeff**i for i in range(n - 1)]
        total_gaps = sum(gaps)

        prices: list[Decimal] = []
        pos = first
        for i in range(n):
            prices.append(pos)
            if i < n - 1:
                pos += total_range * (Decimal(str(gaps[i])) / Decimal(str(total_gaps)))
        return prices

    @staticmethod
    def custom_prices(config: DCAGridConfig, ref: Decimal, direction: Direction) -> list[Decimal]:
        return [
            GridPriceDistribution._price_at(ref, level.offset_percent, direction)
            for level in config.custom_levels
        ]


class DCAGridEngine:
    """Builds, evaluates and recalculates a DCA/grid."""

    def build(
        self,
        config: DCAGridConfig,
        reference_price: Decimal,
        direction: Direction,
        base_nominal: Decimal = Decimal("100"),
    ) -> GridState:
        if config.mode == TradingMode.CUSTOM:
            return self._build_custom(config, reference_price, direction, base_nominal)
        if config.mode == TradingMode.SIGNAL:
            return self._build_signal(config, reference_price, direction, base_nominal)
        return self._build_simple(config, reference_price, direction, base_nominal)

    def _build_simple(self, config, reference_price, direction, base_nominal) -> GridState:
        prices = GridPriceDistribution.simple_prices(config, reference_price, direction)
        side = _side(direction)
        mult = (
            Decimal("1") + (Decimal(str(config.martingale_percent)) / Decimal("100"))
            if config.martingale_percent > 0
            else Decimal("1")
        )
        levels = [
            self._make_level(i, side, price, base_nominal * (mult**i), reference_price)
            for i, price in enumerate(prices)
        ]
        offset_zero_first = config.first_order_offset_percent == 0
        if offset_zero_first and levels:
            levels[0].is_market = True
            levels[0].status = LevelStatus.ACTIVE
        return self._assign_active(config, GridState(
            mode=TradingMode.SIMPLE,
            direction=direction,
            reference_price=reference_price,
            base_nominal=base_nominal,
            levels=levels,
            active_limit=config.active_limit,
        ))

    def _build_custom(self, config, reference_price, direction, base_nominal) -> GridState:
        self._validate_custom(config)
        prices = GridPriceDistribution.custom_prices(config, reference_price, direction)
        side = _side(direction)
        levels = [
            self._make_level(
                i,
                side,
                price,
                base_nominal * (Decimal(str(level.nominal_percent)) / Decimal("100")),
                reference_price,
            )
            for i, (price, level) in enumerate(zip(prices, config.custom_levels, strict=False))
        ]
        return self._assign_active(config, GridState(
            mode=TradingMode.CUSTOM,
            direction=direction,
            reference_price=reference_price,
            base_nominal=base_nominal,
            levels=levels,
            active_limit=config.active_limit,
        ))

    def _build_signal(self, config, reference_price, direction, base_nominal) -> GridState:
        side = _side(direction)
        is_market = config.first_order_offset_percent == 0
        price = None if is_market else GridPriceDistribution.first_order_price(
            reference_price, config.first_order_offset_percent, direction
        )
        nominal = base_nominal
        quantity = nominal / price if price else nominal / reference_price
        first = GridLevel(
            index=0,
            side=side,
            price=reference_price if price is None else price,
            nominal=nominal,
            quantity=quantity,
            offset_percent=config.first_order_offset_percent,
            status=LevelStatus.ACTIVE,
            is_market=is_market,
        )
        return GridState(
            mode=TradingMode.SIGNAL,
            direction=direction,
            reference_price=reference_price,
            base_nominal=base_nominal,
            levels=[first],
            active_limit=config.active_limit,
            last_order_price=reference_price,
        )

    def _make_level(self, index, side, price, nominal, reference_price) -> GridLevel:
        offset = abs(price - reference_price) / reference_price * Decimal("100")
        return GridLevel(
            index=index,
            side=side,
            price=price,
            nominal=nominal,
            quantity=nominal / price,
            offset_percent=float(offset),
            status=LevelStatus.WAITING,
        )

    @staticmethod
    def _assign_active(config, state: GridState) -> GridState:
        active = state.active_limit if state.active_limit is not None else len(state.levels)
        for lvl in state.levels:
            lvl.status = LevelStatus.ACTIVE if lvl.index < active else LevelStatus.WAITING
        return state

    @staticmethod
    def _validate_custom(config: DCAGridConfig) -> None:
        if not config.custom_levels:
            raise ValueError("CUSTOM mode requires at least one custom level")
        offsets = [lvl.offset_percent for lvl in config.custom_levels]
        for prev, curr in zip(offsets, offsets[1:], strict=False):
            if curr < prev:
                raise ValueError("CUSTOM offsets must be monotonic in the averaging direction")

    def on_fill(self, state: GridState, level_index: int) -> GridState:
        """Mark a level filled and promote the next waiting level to active."""
        for lvl in state.levels:
            if lvl.index == level_index and lvl.status != LevelStatus.FILLED:
                lvl.status = LevelStatus.FILLED
                lvl.filled_quantity = lvl.quantity
                if level_index not in state.filled:
                    state.filled.append(level_index)
                self._refresh_active(state)
        return state

    @staticmethod
    def _refresh_active(state: GridState) -> None:
        unfilled = state.unfilled()
        limit = state.active_limit if state.active_limit is not None else len(unfilled)
        for i, lvl in enumerate(unfilled):
            lvl.status = LevelStatus.ACTIVE if i < limit else LevelStatus.WAITING

    def apply_average(self, state: GridState, quantity: Decimal, price: Decimal) -> Decimal:
        """Update the authoritative average position price after a fill.

        average = sum(quantity_i * price_i) / sum(quantity_i).
        """
        prev_qty = sum(lvl.quantity for lvl in state.filled_levels())
        return state.average_price if prev_qty == 0 else (
            (state.average_price * prev_qty + quantity * price) / (prev_qty + quantity)
        )

    def evaluate_pullup(
        self,
        config: DCAGridConfig,
        state: GridState,
        reference_price: Decimal,
        current_price: Decimal,
    ) -> bool:
        """Return True if the pending grid must be cancelled (pull-up triggered)."""
        first = next((lvl for lvl in state.levels if lvl.index == 0), None)
        if first is None or first.is_market or config.first_order_offset_percent == 0:
            return False
        limit_price = first.price
        threshold = reference_price * (Decimal(str(config.pull_up_percent)) / Decimal("100"))
        if state.direction == Direction.LONG:
            return current_price >= limit_price + threshold
        return current_price <= limit_price - threshold

    def signal_dca_order(
        self, config: DCAGridConfig, state: GridState, signal_fired: bool, current_price: Decimal
    ) -> DCAOrder | None:
        """SIGNAL mode: for the next averaging market order require signal + min offset."""
        if not signal_fired:
            return None
        if not self._signal_offset_ok(config, state, current_price):
            return None
        next_index = len(state.levels)
        mult = (
            Decimal("1") + (Decimal(str(config.martingale_percent)) / Decimal("100"))
            if config.martingale_percent > 0
            else Decimal("1")
        )
        nominal = state.base_nominal * (mult**next_index)
        quantity = nominal / current_price
        offset = (
            abs(current_price - state.reference_price) / state.reference_price * Decimal("100")
        )
        return DCAOrder(
            level_index=next_index,
            side=_side(state.direction),
            price=None,
            quantity=quantity,
            nominal=nominal,
            offset_percent=float(offset),
            is_market=True,
        )

    def _signal_offset_ok(
        self, config: DCAGridConfig, state: GridState, current_price: Decimal
    ) -> bool:
        min_off = Decimal(str(config.signal_min_offset_percent)) / Decimal("100")
        if config.signal_offset_type == SignalOffsetReference.PREVIOUS_ORDER:
            base = state.last_order_price or state.reference_price
        else:
            base = state.reference_price
        if base == 0:
            return False
        if state.direction == Direction.LONG:
            return current_price <= base * (Decimal("1") - min_off)
        return current_price >= base * (Decimal("1") + min_off)

    def recalculate(
        self,
        config: DCAGridConfig,
        state: GridState,
        new_reference_price: Decimal,
        base_nominal: Decimal,
        new_average_price: Decimal,
    ) -> GridState:
        """Rebuild unfilled levels around a new reference keeping filled immutable."""
        if config.mode == TradingMode.SIMPLE:
            prices = GridPriceDistribution.simple_prices(
                config, new_reference_price, state.direction
            )
            side = _side(state.direction)
            mult = (
                Decimal("1") + (Decimal(str(config.martingale_percent)) / Decimal("100"))
                if config.martingale_percent > 0
                else Decimal("1")
            )
            for i, price in enumerate(prices):
                lvl = state.levels[i] if i < len(state.levels) else None
                if lvl is not None and lvl.status == LevelStatus.FILLED:
                    continue
                nominal = base_nominal * (mult**i)
                if lvl is None:
                    state.levels.append(
                        self._make_level(i, side, price, nominal, new_reference_price)
                    )
                else:
                    lvl.price = price
                    lvl.nominal = nominal
                    lvl.quantity = nominal / price
                    lvl.offset_percent = float(
                        abs(price - new_reference_price) / new_reference_price * 100
                    )
                    lvl.is_market = False
        state.reference_price = new_reference_price
        state.average_price = new_average_price
        self._refresh_active(state)
        return state


def _side(direction: Direction) -> OrderSide:
    return OrderSide.BUY if direction == Direction.LONG else OrderSide.SELL
