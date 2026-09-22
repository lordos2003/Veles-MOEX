"""TInvestAdapter unit tests (mocked client, no real token/network)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers import (
    AccountNotFoundError,
    AuthenticationError,
    InstrumentNotFoundError,
    InvalidRequestError,
    ResourceNotFoundError,
    TInvestAdapter,
)
from app.brokers.base import BrokerOrderRequest
from app.brokers.tinvest import _quotation_to_decimal
from app.domain.marketdata import Timeframe
from app.models.enums import OrderSide, OrderStatus, OrderType
from tests.fakes import TInvestFakeClient

_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
_GET_INSTRUMENT = "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
_LAST_PRICE = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"
_CANDLES = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
_PORTFOLIO = "tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio"
_GET_ORDERS = "tinkoff.public.invest.api.contract.v1.OrdersService/GetOrders"
_OPERATIONS = "tinkoff.public.invest.api.contract.v1.OperationsService/GetOperationsByCursor"


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
async def test_place_order_requires_account_context() -> None:
    adapter = TInvestAdapter(client=TInvestFakeClient())
    request = BrokerOrderRequest(
        instrument_figi="BBG004730N88", side=OrderSide.BUY, quantity=1, type=OrderType.MARKET
    )
    with pytest.raises(InvalidRequestError):
        await adapter.place_order(request)


def test_quotation_to_decimal() -> None:
    assert _quotation_to_decimal({"units": "114", "nano": 250000000}) == Decimal("114.25")
    assert _quotation_to_decimal(None) is None


@pytest.mark.asyncio
async def test_get_open_positions_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF"}]},
            _PORTFOLIO: {
                "totalAmountPortfolio": {"currency": "RUB", "units": "3000", "nano": 0},
                "totalAmountCurrencies": {"currency": "RUB", "units": "1000", "nano": 0},
                "positions": [
                    {
                        "figi": "BBG004730N88",
                        "ticker": "SBER",
                        "instrumentType": "share",
                        "quantity": {"units": "10", "nano": 0},
                        "averagePositionPrice": {"currency": "RUB", "units": "280", "nano": 0},
                        "currentPrice": {"currency": "RUB", "units": "300", "nano": 0},
                    }
                ],
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    positions = await adapter.get_open_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.account_id == "acc-1"
    assert p.instrument_figi == "BBG004730N88"
    assert p.quantity == Decimal("10")
    assert p.average_price == Decimal("280")
    assert p.current_price == Decimal("300")
    assert p.current_value == Decimal("3000")
    assert p.unrealized_pnl == Decimal("200")
    assert p.currency == "RUB"


@pytest.mark.asyncio
async def test_get_orders_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF"}]},
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "ord-1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
                        "lotsRequested": 10,
                        "lotsExecuted": 10,
                        "figi": "BBG004730N88",
                        "ticker": "SBER",
                        "direction": "ORDER_DIRECTION_BUY",
                        "orderType": "ORDER_TYPE_LIMIT",
                        "initialSecurityPrice": {"currency": "RUB", "units": "300", "nano": 0},
                        "currency": "RUB",
                        "orderDate": "2025-01-01T10:00:00Z",
                        "stages": [{"executionTime": "2025-01-01T10:05:00Z"}],
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    orders = await adapter.get_orders()
    assert len(orders) == 1
    order = orders[0]
    assert order.order_id == "ord-1"
    assert order.status == OrderStatus.FILLED
    assert order.type == OrderType.LIMIT
    assert order.side == OrderSide.BUY
    assert order.requested_quantity == Decimal("10")
    assert order.executed_quantity == Decimal("10")
    assert order.price == Decimal("300")
    assert order.created_at is not None
    assert order.updated_at is not None


@pytest.mark.asyncio
async def test_get_deals_normalized() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF"}]},
            _OPERATIONS: {
                "items": [
                    {
                        "id": "op-1",
                        "figi": "BBG004730N88",
                        "type": "OPERATION_TYPE_BUY",
                        "quantity": 10,
                        "quantityDone": 10,
                        "price": {"currency": "RUB", "units": "300", "nano": 0},
                        "payment": {"currency": "RUB", "units": "-3000", "nano": 0},
                        "commission": {"currency": "RUB", "units": "0", "nano": 100000000},
                        "date": "2025-01-01T10:00:00Z",
                    }
                ],
                "hasNext": False,
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    deals = await adapter.get_deals()
    assert len(deals) == 1
    deal = deals[0]
    assert deal.deal_id == "op-1"
    assert deal.instrument_figi == "BBG004730N88"
    assert deal.side == OrderSide.BUY
    assert deal.quantity == Decimal("10")
    assert deal.price == Decimal("300")
    assert deal.commission == Decimal("0.1")
    assert deal.happened_at is not None


@pytest.mark.asyncio
async def test_get_orders_maps_unknown_status_to_unknown() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "o1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_UNSPECIFIED",
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    orders = await adapter.get_orders()
    assert orders[0].status == OrderStatus.UNKNOWN
