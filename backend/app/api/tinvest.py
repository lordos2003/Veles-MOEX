"""Read-only T-Invest + market data REST endpoints.

Instruments go through the internal InstrumentService (PostgreSQL); market data
goes through the internal MarketDataService (broker -> normalized DTOs). All
T-Invest specifics stay inside TInvestAdapter. Errors map to HTTP codes via the
global handler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_broker_adapter, get_instrument_service, get_market_data_service
from app.brokers import (
    AccountNotFoundError,
    BrokerAccount,
    BrokerAdapter,
    BrokerPosition,
    InstrumentNotFoundError,
    InvalidRequestError,
    TInvestError,
)
from app.domain.instrument import InstrumentType
from app.domain.marketdata import Candle, LastPrice, Timeframe
from app.models.instrument import Instrument
from app.schemas.invest import (
    AccountInfoResponse,
    CandleResponse,
    InstrumentResponse,
    LastPriceResponse,
    PositionResponse,
    SyncResponse,
    TInvestStatusResponse,
)
from app.services.instruments import InstrumentService
from app.services.market_data import MarketDataService

router = APIRouter(tags=["tinvest"])


@router.get("/tinvest/status", response_model=TInvestStatusResponse)
async def tinvest_status(
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> TInvestStatusResponse:
    """Probe T-Invest connectivity/authentication."""
    if not broker.is_configured:
        return TInvestStatusResponse(
            status="not_configured", message="T-Invest API token is not configured"
        )
    try:
        await broker.connect()
        return TInvestStatusResponse(status="connected", message="T-Invest API connected")
    except TInvestError as exc:
        return TInvestStatusResponse(status="error", message=str(exc))


@router.get("/accounts", response_model=list[AccountInfoResponse])
async def list_accounts(
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> list[AccountInfoResponse]:
    """List broker accounts."""
    accounts = await broker.get_accounts()
    return [_account_to_schema(acc) for acc in accounts]


@router.get("/accounts/{account_id}", response_model=AccountInfoResponse)
async def account_info(
    account_id: str,
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
) -> AccountInfoResponse:
    """Return account summary (cash/equity) and its positions."""
    try:
        account = await broker.get_account(account_id)
    except AccountNotFoundError:
        raise
    positions = await broker.get_open_positions(account_id)
    return _account_to_schema(account, positions)


# --- Instruments (via internal InstrumentService / PostgreSQL) ---


@router.get("/instruments", response_model=list[InstrumentResponse])
async def list_instruments(
    instrument_service: Annotated[InstrumentService, Depends(get_instrument_service)],
    type_: Annotated[InstrumentType | None, Query(alias="type")] = None,
    active: Annotated[bool | None, Query()] = None,
    ticker: Annotated[str | None, Query()] = None,
) -> list[InstrumentResponse]:
    """List instruments, filtered by type / active / ticker."""
    instruments = await instrument_service.list(type_=type_, active=active, ticker=ticker)
    return [_instrument_to_schema(item) for item in instruments]


@router.get("/instruments/{figi}", response_model=InstrumentResponse)
async def instrument_by_figi(
    figi: str,
    instrument_service: Annotated[InstrumentService, Depends(get_instrument_service)],
) -> InstrumentResponse:
    """Return instrument details by FIGI."""
    instrument = await instrument_service.get_by_figi(figi)
    if instrument is None:
        raise InstrumentNotFoundError(f"Instrument not found: {figi}")
    return _instrument_to_schema(instrument)


@router.post("/instruments/sync", response_model=SyncResponse)
async def sync_instruments(
    instrument_service: Annotated[InstrumentService, Depends(get_instrument_service)],
    broker: Annotated[BrokerAdapter, Depends(get_broker_adapter)],
    kind: Annotated[str, Query()] = "share",
) -> SyncResponse:
    """Synchronize instruments from the broker into PostgreSQL."""
    count = await instrument_service.sync_from_broker(broker, kind)
    return SyncResponse(synced=count)


# --- Market data (via internal MarketDataService) ---


@router.get("/market-data/{figi}/last-price", response_model=LastPriceResponse)
async def last_price(
    figi: str,
    market_data: Annotated[MarketDataService, Depends(get_market_data_service)],
) -> LastPriceResponse:
    """Return the last trade price for an instrument."""
    price = await market_data.get_last_price(figi)
    return _last_price_to_schema(price)


@router.get("/market-data/{figi}/candles", response_model=list[CandleResponse])
async def candles(
    figi: str,
    timeframe: Annotated[str, Query(description="1m/5m/15m/30m/1h/4h/1d/1w/1mo")],
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    market_data: Annotated[MarketDataService, Depends(get_market_data_service)],
) -> list[CandleResponse]:
    """Return historical OHLCV candles (normalized, sorted, de-duplicated)."""
    tf = _map_timeframe(timeframe)
    candles_data = await market_data.get_candles(figi, tf, from_, to)
    return [_candle_to_schema(item) for item in candles_data]


# --- converters ---


def _account_to_schema(
    account: BrokerAccount, positions: list[BrokerPosition] | None = None
) -> AccountInfoResponse:
    return AccountInfoResponse(
        account_id=account.account_id,
        currency=account.currency,
        available_cash=account.available_cash,
        equity=account.equity,
        name=account.name,
        account_type=account.account_type,
        status=account.status,
        opened_at=account.opened_at,
        closed_at=account.closed_at,
        positions=[
            PositionResponse(
                figi=position.instrument_figi,
                quantity=position.quantity,
                average_price=position.average_price,
            )
            for position in (positions or [])
        ],
    )


def _instrument_to_schema(item: Instrument) -> InstrumentResponse:
    return InstrumentResponse(
        figi=item.figi,
        ticker=item.ticker,
        name=item.name,
        instrument_type=item.instrument_type,
        currency=item.currency,
        lot_size=item.lot_size,
        tick_size=item.tick_size,
        trading_status=item.trading_status or "TRADING_AVAILABLE",
        exchange=item.exchange,
        is_active=item.is_active if item.is_active is not None else True,
    )


def _last_price_to_schema(item: LastPrice) -> LastPriceResponse:
    return LastPriceResponse(
        figi=item.figi,
        ticker=item.ticker,
        price=item.price,
        timestamp=item.timestamp,
    )


def _candle_to_schema(item: Candle) -> CandleResponse:
    return CandleResponse(
        figi=item.figi,
        timeframe=item.timeframe.value,
        timestamp=item.timestamp,
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=item.volume,
        is_complete=item.is_complete,
    )


def _map_timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError as exc:
        raise InvalidRequestError(f"Unsupported timeframe: {value}") from exc
