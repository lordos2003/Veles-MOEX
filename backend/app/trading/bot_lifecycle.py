"""Bot lifecycle (broker-neutral, MVP-6.5).

A Bot is a persisted application entity; a :class:`BotRuntime` is the runtime
state/controller for one bot. It is the upstream control layer in the live
chain:

``BotRuntime -> TradingEngine -> RiskManager -> OrderManager -> Broker``

The runtime owns the bot state machine (STOPPED / STARTING / RUNNING /
STOP_REQUESTED / ERROR / EMERGENCY_STOP) and only permits execution when the bot
is RUNNING. START calls ``RiskManager.check_start`` before transitioning to
RUNNING and ``start_bot`` on success; normal STOP and EMERGENCY_STOP call
``stop_bot``. EMERGENCY_STOP cancels the bot's active orders through the existing
broker-neutral ``OrderManager`` path when available.

T-Invest is never imported here; the runtime only depends on broker-neutral
domain objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.enums import BotState
from app.trading.domain import TERMINAL_STATES, OrderState
from app.trading.risk_manager import RiskManager

if TYPE_CHECKING:
    from app.trading.domain import ExecutionIntent, InternalOrder
    from app.trading.order_manager import OrderManager

__all__ = [
    "ALLOWED_BOT_TRANSITIONS",
    "BotRuntime",
    "BotRuntimeManager",
    "BotState",
    "BotStateError",
    "BotStartRejected",
    "can_transition",
]


class BotStateError(RuntimeError):
    """Raised when an invalid bot-state transition is requested."""


class BotStartRejected(RuntimeError):
    """Raised when the Risk Manager blocks a START."""


# Explicit allowed lifecycle transitions. No free-for-all status assignment.
ALLOWED_BOT_TRANSITIONS: dict[BotState, frozenset[BotState]] = {
    BotState.STOPPED: frozenset({BotState.STARTING}),
    BotState.STARTING: frozenset({BotState.RUNNING, BotState.ERROR}),
    BotState.RUNNING: frozenset(
        {BotState.STOP_REQUESTED, BotState.EMERGENCY_STOP, BotState.ERROR}
    ),
    BotState.STOP_REQUESTED: frozenset({BotState.STOPPED, BotState.ERROR}),
    BotState.ERROR: frozenset({BotState.STARTING}),
    BotState.EMERGENCY_STOP: frozenset({BotState.STOPPED}),
}


def can_transition(current: BotState, target: BotState) -> bool:
    """Return whether ``target`` is a legal transition from ``current``."""
    return target in ALLOWED_BOT_TRANSITIONS.get(current, frozenset())


class BotRuntime:
    """Runtime state/controller for a single bot.

    The runtime does not open a broker connection (the broker connection is the
    shared live runtime) and never imports a broker.
    """

    def __init__(
        self,
        bot_id: int,
        risk_manager: RiskManager,
        *,
        submit_cb: Any | None = None,
        order_manager: OrderManager | None = None,
        state: BotState = BotState.STOPPED,
    ) -> None:
        self.bot_id = bot_id
        self._risk_manager = risk_manager
        self._submit_cb = submit_cb
        self._order_manager = order_manager
        self._state = state

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def running(self) -> bool:
        return self._state is BotState.RUNNING

    def can_submit(self) -> bool:
        """Only RUNNING bots may generate/send new intents."""
        return self._state is BotState.RUNNING

    def _transition(self, target: BotState) -> None:
        if target is self._state:
            return
        if not can_transition(self._state, target):
            raise BotStateError(
                f"invalid bot transition {self._state.value} -> {target.value}"
            )
        self._state = target

    # --- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        """Transition STOPPED/ERROR -> RUNNING via the Risk Manager start guard."""
        self._transition(BotState.STARTING)
        if not self._risk_manager.check_start(self.bot_id):
            self._transition(BotState.ERROR)
            raise BotStartRejected(f"bot {self.bot_id} start rejected by risk manager")
        self._risk_manager.start_bot(self.bot_id)
        self._transition(BotState.RUNNING)

    async def stop(self) -> None:
        """Normal stop: block new intents, cancel active orders, leave position open."""
        if self._state is BotState.STOPPED:
            return
        self._transition(BotState.STOP_REQUESTED)
        self._risk_manager.stop_bot(self.bot_id)
        await self._cancel_active_orders()
        self._transition(BotState.STOPPED)

    async def emergency_stop(self) -> None:
        """Emergency stop: block new intents and cancel active orders."""
        self._transition(BotState.EMERGENCY_STOP)
        self._risk_manager.stop_bot(self.bot_id)
        await self._cancel_active_orders()

    # --- execution gate ----------------------------------------------------------

    async def submit_intent(self, intent: ExecutionIntent) -> InternalOrder:
        """Forward an intent to the execution path, gated on RUNNING."""
        if not self.can_submit():
            raise BotStateError(
                f"bot {self.bot_id} cannot submit intents in state {self._state.value}"
            )
        if self._submit_cb is None:
            raise RuntimeError("bot runtime has no execution path wired")
        return await self._submit_cb(intent)

    async def _cancel_active_orders(self) -> None:
        """Cancel the bot's active orders via the broker-neutral OrderManager path.

        Boundary: if no OrderManager is wired, or the domain cannot correlate
        orders to a bot (no ``bot_id``), nothing is cancelled. This is documented
        as a limitation rather than fabricated behavior.
        """
        if self._order_manager is None:
            return
        for order in self._order_manager.list_orders():
            if getattr(order, "bot_id", None) != self.bot_id:
                continue
            if order.status in TERMINAL_STATES or order.status is OrderState.CANCEL_REQUESTED:
                continue
            await self._order_manager.cancel(order.order_id)


class BotRuntimeManager:
    """Registry/controller for the bot runtimes of the running application."""

    def __init__(
        self,
        risk_manager: RiskManager,
        *,
        runtime_factory: Any | None = None,
    ) -> None:
        self._risk_manager = risk_manager
        self._runtime_factory = runtime_factory
        self._runtimes: dict[int, BotRuntime] = {}

    def register(self, runtime: BotRuntime) -> None:
        self._runtimes[runtime.bot_id] = runtime

    def get(self, bot_id: int) -> BotRuntime | None:
        return self._runtimes.get(bot_id)

    def list(self) -> list[BotRuntime]:
        return list(self._runtimes.values())

    def _get_or_create(self, bot_id: int) -> BotRuntime:
        runtime = self._runtimes.get(bot_id)
        if runtime is None:
            if self._runtime_factory is None:
                raise KeyError(f"no bot runtime registered for bot {bot_id}")
            runtime = self._runtime_factory(bot_id)
            self._runtimes[bot_id] = runtime
        return runtime

    async def start(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        runtime.start()
        return runtime

    async def stop(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        await runtime.stop()
        return runtime

    async def emergency_stop(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        await runtime.emergency_stop()
        return runtime
