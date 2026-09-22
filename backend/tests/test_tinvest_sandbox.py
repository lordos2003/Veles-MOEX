"""T-Invest sandbox integration-style tests (MVP-6.2).

These wire the real TInvestAdapter (against a mocked client that returns
sandbox-like responses) with the OrderManager / PositionManager to cover the
execution lifecycle: market order, limit order, reject, cancel, fill and
position update, plus unary recovery. No real token/network is used.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.brokers import TInvestAdapter
from app.brokers.base import BrokerOrderRequest
from app.brokers.tinvest_errors import InvalidRequestError
from app.brokers.tinvest_streams import TInvestStreamManager, TInvestStreamTransport
from app.models.enums import OrderSide, OrderType
from app.trading import OrderManager, OrderState, PositionManager, TradeFill
from tests.fakes import TInvestFakeClient

FIGI = "BBG004730N88"
_GET_ACCOUNTS = "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
_GET_INSTRUMENT = "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
_POST_ORDER = "tinkoff.public.invest.api.contract.v1.OrdersService/PostOrder"
_GET_ORDER_STATE = "tinkoff.public.invest.api.contract.v1.OrdersService/GetOrderState"
_CANCEL_ORDER = "tinkoff.public.invest.api.contract.v1.OrdersService/CancelOrder"


def _instrument() -> dict:
    return {
        "instrument": {
            "figi": FIGI,
            "ticker": "SBER",
            "name": "Sberbank",
            "currency": "RUB",
            "lot": 10,
            "instrumentType": "share",
            "minPriceIncrement": {"units": "0.01", "nano": 0},
            "apiTradeAvailableFlag": True,
        }
    }


def _adapter(
    post_status: str = "EXECUTION_REPORT_STATUS_NEW",
    post_message: str | None = None,
    order_state_status: str | None = None,
) -> tuple[TInvestAdapter, TInvestFakeClient]:
    responses = {
        _GET_ACCOUNTS: {"accounts": [{"id": "acc-1"}]},
        _GET_INSTRUMENT: _instrument(),
        _POST_ORDER: {
            "orderId": "broker-1",
            "executionReportStatus": post_status,
            "lotsRequested": 10,
            "lotsExecuted": 0,
            "figi": FIGI,
            "direction": "ORDER_DIRECTION_BUY",
            "orderType": "ORDER_TYPE_MARKET",
            "message": post_message,
            "initialSecurityPrice": {"currency": "RUB", "units": "100", "nano": 0},
            "currency": "RUB",
        },
    }
    if order_state_status is not None:
        responses[_GET_ORDER_STATE] = {
            "orderId": "broker-1",
            "executionReportStatus": order_state_status,
            "lotsRequested": 10,
            "lotsExecuted": 10,
            "figi": FIGI,
            "currency": "RUB",
            "initialSecurityPrice": {"currency": "RUB", "units": "100", "nano": 0},
        }
    fake = TInvestFakeClient(responses=responses)
    return TInvestAdapter(client=fake), fake


def _intent(om: OrderManager, quantity="100"):
    return om.create_intent(
        intent_id="i-1",
        trade_id="bot-1",
        instrument_figi=FIGI,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        account_id="acc-1",
        idempotency_key="8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
    )


@pytest.mark.asyncio
async def test_sandbox_market_order_flow() -> None:
    adapter, fake = _adapter()
    om = OrderManager(adapter, PositionManager())
    order = await om.submit(_intent(om))
    assert order.status == OrderState.SUBMITTED
    assert order.broker_order_id == "broker-1"
    assert order.requested_quantity == Decimal("100")
    post_call = next(c for c in fake.calls if c[0] == _POST_ORDER)
    assert post_call[1]["quantity"] == 10  # 100 units / lot 10
    assert post_call[1]["accountId"] == "acc-1"


@pytest.mark.asyncio
async def test_sandbox_limit_order_and_tick_validation() -> None:
    adapter, _ = _adapter()
    om = OrderManager(adapter, PositionManager())
    intent = om.create_intent(
        intent_id="i-2",
        trade_id="bot-1",
        instrument_figi=FIGI,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("100"),
        limit_price=Decimal("100"),
        account_id="acc-1",
        idempotency_key="7a1b2c3d-4e5f-6789-abcd-ef0123456789",
    )
    order = await om.submit(intent)
    assert order.status == OrderState.SUBMITTED


@pytest.mark.asyncio
async def test_sandbox_reject_rejected() -> None:
    adapter, _ = _adapter(
        post_status="EXECUTION_REPORT_STATUS_REJECTED", post_message="Not enough funds"
    )
    om = OrderManager(adapter, PositionManager())
    order = await om.submit(_intent(om))
    assert order.status == OrderState.REJECTED
    assert order.reject_info == "Not enough funds"


@pytest.mark.asyncio
async def test_sandbox_cancel_flow() -> None:
    adapter, fake = _adapter()
    om = OrderManager(adapter, PositionManager())
    order = await om.submit(_intent(om))
    await om.cancel(order.order_id)
    assert order.status == OrderState.CANCELLED
    call = next(c for c in fake.calls if c[0] == _CANCEL_ORDER)
    assert call[1]["accountId"] == "acc-1"
    assert call[1]["orderId"] == "broker-1"


@pytest.mark.asyncio
async def test_sandbox_fill_updates_position() -> None:
    adapter, _ = _adapter()
    om = OrderManager(adapter, PositionManager())
    order = await om.submit(_intent(om, quantity="20"))
    om.on_trade_fill(
        TradeFill(
            execution_id="t1",
            broker_order_id=order.broker_order_id,
            quantity=Decimal("10"),
            price=Decimal("100"),
        )
    )
    om.on_trade_fill(
        TradeFill(
            execution_id="t2",
            broker_order_id=order.broker_order_id,
            quantity=Decimal("10"),
            price=Decimal("101"),
        )
    )
    assert order.status == OrderState.FILLED
    assert order.filled_quantity == Decimal("20")
    assert om.positions().get(FIGI).quantity == Decimal("20")
    assert om.positions().get(FIGI).average_price == Decimal("100.5")


@pytest.mark.asyncio
async def test_sandbox_recovery_via_unary() -> None:
    adapter, _ = _adapter(order_state_status="EXECUTION_REPORT_STATUS_FILL")
    om = OrderManager(adapter, PositionManager())
    order = await om.submit(_intent(om, quantity="20"))
    assert order.status == OrderState.SUBMITTED

    class EmptyTransport(TInvestStreamTransport):
        async def connect(self, accounts): ...
        async def messages(self):
            if False:
                yield {}
        async def close(self): ...

    mgr = TInvestStreamManager(adapter, EmptyTransport(), om, "acc-1")
    await mgr._recover()
    # get_orders() returns [] in the fake client -> no order update; get_open_positions
    # also returns [] -> no position. Recovery is inert for an untracked stream here.
    assert order.status == OrderState.SUBMITTED
    refreshed = await om.refresh(order.order_id)
    assert refreshed.status == OrderState.FILLED


@pytest.mark.asyncio
async def test_place_order_requires_account_id_in_sandbox() -> None:
    adapter, _ = _adapter()
    with pytest.raises(InvalidRequestError):
        await adapter.place_order(
            BrokerOrderRequest(
                instrument_figi=FIGI,
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                type=OrderType.MARKET,
                idempotency_key="8f4b2e0a-1f3e-4c7b-9a11-6c4d2e0a53b1",
            )
        )
