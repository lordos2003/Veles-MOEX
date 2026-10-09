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
from app.brokers.base import BrokerOrderRequest, BrokerStopOrderRequest, StopOrderStatus
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
_STOP_ORDERS = "tinkoff.public.invest.api.contract.v1.StopOrdersService"


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
                    # P8 (MVP-7.3): real sandbox sample of a MOEX share.
                    "realExchange": "REAL_EXCHANGE_MOEX",
                    "exchange": "moex_morning_weekend",
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
    # P8: MOEX enum -> displayable exchange label; raw schedule value is not
    # shown verbatim anywhere.
    assert instrument.real_exchange == "REAL_EXCHANGE_MOEX"
    assert instrument.exchange == "MOEX"


@pytest.mark.asyncio
async def test_to_instrument_keeps_raw_exchange_for_non_moex() -> None:
    # P8 (MVP-7.3): a foreign/SPB-listed paper (real sandbox sample — CK
    # Hutchison-class hkd share from SPBHKEX) must NOT be relabelled "MOEX":
    # the display label follows the RealExchange enum only.
    instrument = TInvestAdapter._to_instrument(
        {
            "figi": "BBG0013B4HH5",
            "ticker": "CKC",
            "name": "CK Hutchison Holdings",
            "currency": "HKD",
            "lot": 10,
            "instrumentType": "share",
            "apiTradeAvailableFlag": False,
            "realExchange": "REAL_EXCHANGE_RTS",
            "exchange": "unknown",
        },
        "share",
    )
    assert instrument.real_exchange == "REAL_EXCHANGE_RTS"
    assert instrument.exchange == "unknown"
    assert instrument.is_active is False


@pytest.mark.asyncio
async def test_to_instrument_maps_first_candle_dates() -> None:
    # MVP-7.6 (H2): the broker's earliest-history facts (instruments.proto
    # fields 56/57) map to the broker-neutral DTO; absent -> None, nothing is
    # substituted. The REST gateway serializes proto fields as camelCase
    # (first1minCandleDate — verified against the live sandbox response).
    instrument = TInvestAdapter._to_instrument(
        {
            "figi": "BBG004730N88",
            "ticker": "SBER",
            "realExchange": "REAL_EXCHANGE_MOEX",
            "first1minCandleDate": "2020-02-07T00:00:00Z",
            "first1dayCandleDate": "1998-01-01T00:00:00Z",
        },
        "share",
    )
    assert instrument.first_1min_candle_date == datetime(2020, 2, 7, tzinfo=UTC)
    assert instrument.first_1day_candle_date == datetime(1998, 1, 1, tzinfo=UTC)

    bare = TInvestAdapter._to_instrument(
        {"figi": "F1", "realExchange": "REAL_EXCHANGE_MOEX"}, "share"
    )
    assert bare.first_1min_candle_date is None
    assert bare.first_1day_candle_date is None


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
            _GET_INSTRUMENT: {
                "instrument": {"figi": "BBG004730N88", "lot": 10, "instrumentType": "share"}
            },
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
                        "stages": [
                            {
                                "executionTime": "2025-01-01T10:05:00Z",
                                "tradeId": "trade-1",
                                "quantity": 10,
                                "price": {"currency": "RUB", "units": "300", "nano": 0},
                            }
                        ],
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
    # lots are normalized to canonical units (10 lots * lot_size 10 = 100 units)
    assert order.requested_quantity == Decimal("100")
    assert order.executed_quantity == Decimal("100")
    assert order.price == Decimal("300")
    assert order.executed_average_price == Decimal("300")
    assert len(order.executions) == 1
    assert order.executions[0].execution_id == "trade-1"
    assert order.executions[0].quantity == Decimal("100")
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


@pytest.mark.asyncio
async def test_executed_average_price_from_stages_not_initial() -> None:
    """Blocker 2: executed average price comes from stages, not initial order price."""
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_INSTRUMENT: {
                "instrument": {"figi": "BBG004730N88", "lot": 1, "instrumentType": "share"}
            },
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "o1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
                        "lotsRequested": 10,
                        "lotsExecuted": 10,
                        "figi": "BBG004730N88",
                        "direction": "ORDER_DIRECTION_BUY",
                        "orderType": "ORDER_TYPE_LIMIT",
                        "initialSecurityPrice": {"units": "100", "nano": 0},
                        "currency": "RUB",
                        "stages": [
                            {"tradeId": "t1", "quantity": 6, "price": {"units": "110", "nano": 0}},
                            {"tradeId": "t2", "quantity": 4, "price": {"units": "130", "nano": 0}},
                        ],
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    order = (await adapter.get_orders())[0]
    assert order.price == Decimal("100")  # initial/limit order price
    assert order.executed_average_price == Decimal("118")  # (110*6 + 130*4)/10
    assert len(order.executions) == 2
    assert order.executions[0].execution_id == "t1"


