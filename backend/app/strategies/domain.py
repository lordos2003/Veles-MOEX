"""Shared lightweight value objects for the Strategy Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.enums import OrderSide
from app.strategies.bars import Snapshot


@dataclass
class MarketContext:
    """Market snapshot handed to the Strategy Engine (broker-agnostic)."""

    instrument_id: int | None = None
    price: float | None = None
    timestamp: datetime | None = None
    snapshot: Snapshot | None = None


@dataclass
class EntrySignal:
    """Signal produced by the Entry Engine. Does not place orders."""

    action: str = "enter"
    direction: OrderSide = OrderSide.BUY
    reasons: list[str] = field(default_factory=list)


@dataclass
class GridOrder:
    """A planned order produced by the DCA/Grid Engine."""

    side: OrderSide
    quantity: float
    price: float | None = None
    offset_percent: float = 0.0


@dataclass
class ExitPlan:
    """A planned exit order produced by the Exit Engine."""

    side: OrderSide
    quantity: float
    price: Decimal | None = None
    offset_percent: float = 0.0


@dataclass
class Plan:
    """A complete plan produced by the Strategy Engine for the Trading Engine."""

    entry: EntrySignal | None = None
    grid: list[GridOrder] = field(default_factory=list)
    exits: list[ExitPlan] = field(default_factory=list)
