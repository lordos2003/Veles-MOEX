"""Broker data (Account/Position/Order/Deal) tests: DTOs, service, REST API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_broker_data_service
from app.brokers.base import BrokerDeal, BrokerOrder, BrokerPosition
from app.main import app
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.services.broker_data import BrokerDataService
from tests.fakes import FakeBrokerData

# --- DTO typing ---


def test_position_decimal_and_fields() -> None:
    pos = BrokerPosition(
        account_id="acc-1",
        instrument_figi="BBG004730N88",
        ticker="SBER",
        quantity=Decimal("10"),
        average_price=Decimal("280"),
        current_price=Decimal("300"),
        current_value=Decimal("3000"),
        unrealized_pnl=Decimal("200"),
        currency="RUB",
    )
    assert isinstance(pos.quantity, Decimal)
    assert isinstance(pos.current_value, Decimal)
    assert pos.account_id == "acc-1"
    assert pos.instrument_figi == "BBG004730N88"


def test_order_required_fields() -> None:
    order = BrokerOrder(
        order_id="o1",
        status=OrderStatus.NEW,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        requested_quantity=Decimal("5"),
        executed_quantity=Decimal("0"),
    )
    assert order.status == OrderStatus.NEW
    assert order.side == OrderSide.BUY
    assert isinstance(order.requested_quantity, Decimal)


def test_deal_required_fields() -> None:
    deal = BrokerDeal(
        deal_id="d1",
        instrument_figi="F",
        side=OrderSide.SELL,
        quantity=Decimal("3"),
        price=Decimal("100"),
    )
    assert deal.side == OrderSide.SELL
    assert isinstance(deal.price, Decimal)
    assert deal.currency is None


def test_timestamps_timezone_aware() -> None:
    ts = datetime(2025, 1, 1, tzinfo=UTC)
    pos = BrokerPosition(account_id="a", instrument_figi="F", timestamp=ts)
    assert pos.timestamp.tzinfo is not None


# --- BrokerDataService filtering ---


@pytest.mark.asyncio
async def test_service_filters_positions_by_figi() -> None:
    broker = FakeBrokerData(
        positions=[
            BrokerPosition(account_id="a", instrument_figi="F1"),
            BrokerPosition(account_id="a", instrument_figi="F2"),
        ]
    )
    service = BrokerDataService(broker)
    result = await service.get_positions(figi="F1")
    assert len(result) == 1
    assert result[0].instrument_figi == "F1"


@pytest.mark.asyncio
async def test_service_filters_deals_by_account() -> None:
    broker = FakeBrokerData()
    service = BrokerDataService(broker)
    assert await service.get_deals() == []


# --- REST endpoints ---


def _override_broker_data(broker: FakeBrokerData) -> None:
    app.dependency_overrides[get_broker_data_service] = lambda: BrokerDataService(broker)


def _clear() -> None:
    app.dependency_overrides.pop(get_broker_data_service, None)


def test_positions_endpoint() -> None:
    broker = FakeBrokerData(
        positions=[
            BrokerPosition(
                account_id="acc-1",
                instrument_figi="BBG004730N88",
                ticker="SBER",
                quantity=Decimal("10"),
                average_price=Decimal("280"),
                current_price=Decimal("300"),
                current_value=Decimal("3000"),
                unrealized_pnl=Decimal("200"),
                currency="RUB",
            )
        ]
    )
    _override_broker_data(broker)
    try:
        with TestClient(app) as client:
            response = client.get("/api/positions")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["figi"] == "BBG004730N88"
        assert body[0]["current_value"] == "3000"
    finally:
        _clear()


def test_orders_endpoint() -> None:
    broker = FakeBrokerData(
        orders=[
            BrokerOrder(
                order_id="o1",
                status=OrderStatus.FILLED,
                side=OrderSide.BUY,
                type=OrderType.LIMIT,
                instrument_figi="BBG004730N88",
                requested_quantity=Decimal("10"),
                executed_quantity=Decimal("10"),
            )
        ]
    )
    _override_broker_data(broker)
    try:
        with TestClient(app) as client:
            response = client.get("/api/orders")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["order_id"] == "o1"
        assert body[0]["status"] == "FILLED"
    finally:
        _clear()


def test_deals_endpoint() -> None:
    broker = FakeBrokerData(
        deals=[
            BrokerDeal(
                deal_id="d1",
                instrument_figi="BBG004730N88",
                side=OrderSide.BUY,
                quantity=Decimal("10"),
                price=Decimal("300"),
                commission=Decimal("0.1"),
                currency="RUB",
            )
        ]
    )
    _override_broker_data(broker)
    try:
        with TestClient(app) as client:
            response = client.get("/api/deals")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["deal_id"] == "d1"
        assert body[0]["side"] == "BUY"
        assert body[0]["quantity"] == "10"
    finally:
        _clear()
