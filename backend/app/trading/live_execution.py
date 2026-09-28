"""Live execution composition / startup gate (MVP-6.3).

``LiveExecutionService`` is the production composition root that wires the
durable store, the broker-neutral managers and the recovery coordinator
together. On startup it runs ``recover()``; live execution is only allowed once
recovery returns ``SAFE``. When recovery returns ``BLOCKED``, ``submit()`` is
refused so unsafe new execution cannot resume.
"""

from __future__ import annotations

from decimal import Decimal

from app.trading.bot_lifecycle import BotRuntimeManager, BotStateError
from app.trading.domain import ExecutionIntent, InternalOrder
from app.trading.engine import TradingEngine
from app.trading.market_context import (
    MarketContextUnavailable,
    build_market_context,
    build_market_snapshot_context,
)
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.recovery import LiveRecoveryCoordinator, RecoveryResult
from app.trading.risk_manager import RiskLimits, RiskManager
from app.trading.state import LiveStateStore


class LiveExecutionBlocked(RuntimeError):
    """Raised when live execution is attempted before a safe recovery."""


class LiveExecutionService:
    """Gates live execution behind a successful startup/recovery reconciliation."""

    def __init__(
        self,
        broker,
        store: LiveStateStore,
        order_manager: OrderManager,
        position_manager: PositionManager,
        account_id: str | None = None,
        transport=None,
        *,
        risk_manager: RiskManager | None = None,
        trading_engine: TradingEngine | None = None,
        bot_runtime_manager: BotRuntimeManager | None = None,
        market_data: object | None = None,
    ) -> None:
        self._broker = broker
        self._order_manager = order_manager
        self._coordinator = LiveRecoveryCoordinator(
            store, order_manager, position_manager, broker
        )
        self._account_id = account_id
        self._safe = False
        self._session_owner = None
        self._stream_transport = transport
        self._stream_manager = None
        self._market_data = market_data
        self._risk_manager = risk_manager or RiskManager(position_manager=position_manager)
        self._trading_engine = trading_engine or TradingEngine(
            broker, None, order_manager, position_manager, self._risk_manager
        )
        self._bot_runtime_manager = bot_runtime_manager

    async def build_context(self, instrument_figi: str):
        """Construct a last-price-only live MarketContext from broker data.

        Uses the wired ``MarketDataService``-like provider (if any); raises
        |MarketContextUnavailable| when no usable live price is available. The
        per-bot strategy-cycle path (snapshot + per-bot timeframe) goes
        through the bot runtime's market-context provider (MVP-6.10, see
        ``build_live_service``).
        """
        if self._market_data is None:
            raise MarketContextUnavailable(
                "no market-data source is wired into the live service"
            )
        return await build_market_context(self._market_data, instrument_figi)

    @property
    def can_execute(self) -> bool:
        """True once a SAFE recovery has completed."""
        return self._safe

    @property
    def bot_runtime(self) -> BotRuntimeManager | None:
        """The bot lifecycle manager wired into this service (may be None)."""
        return self._bot_runtime_manager

    @property
    def coordinator(self) -> LiveRecoveryCoordinator:
        return self._coordinator

    async def start(self) -> RecoveryResult:
        """Run reconciliation and gate execution according to its outcome."""
        account_id = self._account_id
        if account_id is None:
            accounts = await self._broker.get_accounts()
            if not accounts:
                raise LiveExecutionBlocked("no broker account available for recovery")
            account_id = accounts[0].account_id
        self._account_id = account_id
        result = await self._coordinator.recover(account_id)
        self._safe = result.safe
        if result.safe:
            await self._trading_engine.start()
        return result

    async def submit(self, intent: ExecutionIntent) -> InternalOrder:
        """Submit an intent only after a SAFE recovery, through the Risk gate.

        When a bot lifecycle is wired, submission is additionally gated on the
        owning bot being in RUNNING (the authoritative upstream control layer).
        """
        if not self._safe:
            raise LiveExecutionBlocked("live execution blocked until recovery succeeds")
        if self._bot_runtime_manager is not None:
            if intent.bot_id is None:
                raise BotStateError(
                    "live submit requires a bot_id while the bot lifecycle is enabled"
                )
            runtime = self._bot_runtime_manager.get(intent.bot_id)
            if runtime is None:
                raise BotStateError(f"no bot runtime for bot {intent.bot_id}")
            return await runtime.submit_intent(intent)
        return await self._trading_engine.submit_intent(intent)

    def build_stream_manager(self, transport):
        """Compose an OrderStateStream manager whose reconnect runs full recovery.

        On reconnect the stream manager runs unary recovery, then this recovery
        hook (durable reconciliation); live events are dispatched only when it is
        SAFE, otherwise they are paused.
        """
        from app.brokers.tinvest_streams import TInvestStreamManager

        return TInvestStreamManager(
            self._broker,
            transport,
            self._order_manager,
            self._account_id,
            recovery=self._stream_recovery,
        )

    async def _stream_recovery(self) -> bool:
        """Full recovery used as the reconnect gate. Returns True when SAFE."""
        account_id = self._account_id
        if account_id is None:
            accounts = await self._broker.get_accounts()
            account_id = accounts[0].account_id if accounts else None
        result = await self._coordinator.recover(account_id)
        self._safe = result.safe
        return result.safe

    async def run_stream_forever(self) -> None:
        """Run the production OrderStateStream live runtime until :meth:`shutdown`.

        Creates the T-Invest WebSocket transport (unless injected) and runs the
        stream manager, whose reconnect path already runs unary recovery then the
        full durable recovery gate before dispatching live events.
        """
        if not self._safe:
            raise LiveExecutionBlocked(
                "cannot start live stream before a SAFE recovery"
            )
        if self._stream_transport is None:
            self._stream_transport = await self._build_transport()
        self._stream_manager = self.build_stream_manager(self._stream_transport)
        await self._stream_manager.run()

    async def shutdown(self) -> None:
        """Stop the live stream and close the session/transport."""
        await self._trading_engine.stop()
        if self._stream_manager is not None:
            self._stream_manager.stop()
        if self._stream_transport is not None:
            try:
                await self._stream_transport.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
        session = self._session_owner
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    async def _build_transport(self):
        from app.brokers.tinvest_stream_transport import build_stream_transport
        from app.core.config import get_settings

        settings = get_settings()
        return build_stream_transport(
            settings.tinvest_stream_url, settings.tinvest_token
        )


