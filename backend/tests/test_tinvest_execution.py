"""T-Invest Open API execution (MVP-6.2) adapter tests.

Covers order submission (MARKET/LIMIT), units->lots conversion, lot/tick
validation, Decimal<->Quotation, UUID idempotency, order lifecycle mapping,
BESTPRICE handling and account context. All broker interaction uses a mocked
TInvestFakeClient (no real token/network).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.brokers.base import BrokerOrderRequest
from app.brokers.tinvest import (
    _ORDER_SIDE_TO_TINVEST,
    _ORDER_TYPE_TO_TINVEST,
    _decimal_to_quotation,
)
from app.brokers.tinvest_errors import InvalidRequestError
from app.models.enums import OrderSide, OrderStatus, OrderType
from tests.fakes import TInvestFakeClient

_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
_GET_INSTRUMENT = "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
_POST_ORDER = "tinkoff.public.invest.api.contract.v1.OrdersService/PostOrder"
_GET_ORDER_STATE = "tinkoff.public.invest.api.contract.v1.OrdersService/GetOrderState"
_CANCEL_ORDER = "tinkoff.public.invest.api.contract.v1.OrdersService/CancelOrder"


def _instrument_response(lot: int = 10, tick: str = "1") -> dict:
    return {
        "instrument": {
            "figi": "BBG004730N88",
            "ticker": "SBER",
            "name": "Sberbank",
            "currency": "RUB",
            "lot": lot,
            "instrumentType": "share",
            "minPriceIncrement": {"units": tick, "nano": 0},
            "apiTradeAvailableFlag": True,
        }
    }


def _post_response(status: str = "EXECUTION_REPORT_STATUS_NEW", lots: int = 10) -> dict:
    return {
        "orderId": "broker-1",
        "executionReportStatus": status,
        "lotsRequested": lots,
        "lotsExecuted": 0,
        "figi": "BBG004730N88",
        "direction": "ORDER_DIRECTION_BUY",
        "orderType": "ORDER_TYPE_LIMIT",
        "initialSecurityPrice": {"currency": "RUB", "units": "100", "nano": 0},
        "currency": "RUB",
    }


def _request(
    quantity="100",
    side=OrderSide.BUY,
    type_=OrderType.MARKET,
    price=None,
    account_id="acc-1",
    idempotency_key="8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
) -> BrokerOrderRequest:
    return BrokerOrderRequest(
        instrument_figi="BBG004730N88",
        side=side,
        quantity=Decimal(quantity),
        type=type_,
        price=Decimal(price) if price is not None else None,
        account_id=account_id,
        idempotency_key=idempotency_key,
    )


def _adapter() -> TInvestAdapterWithClient:
    fake = TInvestFakeClient(
        responses={
            _GET_INSTRUMENT: _instrument_response(),
            _POST_ORDER: _post_response(),
        }
    )
    return TInvestAdapterWithClient(fake)


class TInvestAdapterWithClient:
    """Small wrapper so tests can inspect the adapter's client calls."""

    def __init__(self, fake: TInvestFakeClient) -> None:
        from app.brokers import TInvestAdapter

        self.fake = fake
        self.adapter = TInvestAdapter(client=fake)


@pytest.mark.asyncio
async def test_market_order_builds_lots_and_sends_account() -> None:
    t = _adapter()
    result = await t.adapter.place_order(_request(type_=OrderType.MARKET))

    post_call = next(c for c in t.fake.calls if c[0] == _POST_ORDER)
    body = post_call[1]
    # units 100 / lot 10 -> 10 lots.
    assert body["quantity"] == 10
    assert body["accountId"] == "acc-1"
    assert body["direction"] == _ORDER_SIDE_TO_TINVEST[OrderSide.BUY]
    assert body["orderType"] == _ORDER_TYPE_TO_TINVEST[OrderType.MARKET]
    assert body["instrumentId"] == "BBG004730N88"
    assert "price" not in body

    assert result.order_id == "broker-1"
    assert result.status == OrderStatus.NEW


@pytest.mark.asyncio
async def test_limit_order_sends_quotation_price() -> None:
    t = _adapter()
    await t.adapter.place_order(
        _request(
            type_=OrderType.LIMIT,
            price="100",
            idempotency_key="c3d1f2e0-0b5e-4a9d-8c31-7f2a9b0e1d21",
        )
    )
    post_call = next(c for c in t.fake.calls if c[0] == _POST_ORDER)
    body = post_call[1]
    assert body["orderType"] == "ORDER_TYPE_LIMIT"
    assert body["price"] == {"units": "100", "nano": 0}


@pytest.mark.asyncio
async def test_invalid_lot_multiple_rejected() -> None:
    t = _adapter()
    with pytest.raises(InvalidRequestError):
        await t.adapter.place_order(_request(quantity="95"))


