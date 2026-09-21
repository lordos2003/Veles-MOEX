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

from pydantic import BaseModel, Field

from app.strategies.filters import CalculationMethod, FilterGroup


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

    method: CalculationMethod = CalculationMethod.AT_BAR_CLOSE
    # Groups are OR-ed; conditions within a group are AND-ed.
    groups: list[FilterGroup] = Field(default_factory=list)


class DCAGridConfig(BaseModel):
    """DCA / Grid configuration (Architecture & Product Specification section 5).

    SIMPLE mode derives a limit-order grid from the parameters below. CUSTOM
    mode uses ``custom_levels``. SIGNAL mode uses the first order plus a signal
    filter for subsequent market averaging orders.
    """

    mode: TradingMode = TradingMode.SIMPLE
    levels: int = Field(default=1, ge=1)
    overlap_percent: float = 0.0
    spacing_percent: float = 0.0
    martingale_percent: float = 0.0
    logarithmic_factor: float = 1.0
    first_order_offset_percent: float = 0.0
    pull_up_percent: float = 0.0
    # Partial grid: max simultaneously active/eligible grid orders.
    active_limit: int | None = None
    # --- CUSTOM mode ---
    custom_levels: list[CustomLevel] = Field(default_factory=list)
    # --- SIGNAL mode ---
    signal_groups: list[FilterGroup] = Field(default_factory=list)
    signal_offset_type: SignalOffsetReference = SignalOffsetReference.REFERENCE
    signal_min_offset_percent: float = 0.0


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

    kind: Literal["fixed_percentage"] = "fixed_percentage"
    percent: float


class MultiTakeTP(BaseModel):
    """Partial exits at several profit levels."""

    kind: Literal["multi_take"] = "multi_take"
    takes: list[TakeItem] = Field(default_factory=list)
    breakeven: BreakEvenConfig | None = None


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
    """Separate protective exit mechanism."""

    kind: Literal["percent", "signal"] = "percent"
    percent: float | None = None
    groups: list[FilterGroup] = Field(default_factory=list)


class ExitConfig(BaseModel):
    """Exit block of a strategy."""

    take_profit: TPConfig
    stop_loss: StopLossConfig | None = None


class RiskConfig(BaseModel):
    """Risk block. Risk Manager is authoritative and separate from the strategy."""

    max_position_size: float | None = None
    max_concurrent_bots: int | None = None
    daily_loss_limit: float | None = None
    emergency_stop: bool = False


class StrategyConfig(BaseModel):
    """Full strategy configuration (Architecture & Product Specification section 3)."""

    name: str = ""
    direction: Direction = Direction.LONG
    instrument_id: int | None = None
    entry: EntryConfig = Field(default_factory=EntryConfig)
    dca_grid: DCAGridConfig = Field(default_factory=DCAGridConfig)
    exit: ExitConfig
    risk: RiskConfig = Field(default_factory=RiskConfig)
