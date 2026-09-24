"""Broker-neutral position-sizing boundary (MVP-6.8).

The first live order quantity must come from an explicit, authoritative sizing
source. There is currently no such source in the Bot/trading configuration, so
this module implements the typed boundary only: live execution is blocked until
a sizing source is configured. No financial default (100, 1.0) is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class SizingNotConfigured(RuntimeError):
    """Raised when live execution is attempted without an explicit sizing source."""


@dataclass(frozen=True)
class PositionSizing:
    """An explicit broker-neutral sizing source.

    ``base_nominal`` is the currency nominal used to size the first live grid
    order. It must be a positive ``Decimal`` supplied by an authoritative
    source; an unset or non-positive value blocks live execution.
    """

    base_nominal: Decimal | None = None

    def resolve_base_nominal(self) -> Decimal:
        """Return the positive base nominal or raise |SizingNotConfigured|."""
        if self.base_nominal is None or self.base_nominal <= 0:
            raise SizingNotConfigured(
                "no authoritative position-sizing source configured; live "
                "execution is blocked until a sizing source is wired"
            )
        return self.base_nominal
