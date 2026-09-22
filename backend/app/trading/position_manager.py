"""Position Manager (broker-neutral, MVP-6.1).

The Position Manager is the authoritative local representation of a position.
Positions change only from actual fills (or explicit position updates), never
from the mere fact that an order was submitted.

Average price uses the weighted mean: sum(quantity_i * price_i) / sum(quantity_i)
with ``Decimal``. Reducing/closing adjusts quantity and realizes P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.models.enums import OrderSide
from app.trading.domain import PositionUpdate


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Position:
    """A signed position for one instrument."""

    instrument_figi: str
    quantity: Decimal = Decimal("0")  # + long / - short
    average_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    current_price: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    updated_at: datetime | None = field(default_factory=_utcnow)

    def recompute_unrealized(self) -> None:
        if self.current_price is None or self.quantity == 0:
            self.unrealized_pnl = Decimal("0")
            return
        if self.quantity > 0:
            self.unrealized_pnl = (self.current_price - self.average_price) * self.quantity
        else:
            self.unrealized_pnl = (
                self.average_price - self.current_price
            ) * abs(self.quantity)


class PositionManager:
    """Tracks positions and recomputes weighted-average price on fills."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def get(self, instrument_figi: str) -> Position | None:
        return self._positions.get(instrument_figi)

    def list(self) -> list[Position]:
        return list(self._positions.values())

    def clear(self) -> None:
        self._positions.clear()

    def load_state(self, positions: list[Position]) -> None:
        """Replace the manager state with a recovered set of positions."""
        self._positions.clear()
        for position in positions:
            self._positions[position.instrument_figi] = position

    def apply_fill(
        self,
        instrument_figi: str,
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        timestamp: datetime | None = None,
    ) -> Position:
        """Apply a fill to a position (increase / reduce / reverse)."""
        pos = self._positions.get(instrument_figi)
        if pos is None:
            pos = Position(instrument_figi=instrument_figi, average_price=price)
            self._positions[instrument_figi] = pos

        delta = quantity if side == OrderSide.BUY else -quantity
        if pos.quantity == 0:
            pos.quantity = delta
            pos.average_price = price
        elif _same_sign(pos.quantity, delta):
            pos.quantity += delta
            if pos.quantity != 0:
                pos.average_price = _weighted_avg(
                    abs(pos.quantity - delta), pos.average_price, abs(delta), price,
                    abs(pos.quantity),
                )
        else:
            self._reduce_or_reverse(pos, delta, price)

        pos.fees += fee
        pos.updated_at = timestamp or _utcnow()
        pos.recompute_unrealized()
        return pos

    def apply_position_update(self, update: PositionUpdate) -> Position:
        pos = self._positions.get(update.instrument_figi)
        if pos is None:
            pos = Position(instrument_figi=update.instrument_figi)
            self._positions[update.instrument_figi] = pos
        pos.quantity = update.quantity
        if update.average_price is not None:
            pos.average_price = update.average_price
        if update.current_price is not None:
            pos.current_price = update.current_price
        if update.unrealized_pnl is not None:
            pos.unrealized_pnl = update.unrealized_pnl
        pos.updated_at = update.timestamp
        pos.recompute_unrealized()
        return pos

    def mark_to_market(self, instrument_figi: str, current_price: Decimal) -> Position:
        pos = self._positions.get(instrument_figi)
        if pos is None:
            pos = Position(instrument_figi=instrument_figi, current_price=current_price)
            self._positions[instrument_figi] = pos
        pos.current_price = current_price
        pos.recompute_unrealized()
        return pos

    @staticmethod
    def _reduce_or_reverse(pos: Position, delta: Decimal, price: Decimal) -> None:
        """Handle a fill on the opposite side (reduce, close or reverse)."""
        current = abs(pos.quantity)
        closing = min(abs(delta), current)
        if pos.quantity > 0:
            pos.realized_pnl += (price - pos.average_price) * closing
        else:
            pos.realized_pnl += (pos.average_price - price) * closing

        signed_close = -closing if pos.quantity > 0 else closing
        pos.quantity += signed_close

        if abs(delta) > current:
            # Reversal: remainder opens an opposite position at the fill price.
            pos.quantity = delta + (current if delta < 0 else -current)
            pos.average_price = price
        elif pos.quantity == 0:
            pos.average_price = Decimal("0")


def _same_sign(a: Decimal, b: Decimal) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _weighted_avg(
    prev_qty: Decimal, prev_avg: Decimal, new_qty: Decimal, new_price: Decimal, total_qty: Decimal
) -> Decimal:
    if total_qty == 0:
        return Decimal("0")
    return (prev_qty * prev_avg + new_qty * new_price) / total_qty
