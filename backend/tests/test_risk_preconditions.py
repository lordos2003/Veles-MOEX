"""MVP-6.6 Risk Manager execution preconditions (deterministic).

Broker-neutral, no real orders, no fake funds/capacity data, no T-Invest.
"""

from __future__ import annotations

import dataclasses
import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.enums import OrderSide, OrderType
from app.trading import (
    PositionManager,
    RiskLimits,
    RiskManager,
    RiskRejected,
)
from app.trading.domain import ExecutionIntent


def _intent(
    quantity: str = "5",
    order_type: OrderType = OrderType.MARKET,
    limit_price: str | None = None,
    instrument_figi: str = "BBG000",
    **kwargs,
) -> ExecutionIntent:
    return ExecutionIntent(
        intent_id="i-1",
        trade_id="t-1",
        instrument_figi=instrument_figi,
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Decimal(quantity),
        limit_price=Decimal(limit_price) if limit_price is not None else None,
        **kwargs,
    )


def test_zero_quantity_rejected() -> None:
    with pytest.raises(RiskRejected):
        RiskManager().check_order(_intent(quantity="0"))


def test_negative_quantity_rejected() -> None:
    with pytest.raises(RiskRejected):
        RiskManager().check_order(_intent(quantity="-3"))


@pytest.mark.parametrize("limit_price", [None, "0", "-5"])
def test_invalid_limit_price_rejected(limit_price: str | None) -> None:
    with pytest.raises(RiskRejected):
        RiskManager().check_order(
            _intent(order_type=OrderType.LIMIT, limit_price=limit_price)
        )


def test_market_intent_does_not_require_limit_price() -> None:
    assert (
        RiskManager().check_order(_intent(order_type=OrderType.MARKET, limit_price=None))
        is None
    )


def test_emergency_stop_rejects() -> None:
    with pytest.raises(RiskRejected):
        RiskManager(limits=RiskLimits(emergency_stop=True)).check_order(_intent())


def test_configured_position_limit_rejects() -> None:
    position_manager = PositionManager()
    position_manager.apply_fill("BBG000", OrderSide.BUY, Decimal("8"), Decimal("100"))
    risk = RiskManager(
        limits=RiskLimits(max_position_size=Decimal("10")),
        position_manager=position_manager,
    )
    with pytest.raises(RiskRejected):
        risk.check_order(_intent(quantity="5"))


def test_configured_daily_loss_limit_rejects() -> None:
    risk = RiskManager(
        limits=RiskLimits(daily_loss_limit=Decimal("100")),
        daily_pnl=Decimal("-150"),
    )
    with pytest.raises(RiskRejected):
        risk.check_order(_intent())


def test_allowed_order_passes() -> None:
    assert RiskManager().check_order(_intent()) is None


def test_configured_instrument_restriction_rejects() -> None:
    blocked = RiskLimits(blocked_instruments=frozenset({"BBG000"}))
    with pytest.raises(RiskRejected):
        RiskManager(limits=blocked).check_order(_intent(instrument_figi="BBG000"))


def test_instrument_status_provider_rejects_when_not_permitted() -> None:
    risk = RiskManager(instrument_status_check=lambda figi: figi != "BBG000")
    with pytest.raises(RiskRejected):
        risk.check_order(_intent(instrument_figi="BBG000"))
    # An unknown (None) status does not block the order.
    unknown = RiskManager(instrument_status_check=lambda figi: None)
    assert unknown.check_order(_intent(instrument_figi="BBG000")) is None


def test_no_fake_funds_or_capacity_data_used() -> None:
    fields = {field.name for field in dataclasses.fields(RiskLimits)}
    assert "available_funds" not in fields
    assert "max_capacity" not in fields
    # With no configured limits and no position data, a large quantity is not
    # blocked by any fabricated capacity/funds gate.
    assert RiskManager().check_order(_intent(quantity="1000000")) is None


def test_risk_manager_remains_broker_neutral() -> None:
    from app.trading import risk_manager as module

    source = inspect.getsource(module)
    assert "app.brokers.tinvest" not in source
    assert "import tinvest" not in source


def test_risk_limits_from_settings_maps_only_configured_values() -> None:
    from app.trading.live_execution import risk_limits_from_settings

    empty = SimpleNamespace(
        risk_max_position_size=None,
        risk_daily_loss_limit=None,
        risk_max_concurrent_bots=None,
        risk_blocked_instruments=[],
    )
    limits = risk_limits_from_settings(empty)
    assert limits.max_position_size is None
    assert limits.daily_loss_limit is None
    assert limits.max_concurrent_bots is None
    assert limits.blocked_instruments is None

    configured = SimpleNamespace(
        risk_max_position_size=10.0,
        risk_daily_loss_limit=100.5,
        risk_max_concurrent_bots=2,
        risk_blocked_instruments=["BBG000"],
    )
    limits = risk_limits_from_settings(configured)
    assert limits.max_position_size == Decimal("10")
    assert limits.daily_loss_limit == Decimal("100.5")
    assert limits.max_concurrent_bots == 2
    assert limits.blocked_instruments == frozenset({"BBG000"})


def test_bot_lifecycle_gate_is_not_duplicated_in_risk_manager() -> None:
    # The bot RUNNING state is checked upstream by the bot lifecycle gate; the
    # risk gate must not inspect bot states.
    from app.trading import risk_manager as module

    source = inspect.getsource(module)
    assert "BotState" not in source
    assert "bot_runtime" not in source