@pytest.mark.asyncio
async def test_operation_to_deals_correlates_broker_order() -> None:
    """Blocker 3: BrokerDeal carries the real broker order id when available."""
    item = {
        "id": "op-1",
        "figi": "BBG004730N88",
        "type": "OPERATION_TYPE_BUY",
        "quantity": 10,
        "quantityDone": 10,
        "price": {"units": "300", "nano": 0},
        "commission": {"units": "0", "nano": 100000000},
        "orderId": "order-9",
    }
    deals = TInvestAdapter._operation_to_deals(item, "acc-1")
    assert len(deals) == 1
    assert deals[0].deal_id == "op-1"
    assert deals[0].order_id == "order-9"
    assert deals[0].instrument_figi == "BBG004730N88"


@pytest.mark.asyncio
async def test_lot_size_unavailable_blocks_order_normalization() -> None:
    """Final 2: missing lot size must raise, never return false canonical units."""
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "o1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
                        "lotsRequested": 10,
                        "lotsExecuted": 10,
                        "figi": "BBG004730N88",
                        "direction": "ORDER_DIRECTION_BUY",
                        "orderType": "ORDER_TYPE_LIMIT",
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.get_orders()


@pytest.mark.asyncio
async def test_order_without_figi_but_quantity_rejected() -> None:
    """Final: an order with quantity but no FIGI cannot be normalized to units."""
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "o1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
                        "lotsRequested": 5,
                        "lotsExecuted": 0,
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.get_orders()


def test_to_order_has_no_silent_lot_fallback() -> None:
    """The adapter must not fall back to a factor of 1 for a missing lot size."""
    import inspect

    src = inspect.getsource(TInvestAdapter._to_order)
    assert 'factor = Decimal("1")' not in src


