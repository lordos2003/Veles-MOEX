"""Strategy configuration schemas.

Per Architecture & Product Specification section 3, a strategy is
configuration/data (not Python code). These models define the shape of that
configuration. The Exit Engine is modeled explicitly so the TP types requested
(FixedPercentageTP, MultiTakeTP, SignalTP, TrailingTP) are first-class rather
than a single generic percentage field (Veles TP requirements).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.marketdata import Timeframe
from app.strategies.filters import CalculationMethod, FilterGroup
from app.strategies.indicators import validate_spec_args


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradingMode(StrEnum):
    SIMPLE = "simple"
    CUSTOM = "custom"
    SIGNAL = "signal"


class SignalOffsetReference(StrEnum):
    PREVIOUS_ORDER = "previous_order"
    REFERENCE = "reference"


class ExitMode(StrEnum):
    SIMPLE = "simple"
    CUSTOM = "custom"
    SIGNAL = "signal"


class StopLossReference(StrEnum):
    AVERAGE_PRICE = "average_price"
    LAST_ORDER = "last_order"



class CustomLevel(BaseModel):
    """One explicit averaging level in CUSTOM mode.

    ``offset_percent`` is the distance from the reference entry price in the
    averaging direction; ``nominal_percent`` is the order nominal as a
    percentage of the base nominal (100 = full-size single order).
    """

    offset_percent: float
    nominal_percent: float = Field(gt=0)


class EntryConfig(BaseModel):
    """Entry conditions (Veles-style filters/signals)."""

    method: CalculationMethod = Field(
        default=CalculationMethod.AT_BAR_CLOSE,
        description="Entry evaluation method (market, at-bar-close, next-bar-open)",
    )
    # Groups are OR-ed; conditions within a group are AND-ed.
    groups: list[FilterGroup] = Field(
        default_factory=list, description="Filter groups (OR between groups, AND within a group)"
    )


class DCAGridConfig(BaseModel):
    """DCA / Grid configuration (Architecture & Product Specification section 5).

    SIMPLE mode derives a limit-order grid from the parameters below. CUSTOM
    mode uses ``custom_levels``. SIGNAL mode uses the first order plus a signal
    filter for subsequent market averaging orders.
    """

    mode: TradingMode = Field(
        default=TradingMode.SIMPLE, description="Grid mode: simple/custom/signal"
    )
    levels: int = Field(default=1, ge=1, description="Number of averaging levels (>=1)")
    overlap_percent: float = Field(default=0.0, description="Grid overlap percent")
    spacing_percent: float = Field(default=0.0, description="Distance between grid levels, percent")
    martingale_percent: float = Field(
        default=0.0, description="Martingale multiplier percent per level"
    )
    logarithmic_factor: float = Field(default=1.0, description="Logarithmic grid factor")
    first_order_offset_percent: float = Field(
        default=0.0, description="First order offset from entry, percent"
    )
    pull_up_percent: float = Field(default=0.0, description="Pull-up (protraction) percent")
    # Partial grid: max simultaneously active/eligible grid orders.
    active_limit: int | None = Field(
        default=None, description="Max simultaneously active grid orders"
    )
    # --- CUSTOM mode ---
    custom_levels: list[CustomLevel] = Field(
        default_factory=list, description="Explicit CUSTOM-mode levels"
    )
    # --- SIGNAL mode ---
    signal_groups: list[FilterGroup] = Field(
        default_factory=list, description="Signal filter groups for SIGNAL-mode averaging"
    )
    signal_offset_type: SignalOffsetReference = Field(
        default=SignalOffsetReference.REFERENCE,
        description="Signal-mode offset reference: previous_order or reference",
    )
    signal_min_offset_percent: float = Field(
        default=0.0, description="Min offset percent for SIGNAL-mode averaging"
    )


class TakeItem(BaseModel):
    """One multi-take level: profit offset and share of position."""

    offset_percent: float
    volume_percent: float


class BreakEvenConfig(BaseModel):
    """Break-even protection reference (Veles TP section)."""

    reference: Literal["average_price", "previous_take"] = "average_price"
    deviation_percent: float = 0.0


class FixedPercentageTP(BaseModel):
    """Single take-profit expressed as a percentage from average price."""

    kind: Literal["fixed_percentage"] = Field(
        default="fixed_percentage", description="Take-profit kind: fixed_percentage"
    )
    percent: float = Field(gt=0, description="Take-profit percent from average price (>0)")


class MultiTakeTP(BaseModel):
    """Partial exits at several profit levels (Veles Custom TP mode)."""

    kind: Literal["multi_take"] = "multi_take"
    takes: list[TakeItem] = Field(default_factory=list)
    breakeven: BreakEvenConfig | None = None

    @model_validator(mode="after")
    def _validate_takes(self) -> MultiTakeTP:
        if not self.takes:
            raise ValueError("Multi-Take requires at least one take level")
        offsets = [t.offset_percent for t in self.takes]
        for prev, curr in zip(offsets, offsets[1:], strict=False):
            if curr <= prev:
                raise ValueError("Multi-Take offsets must be strictly increasing")
        if any(t.volume_percent <= 0 for t in self.takes):
            raise ValueError("Multi-Take volume percentages must be positive")
        if sum(t.volume_percent for t in self.takes) > 100.0:
            raise ValueError("Multi-Take total volume may not exceed 100%")
        if self.breakeven is not None and len(self.takes) < 2:
            raise ValueError("Break-Even protection requires Multi-Take with at least two takes")
        return self


class SignalTP(BaseModel):
    """Exit on an indicator/filter signal, with optional minimum P&L."""

    kind: Literal["signal"] = "signal"
    groups: list[FilterGroup] = Field(default_factory=list)
    min_pnl_percent: float | None = None


class TrailingTP(BaseModel):
    """Future/conditional trailing exit. Verify T-Invest/MOEX support first."""

    kind: Literal["trailing"] = "trailing"
    deviation_percent: float = 0.0


TPConfig = Annotated[
    FixedPercentageTP | MultiTakeTP | SignalTP | TrailingTP,
    Field(discriminator="kind"),
]


class StopLossConfig(BaseModel):
    """Simple percentage Stop Loss (market exit).

    ``stop_bot_after`` (MVP-6.16 E3): whether the bot must be stopped after the
    stop-loss closes the deal. No implicit production default: ``None`` forces
    an explicit choice at live START (HTTP 409), so a live strategy always
    declares what happens after the stop.
    """

    kind: Literal["percent"] = Field(default="percent", description="Stop-loss kind: percent")
    percent: float = Field(
        gt=0,
        description="Stop-loss percent from P0, above the grid overlap (>0)",
    )
    stop_bot_after: bool | None = Field(
        default=None,
        description="Explicit choice: stop the bot after the stop-loss closes the deal",
    )


class SignalStopLossConfig(BaseModel):
    """Indicator/filter based Stop Loss (market exit)."""

    kind: Literal["signal"] = "signal"
    groups: list[FilterGroup] = Field(default_factory=list)
    reference: StopLossReference = StopLossReference.AVERAGE_PRICE
    min_offset_percent: float = 0.0
    offset_enabled: bool = True


class ExitConfig(BaseModel):
    """Exit block of a strategy.

    Simple and Signal Stop Loss are independent: both may be configured and are
    evaluated separately (whichever triggers first closes the position).
    """

    take_profit: TPConfig = Field(description="Take-profit configuration")
    stop_loss: StopLossConfig | None = Field(
        default=None, description="Simple percentage stop-loss (market exit)"
    )
    signal_stop: SignalStopLossConfig | None = Field(
        default=None, description="Signal-based stop-loss (market exit)"
    )


class RiskConfig(BaseModel):
    """Risk block. Risk Manager is authoritative and separate from the strategy."""

    max_position_size: float | None = Field(default=None, description="Max position size limit")
    max_concurrent_bots: int | None = Field(default=None, description="Max concurrent bots limit")
    daily_loss_limit: float | None = Field(default=None, description="Daily loss limit")
    emergency_stop: bool = Field(default=False, description="Emergency stop enabled")


class StrategyConfig(BaseModel):
    """Full strategy configuration (Architecture & Product Specification section 3).

    A strategy is configuration/data, not code. The Veles filter/signal
    semantics are modeled through ``EntryConfig``/``ExitConfig`` blocks; no
    indicator parameters are invented beyond what the filters declare.
    """

    name: str = Field(default="", description="Strategy display name")
    direction: Direction = Field(
        default=Direction.LONG,
        description="Trading direction: LONG or SHORT",
    )
    instrument_id: int | None = Field(
        default=None,
        description="Internal Instrument id; None blocks live processing explicitly",
    )
    # The bot's own market-data timeframe for the live strategy path
    # (MVP-6.10). No implicit production default: ``None`` (missing) blocks the
    # live processing cycle explicitly (TimeframeNotConfigured); an invalid
    # value fails strategy configuration validation (StrategyLoadError).
    # Backtest timeframes live on BacktestConfig, not here.
    timeframe: Timeframe | None = Field(
        default=None, description="Live bot market-data timeframe (1m/5m/.../1mo)"
    )
    # The explicitly configured number of candle bars the live market
    # snapshot must fetch for this bot's timeframe (MVP-6.10). This is a
    # project-level contract parameter, NOT a Veles indicator/warmup
    # semantic: the official Veles documentation does not define a
    # universal required-history/lookback rule, so no lookback is derived
    # from indicator periods/shifts. ``None`` (missing) blocks the live
    # processing cycle explicitly (LookbackNotConfigured); a non-positive
    # value fails strategy configuration validation (StrategyLoadError).
    lookback_bars: int | None = Field(
        default=None, ge=1, description="Explicit live snapshot history in bars (>=1)"
    )
    entry: EntryConfig = Field(default_factory=EntryConfig, description="Entry conditions")
    dca_grid: DCAGridConfig = Field(
        default_factory=DCAGridConfig, description="DCA/Grid averaging configuration"
    )
    exit: ExitConfig = Field(description="Exit block (take-profit, stop-loss)")
    risk: RiskConfig = Field(default_factory=RiskConfig, description="Risk block")

    @model_validator(mode="after")
    def _validate_indicator_params(self) -> StrategyConfig:
        """Every declared indicator arg must provide the parameters its
        calculation consumes (MVP-7.2 I4): a missing period/parameter is an
        explicit validation error, never a hidden engine fallback. Applies to
        entry groups, grid signal groups and exit signal groups (signal TP,
        signal stop-loss)."""
        for group in _iter_filter_groups(self):
            for cond in group.conditions:
                for arg in (cond.arg1, cond.arg2):
                    if getattr(arg, "kind", None) == "indicator":
                        validate_spec_args(arg.name, arg.period, arg.params)
        return self


def _iter_filter_groups(config: StrategyConfig):
    """Yield every FilterGroup the strategy evaluates (entry, grid signals,
    signal TP, signal stop-loss)."""
    yield from config.entry.groups
    yield from config.dca_grid.signal_groups
    tp = config.exit.take_profit
    if isinstance(tp, SignalTP):
        yield from tp.groups
    if config.exit.signal_stop is not None:
        yield from config.exit.signal_stop.groups
