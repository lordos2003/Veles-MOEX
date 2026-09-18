"""Trading Engine.

The Trading Engine pairs a Strategy Engine with broker/execution components
(Order Manager, Position Manager, Risk Manager) and a BrokerAdapter. Live uses
TInvestAdapter; Backtest uses BacktestBroker — both implement BrokerAdapter, so
Live and Backtest share one Trading Engine (Architecture & Product Specification
section 11).

Trading logic is not implemented yet; this defines the orchestration seams.
"""

from __future__ import annotations

from app.brokers import BrokerAdapter
from app.strategies.domain import MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.risk_manager import RiskManager


class TradingEngine:
    """Orchestrates strategy evaluation and broker execution."""

    def __init__(
        self,
        broker: BrokerAdapter,
        strategy_engine: StrategyEngine,
        order_manager: OrderManager,
        position_manager: PositionManager,
        risk_manager: RiskManager,
    ) -> None:
        self.broker = broker
        self.strategy_engine = strategy_engine
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.risk_manager = risk_manager

    async def start(self) -> None:
        """Connect to the broker and begin processing."""
        raise NotImplementedError("Trading engine start is not implemented yet")

    async def stop(self) -> None:
        """Stop processing and disconnect."""
        raise NotImplementedError("Trading engine stop is not implemented yet")

    async def process(self, context: MarketContext) -> Plan:
        """Evaluate the strategy and route the resulting plan to execution."""
        raise NotImplementedError("Trading engine processing is not implemented yet")
