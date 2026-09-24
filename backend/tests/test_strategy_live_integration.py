"""MVP-6.7 Strategy -> Bot Runtime -> Trading Engine integration tests.

Focused on the new MVP-6.7 contracts: strategy version loading, the per-bot
strategy execution path, the RiskManager gate and the explicit conversion /
market-data boundaries. Deterministic and broker-neutral: no real orders, no
T-Invest, no fabricated market data. Existing MVP-6.5/6.6 suites are the
regression check for the unchanged lifecycle behavior.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.bots.strategy import BotStrategy, StrategyLoadError, load_bot_strategy
from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.models.account import Account
from app.models.base import Base
from app.models.bot import Bot
from app.models.enums import BotState, OrderSide, OrderStatus, OrderType
from app.models.instrument import Instrument
from app.models.strategy import Strategy, StrategyVersion
from app.strategies.config import (
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.domain import EntrySignal, ExitPlan, GridOrder, MarketContext, Plan
from app.trading import (
    BotRuntime,
    BotStateError,
    OrderManager,
    RiskLimits,
    RiskManager,
    RiskRejected,
    TradingEngine,
)
from app.trading.plan_intent import plan_to_intents

VALID_STRATEGY_CONFIG = {
    "name": "grid-test",
    "direction": "LONG",
    "entry": {"method": "at_bar_close", "groups": []},
    "dca_grid": {"mode": "simple", "levels": 2, "spacing_percent": 0.5},
    "exit": {"take_profit": {"kind": "fixed_percentage", "percent": 2.0}},
}


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw) -> str:
    return "JSON"


class FakeBroker:
    """Duck-typed broker; records place/cancel calls."""

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls: list[tuple[str, str]] = []

    async def place_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self.place_calls += 1
        return BrokerOrder(
            order_id=f"broker-{self.place_calls}",
            status=OrderStatus.SUBMITTED,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            type=request.type,
            side=request.side,
            requested_quantity=request.quantity,
        )

    async def cancel_order(self, order_id: str, account_id: str | None = None) -> None:
        self.cancel_calls.append((order_id, account_id or ""))


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [
        Strategy.__table__,
        StrategyVersion.__table__,
        Bot.__table__,
        Account.__table__,
        Instrument.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()
    await engine.dispose()


async def _seed_bot(
    session: AsyncSession, *, config: dict | None = None, version_id: int | None = None
) -> Bot:
    # Explicit ids: SQLite does not autoincrement BigInteger primary keys.
    account = Account(name="acc", broker="tinvest")
    account.id = 1
    instrument = Instrument(figi="BBG000", ticker="SBER", trading_status="TRADING_AVAILABLE")
    instrument.id = 1
    strategy = Strategy(name="s", config={})
    strategy.id = 1
    session.add_all([account, instrument, strategy])
    await session.flush()
    if version_id is None:
        version = StrategyVersion(
            strategy_id=strategy.id,
            version=1,
            config=config or VALID_STRATEGY_CONFIG,
        )
        version.id = 1
        session.add(version)
        await session.flush()
        version_id = version.id
    bot = Bot(
        name="bot",
        strategy_version_id=version_id,
        account_id=account.id,
        instrument_id=instrument.id,
    )
    bot.id = 1
    session.add(bot)
    await session.commit()
    return bot


def _strategy() -> BotStrategy:
    return BotStrategy(
        strategy_version_id=1,
        version=1,
        config=StrategyConfig(
            exit=ExitConfig(take_profit=FixedPercentageTP(percent=2.0))
        ),
    )


def _runtime_with_strategy(
    risk: RiskManager,
    om: OrderManager,
    broker: FakeBroker,
    strategy_engine: object | None = None,
    *,
    loader=None,
    bot_id: int = 1,
    figi: str = "BBG000",
    state: BotState = BotState.STOPPED,
) -> BotRuntime:
    strategy = _strategy()

    async def _load() -> BotStrategy:
        if loader is not None:
            raise loader
        return strategy

    async def _make_engine(s: BotStrategy) -> TradingEngine:
        engine = TradingEngine(
            broker,
            strategy_engine or _StubStrategyEngine(),
            om,
            om.positions(),
            risk,
            strategy_config=s.config,
            intent_factory=lambda plan, ctx: plan_to_intents(
                plan, instrument_figi=figi, bot_id=bot_id, account_id="acc-1"
            ),
        )
        await engine.start()
        return engine

    return BotRuntime(
        bot_id,
        risk,
        state=state,
        strategy_loader=_load,
        trading_engine_factory=_make_engine,
    )


class _StubStrategyEngine:
    """Returns a fixed plan with one DCA/Grid order (no real calculations)."""

    def __init__(self) -> None:
        self.evaluate_calls = 0

    def evaluate(self, config, context) -> Plan:
        self.evaluate_calls += 1
        return Plan(grid=[GridOrder(side=OrderSide.BUY, quantity=2.0, price=100.0)])


# --- 1-3: StrategyVersion loading ---------------------------------------------


async def test_valid_bot_strategy_loads_config(db_session: AsyncSession) -> None:
    bot = await _seed_bot(db_session)
    loaded = await load_bot_strategy(db_session, bot)
    assert loaded.strategy_version_id == bot.strategy_version_id
    assert loaded.version == 1
    assert isinstance(loaded.config, StrategyConfig)
    assert loaded.config.exit.take_profit.kind == "fixed_percentage"


async def test_missing_strategy_version_rejected(db_session: AsyncSession) -> None:
    bot = await _seed_bot(db_session, version_id=9999)
    with pytest.raises(StrategyLoadError):
        await load_bot_strategy(db_session, bot)


async def test_invalid_strategy_config_rejected(db_session: AsyncSession) -> None:
    # No "exit" block: the stored configuration does not validate.
    bot = await _seed_bot(db_session, config={"entry": {"method": "at_bar_close"}})
    with pytest.raises(StrategyLoadError):
        await load_bot_strategy(db_session, bot)


# --- 4-5: failed strategy load and risk slot ----------------------------------


async def test_failed_strategy_load_moves_bot_to_error() -> None:
    risk = RiskManager()
    rt = _runtime_with_strategy(
        risk, OrderManager(FakeBroker()), FakeBroker(), loader=StrategyLoadError("bad config")
    )
    with pytest.raises(StrategyLoadError):
        await rt.start()
    assert rt.state is BotState.ERROR
    assert rt.strategy is None


async def test_failed_strategy_load_does_not_consume_concurrent_bot_slot() -> None:
    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    om = OrderManager(FakeBroker())
    failing = _runtime_with_strategy(
        risk, om, FakeBroker(), loader=StrategyLoadError("bad config")
    )
    with pytest.raises(StrategyLoadError):
        await failing.start()
    assert failing.state is BotState.ERROR
    # The failed load must not have occupied the concurrent-bot slot: a second
    # bot with a valid strategy can start, and no third can.
    working = _runtime_with_strategy(risk, om, FakeBroker(), bot_id=2)
    await working.start()
    assert working.state is BotState.RUNNING
    assert risk.check_start(3) is False


# --- 6: no execution without RUNNING ------------------------------------------


async def test_strategy_cannot_execute_when_bot_not_running() -> None:
    risk = RiskManager()
    om = OrderManager(FakeBroker())
    broker = FakeBroker()
    rt = _runtime_with_strategy(risk, om, broker)
    assert rt.state is BotState.STOPPED
    with pytest.raises(BotStateError):
        await rt.execute_strategy(MarketContext(price=100.0))
    assert broker.place_calls == 0


# --- 7-8: plan reaches the TradingEngine; RiskManager first -------------------


async def test_strategy_plan_reaches_trading_engine() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(position_manager=om.positions())
    rt = _runtime_with_strategy(risk, om, broker)
    await rt.start()
    assert rt.state is BotState.RUNNING

    plan = await rt.execute_strategy(MarketContext(price=100.0))
    assert len(plan.grid) == 1

    orders = om.list_orders()
    assert len(orders) == 1
    order = orders[0]
    assert order.instrument_figi == "BBG000"
    assert order.bot_id == 1
    assert order.account_id == "acc-1"
    assert order.order_type is OrderType.LIMIT
    assert order.limit_price == Decimal("100")
    assert order.requested_quantity == Decimal("2")
    assert order.side is OrderSide.BUY
    assert broker.place_calls == 1


async def test_risk_manager_rejects_before_order_manager() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(
        limits=RiskLimits(blocked_instruments=frozenset({"BBG000"})),
        position_manager=om.positions(),
    )
    rt = _runtime_with_strategy(risk, om, broker)
    await rt.start()
    with pytest.raises(RiskRejected):
        await rt.execute_strategy(MarketContext(price=100.0))
    assert broker.place_calls == 0
    assert om.list_orders() == []


async def test_duplicate_plan_evaluation_is_idempotent() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(position_manager=om.positions())
    rt = _runtime_with_strategy(risk, om, broker)
    await rt.start()
    await rt.execute_strategy(MarketContext(price=100.0))
    await rt.execute_strategy(MarketContext(price=100.0))
    # Same plan -> same intent id -> the idempotent OrderManager path dedups.
    assert len(om.list_orders()) == 1
    assert broker.place_calls == 1


# --- boundaries ----------------------------------------------------------------


async def test_entry_signal_without_quantity_is_not_converted() -> None:
    plan = Plan(entry=EntrySignal(action="enter", direction=OrderSide.BUY))
    intents = plan_to_intents(plan, instrument_figi="BBG000", bot_id=1)
    assert intents == []


async def test_exit_placeholder_quantity_is_not_converted() -> None:
    # The ExitEngine placeholder (position_qty=1.0) must never become a live order.
    plan = Plan(exits=[ExitPlan(side=OrderSide.SELL, quantity=1.0, price=Decimal("100"))])
    intents = plan_to_intents(plan, instrument_figi="BBG000", bot_id=1)
    assert intents == []


def test_no_fabricated_market_context_in_trading_code() -> None:
    base = Path(__file__).resolve().parents[1] / "app" / "trading"
    for name in ("bot_lifecycle.py", "engine.py", "plan_intent.py"):
        source = (base / name).read_text(encoding="utf-8")
        # MarketContext may only appear as a type, never be constructed.
        assert "MarketContext(" not in source, name
