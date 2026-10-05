"""MVP-6.12 deal continuation domain (broker-neutral).

A "deal" is one position cycle: from the FLAT entry (the grid opens position
size) to the closing take-profit fill. The deal layer consumes only the
broker-neutral trading domain (|ExecutionIntent| / |InternalOrder| /
|Fill| / |OrderState|) and the existing DCA-grid math (``DCAGridEngine``);
it never imports a broker, and no Veles semantics are invented here.

Money/quantity values use ``Decimal``; timestamps are timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.models.enums import OrderSide
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    FixedPercentageTP,
    StopLossConfig,
    StrategyConfig,
    TradingMode,
)
from app.strategies.exit import simple_stop_level


def utcnow() -> datetime:
    return datetime.now(UTC)


class DealStatus(StrEnum):
    OPENING = "OPENING"  # entry orders submitted, entry fill not yet confirmed
    OPEN = "OPEN"  # entry filled; grid + Deal-owned take-profit working
    CLOSING = "CLOSING"  # position closed; remaining grid orders being cancelled
    CLOSED = "CLOSED"
    ERROR = "ERROR"  # known but unreconcilable state; new submissions blocked


class DealLevelStatus(StrEnum):
    WAITING = "waiting"
    ACTIVE = "active"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class DealLevel:
    """One planned grid order of a Deal (the persisted counterpart of a grid level)."""

    index: int
    side: OrderSide
    price: Decimal | None  # None for a market first order (offset 0)
    nominal: Decimal
    quantity: Decimal
    offset_percent: float
    status: DealLevelStatus = DealLevelStatus.WAITING
    is_market: bool = False
    filled_quantity: Decimal = Decimal("0")
    intent_id: str | None = None
    order_id: str | None = None
    broker_order_id: str | None = None


@dataclass
class Deal:
    """The persisted state of one live position cycle.

    The take-profit (D4) is Deal-owned: at most one TP order exists at a time
    (``tp_order_id``); it is re-armed on every grid fill from the
    |PositionManager| average price and quantity.

    The simple stop-loss (MVP-6.16 E1/E2) is Deal-owned too: ``p0_price``
    captures the actual average fill price of the level-0 grid order, ``sl_percent``
    the configured SL%, ``sl_offset`` the grid-ladder component and ``sl_order_id``
    the broker stop order id (or None while disarmed). At most one stop order
    exists at a time.
    """

    id: int | None = None
    bot_id: int | None = None
    instrument_figi: str = ""
    direction: Direction = Direction.LONG
    status: DealStatus = DealStatus.OPENING
    deposit: Decimal | None = None  # C6 entry-time deposit value
    base_nominal: Decimal = Decimal("0")
    reference_price: Decimal = Decimal("0")
    # D3/D5: per-instrument rounding facts captured at entry so recovery can
    # re-arm the TP with exactly the same lot/tick contract after a restart.
    lot_size: int | None = None
    tick_size: Decimal | None = None
    tp_percent: float = 0.0
    active_limit: int | None = None
    account_id: str | None = None
    levels: list[DealLevel] = field(default_factory=list)
    average_price: Decimal = Decimal("0")
    tp_rev: int = 0
    tp_price: Decimal | None = None
    tp_quantity: Decimal | None = None
    tp_intent_id: str | None = None
    tp_order_id: str | None = None
    tp_broker_order_id: str | None = None
    # MVP-6.16 E1/E2/E3 stop-loss state (see class docstring).
    sl_percent: float | None = None
    sl_offset: Decimal = Decimal("0")
    p0_price: Decimal | None = None
    sl_rev: int = 0
    sl_order_id: str | None = None
    sl_quantity: Decimal | None = None
    sl_price: Decimal | None = None
    close_reason: str | None = None
    stop_bot_after: bool | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    closed_at: datetime | None = None

    def level(self, index: int) -> DealLevel | None:
        return next((lvl for lvl in self.levels if lvl.index == index), None)

    def level_by_order(self, order_id: str) -> DealLevel | None:
        return next((lvl for lvl in self.levels if lvl.order_id == order_id), None)

    def is_tp_intent(self, intent_id: str) -> bool:
        return intent_id == self.tp_intent_id or intent_id.startswith(
            f"deal-{self.id}-tp-"
        )

    def tp_price_from_average(self, average_price: Decimal) -> Decimal:
        """D4 raw TP price: average x (1 +- tp_percent/100), before tick alignment.

        The LONG take-profit sits above the average (plus); the SHORT one below
        (minus). The caller applies |align_tp_price| (D3).
        """
        factor = Decimal("1") + Decimal(str(self.tp_percent)) / Decimal("100")
        if self.direction == Direction.SHORT:
            factor = Decimal("1") - Decimal(str(self.tp_percent)) / Decimal("100")
        return average_price * factor

    def sl_price_from_p0(self) -> Decimal:
        """E1 raw stop level: P0 x (1 -+ combined_offset/100), before tick alignment.

        Delegates to the shared |simple_stop_level| formula (Backtest and Live
        use exactly the same math); ``combined_offset`` is ``sl_offset +
        sl_percent``. The caller applies |align_stop_price|.
        """
        percent = float(self.sl_offset) + (self.sl_percent or 0.0)
        return simple_stop_level(self.p0_price, self.direction, percent)


# --- D3: tick alignment ------------------------------------------------------------
#
# Every limit price must be a multiple of the instrument tick size, rounded in
# the safe direction: grid levels LONG round down / SHORT round up (a BUY limit
# below the theoretical price is safer, a SELL limit above is safer); the TP
# LONG rounds up / SHORT rounds down (the exit limit sits on the winning side).


class DealError(RuntimeError):
    """Base class for broker-neutral deal-continuation failures."""


class DealTickSizeInvalid(DealError):
    """D3: a missing/non-positive tick size makes limit alignment impossible."""


class DealStopExecuted(DealError):
    """E2: the Deal's stop executed while its cancel was in flight.

    Not an unknown outcome — the stop is consumed and the Deal must close with
    ``close_reason="stop_loss"`` (the caller re-reads the position facts).
    """


def _require_tick(tick_size: Decimal | None) -> Decimal:
    if tick_size is None or tick_size <= 0:
        raise DealTickSizeInvalid(
            f"a positive tick size is required for D3 price alignment, got {tick_size!r}"
        )
    return tick_size


def round_down_to_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    tick = _require_tick(tick_size)
    return (price // tick) * tick


def round_up_to_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    tick = _require_tick(tick_size)
    quotient, remainder = divmod(price, tick)
    return (quotient + (1 if remainder else 0)) * tick


def align_grid_price(price: Decimal, tick_size: Decimal, direction: Direction) -> Decimal:
    """D3 grid alignment: LONG down, SHORT up (the safe direction for entries)."""
    if direction == Direction.LONG:
        return round_down_to_tick(price, tick_size)
    return round_up_to_tick(price, tick_size)


def align_tp_price(price: Decimal, tick_size: Decimal, direction: Direction) -> Decimal:
    """D3 take-profit alignment: LONG up, SHORT down (the winning-side direction)."""
    if direction == Direction.LONG:
        return round_up_to_tick(price, tick_size)
    return round_down_to_tick(price, tick_size)


def align_stop_price(price: Decimal, tick_size: Decimal, direction: Direction) -> Decimal:
    """E1 stop alignment: LONG up, SHORT down.

    The stop is a conditional market order, but its trigger must sit on the
    broker's tick grid; the same direction as |align_tp_price| (an early
    trigger is the safe side for a protective stop: a LONG stop that rounds up
    triggers earlier, a SHORT stop that rounds down triggers earlier).
    """
    if direction == Direction.LONG:
        return round_up_to_tick(price, tick_size)
    return round_down_to_tick(price, tick_size)


def deal_stop_intent_id(deal_id: str, rev: int) -> str:
    """E2: unique intent_id for a stop-loss order attempt.

    Includes the re-arm revision so each placement (and its idempotent retry)
    is a distinct intent; the retry must reuse the same intent_id for the same
    ``rev`` (see |_stop_intent|).
    """
    return f"deal-{deal_id}-sl-{rev}"


# --- D1: strategy-config scope -----------------------------------------------------


class DealConfigUnsupported(ValueError):
    """Raised when a live strategy is outside the MVP-6.12 D1 deal scope.

    Maps to HTTP 409 through the existing bot-start error mapping (a named,
    explicit error — no silent fallback to a non-deal path).
    """


def validate_live_deal_config(config: StrategyConfig) -> None:
    """Validate that a live strategy is covered by the deal scope.

    D1/MVP-6.16 E4: grid mode SIMPLE or CUSTOM; take-profit kind
    ``fixed_percentage``; stop loss either absent or the simple percentage kind
    (``kind="percent"``) with an explicit ``stop_bot_after`` choice; no signal
    stop; ``pull_up_percent == 0``. Anything else is rejected at bot START with
    an explicit named error.
    """
    dca: DCAGridConfig = config.dca_grid
    if dca.mode not in (TradingMode.SIMPLE, TradingMode.CUSTOM):
        raise DealConfigUnsupported(
            f"live deal support (MVP-6.12 D1) does not cover grid mode "
            f"{dca.mode.value!r}; supported modes are SIMPLE and CUSTOM"
        )
    tp = config.exit.take_profit
    if not isinstance(tp, FixedPercentageTP):
        kind = getattr(tp, "kind", type(tp).__name__)
        raise DealConfigUnsupported(
            f"live deal support (MVP-6.12 D1) requires take_profit kind "
            f"'fixed_percentage', got {kind!r}"
        )
    sl = config.exit.stop_loss
    if sl is not None and not isinstance(sl, StopLossConfig):
        raise DealConfigUnsupported(
            f"live deal support (MVP-6.16 E4) covers only the simple percentage "
            f"stop_loss, got kind {getattr(sl, 'kind', type(sl).__name__)!r}"
        )
    if sl is not None and sl.stop_bot_after is None:
        raise DealConfigUnsupported(
            "live deal support (MVP-6.16 E3) requires an explicit "
            "stop_loss.stop_bot_after choice (true/false), got None"
        )
    if config.exit.signal_stop is not None:
        raise DealConfigUnsupported(
            "live deal support (MVP-6.12 D1) does not cover signal_stop"
        )
    if dca.pull_up_percent != 0:
        raise DealConfigUnsupported(
            "live deal support (MVP-6.12 D1) does not cover a non-zero "
            "pull_up_percent"
        )


# --- deal errors -------------------------------------------------------------------


class DealBlocked(DealError):
    """The bot has a Deal that needs reconciliation; new submissions are blocked."""


class DealOrderRejected(DealError):
    """A broker rejected a Deal order; the entry cannot proceed safely."""


class DealReconciliationRequired(DealError):
    """A cancel outcome is unknown (or a deal contradicts broker facts).

    Per D4/D5 no second TP is placed and new submissions for the bot are
    blocked until reconciliation resolves (or marks ERROR) the Deal.
    """


class DealPositionContradiction(DealError):
    """The Deal contradicts the reconciled broker position (D5 -> ERROR)."""


# --- store boundary ----------------------------------------------------------------


class DealStore(Protocol):
    """Persists broker-neutral Deal state (SQLAlchemy / in-memory)."""

    async def save(self, deal: Deal) -> Deal: ...

    async def get(self, deal_id: int) -> Deal | None: ...

    async def list_unclosed(self) -> list[Deal]: ...


class InMemoryDealStore:
    """Deterministic in-memory DealStore used by tests."""

    def __init__(self) -> None:
        self._deals: dict[int, Deal] = {}
        self._seq = 0

    async def save(self, deal: Deal) -> Deal:
        if deal.id is None:
            self._seq += 1
            deal.id = self._seq
        deal.updated_at = utcnow()
        self._deals[deal.id] = deal
        return deal

    async def get(self, deal_id: int) -> Deal | None:
        return self._deals.get(deal_id)

    async def list_unclosed(self) -> list[Deal]:
        return [
            deal for deal in self._deals.values() if deal.status != DealStatus.CLOSED
        ]


# --- intent id correlation ---------------------------------------------------------


def deal_grid_intent_id(deal_id: int, level_index: int) -> str:
    return f"deal-{deal_id}-grid-{level_index}"


def deal_tp_intent_id(deal_id: int, rev: int) -> str:
    return f"deal-{deal_id}-tp-{rev}"
