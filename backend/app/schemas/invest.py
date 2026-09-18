"""Pydantic schemas for the T-Invest / market data REST API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class TInvestStatusResponse(BaseModel):
    status: Literal["not_configured", "connected", "disconnected", "error"]
    message: str


class PositionResponse(BaseModel):
    figi: str
    ticker: str | None = None
    instrument_type: str | None = None
    quantity: Decimal
    average_price: Decimal


class AccountInfoResponse(BaseModel):
    account_id: str
    currency: str = "RUB"
    available_cash: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    name: str | None = None
    account_type: str | None = None
    status: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    positions: list[PositionResponse] = []


class InstrumentResponse(BaseModel):
    figi: str
    ticker: str | None = None
    name: str | None = None
    instrument_type: str | None = None
    currency: str | None = None
    lot_size: int | None = None
    tick_size: Decimal | None = None
    trading_status: str = "TRADING_AVAILABLE"
    exchange: str | None = None
    is_active: bool = True


class SyncResponse(BaseModel):
    synced: int


class LastPriceResponse(BaseModel):
    figi: str
    ticker: str | None = None
    price: Decimal
    timestamp: datetime | None = None


class CandleResponse(BaseModel):
    figi: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    is_complete: bool | None = None
