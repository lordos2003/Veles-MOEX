"""Backtest Engine.

Backtest reuses the same Strategy/Trading Engine as Live, but drives execution
through |BacktestBroker| instead of a live broker adapter.

Backtest execution is not implemented yet; this defines the interface and the
wiring contract.
"""

from __future__ import annotations

from app.trading.engine import TradingEngine


class BacktestEngine:
    """Runs a strategy over historical data via the shared Trading Engine."""

    def __init__(self, trading_engine: TradingEngine) -> None:
        # The injected Trading Engine must be wired to a BacktestBroker so it
        # shares the same Strategy/Trading logic as Live.
        self.trading_engine = trading_engine

    def run(self, config: object, data_source: object) -> object:
        """Execute the backtest and return a result object.

        Full backtest pipeline (data load, modeling, statistics) is MVP-3.
        """
        raise NotImplementedError("Backtest execution is not implemented yet")
