"""Broker-neutral position-sizing boundary (MVP-6.8 / MVP-6.11).

MVP-6.8 introduced the typed boundary: live execution is blocked until an
authoritative sizing source is configured. MVP-6.11 (approved contracts C2/C3,
2026-09-29) completes it:

- C2: the bot deposit ``D`` (a *bot* setting, Veles "Full list of bot settings":
  "The amount within which the bot trades") is converted to the DCA/Grid base
  nominal so that the sum of the nominals of all grid orders of one deal
  (first order included) equals ``D``. Spot semantics only: no leverage, no
  margin, no FX conversion.
- C3: MOEX lot rounding — order quantity in units = nominal / order_price,
  rounded **down** to a whole number of lots. If any order of the deal rounds
  to 0 lots, the whole entry is blocked (no partial grid).

No financial default (100, 1.0, a default lot, a default currency) is ever
invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.strategies.config import DCAGridConfig, TradingMode
from app.strategies.domain import GridOrder


class SizingNotConfigured(RuntimeError):
    """Raised when live execution is attempted without an explicit sizing source."""


class SizingError(RuntimeError):
    """Base for MVP-6.11 deposit-sizing contract violations (C2/C3)."""


class CustomDepositExceeded(SizingError):
    """CUSTOM mode: the configured level nominals exceed the bot deposit."""


class SignalSizingUnsupported(SizingError):
    """SIGNAL mode sizing is blocked by the MVP-6.11 contract (see below)."""


class SizingBelowLot(SizingError):
    """A grid level rounds down to 0 lots; the whole entry is blocked (C3)."""


class LotSizeUnavailable(SizingError):
    """The instrument lot size is missing/non-positive; no default lot (C3)."""


class CurrencyUnavailable(SizingError):
    """The instrument currency cannot be resolved; the entry is blocked (C3)."""


@dataclass(frozen=True)
class PositionSizing:
    """An explicit broker-neutral sizing source.

    ``base_nominal`` is the resolved first-order currency nominal (MVP-6.8).
    ``deposit`` is the bot deposit (MVP-6.11 C5): when set, the base nominal is
    derived from it by |deposit_to_base_nominal| (C2) using the bot's own
    ``DCAGridConfig``. ``lot_size`` / ``currency`` are the instrument
    constraints used by the MOEX lot-rounding contract (C3). An unset or
    non-positive source blocks live execution; nothing is fabricated.
    """

    base_nominal: Decimal | None = None
    deposit: Decimal | None = None
    lot_size: int | None = None
    currency: str | None = None

    def resolve_base_nominal(self, dca_grid: DCAGridConfig | None = None) -> Decimal:
        """Return the positive base nominal or raise |SizingNotConfigured|.

        With an explicit ``base_nominal`` (MVP-6.8) it is returned as-is. With
        a bot ``deposit`` (MVP-6.11 C5) the C2 conversion is applied to the
        bot's own ``dca_grid`` configuration; a missing ``dca_grid`` is an
        explicit configuration error, not an implicit default.
        """
        if self.base_nominal is not None:
            if self.base_nominal <= 0:
                raise SizingNotConfigured(
                    "position-sizing base nominal must be positive; live "
                    "execution is blocked until a valid sizing source is wired"
                )
            return self.base_nominal
        if self.deposit is not None:
            if self.deposit <= 0:
                raise SizingNotConfigured(
                    "bot deposit must be positive; live execution is blocked "
                    "until a valid deposit is configured"
                )
            if dca_grid is None:
                raise SizingNotConfigured(
                    "the deposit-to-base-nominal conversion requires the bot's "
                    "dca_grid configuration; live execution is blocked"
                )
            return deposit_to_base_nominal(self.deposit, dca_grid)
        raise SizingNotConfigured(
            "no authoritative position-sizing source configured; live "
            "execution is blocked until a sizing source is wired"
        )


def deposit_to_base_nominal(deposit: Decimal, dca_grid: DCAGridConfig) -> Decimal:
    """Convert the bot deposit to the DCA/Grid base nominal (MVP-6.11 C2).

    The sum of the nominals of **all** grid orders of one deal (first order
    included) must equal the deposit ``D``:

    - SIMPLE: ``n = dca_grid.levels`` grid orders, ``k = 1 + martingale/100``
      (``k = 1`` when martingale is off), ``first_nominal = D / sum(k**i)``;
      level ``i`` nominal = ``first_nominal * k**i`` — the unchanged
      ``DCAGridEngine`` martingale math, only the base nominal is derived.
    - CUSTOM: level nominal = ``D * nominal_percent / 100`` (the existing
      ``_build_custom`` math with ``base_nominal = D``). When the configured
      level percentages sum to more than 100 the deal would exceed the deposit:
      an explicit |CustomDepositExceeded| is raised.
    - SIGNAL: the existing SIGNAL engine does **not** use
      ``DCAGridConfig.levels`` as a maximum order-count limit (subsequent
      averaging orders are unbounded), so no limit is invented: sizing blocks
      with an explicit |SignalSizingUnsupported|.

    Spot semantics only: the deposit is used 1:1 (no leverage/margin field
    exists in the configuration and none is added).
    """
    if deposit is None or deposit <= 0:
        raise SizingNotConfigured(
            "the bot deposit must be a positive Decimal; live execution is "
            "blocked until a valid deposit is configured"
        )
    mode = dca_grid.mode
    if mode is TradingMode.SIMPLE:
        n = dca_grid.levels
        k = (
            Decimal("1") + Decimal(str(dca_grid.martingale_percent)) / Decimal("100")
            if dca_grid.martingale_percent > 0
            else Decimal("1")
        )
        total = sum((k**i for i in range(n)), Decimal("0"))
        return deposit / total
    if mode is TradingMode.CUSTOM:
        total_percent = sum(
            (Decimal(str(level.nominal_percent)) for level in dca_grid.custom_levels),
            Decimal("0"),
        )
        if total_percent > Decimal("100"):
            raise CustomDepositExceeded(
                f"CUSTOM mode level nominals sum to {total_percent}% of the "
                f"deposit, which exceeds the deposit (100%); the entry is "
                "blocked"
            )
        return deposit
    if mode is TradingMode.SIGNAL:
        raise SignalSizingUnsupported(
            "SIGNAL mode sizing is not supported in MVP-6.11: the SIGNAL engine "
            "does not use DCAGridConfig.levels as a maximum order-count limit "
            "(subsequent averaging orders are unbounded), and no limit is "
            "invented; live SIGNAL entry is blocked until a separately "
            "approved contract"
        )
    raise SizingError(f"unknown trading mode: {mode!r}")


def round_grid_to_lot(
    grid: list[GridOrder], *, lot_size: int | None, currency: str | None
) -> list[GridOrder]:
    """Round each grid level quantity down to whole lots (MVP-6.11 C3).

    MOEX/T-Invest rule (project contract, not a Veles rule): order quantity in
    units = nominal / order_price, then rounded **down** to a whole number of
    lots (``lot_size`` from the instrument). If **any** order of the deal
    rounds to 0 lots, the **whole entry** is blocked with |SizingBelowLot|
    (naming the level, its nominal, price and lot size); no partial grid is
    returned. The unused remainder of the deposit after rounding stays unused
    (no redistribution). A missing/non-positive lot size or an unresolvable
    instrument currency blocks with an explicit error; no default lot or
    currency is substituted.
    """
    if not grid:
        return grid
    if lot_size is None or lot_size <= 0:
        raise LotSizeUnavailable(
            "the instrument lot size is missing or non-positive; the entry is "
            "blocked (no default lot)"
        )
    if currency is None or not str(currency).strip():
        raise CurrencyUnavailable(
            "the instrument currency cannot be resolved; the entry is blocked "
            "(no FX conversion, no default currency)"
        )
    lot = Decimal(lot_size)
    rounded: list[GridOrder] = []
    for index, order in enumerate(grid):
        quantity = Decimal(str(order.quantity))
        lots = quantity // lot if quantity > 0 else Decimal("0")
        if lots <= 0:
            price = "market" if order.price is None else f"{order.price}"
            raise SizingBelowLot(
                f"grid level {index} (nominal {order.nominal} at {price}) rounds "
                f"to 0 whole lots (lot size {lot_size}); the whole entry is "
                "blocked, no partial grid is submitted"
            )
        rounded.append(
            GridOrder(
                side=order.side,
                quantity=float(lots * lot),
                price=order.price,
                offset_percent=order.offset_percent,
                nominal=order.nominal,
            )
        )
    return rounded