def risk_limits_from_settings(settings) -> RiskLimits:
    """Map typed application settings to RiskManager limits.

    Only explicitly configured values are applied; unset values stay ``None``
    (check disabled) and empty blocklists stay ``None`` (no restriction). No
    financial defaults are invented.
    """
    return RiskLimits(
        max_position_size=(
            Decimal(str(settings.risk_max_position_size))
            if settings.risk_max_position_size is not None
            else None
        ),
        max_concurrent_bots=settings.risk_max_concurrent_bots,
        daily_loss_limit=(
            Decimal(str(settings.risk_daily_loss_limit))
            if settings.risk_daily_loss_limit is not None
            else None
        ),
        blocked_instruments=(
            frozenset(settings.risk_blocked_instruments)
            if settings.risk_blocked_instruments
            else None
        ),
    )


async def build_live_service() -> LiveExecutionService:
    """Compose a live execution service from application settings.

    Uses the configured T-Invest adapter and the SQLAlchemy-backed durable state
    store. The caller owns the returned service; ``shutdown()`` closes the
    underlying session.

    Strategy path (MVP-6.7): each bot runtime loads **its own** immutable
    StrategyVersion (validated into a ``StrategyConfig``) on START and gets its
    own ``TradingEngine`` (shared broker-neutral ``StrategyEngine`` instances,
    per-bot ``StrategyConfig``). Strategy evaluation is triggered by
    ``BotRuntime.execute_strategy(MarketContext)``; the ``MarketContext`` is
    an explicit broker-neutral input — built by the bot runtime's
    market-context provider from real broker-neutral market data (MVP-6.10) or
    supplied explicitly — and no market data is ever fabricated. Plan items
    are converted to ``ExecutionIntent``s by ``plan_to_intents`` at the
    orchestration boundary (DCA/Grid orders only; entry signals and exit plans
    are explicit boundaries — see ``app.trading.plan_intent``). Every intent is
    risk-gated: ``RiskManager`` is always consulted before ``OrderManager``.

    Startup bot-state sync: persisted bot states are restored into the runtime
    manager so DB and runtime never contradict. Persisted RUNNING/STARTING bots
    are restored in ERROR (blocked until an explicit START); STOP_REQUESTED is
    restored as STOPPED. The Risk Manager is never re-occupied implicitly.

    Risk limits (MVP-6.6) come from the typed application settings
    (``risk_*`` environment variables) via ``risk_limits_from_settings``;
    unset values leave the corresponding check disabled. The instrument
    trading-status dependency is NOT wired here: instrument status is stored in
    PostgreSQL behind the async ``InstrumentService`` while the execution gate
    is synchronous, so the check is explicitly unavailable in production
    (documented boundary, no fabricated values).

    Per-bot risk configuration limitation: ``StrategyConfig.risk`` is NOT
    copied into the global Risk Manager; the execution Risk Manager uses the
    application settings only (documented boundary, no precedence invented).

    Market-context / sizing boundary (MVP-6.8): a broker-neutral
    ``MarketDataService`` is wired into the service and a live MarketContext is
    built via ``build_market_context()`` from the real last price (no fabricated
    prices/candles/timestamps). No authoritative position-sizing
    source exists yet, so the per-bot ``TradingEngine`` is created without a
    sizing source and ``process()`` blocks live strategy execution with
    ``SizingNotConfigured`` until a sizing source is configured.

    Position quantity boundary (MVP-6.9): the wired ``PositionManager`` is the
    only authoritative source of live execution quantity. The per-bot
    ``TradingEngine`` is given its ``instrument_figi`` so ``process()`` can
    resolve the real exit quantity via ``PositionManager.resolve_quantity``;
    the old ``position_qty=1.0`` placeholder is removed from the live path. The
    authoritative positions are reconciled from the broker-neutral adapter
    (``get_open_positions``) during recovery; the broker is never queried inside
    the strategy/exit/trading layers.

    Market snapshot / per-bot timeframe (MVP-6.10): the bot runtime's
    market-context provider builds the live MarketContext for a strategy cycle
    from the bot's own configured timeframe
    (``StrategyConfig.timeframe``) and the explicitly configured snapshot
    lookback (``StrategyConfig.lookback_bars``) via
    ``MarketDataService.get_snapshot`` ->
    ``build_market_snapshot_context``. The Strategy path stays broker-neutral:
    T-Invest-specific mapping remains inside ``TInvestAdapter``; prices stay
    ``Decimal`` and timestamps timezone-aware UTC. No global runtime timeframe
    or implicit default exists: a missing timeframe fails the cycle with
    ``TimeframeNotConfigured``, a missing explicit lookback fails the cycle
    with ``LookbackNotConfigured`` (no lookback is inferred from indicator
    periods/shifts — the Veles documentation defines no universal
    warmup/history rule), and a missing/invalid snapshot blocks live intent
    creation (``MarketDataUnavailable``). The MVP-6.9 position-state invariant
    is preserved (unresolved position state still blocks all live intents);
    Backtest semantics are untouched.
    """
    from app.bots.repository import BotRepository
    from app.bots.strategy import (
        BotStrategy,
        StrategyLoadError,
        load_bot_strategy_by_id,
    )
    from app.brokers import TInvestAdapter
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.enums import BotState
    from app.models.instrument import Instrument
    from app.persistence.execution_state import SqlAlchemyLiveStateStore
    from app.services.market_data import MarketDataService
    from app.strategies.domain import MarketContext, Plan
    from app.trading.bot_lifecycle import BotRuntime
    from app.trading.engine import compose_strategy_engine
    from app.trading.plan_intent import plan_to_intents

    broker = TInvestAdapter()
    session = SessionLocal()
    store = SqlAlchemyLiveStateStore(session)
    order_manager = OrderManager(broker)
    position_manager = order_manager.positions()
    risk_manager = RiskManager(
        limits=risk_limits_from_settings(get_settings()),
        position_manager=position_manager,
    )
    trading_engine = TradingEngine(
        broker, None, order_manager, position_manager, risk_manager
    )
    strategy_engine = compose_strategy_engine()
    bot_repository = BotRepository(session)
    market_data = MarketDataService(broker)

    async def _submit_cb(intent: ExecutionIntent) -> InternalOrder:
        return await trading_engine.submit_intent(intent)

    def _make_runtime(bot_id: int, state: BotState = BotState.STOPPED) -> BotRuntime:
        async def _load_strategy() -> BotStrategy:
            return await load_bot_strategy_by_id(session, bot_id)

        async def _make_market_context(bot_strategy: BotStrategy) -> MarketContext:
            # MVP-6.10: the live MarketContext for this bot's strategy cycle is
            # built from the bot's own configured timeframe and the explicitly
            # configured snapshot lookback (lookback_bars) via the broker-
            # neutral MarketDataService. A missing timeframe, a missing
            # explicit lookback, or a missing/invalid snapshot fails the cycle
            # explicitly (no fabricated market data, no implicit defaults, no
            # lookback inferred from indicator semantics).
            bot = await bot_repository.get(bot_id)
            if bot is None:
                raise StrategyLoadError(f"bot {bot_id} not found")
            instrument = await session.get(Instrument, bot.instrument_id)
            if instrument is None:
                raise StrategyLoadError(
                    f"bot {bot_id} references missing instrument "
                    f"{bot.instrument_id}"
                )
            return await build_market_snapshot_context(
                market_data, instrument.figi, bot_strategy.config
            )

        async def _make_bot_engine(bot_strategy: BotStrategy) -> TradingEngine:
            bot = await bot_repository.get(bot_id)
            if bot is None:
                raise StrategyLoadError(f"bot {bot_id} not found")
            instrument = await session.get(Instrument, bot.instrument_id)
            if instrument is None:
                raise StrategyLoadError(
                    f"bot {bot_id} references missing instrument "
                    f"{bot.instrument_id}"
                )
            account = await session.get(Account, bot.account_id)

            def _intent_factory(
                plan: Plan, context: MarketContext
            ) -> list[ExecutionIntent]:
                return plan_to_intents(
                    plan,
                    instrument_figi=instrument.figi,
                    bot_id=bot_id,
                    account_id=(
                        account.external_account_id if account is not None else None
                    ),
                )

            engine = TradingEngine(
                broker,
                strategy_engine,
                order_manager,
                position_manager,
                risk_manager,
                strategy_config=bot_strategy.config,
                intent_factory=_intent_factory,
                instrument_figi=instrument.figi,
                # MVP-6.8/6.9 boundary: no authoritative position-sizing source is
                # wired for a bot yet, so `sizing` stays None and
                # `TradingEngine.process()` blocks live strategy execution with
                # SizingNotConfigured until a sizing source is configured. No
                # default (100 / 1.0) is used. The authoritative exit quantity
                # comes from the wired PositionManager (MVP-6.9), never a
                # placeholder.
            )
            await engine.start()
            return engine

        return BotRuntime(
            bot_id,
            risk_manager,
            submit_cb=_submit_cb,
            order_manager=order_manager,
            state=state,
            strategy_loader=_load_strategy,
            trading_engine_factory=_make_bot_engine,
            market_context_provider=_make_market_context,
        )

    bot_runtime_manager = BotRuntimeManager(risk_manager, runtime_factory=_make_runtime)
    await bot_runtime_manager.restore_persisted_states(bot_repository)

    service = LiveExecutionService(
        broker,
        store,
        order_manager,
        position_manager,
        risk_manager=risk_manager,
        trading_engine=trading_engine,
        bot_runtime_manager=bot_runtime_manager,
        market_data=market_data,
    )
    service._session_owner = session
    return service
