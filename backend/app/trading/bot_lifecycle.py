"""Bot lifecycle (broker-neutral, MVP-6.5 / MVP-6.7).

A Bot is a persisted application entity; a :class:`BotRuntime` is the runtime
state/controller for one bot. It is the upstream control layer in the live
chain:

``BotRuntime -> TradingEngine -> RiskManager -> OrderManager -> Broker``

The runtime owns the bot state machine (STOPPED / STARTING / RUNNING /
STOP_REQUESTED / ERROR / EMERGENCY_STOP) and only permits execution when the bot
is RUNNING. START loads the bot's own immutable strategy first (when a strategy
loader is wired), then calls ``RiskManager.check_start`` before transitioning to
RUNNING and ``start_bot`` on success; any START failure transitions the bot to
ERROR without occupying a concurrent-bot slot. normal STOP and EMERGENCY_STOP
call ``stop_bot``. EMERGENCY_STOP cancels the bot's active orders through the
existing broker-neutral ``OrderManager`` path when available.

Strategy execution (MVP-6.7) goes through the bot's own TradingEngine:
``execute_strategy(MarketContext)`` evaluates the bot's StrategyConfig via the
Strategy Engine and submits the resulting intents through
``RiskManager -> OrderManager``. A MarketContext is always an explicit
broker-neutral input; no market data is fabricated. When called without an
explicit context, the runtime's market-context provider builds a live
snapshot for the bot's own configured timeframe from real broker-neutral
market data (MVP-6.10); a missing/invalid snapshot or timeframe fails the
cycle explicitly.

T-Invest is never imported here; the runtime only depends on broker-neutral
domain objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.enums import BotState
from app.trading.domain import TERMINAL_STATES, OrderState
from app.trading.risk_manager import RiskManager

if TYPE_CHECKING:
    from app.bots.strategy import BotStrategy
    from app.strategies.domain import MarketContext, Plan
    from app.trading.domain import ExecutionIntent, InternalOrder
    from app.trading.engine import TradingEngine
    from app.trading.order_manager import OrderManager

__all__ = [
    "ALLOWED_BOT_TRANSITIONS",
    "BotRuntime",
    "BotRuntimeManager",
    "BotState",
    "BotStateError",
    "BotStartRejected",
    "RESTART_STATE_MAP",
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


#: Persisted-state -> restored-runtime-state after a process restart.
#: A bot persisted in RUNNING/STARTING was interrupted mid-execution; its
#: runtime state is unknown, so it is restored in ERROR (execution blocked until
#: an explicit START). STOP_REQUESTED is restored as STOPPED. Other states are
#: restored as-is. The Risk Manager is never re-occupied via ``start_bot()``.
RESTART_STATE_MAP: dict[BotState, BotState] = {
    BotState.RUNNING: BotState.ERROR,
    BotState.STARTING: BotState.ERROR,
    BotState.STOP_REQUESTED: BotState.STOPPED,
}


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
        strategy_loader: Any | None = None,
        trading_engine_factory: Any | None = None,
        market_context_provider: Any | None = None,
    ) -> None:
        self.bot_id = bot_id
        self._risk_manager = risk_manager
        self._submit_cb = submit_cb
        self._order_manager = order_manager
        self._state = state
        # MVP-6.7 strategy path (all optional; production wires all):
        #   strategy_loader: () -> Awaitable[BotStrategy]
        #       loads this bot's immutable, validated strategy version;
        #   trading_engine_factory: (BotStrategy) -> Awaitable[TradingEngine]
        #       builds this bot's own TradingEngine (per-bot StrategyConfig);
        #   market_context_provider: (BotStrategy) -> Awaitable[MarketContext]
        #       (MVP-6.10) builds the live broker-neutral MarketContext for
        #       this bot's own timeframe from real market data; a missing or
        #       invalid snapshot fails the cycle explicitly (no fabricated
        #       market data).
        self._strategy_loader = strategy_loader
        self._trading_engine_factory = trading_engine_factory
        self._market_context_provider = market_context_provider
        self._strategy: BotStrategy | None = None
        self._trading_engine: TradingEngine | None = None

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def running(self) -> bool:
        return self._state is BotState.RUNNING

    @property
    def strategy(self) -> BotStrategy | None:
        """This bot's immutable, validated strategy (set on a successful START)."""
        return self._strategy

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

    async def start(self) -> None:
        """Transition STOPPED/ERROR -> RUNNING.

        When a strategy loader is wired, the bot's own immutable strategy is
        loaded and validated first, and its per-bot TradingEngine is composed;
        only then is the Risk Manager start guard consulted, so a failed
        strategy load never occupies a concurrent-bot slot. Any failure
        transitions the bot to ERROR and re-raises.
        """
        self._transition(BotState.STARTING)
        try:
            if self._strategy_loader is not None:
                self._strategy = await self._strategy_loader()
                if self._trading_engine_factory is not None:
                    self._trading_engine = await self._trading_engine_factory(
                        self._strategy
                    )
            if not self._risk_manager.check_start(self.bot_id):
                raise BotStartRejected(
                    f"bot {self.bot_id} start rejected by risk manager"
                )
            self._risk_manager.start_bot(self.bot_id)
        except Exception:
            self._transition(BotState.ERROR)
            raise
        self._transition(BotState.RUNNING)

    async def stop(self) -> None:
        """Normal stop: block new intents, cancel active orders, leave position open.

        Order: RUNNING -> STOP_REQUESTED -> cancel active bot orders ->
        ``RiskManager.stop_bot()`` -> STOPPED. The ``max_concurrent_bots`` slot
        stays occupied while order cancellation is in progress. A failed
        cancellation leaves the bot in ERROR; the Risk Manager slot is released
        only after that lifecycle transition (no fake RUNNING/STOPPED).
        """
        if self._state is BotState.STOPPED:
            return
        self._transition(BotState.STOP_REQUESTED)
        try:
            await self._cancel_active_orders()
        except Exception:
            self._transition(BotState.ERROR)
            self._risk_manager.stop_bot(self.bot_id)
            raise
        self._risk_manager.stop_bot(self.bot_id)
        self._transition(BotState.STOPPED)

    async def emergency_stop(self) -> None:
        """Emergency stop: block new intents and cancel active bot orders.

        The Risk Manager slot is always released on completion (even if
        cancellation fails); the bot remains in EMERGENCY_STOP, so execution
        stays blocked and the position is never closed automatically.
        """
        self._transition(BotState.EMERGENCY_STOP)
        try:
            await self._cancel_active_orders()
        finally:
            self._risk_manager.stop_bot(self.bot_id)

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

    async def execute_strategy(self, context: MarketContext | None = None) -> Plan:
        """Evaluate this bot's strategy and submit the resulting intents.

        The |MarketContext| is an explicit broker-neutral input (no fabricated
        market data). When no explicit context is given, this bot's
        market-context provider is used (MVP-6.10): a live broker-neutral
        snapshot for the bot's own configured timeframe, built from real
        market data. A missing provider/strategy or a missing/invalid snapshot
        fails the processing cycle explicitly (no fabricated market data, no
        implicit default). Evaluation and all intent submissions go through
        the bot's own TradingEngine, so the Risk Manager is always
        authoritative before the Order Manager. Only RUNNING bots may execute
        their strategy.
        """
        if not self.can_submit():
            raise BotStateError(
                f"bot {self.bot_id} cannot execute its strategy in state "
                f"{self._state.value}"
            )
        if self._trading_engine is None:
            raise RuntimeError(
                f"bot {self.bot_id} has no strategy execution path wired"
            )
        if context is None:
            if self._market_context_provider is None:
                raise RuntimeError(
                    f"bot {self.bot_id} was called without an explicit market "
                    "context and has no market-context source wired"
                )
            if self._strategy is None:
                raise RuntimeError(
                    f"bot {self.bot_id} has no loaded strategy for the "
                    "market-context source"
                )
            context = await self._market_context_provider(self._strategy)
        return await self._trading_engine.process(context)

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

    def restore_state(self, bot_id: int, state: BotState) -> BotRuntime:
        """Register (or keep) a runtime at an explicit restored state.

        Used by :meth:`restore_persisted_states`; never starts the Risk Manager.
        """
        runtime = self._runtimes.get(bot_id)
        if runtime is None:
            if self._runtime_factory is None:
                raise KeyError(f"no bot runtime registered for bot {bot_id}")
            runtime = self._runtime_factory(bot_id, state)
            self._runtimes[bot_id] = runtime
        return runtime

    async def restore_persisted_states(self, repository: Any) -> None:
        """Reconcile runtime state with persisted bot states after a restart.

        Semantics: persisted RUNNING/STARTING bots were interrupted by the
        process restart and are restored in ERROR (execution blocked until an
        explicit START); persisted STOP_REQUESTED is restored as STOPPED; other
        states are restored as-is. The Risk Manager is never re-occupied via
        ``start_bot()``. The DB is synced to the restored state via the
        repository, so persisted and runtime states cannot contradict.
        """
        for bot in await repository.list():
            try:
                persisted = BotState(bot.status)
            except ValueError:
                persisted = BotState.STOPPED
            restored = RESTART_STATE_MAP.get(persisted, persisted)
            self.restore_state(bot.id, restored)
            if restored != persisted:
                await repository.update_state(bot, restored)

    async def start(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        await runtime.start()
        return runtime

    async def stop(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        await runtime.stop()
        return runtime

    async def emergency_stop(self, bot_id: int) -> BotRuntime:
        runtime = self._get_or_create(bot_id)
        await runtime.emergency_stop()
        return runtime
