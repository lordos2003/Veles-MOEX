"""Trading Engine (broker-neutral orchestration).

The Trading Engine pairs a Strategy Engine with execution components (Order
Manager, Position Manager, Risk Manager) and a BrokerAdapter. Live uses
TInvestAdapter; Backtest uses BacktestBroker — both implement BrokerAdapter, so
Live and Backtest share one Trading Engine (Architecture & Product Specification
section 11).

`process()` is the authoritative orchestration seam: it evaluates the strategy
plan, then routes execution through the Risk Manager before sending an intent to
the Order Manager. The Risk Manager is never bypassed. T-Invest is never imported
here; financial decisions come only from the Strategy/Risk configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from app.brokers import BrokerAdapter
from app.domain.marketdata import Timeframe
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading.domain import TERMINAL_STATES, ExecutionIntent
from app.trading.market_context import TimeframeNotConfigured
from app.trading.order_manager import OrderManager
from app.trading.position_manager import (
    InvalidPositionQuantity,
    LivePositionState,
    PositionManager,
    PositionUnavailable,
)
from app.trading.risk_manager import RiskManager
from app.trading.sizing import (
    PositionSizing,
    SizingNotConfigured,
    round_grid_to_lot,
)


def compose_strategy_engine() -> StrategyEngine:
    """Production composition of the broker-neutral Strategy Engine.

    Constructs the existing Entry / DCA-Grid / Exit engines around a
    ``StrategyEngine`` without altering their calculations. No broker code is
    imported; the composed engine remains broker-neutral.
    """
    return StrategyEngine(
        entry=EntryEngine(), dca_grid=DCAGridEngine(), exit_engine=ExitEngine()
    )


class TradingEngine:
    """Orchestrates strategy evaluation and risk-gated broker execution."""

    def __init__(
        self,
        broker: BrokerAdapter,
        strategy_engine: StrategyEngine,
        order_manager: OrderManager,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        *,
        strategy_config=None,
        intent_factory: (
            Callable[[Plan, MarketContext], ExecutionIntent | list[ExecutionIntent] | None]
            | None
        ) = None,
        sizing: PositionSizing | None = None,
        instrument_figi: str | None = None,
        bot_id: int | None = None,
    ) -> None:
        self.broker = broker
        self.strategy_engine = strategy_engine
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self._strategy_config = strategy_config
        self._intent_factory = intent_factory
        self._sizing = sizing
        self._instrument_figi = instrument_figi
        # The owning bot, used to correlate active (non-terminal) orders for the
        # MVP-6.11 C4 FLAT-entry precondition.
        self._bot_id = bot_id
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def strategy_configured(self) -> bool:
        """Whether the Strategy -> TradingEngine path is wired (engine + config)."""
        return self.strategy_engine is not None and self._strategy_config is not None

    async def start(self) -> None:
        """Begin processing.

        The live runtime already manages the broker connection, so the engine
        does not open a second broker connection here (no fictitious behavior).
        """
        self._started = True

    async def stop(self) -> None:
        """Stop processing."""
        self._started = False

    async def submit_intent(self, intent: ExecutionIntent):
        """Risk-gated submission of a pre-built execution intent."""
        if not self._started:
            raise RuntimeError("TradingEngine is not started")
        self.risk_manager.check_order(intent)  # raises RiskRejected on violation
        return await self.order_manager.submit(intent)

    async def process(self, context: MarketContext) -> Plan:
        """Evaluate the strategy and route execution through the Risk Manager.

        This is the integration seam for the Strategy -> TradingEngine ->
        RiskManager -> OrderManager pipeline. It requires a StrategyEngine, a
        strategy config and an explicit sizing source; a missing sizing source
        raises |SizingNotConfigured| so live execution is blocked until a sizing
        source is configured (no fabricated order quantity). Production live
        execution goes through :meth:`submit_intent` and must not invoke this
        with ``None``.

        ``intent_factory`` may return a single intent, a list of intents, or
        None; every returned intent is submitted through :meth:`submit_intent`,
        so the Risk Manager is always consulted before the Order Manager.

        Live per-bot engines (``instrument_figi`` set) additionally require a
        per-bot timeframe in the strategy config (a missing one raises
        |TimeframeNotConfigured|) and a non-empty bar series for that timeframe
        in the market context. The live position state (MVP-6.11 C4, established
        only by a successful broker reconciliation and kept by fills) governs
        which intents may be created:

        - UNKNOWN / SIGN_MISMATCH: **no** live ExecutionIntent at all for this
          cycle (the MVP-6.9 blocking behavior is preserved);
        - FLAT: entry only — the grid built from the current snapshot, rounded
          down to whole lots (C3, |SizingBelowLot| blocks the whole entry when
          any level rounds to 0 lots), submitted only when the bot has no
          active (non-terminal) orders; no exit intents;
        - OPEN: exits only (real quantity via |PositionManager.resolve_quantity|);
          no new grid/entry intents from a fresh evaluation (deal continuation /
          grid state persistence is out of scope).
        """
        if not self._started:
            raise RuntimeError("TradingEngine is not started")
        if not self.strategy_configured:
            raise RuntimeError(
                "TradingEngine.process() requires a StrategyEngine and a strategy "
                "config; the live execution path uses submit_intent() instead"
            )
        if self._sizing is None:
            raise SizingNotConfigured(
                "TradingEngine.process() requires an explicit position-sizing "
                "source to build a safe live order quantity"
            )
        base_nominal = self._sizing.resolve_base_nominal(self._strategy_config.dca_grid)
        timeframe = self._require_live_timeframe()
        position_state = self._live_position_state()
        position_qty = self._exit_position_quantity()
        plan = self.strategy_engine.evaluate(
            self._strategy_config,
            context,
            base_nominal=base_nominal,
            position_qty=position_qty,
        )
        if self._position_gates_execution(position_state):
            return plan
        if self._snapshot_gates_execution(context, timeframe):
            return plan
        if position_state is LivePositionState.FLAT:
            if self._entry_blocked_by_active_orders():
                return plan
            plan.grid = round_grid_to_lot(
                plan.grid,
                lot_size=self._sizing.lot_size,
                currency=self._sizing.currency,
            )
            plan.exits = []
        elif position_state is LivePositionState.OPEN:
            plan.grid = []
        if self._intent_factory is not None:
            result = self._intent_factory(plan, context)
            if result is not None:
                intents = result if isinstance(result, (list, tuple)) else [result]
                for intent in intents:
                    await self.submit_intent(intent)
        return plan

    def _position_gates_execution(self, position_state: LivePositionState | None) -> bool:
        """Whether the live position state must block all live intents (C4).

        For a live per-bot engine (``instrument_figi`` set), the PositionManager
        is the only authoritative quantity source. UNKNOWN (never reconciled,
        reconciliation failed, or stale) and SIGN_MISMATCH block **all** live
        ExecutionIntents for this processing cycle (MVP-6.9 behavior preserved:
        no position / zero / sign-mismatch => no live order at all). FLAT and
        OPEN are permitted states, governed further by the entry/exit rules in
        :meth:`process`. Generic/Backtest engines (no ``instrument_figi``) are
        not gated here.
        """
        if self._instrument_figi is None:
            return False
        return position_state not in (
            LivePositionState.FLAT,
            LivePositionState.OPEN,
        )

    def _live_position_state(self) -> LivePositionState | None:
        """The live position state for this engine's instrument (C4), or None
        for a generic/Backtest engine (no ``instrument_figi``)."""
        if self._instrument_figi is None:
            return None
        return self.position_manager.position_state(
            self._instrument_figi, self._strategy_config.direction
        )

    def _entry_blocked_by_active_orders(self) -> bool:
        """Whether a FLAT entry must be blocked for this cycle (MVP-6.11 C4).

        Entry from FLAT is allowed only if the bot has **no active
        (non-terminal) orders** in the OrderManager; otherwise the bot would
        re-enter on every cycle while a limit first order or grid is still
        working. When the bot cannot be correlated (no ``bot_id``), the
        precondition cannot be verified and the entry is blocked (no
        fabricated safety assumption).
        """
        if self._bot_id is None:
            return True
        return any(
            order.bot_id == self._bot_id and order.status not in TERMINAL_STATES
            for order in self.order_manager.list_orders()
        )

    def _require_live_timeframe(self) -> Timeframe | None:
        """Enforce the per-bot timeframe for a live strategy cycle (MVP-6.10).

        Returns the configured timeframe, or ``None`` for a generic/Backtest
        engine (no ``instrument_figi``; no live timeframe requirement). A live
        per-bot engine without a configured timeframe raises
        |TimeframeNotConfigured|: the processing cycle fails explicitly, no
        global runtime timeframe or implicit production default is substituted.
        """
        if self._instrument_figi is None:
            return None
        timeframe = self._strategy_config.timeframe
        if timeframe is None:
            raise TimeframeNotConfigured(
                "live strategy cycle requires a per-bot timeframe in the "
                "strategy configuration (no implicit default)"
            )
        return timeframe

    def _snapshot_gates_execution(self, context: MarketContext, timeframe) -> bool:
        """Whether a missing/invalid market snapshot must block all live intents.

        For a live per-bot engine, the market context must carry a non-empty
        bar series for the bot's own configured timeframe: a missing or empty
        snapshot blocks **all** live ExecutionIntent creation/submission for
        this cycle. Generic/Backtest engines (``timeframe is None``) are not
        gated here.
        """
        if timeframe is None:
            return False
        snapshot = context.snapshot
        if snapshot is None:
            return True
        series = snapshot.get(timeframe)
        return series is None or not series.bars

    def _exit_position_quantity(self) -> Decimal | None:
        """Resolve the authoritative live exit quantity from the PositionManager.

        The PositionManager is the only authoritative quantity source: the broker
        is never queried here. The quantity is resolved only for the OPEN live
        position state (MVP-6.11 C4); every other state yields ``None`` (no
        position / zero / sign-mismatch / unknown), which also makes
        :meth:`_position_gates_execution` block **all** live intents for this
        cycle. The broker-neutral domain errors are caught and mapped to ``None``.
        """
        if self._instrument_figi is None:
            return None
        if self._live_position_state() is not LivePositionState.OPEN:
            return None
        try:
            return self.position_manager.resolve_quantity(
                self._instrument_figi, self._strategy_config.direction
            )
        except (PositionUnavailable, InvalidPositionQuantity):
            return None
