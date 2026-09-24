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

from app.brokers import BrokerAdapter
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading.domain import ExecutionIntent
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager
from app.trading.sizing import PositionSizing, SizingNotConfigured


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
    ) -> None:
        self.broker = broker
        self.strategy_engine = strategy_engine
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self._strategy_config = strategy_config
        self._intent_factory = intent_factory
        self._sizing = sizing
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
        base_nominal = self._sizing.resolve_base_nominal()
        plan = self.strategy_engine.evaluate(
            self._strategy_config, context, base_nominal=base_nominal
        )
        if self._intent_factory is not None:
            result = self._intent_factory(plan, context)
            if result is not None:
                intents = result if isinstance(result, (list, tuple)) else [result]
                for intent in intents:
                    await self.submit_intent(intent)
        return plan