@pytest.mark.asyncio
async def test_price_not_multiple_of_tick_rejected() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_INSTRUMENT: _instrument_response(lot=10, tick="1"),
            _POST_ORDER: _post_response(),
        }
    )
    from app.brokers import TInvestAdapter

    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.place_order(_request(type_=OrderType.LIMIT, price="100.25"))


@pytest.mark.asyncio
async def test_missing_account_id_rejected() -> None:
    fake = TInvestFakeClient(responses={_GET_INSTRUMENT: _instrument_response()})
    from app.brokers import TInvestAdapter

    adapter = TInvestAdapter(client=fake)
    with pytest.raises(InvalidRequestError):
        await adapter.place_order(_request(account_id=None))


@pytest.mark.asyncio
async def test_non_uuid_idempotency_rejected() -> None:
    t = _adapter()
    with pytest.raises(InvalidRequestError):
        await t.adapter.place_order(_request(idempotency_key="not-a-uuid"))


@pytest.mark.asyncio
async def test_uuid_idempotency_sent_verbatim() -> None:
    key = "8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1"
    t = _adapter()
    await t.adapter.place_order(_request(type_=OrderType.MARKET, idempotency_key=key))
    post_call = next(c for c in t.fake.calls if c[0] == _POST_ORDER)
    assert post_call[1]["orderId"] == key


@pytest.mark.asyncio
async def test_missing_idempotency_key_generates_uuid() -> None:
    t = _adapter()
    await t.adapter.place_order(_request(type_=OrderType.MARKET, idempotency_key=""))
    post_call = next(c for c in t.fake.calls if c[0] == _POST_ORDER)
    UUID(post_call[1]["orderId"])  # must parse as a UUID


@pytest.mark.asyncio
async def test_cancel_requires_account() -> None:
    t = _adapter()
    with pytest.raises(InvalidRequestError):
        await t.adapter.cancel_order("broker-1")


@pytest.mark.asyncio
async def test_cancel_sends_account_and_exchange_id_type() -> None:
    t = _adapter()
    await t.adapter.cancel_order("broker-1", account_id="acc-1")
    call = next(c for c in t.fake.calls if c[0] == _CANCEL_ORDER)
    assert call[1] == {
        "accountId": "acc-1",
        "orderId": "broker-1",
        "orderIdType": "ORDER_ID_TYPE_EXCHANGE",
    }


@pytest.mark.asyncio
async def test_get_order_requires_account() -> None:
    t = _adapter()
    with pytest.raises(InvalidRequestError):
        await t.adapter.get_order("broker-1")


@pytest.mark.asyncio
async def test_get_order_maps_state() -> None:
    fake = TInvestFakeClient(
        responses={
            _GET_INSTRUMENT: _instrument_response(),
            _GET_ORDER_STATE: {
                "orderId": "broker-1",
                "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL",
                "lotsRequested": 10,
                "lotsExecuted": 10,
                "figi": "BBG004730N88",
                "currency": "RUB",
                "initialSecurityPrice": {"currency": "RUB", "units": "100", "nano": 0},
            },
        }
    )
    from app.brokers import TInvestAdapter

    adapter = TInvestAdapter(client=fake)
    order = await adapter.get_order("broker-1", account_id="acc-1")
    assert order.status == OrderStatus.FILLED
    # 10 lots * lot_size 10 (from _instrument_response) = 100 canonical units
    assert order.requested_quantity == Decimal("100")
    assert order.executed_quantity == Decimal("100")


@pytest.mark.asyncio
async def test_lifecycle_status_map_via_get_orders() -> None:
    _GET_ORDERS = "tinkoff.public.invest.api.contract.v1.OrdersService/GetOrders"
    fake = TInvestFakeClient(
        responses={
            _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
            _GET_ORDERS: {
                "orders": [
                    {"orderId": "o1", "executionReportStatus": st}
                    for st in (
                        "EXECUTION_REPORT_STATUS_NEW",
                        "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
                        "EXECUTION_REPORT_STATUS_FILL",
                        "EXECUTION_REPORT_STATUS_REJECTED",
                        "EXECUTION_REPORT_STATUS_CANCELLED",
                    )
                ]
            },
        }
    )
    from app.brokers import TInvestAdapter

    adapter = TInvestAdapter(client=fake)
    orders = await adapter.get_orders()
    assert [o.status for o in orders] == [
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    ]


def test_bestprice_not_mapped_to_limit() -> None:
    from app.brokers.tinvest import _map_order_type

    assert _map_order_type("ORDER_TYPE_BESTPRICE") is None
    assert _map_order_type("ORDER_TYPE_LIMIT") == OrderType.LIMIT


def test_decimal_to_quotation() -> None:
    assert _decimal_to_quotation(Decimal("300.25")) == {"units": "300", "nano": 250000000}
    assert _decimal_to_quotation(Decimal("1.5")) == {"units": "1", "nano": 500000000}
