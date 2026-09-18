"""Domain model sanity tests."""

from __future__ import annotations

from app.models import (
    Account,
    Base,
    Bot,
    Execution,
    Instrument,
    Order,
    OrderStatus,
    Position,
    Strategy,
    StrategyVersion,
)


def test_all_core_models_are_declarative() -> None:
    for cls in (Instrument, Account, Order, Execution, Position, Strategy, StrategyVersion, Bot):
        assert issubclass(cls, Base), cls


def test_required_tables_registered() -> None:
    tables = Base.metadata.tables
    for name in (
        "instruments",
        "accounts",
        "orders",
        "executions",
        "positions",
        "strategies",
        "strategy_versions",
        "bots",
    ):
        assert name in tables, name


def test_strategy_version_is_separate_entity() -> None:
    assert StrategyVersion is not Strategy
    columns = StrategyVersion.__table__.columns.keys()
    assert "strategy_id" in columns
    assert "config" in columns


def test_order_status_enum_matches_spec() -> None:
    expected = {
        "NEW",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "EXPIRED",
        "ERROR",
    }
    assert {s.value for s in OrderStatus} == expected


def test_models_instantiable_without_db() -> None:
    instrument = Instrument(ticker="SBER", name="Sberbank", is_active=True)
    account = Account(name="Demo", broker="tinvest", is_active=True)
    strategy = Strategy(name="TestStrategy", config={})
    version = StrategyVersion(strategy_id=1, version=1, config={})
    bot = Bot(
        name="TestBot",
        strategy_version_id=1,
        account_id=1,
        instrument_id=1,
        status="stopped",
    )
    assert instrument.ticker == "SBER"
    assert account.broker == "tinvest"
    assert strategy.name == "TestStrategy"
    assert version.version == 1
    assert bot.name == "TestBot"