@pytest.mark.asyncio
async def test_zero_quantity_no_figi_order_returns_zero_units() -> None:
    """A zero-quantity, no-FIGI order maps to zero canonical units (no fallback)."""
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_ORDERS: {
                "orders": [
                    {
                        "orderId": "o1",
                        "executionReportStatus": "EXECUTION_REPORT_STATUS_NEW",
                    }
                ]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    order = (await adapter.get_orders())[0]
    assert order.requested_quantity == Decimal("0")
    assert order.executed_quantity == Decimal("0")
    assert order.executions == []


# --- MVP-6.16: stop orders -------------------------------------------------


def _stop_fake(**extra) -> TInvestFakeClient:
    responses = {
        _GET_ACCOUNTS: {"accounts": [{"id": "acc-1", "type": "ACCOUNT_TYPE_TINKOFF"}]},
        _GET_INSTRUMENT: {
            "instrument": {"figi": "BBG004730N88", "lot": 10, "instrumentType": "share"}
        },
    }
    responses.update(extra)
    return TInvestFakeClient(responses=responses)


@pytest.mark.asyncio
async def test_place_stop_order_posts_stop_loss_market_body() -> None:
    import re

    fake = _stop_fake(
        **{f"{_STOP_ORDERS}/PostStopOrder": {"stopOrderId": "stop-1"}}
    )
    adapter = TInvestAdapter(client=fake)
    stop = await adapter.place_stop_order(
        BrokerStopOrderRequest(
            instrument_figi="BBG004730N88",
            side=OrderSide.SELL,
            quantity=Decimal("30"),
            stop_price=Decimal("80"),
            account_id="acc-1",
        )
    )
    path, body = fake.calls[-1]
    assert path == f"{_STOP_ORDERS}/PostStopOrder"
    assert body["instrumentId"] == "BBG004730N88"
    assert body["quantity"] == 3  # canonical 30 units / lot 10
    assert body["stopPrice"] == {"units": "80", "nano": 0}
    assert body["direction"] == "ORDER_DIRECTION_SELL"
    assert body["accountId"] == "acc-1"
    assert body["expirationType"] == "STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL"
    assert body["stopOrderType"] == "STOP_ORDER_TYPE_STOP_LOSS"
    assert body["exchangeOrderType"] == "EXCHANGE_ORDER_TYPE_MARKET"
    assert re.fullmatch(r"[0-9a-f-]{36}", body["orderId"]) is not None
    assert stop.order_id == "stop-1"
    assert stop.status is StopOrderStatus.ACTIVE
    assert stop.quantity == Decimal("30")
    assert stop.stop_price == Decimal("80")


@pytest.mark.asyncio
async def test_place_stop_order_rejects_non_lot_multiple() -> None:
    fake = _stop_fake()
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.place_stop_order(
            BrokerStopOrderRequest(
                instrument_figi="BBG004730N88",
                side=OrderSide.SELL,
                quantity=Decimal("15"),  # not a multiple of lot 10
                stop_price=Decimal("80"),
                account_id="acc-1",
            )
        )


@pytest.mark.asyncio
async def test_place_stop_order_requires_account_context() -> None:
    adapter = TInvestAdapter(client=_stop_fake())
    with pytest.raises(InvalidRequestError):
        await adapter.place_stop_order(
            BrokerStopOrderRequest(
                instrument_figi="BBG004730N88",
                side=OrderSide.SELL,
                quantity=Decimal("30"),
                stop_price=Decimal("80"),
            )
        )


@pytest.mark.asyncio
async def test_cancel_stop_order_posts_account_and_stop_id() -> None:
    fake = _stop_fake()
    adapter = TInvestAdapter(client=fake)
    await adapter.cancel_stop_order("stop-1", account_id="acc-1")
    path, body = fake.calls[-1]
    assert path == f"{_STOP_ORDERS}/CancelStopOrder"
    assert body == {"accountId": "acc-1", "stopOrderId": "stop-1"}


@pytest.mark.asyncio
async def test_cancel_stop_order_requires_account_context() -> None:
    adapter = TInvestAdapter(client=_stop_fake())
    with pytest.raises(InvalidRequestError):
        await adapter.cancel_stop_order("stop-1")


@pytest.mark.asyncio
async def test_get_stop_orders_normalized() -> None:
    fake = _stop_fake(
        **{
            f"{_STOP_ORDERS}/GetStopOrders": {
                "orders": [
                    {
                        "stopOrderId": "stop-1",
                        "figi": "BBG004730N88",
                        "lotsRequested": 3,
                        "status": "STOP_ORDER_STATUS_ACTIVE",
                        "stopPrice": {"units": "80", "nano": 0},
                        "direction": "ORDER_DIRECTION_SELL",
                        "exchangeOrderId": "exch-7",
                        "currency": "RUB",
                        "createDate": "2025-01-01T10:00:00Z",
                        "updateDate": "2025-01-01T10:01:00Z",
                    }
                ]
            }
        }
    )
    adapter = TInvestAdapter(client=fake)
    stops = await adapter.get_stop_orders(account_id="acc-1")
    assert len(stops) == 1
    stop = stops[0]
    assert stop.order_id == "stop-1"
    assert stop.status is StopOrderStatus.ACTIVE
    assert stop.account_id == "acc-1"
    assert stop.instrument_figi == "BBG004730N88"
    assert stop.side == OrderSide.SELL
    assert stop.quantity == Decimal("30")  # 3 lots * lot 10, canonical units
    assert stop.stop_price == Decimal("80")
    assert stop.exchange_order_id == "exch-7"
    assert stop.currency == "RUB"
    assert stop.created_at is not None
    assert stop.updated_at is not None


@pytest.mark.asyncio
async def test_get_stop_orders_maps_unknown_status_to_unknown() -> None:
    fake = _stop_fake(
        **{
            f"{_STOP_ORDERS}/GetStopOrders": {
                "orders": [
                    {
                        "stopOrderId": "s1",
                        "figi": "BBG004730N88",
                        "lotsRequested": 1,
                        "status": "STOP_ORDER_STATUS_UNSPECIFIED",
                    }
                ]
            }
        }
    )
    adapter = TInvestAdapter(client=fake)
    stop = (await adapter.get_stop_orders(account_id="acc-1"))[0]
    assert stop.status is StopOrderStatus.UNKNOWN


@pytest.mark.asyncio
async def test_get_stop_orders_without_lot_size_blocks_normalization() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            f"{_STOP_ORDERS}/GetStopOrders": {
                "orders": [{"stopOrderId": "s1", "figi": "BBG004730N88", "lotsRequested": 1}]
            },
        }
    )
    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.get_stop_orders(account_id="acc-1")


