"""Risk Manager (broker-neutral, MVP-6).

Per Architecture & Product Specification section 9, the Risk Manager is the
authoritative execution guard, separate from the strategy. The strategy and the
live execution path cannot bypass it. Rules are configuration-driven and safe by
default (no limit = allowed); a violation raises |RiskRejected|.

Money/quantity values use ``Decimal``; the Risk Manager only inspects
broker-neutral domain objects and never imports a broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.trading.domain import ExecutionIntent
from app.trading.position_manager import PositionManager


class RiskRejected(RuntimeError):
    """Raised when an operation violates a risk limit."""


@dataclass
class RiskLimits:
    """Configuration-driven risk limits."""

    max_position_size: Decimal | None = None
    max_concurrent_bots: int | None = None
    daily_loss_limit: Decimal | None = None
    emergency_stop: bool = False


class RiskManager:
    """Authoritative guard on trade/position risk."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        position_manager: PositionManager | None = None,
        daily_pnl: Decimal | None = None,
    ) -> None:
        self._limits = limits or RiskLimits()
        self._position_manager = position_manager
        self._daily_pnl = daily_pnl
        self._active_bots = 0

    # --- order gate -------------------------------------------------------------

    def check_order(self, intent: ExecutionIntent) -> None:
        """Reject an order when it violates a risk limit.

        Raises |RiskRejected| on violation; otherwise returns None.
        """
        if self._limits.emergency_stop:
            raise RiskRejected("emergency stop is active")
        self._check_position_size(intent)
        self._check_daily_loss()

    def _check_position_size(self, intent: ExecutionIntent) -> None:
        limit = self._limits.max_position_size
        if limit is None:
            return
        current = self._current_position(intent.instrument_figi)
        # Worst-case projected position magnitude for this intent.
        projected = current + abs(intent.quantity)
        if projected > limit:
            raise RiskRejected(
                f"max position size exceeded: {projected} > {limit} for {intent.instrument_figi}"
            )

    def _check_daily_loss(self) -> None:
        limit = self._limits.daily_loss_limit
        if limit is None or self._daily_pnl is None:
            return
        if self._daily_pnl <= -limit:
            raise RiskRejected("daily loss limit reached")

    def _current_position(self, instrument_figi: str) -> Decimal:
        if self._position_manager is None:
            return Decimal("0")
        position = self._position_manager.get(instrument_figi)
        return abs(position.quantity) if position is not None else Decimal("0")

    # --- lifecycle / bot guard --------------------------------------------------

    def check_start(self, bot_id: int) -> bool:
        """Allow/deny starting a bot (max concurrent bots)."""
        limit = self._limits.max_concurrent_bots
        if limit is not None and self._active_bots >= limit:
            return False
        return True

    def start_bot(self, bot_id: int) -> None:
        self._active_bots += 1

    def stop_bot(self, bot_id: int) -> None:
        self._active_bots = max(0, self._active_bots - 1)

    def check_emergency_stop(self) -> bool:
        """Return whether emergency stop is triggered."""
        return self._limits.emergency_stop

    def set_emergency_stop(self, value: bool) -> None:
        self._limits.emergency_stop = value
