"""BacktestBroker.

Implements the same |BrokerAdapter| interface so that the Backtest engine can
reuse the exact same Strategy/Trading Engine as Live (Architecture & Product
Specification section 11). It must model commissions, order types, partial
fills, DCA, TP, multi-take, signal TP, stop-loss, break-even, slippage,
quantity/lot/tick constraints, trading sessions and instrument rules.

Backtest fill modeling is not implemented yet; methods raise
``NotImplementedError`` until the BacktestBroker is built (MVP-3).
"""

from __future__ import annotations

from datetime import datetime

from app.brokers import (
    BrokerAccount,
    BrokerAdapter,
    BrokerDeal,
    BrokerInstrument,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
)
from app.domain.marketdata import Candle, LastPrice, Timeframe


class BacktestBroker(BrokerAdapter):
    """BrokerAdapter implementation backed by historical data."""

    async def connect(self) -> None:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def close(self) -> None:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_accounts(self) -> list[BrokerAccount]:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_account(self, account_id: str | None = None) -> BrokerAccount:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_instruments(self, kind: str | None = None) -> list[BrokerInstrument]:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_instrument(self, figi: str) -> BrokerInstrument:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_last_price(self, figi: str) -> LastPrice:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_candles(
        self,
        figi: str,
        timeframe: Timeframe,
        from_: datetime,
        to: datetime,
        limit: int | None = None,
    ) -> list[Candle]:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_orders(self, account_id: str | None = None) -> list[BrokerOrder]:
        raise NotImplementedError("Backtest broker is not implemented yet")

    async def get_deals(self, account_id: str | None = None) -> list[BrokerDeal]:
        raise NotImplementedError("Backtest broker is not implemented yet")
