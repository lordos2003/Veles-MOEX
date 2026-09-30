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

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING

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
from app.trading.position_manager import LivePositionState, PositionManager
from app.trading.risk_manager import RiskManager
from app.trading.sizing import (
    PositionSizing,
    SizingNotConfigured,
    round_grid_to_lot,
)

if TYPE_CHECKING:  # pragma: no cover - type-only import (no runtime cycle)
    from app.trading.deal_manager import DealManager


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
        deposit_provider: Callable[[], Awaitable[Decimal | None]] | None = None,
        # MVP-6.12 D2/D6: when wired, the FLAT live entry opens a persisted
        # Deal through the DealManager instead of submitting the grid intents
        # directly, and the OPEN live path creates no exit intents at all
        # (the take-profit belongs to the Deal).
        deal_manager: DealManager | None = None,
        tick_size: Decimal | None = None,
        account_id: str | None = None,
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
        # MVP-6.11 C6: broker-neutral async deposit source read at each FLAT
        # entry (per-bot production wiring reads ``Bot.deposit`` from the
        # repository), so a deposit edit applies from the next deal.
        self._deposit_provider = deposit_provider
        self._deal_manager = deal_manager
        self._tick_size = tick_size
        self._account_id = account_id
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

        Entry sizing is an **entry-only** precondition (review B1): the
        deposit -> base-nominal conversion (C2) is resolved on the FLAT live
        entry path (and for a generic engine without a live position state).
        OPEN / UNKNOWN / SIGN_MISMATCH never read the deposit or the grid mode.
        On the FLAT path the deposit is read at the moment of the entry (C6) via
        the wired async ``deposit_provider``; a deposit edit therefore applies
        from the next deal and never affects an open deal.

        Live deal continuation (MVP-6.12 D2/D6): a live per-bot engine with a
        wired ``deal_manager`` opens a persisted Deal from the FLAT entry (the
        whole grid is built by the DealManager from the same snapshot price,
        lot- and tick-rounded, and persisted before any order is submitted);
        the plan's own grid/exit items are not submitted from here. In OPEN the
        engine creates **no** exit intents at all: the take-profit is owned by
        the Deal (re-armed by the DealManager on every grid fill), and the
        old "exits priced from the market snapshot" path is gone (D6).

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
          active (non-terminal) orders; with a ``deal_manager`` the entry opens
          a Deal instead (D2) and no exit intents are created;
        - OPEN: no new grid/entry intents and **no exit intents** from a fresh
          evaluation (D6) — a deal continuation (open Deal manager wired) keeps
          working its existing grid and its Deal-owned take-profit.
        """
        if not self._started:
            raise RuntimeError("TradingEngine is not started")
        if not self.strategy_configured:
            raise RuntimeError(
                "TradingEngine.process() requires a StrategyEngine and a strategy "
                "config; the live execution path uses submit_intent() instead"
            )
        timeframe = self._require_live_timeframe()
        position_state = self._live_position_state()
        # MVP-6.12 D6: for a live per-bot engine the OPEN path must NOT create
        # exit intents from the strategy evaluation — the take-profit is owned
        # by the Deal (D4). ``position_qty`` stays ``None`` so ``evaluate``
        # never builds market-price-priced exits; the generic/Backtest path is
        # unchanged (it passed ``None`` already).
        position_qty: Decimal | None = None
        deposit, base_nominal = await self._entry_deposit_and_nominal(position_state)
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
            if self._deal_manager is not None:
                # MVP-6.12 D2: the DealManager opens (and persists before
                # submitting) the whole grid once; the plan items are not
                # submitted from here to avoid a second entry.
                await self._submit_live_deal(plan, context, deposit, base_nominal)
                plan.grid = []
                plan.exits = []
                return plan
            plan.grid = round_grid_to_lot(
                plan.grid,
                lot_size=self._sizing.lot_size,
                currency=self._sizing.currency,
            )
            plan.exits = []
        elif position_state is LivePositionState.OPEN:
            # D6: no new grid/entry intents from a fresh evaluation; exits are
            # Deal-owned (never re-created from the market snapshot).
            plan.grid = []
            plan.exits = []
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

    async def _entry_deposit_and_nominal(
        self, position_state: LivePositionState | None
    ) -> tuple[Decimal | None, Decimal | None]:
        """The C6 deposit and C2 base nominal, resolved only on entry (B1).

        Entry sizing (deposit -> base nominal, C2/C3) is an **entry-only**
        precondition: it is resolved on the FLAT live entry path, and for a
        generic engine without a live position state (where it is the only
        source of grid quantity). OPEN / UNKNOWN / SIGN_MISMATCH yield
        ``(None, None)`` — open-deal logic never depends on the deposit or the
        grid mode (B1/C6).

        On the FLAT path the deposit is read at the moment of the entry (C6):
        when a broker-neutral async ``deposit_provider`` is wired (production
        reads ``Bot.deposit`` from the repository once per entry), the latest
        value is used, so a deposit edit applies from the next deal and an
        already open deal is unaffected. Without a provider the static sizing
        source is used (tests / generic engines).
        """
        if self._instrument_figi is None:
            # Generic engine (no live position state): the sizing source remains
            # the only grid quantity source (MVP-6.8 behavior, unchanged).
            if self._sizing is None:
                raise SizingNotConfigured(
                    "TradingEngine.process() requires an explicit position-sizing "
                    "source to build a safe live order quantity"
                )
            return (
                self._sizing.deposit,
                self._sizing.resolve_base_nominal(self._strategy_config.dca_grid),
            )
        if position_state is not LivePositionState.FLAT:
            return None, None
        if self._sizing is None:
            raise SizingNotConfigured(
                "TradingEngine.process() requires an explicit position-sizing "
                "source to build a safe live order quantity"
            )
        if self._deposit_provider is not None:
            deposit = await self._deposit_provider()
            sizing = PositionSizing(
                base_nominal=self._sizing.base_nominal,
                deposit=deposit,
                lot_size=self._sizing.lot_size,
                currency=self._sizing.currency,
            )
            return deposit, sizing.resolve_base_nominal(self._strategy_config.dca_grid)
        return (
            self._sizing.deposit,
            self._sizing.resolve_base_nominal(self._strategy_config.dca_grid),
        )

    async def _submit_live_deal(
        self,
        plan: Plan,
        context: MarketContext,
        deposit: Decimal | None,
        base_nominal: Decimal | None,
    ) -> None:
        """MVP-6.12 D2: open a Deal from a FLAT entry through the DealManager.

        The DealManager builds the whole grid from the same snapshot reference
        price the Strategy Engine used, applies lot/tick rounding to **every**
        level (D3; any failure blocks the whole entry) and persists the Deal
        before submitting any order (D2). The deposit captured here is the C6
        entry-time value and ``base_nominal`` is the C2 conversion already
        resolved by the engine.
        """
        if plan.entry is None or base_nominal is None:
            # No entry signal (or nothing sized) — no deal is opened and no
            # fabricated one is created (same guard as the grid plan).
            return
        reference_price = self.strategy_engine.entry_price(self._strategy_config, context)
        if reference_price <= 0:
            return
        await self._deal_manager.open_deal(
            bot_id=self._bot_id,
            instrument_figi=self._instrument_figi,
            direction=self._strategy_config.direction,
            config=self._strategy_config,
            reference_price=reference_price,
            deposit=deposit,
            base_nominal=base_nominal,
            account_id=self._account_id,
            lot_size=self._sizing.lot_size if self._sizing is not None else None,
            tick_size=self._tick_size,
        )
