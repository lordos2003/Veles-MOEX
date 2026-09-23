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
from app.strategies.domain import MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.trading.domain import ExecutionIntent
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager


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
        intent_factory: Callable[[Plan, MarketContext], ExecutionIntent | None] | None = None,
    ) -> None:
        self.broker = broker
        self.strategy_engine = strategy_engine
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self._strategy_config = strategy_config
        self._intent_factory = intent_factory
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

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
        RiskManager -> OrderManager pipeline. It requires a StrategyEngine and a
        strategy config; production live execution goes through
        :meth:`submit_intent` and must not invoke this with ``None``.
        """
        if not self._started:
            raise RuntimeError("TradingEngine is not started")
        if self.strategy_engine is None or self._strategy_config is None:
            raise RuntimeError(
                "TradingEngine.process() requires a StrategyEngine and a strategy "
                "config; the live execution path uses submit_intent() instead"
            )
        plan = self.strategy_engine.evaluate(self._strategy_config, context)
        if plan.entry is not None and self._intent_factory is not None:
            intent = self._intent_factory(plan, context)
            if intent is not None:
                await self.submit_intent(intent)
        return plan
