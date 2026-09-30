"""Risk Manager (broker-neutral, MVP-6 / MVP-6.6).

Per Architecture & Product Specification section 9, the Risk Manager is the
authoritative execution guard, separate from the strategy. The strategy and the
live execution path cannot bypass it. Rules are configuration-driven and safe by
default (no limit = allowed); a violation raises |RiskRejected|.

``check_order`` enforces the execution preconditions: emergency stop, positive
quantity, a valid limit price for LIMIT intents, instrument/trading permission
(configured blocklist and an optional broker-neutral status provider), configured
position limit and daily loss limit. The bot RUNNING state is NOT checked here:
the bot lifecycle (MVP-6.5) remains the upstream lifecycle gate.

Money/quantity values use ``Decimal``; the Risk Manager only inspects
broker-neutral domain objects and never imports a broker.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import OrderSide, OrderType
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
    # FIGI set that is not allowed for trading. None/empty = no restriction.
    blocked_instruments: frozenset[str] | None = None


class RiskManager:
    """Authoritative guard on trade/position risk.

    ``instrument_status_check`` is an optional broker-neutral dependency:
    ``callable(figi) -> bool | None`` where ``True`` means trading is permitted,
    ``False`` means it is not, and ``None`` means unknown (the check is not
    available). It is never fabricated; when not wired the check is skipped.
    """

    def __init__(
        self,
        limits: RiskLimits | None = None,
        position_manager: PositionManager | None = None,
        daily_pnl: Decimal | None = None,
        instrument_status_check: Callable[[str], bool | None] | None = None,
    ) -> None:
        self._limits = limits or RiskLimits()
        self._position_manager = position_manager
        self._daily_pnl = daily_pnl
        self._active_bots = 0
        self._instrument_status_check = instrument_status_check

    # --- order gate -------------------------------------------------------------

    def check_order(self, intent: ExecutionIntent) -> None:
        """Reject an order when it violates an execution precondition or a limit.

        Raises |RiskRejected| on violation; otherwise returns None.
        """
        if self._limits.emergency_stop:
            raise RiskRejected("emergency stop is active")
        self._check_quantity(intent)
        self._check_price(intent)
        self._check_instrument_permission(intent)
        # D7 (MVP-6.12 owner contract): a position-reducing order (the closing
        # take-profit) must never be blocked by a growth limit — emergency
        # stop, quantity, price and instrument-permission checks above still
        # apply to reducing intents.
        if self._is_reducing(intent):
            return
        self._check_position_size(intent)
        self._check_daily_loss()

    def _check_quantity(self, intent: ExecutionIntent) -> None:
        if intent.quantity <= 0:
            raise RiskRejected(
                f"quantity must be positive, got {intent.quantity} for {intent.instrument_figi}"
            )

    def _check_price(self, intent: ExecutionIntent) -> None:
        if intent.order_type is OrderType.LIMIT:
            price = intent.limit_price
            if price is None or price <= 0:
                raise RiskRejected(
                    f"LIMIT order requires a valid positive limit price, "
                    f"got {price} for {intent.instrument_figi}"
                )

    def _check_instrument_permission(self, intent: ExecutionIntent) -> None:
        blocked = self._limits.blocked_instruments
        if blocked is not None and intent.instrument_figi in blocked:
            raise RiskRejected(
                f"instrument is not allowed for trading: {intent.instrument_figi}"
            )
        if self._instrument_status_check is not None:
            status = self._instrument_status_check(intent.instrument_figi)
            if status is False:
                raise RiskRejected(
                    f"trading is not permitted for {intent.instrument_figi}"
                )

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

    def _is_reducing(self, intent: ExecutionIntent) -> bool:
        """D7: whether the intent reduces the current position.

        An intent is reducing when the PositionManager position for its FIGI
        is non-zero, the intent side is opposite to the position sign, and the
        quantity does not exceed the position magnitude. Only then are the
        position-size and daily-loss limits skipped (a closing TP must never
        be blocked by a limit meant to stop risk from growing). Without a
        known position the intent is treated as increasing (no exemption).
        """
        if self._position_manager is None:
            return False
        position = self._position_manager.get(intent.instrument_figi)
        if position is None or position.quantity == 0:
            return False
        opposite = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        if intent.side is not opposite:
            return False
        return abs(intent.quantity) <= abs(position.quantity)

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
