"""TInvestAdapter unit tests (mocked client, no real token/network)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers import (
    AccountNotFoundError,
    AuthenticationError,
    InstrumentNotFoundError,
    ResourceNotFoundError,
    TInvestAdapter,
)
from app.brokers.base import BrokerOrderRequest
from app.brokers.tinvest import _quotation_to_decimal
from app.domain.marketdata import Timeframe
from app.models.enums import OrderSide, OrderType
from tests.fakes import TInvestFakeClient

_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
_GET_INSTRUMENT = "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
_LAST_PRICE = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"
_CANDLES = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"


def _accounts_response() -> dict:
    return {
        "accounts": [
            {
                "id": "acc-1",
                "type": "ACCOUNT_TYPE_TINKOFF",
                "name": "Main account",
                "status": "ACCOUNT_STATUS_OPEN",
                "openedDate": "2021-01-01T00:00:00Z",
            }
        ]
    }


def test_adapter_not_configured_raises_on_use() -> None:
    adapter = TInvestAdapter()  # no token (settings default is None)
    assert adapter.is_configured is False
    with pytest.raises(AuthenticationError):
        __import__("asyncio").run(adapter.connect())


@pytest.mark.asyncio
async def test_connect_validates_token() -> None:
    fake = TInvestFakeClient(responses={_GET_ACCOUNTS: _accounts_response()})
    adapter = TInvestAdapter(client=fake)
    assert adapter.is_configured is True
    await adapter.connect()
    assert fake.calls[0][0] == _GET_ACCOUNTS


@pytest.mark.asyncio
async def test_get_accounts_normalized() -> None:
    fake = TInvestFakeClient(responses={_GET_ACCOUNTS: _accounts_response()})
    adapter = TInvestAdapter(client=fake)
    accounts = await adapter.get_accounts()
    assert len(accounts) == 1
    account = accounts[0]
    assert account.account_id == "acc-1"
    assert account.name == "Main account"
    assert account.status == "ACCOUNT_STATUS_OPEN"
    assert account.opened_at is not None


@pytest.mark.asyncio
async def test_get_instrument_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_INSTRUMENT: {
                "instrument": {
                    "figi": "BBG004730N88",
                    "ticker": "SBER",
                    "name": "Sberbank",
                    "currency": "RUB",
                    "lot": 10,
                    "instrumentType": "share",
                    "apiTradeAvailableFlag": True,
                    "minPriceIncrement": {"units": "1", "nano": 0},
                }
            }
        }
    )
    adapter = TInvestAdapter(client=fake)
    instrument = await adapter.get_instrument("BBG004730N88")
    assert instrument.figi == "BBG004730N88"
    assert instrument.ticker == "SBER"
    assert instrument.lot_size == 10
    assert instrument.tick_size == _quotation_to_decimal({"units": "1", "nano": 0})
    assert instrument.is_active is True


@pytest.mark.asyncio
async def test_get_instrument_not_found_maps_to_instrument_error() -> None:
    fake = TInvestFakeClient(errors={_GET_INSTRUMENT: ResourceNotFoundError("not found")})
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InstrumentNotFoundError):
        await adapter.get_instrument("BBG004730N88")


@pytest.mark.asyncio
async def test_get_last_price_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _LAST_PRICE: {
                "lastPrices": [
                    {
                        "figi": "BBG004730N88",
                        "ticker": "SBER",
                        "price": {"units": "300", "nano": 500000000},
                        "time": "2025-01-01T00:00:00Z",
                    }
                ]
            }
        }
    )
    adapter = TInvestAdapter(client=fake)
    price = await adapter.get_last_price("BBG004730N88")
    assert price.price == _quotation_to_decimal({"units": "300", "nano": 500000000})
    assert price.ticker == "SBER"


@pytest.mark.asyncio
async def test_get_candles_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _CANDLES: {
                "candles": [
                    {
                        "open": {"units": "100", "nano": 0},
                        "high": {"units": "110", "nano": 0},
                        "low": {"units": "95", "nano": 0},
                        "close": {"units": "108", "nano": 0},
                        "volume": 1200,
                        "time": "2025-01-01T10:00:00Z",
                        "isComplete": True,
                    }
                ]
            }
        }
    )
    adapter = TInvestAdapter(client=fake)
    candles = await adapter.get_candles(
        "BBG004730N88",
        Timeframe.HOUR_1,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 2, tzinfo=UTC),
    )
    assert len(candles) == 1
    candle = candles[0]
    assert candle.open == _quotation_to_decimal({"units": "100", "nano": 0})
    assert candle.close == _quotation_to_decimal({"units": "108", "nano": 0})
    assert candle.volume == 1200
    assert candle.is_complete is True


@pytest.mark.asyncio
async def test_account_not_found_with_no_accounts() -> None:
    fake = TInvestFakeClient(responses={_GET_ACCOUNTS: {"accounts": []}})
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(AccountNotFoundError):
        await adapter.get_account()


@pytest.mark.asyncio
async def test_authentication_failure_propagates() -> None:
    fake = TInvestFakeClient(errors={_GET_ACCOUNTS: AuthenticationError("bad token")})
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(AuthenticationError):
        await adapter.connect()


@pytest.mark.asyncio
async def test_trading_methods_still_not_implemented() -> None:
    adapter = TInvestAdapter(client=TInvestFakeClient())
    request = BrokerOrderRequest(
        instrument_figi="BBG004730N88", side=OrderSide.BUY, quantity=1, type=OrderType.MARKET
    )
    with pytest.raises(NotImplementedError):
        await adapter.place_order(request)


def test_quotation_to_decimal() -> None:
    assert _quotation_to_decimal({"units": "114", "nano": 250000000}) == Decimal("114.25")
    assert _quotation_to_decimal(None) is None
