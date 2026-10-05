"""API schemas for the backtest endpoint (MVP-7.0 R7/R8).

The request accepts either an immutable strategy version or an inline
``StrategyConfig`` (exactly one). Fee, slippage and deposit values are required
explicitly — no financial default is ever invented for an API call. The
response mirrors the in-memory |BacktestResult| (summary, deals with ``reason``,
orders and executions); nothing is persisted in MVP-7.0.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.marketdata import Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.strategies.config import Direction, StrategyConfig


class BacktestRequest(BaseModel):
    """Synchronous backtest run request."""

    model_config = ConfigDict(populate_by_name=True)

    strategy_version_id: int | None = Field(
        default=None, description="Immutable strategy version to reproduce"
    )
    config: StrategyConfig | None = Field(
        default=None, description="Inline strategy configuration (alternative to version)"
    )
    instrument_id: int = Field(description="Local instrument id (table `instruments`)")
    timeframe: Timeframe = Field(description="Candle timeframe of the run")
    from_: datetime = Field(alias="from", description="Period start (UTC, inclusive)")
    to: datetime = Field(description="Period end (UTC, exclusive)")
    deposit: Decimal = Field(gt=0, description="Deal deposit; grid sized from it (R8)")
    maker_fee: Decimal = Field(ge=0, description="Maker commission, fraction (e.g. 0.0003)")
    taker_fee: Decimal = Field(ge=0, description="Taker commission, fraction")
    slippage: Decimal = Field(ge=0, description="Price slippage, fraction")

    @model_validator(mode="after")
    def _exactly_one_strategy_source(self) -> BacktestRequest:
        if (self.strategy_version_id is None) == (self.config is None):
            raise ValueError(
                "exactly one of 'strategy_version_id' or 'config' must be provided"
            )
        return self


class BacktestDealResponse(BaseModel):
    """One closed round-trip trade of the run."""

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
    duration_seconds: float
    executed_orders: int
    reason: str = ""


class BacktestExecutionResponse(BaseModel):
    """A broker-agnostic settled execution of the run (``BrokerDeal``)."""

    deal_id: str
    instrument_figi: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    account_id: str | None = None
    order_id: str | None = None
    commission: Decimal = Decimal("0")
    currency: str | None = None
    happened_at: datetime | None = None


class BacktestOrderResponse(BaseModel):
    """A backtest broker order."""

    order_id: str
    status: OrderStatus
    account_id: str | None = None
    instrument_figi: str | None = None
    type: OrderType | None = None
    side: OrderSide | None = None
    requested_quantity: Decimal = Decimal("0")
    executed_quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    executed_average_price: Decimal | None = None
    currency: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reject_info: str | None = None


class BacktestResponse(BaseModel):
    """Synchronous run result (in-memory, not persisted)."""

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
    deals: list[BacktestDealResponse] = Field(default_factory=list)
    orders: list[BacktestOrderResponse] = Field(default_factory=list)
    executions: list[BacktestExecutionResponse] = Field(default_factory=list)