@pytest.mark.asyncio
async def test_get_stop_orders_with_window_requests_all_statuses() -> None:
    fake = _stop_fake(**{f"{_STOP_ORDERS}/GetStopOrders": {"orders": []}})
    adapter = TInvestAdapter(client=fake)
    from_ = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    to = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    await adapter.get_stop_orders(account_id="acc-1", from_=from_, to=to)
    path, body = fake.calls[-1]
    assert path == f"{_STOP_ORDERS}/GetStopOrders"
    # B1: without an explicit status filter T-Invest returns only ACTIVE
    # orders, so an executed stop would look missing — the caller window is
    # requested with STOP_ORDER_STATUS_ALL and the from/to bounds.
    assert body == {
        "accountId": "acc-1",
        "status": "STOP_ORDER_STATUS_ALL",
        "from": "2026-10-01T08:00:00Z",
        "to": "2026-10-01T09:00:00Z",
    }


@pytest.mark.asyncio
async def test_get_stop_orders_requires_both_window_bounds() -> None:
    adapter = TInvestAdapter(client=_stop_fake())
    with pytest.raises(InvalidRequestError):
        await adapter.get_stop_orders(
            account_id="acc-1", from_=datetime(2026, 10, 1, tzinfo=UTC)
        )


@pytest.mark.asyncio
async def test_place_stop_order_without_id_returns_unknown() -> None:
    # B3: a placement the broker did not acknowledge with an id cannot be
    # correlated — UNKNOWN, never ACTIVE with an empty identity.
    fake = _stop_fake(**{f"{_STOP_ORDERS}/PostStopOrder": {}})
    adapter = TInvestAdapter(client=fake)
    stop = await adapter.place_stop_order(
        BrokerStopOrderRequest(
            instrument_figi="BBG004730N88",
            side=OrderSide.SELL,
            quantity=Decimal("30"),
            stop_price=Decimal("80"),
            account_id="acc-1",
        )
    )
    assert stop.order_id == ""
    assert stop.status is StopOrderStatus.UNKNOWN


# --- Sandbox REST shapes (P5, MVP-7.3) ---
#
# T-Invest REST returns camelCase JSON: OpenSandboxAccount →
# {"accountId": ...}, SandboxPayIn/CloseSandboxAccount requests use
# "accountId", SandboxPayIn response keeps "balance". Source: proto/sandbox.proto
# of RussianInvestments/invest-api-go-sdk (field names confirmed there).

_OPEN_SANDBOX = "tinkoff.public.invest.api.contract.v1.SandboxService/OpenSandboxAccount"
_PAY_IN = "tinkoff.public.invest.api.contract.v1.SandboxService/SandboxPayIn"
_CLOSE_SANDBOX = "tinkoff.public.invest.api.contract.v1.SandboxService/CloseSandboxAccount"


def _sandbox_fake() -> TInvestFakeClient:
    return TInvestFakeClient(
        responses={
            _OPEN_SANDBOX: {"accountId": "sandbox-1"},
            _PAY_IN: {"balance": {"currency": "RUB", "units": "50000", "nano": 0}},
            _CLOSE_SANDBOX: {},
        }
    )


@pytest.mark.asyncio
async def test_open_sandbox_account_reads_rest_accountId() -> None:
    fake = _sandbox_fake()
    adapter = TInvestAdapter(client=fake)
    account_id = await adapter.open_sandbox_account()
    assert account_id == "sandbox-1"
    assert fake.calls == [(_OPEN_SANDBOX, {})]


@pytest.mark.asyncio
async def test_sandbox_pay_in_posts_accountId_and_parses_balance() -> None:
    fake = _sandbox_fake()
    adapter = TInvestAdapter(client=fake)
    balance = await adapter.sandbox_pay_in("sandbox-1", Decimal("50000"), "RUB")
    assert balance == Decimal("50000")
    (_, body), = [c for c in fake.calls if c[0] == _PAY_IN]
    assert body == {
        "accountId": "sandbox-1",
        "amount": {"currency": "RUB", "units": "50000", "nano": 0},
    }


@pytest.mark.asyncio
async def test_close_sandbox_account_posts_accountId() -> None:
    fake = _sandbox_fake()
    adapter = TInvestAdapter(client=fake)
    await adapter.close_sandbox_account("sandbox-1")
    (_, body), = [c for c in fake.calls if c[0] == _CLOSE_SANDBOX]
    assert body == {"accountId": "sandbox-1"}
