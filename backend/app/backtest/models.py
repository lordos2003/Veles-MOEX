"""Backtest result objects.

These are in-memory, deterministic, broker-agnostic summaries. The history is
replayable from a |BacktestConfig|; ``deals`` is per trading round-trip while
``orders`` / ``executions`` are the underlying broker-order / fill records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.brokers.base import BrokerDeal, BrokerOrder
from app.strategies.config import Direction


@dataclass
class BacktestDeal:
    """One closed round-trip trade."""

    deal_id: str
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    duration: timedelta
    executed_orders: int
    reason: str = ""

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0


@dataclass
class BacktestResult:
    """Aggregate result of a backtest run."""

    initial_capital: Decimal
    final_capital: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    roi: Decimal
    total_fees: Decimal
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    average_trade: Decimal
    average_duration: Decimal
    max_drawdown: Decimal
    deals: list[BacktestDeal] = field(default_factory=list)
    orders: list[BrokerOrder] = field(default_factory=list)
    executions: list[BrokerDeal] = field(default_factory=list)
