"""Broker abstraction tests."""

from __future__ import annotations

import pytest

from app.backtest import BacktestBroker
from app.brokers import (
    BrokerAdapter,
    BrokerOrderRequest,
    TInvestAdapter,
)
from app.models.enums import OrderSide, OrderType


def test_broker_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        BrokerAdapter()  # type: ignore[abstract]


def test_tinvest_adapter_exists() -> None:
    adapter = TInvestAdapter()
    assert isinstance(adapter, BrokerAdapter)


def test_backtest_broker_exists() -> None:
    broker = BacktestBroker()
    assert isinstance(broker, BrokerAdapter)


def test_order_request_dataclass() -> None:
    request = BrokerOrderRequest(
        instrument_figi="BBG004730N88",
        side=OrderSide.BUY,
        quantity=10,
        type=OrderType.LIMIT,
        price=300.0,
    )
    assert request.quantity == 10
    assert request.side == OrderSide.BUY
