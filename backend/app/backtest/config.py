"""Backtest configuration.

The backtest is deterministic and fully described by this configuration. Running
the engine with the same inputs reproduces the exact same result.

T-Invest is not referenced here; the strategy is a broker-agnostic
``StrategyConfig`` and market data is the domain ``Candle`` model.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.marketdata import Candle, Timeframe
from app.strategies.config import StrategyConfig


class BacktestConfig(BaseModel):
    """Inputs that fully describe a deterministic backtest run."""

    strategy: StrategyConfig
    instrument_figi: str
    timeframe: Timeframe
    candles: list[Candle] = Field(default_factory=list)
    # Reproducibility anchor: the immutable strategy version this run references.
    strategy_version_id: int | None = None
    # MVP-7.0 R8 deposit path. When ``deposit`` is set, the entry quantity and
    # the whole DCA grid are derived from it via the live sizing functions
    # (deposit_to_base_nominal C2 + round_grid_to_lot C3, app/trading/sizing.py);
    # ``lot_size`` / ``currency`` come from the instrument. Unset fields keep the
    # legacy ``quantity``-driven behavior unchanged.
    deposit: Decimal | None = None
    lot_size: int | None = None
    currency: str | None = None
    initial_capital: Decimal = Decimal("10000")
    quantity: Decimal = Decimal("1")
    maker_fee: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    account_id: str = "backtest"
