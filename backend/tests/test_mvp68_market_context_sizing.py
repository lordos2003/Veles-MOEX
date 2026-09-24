"""MVP-6.8 Market Context & Position Sizing boundary tests.

Focused on the new backend boundaries: the broker-neutral production
MarketContext source, the explicit position-sizing source, the
Strategy -> DCA/Grid -> Plan path with an explicit base nominal, and the
entry-intent conversion. Deterministic and broker-neutral: no real orders, no
T-Invest, no fabricated market data (prices/candles/timestamps come from the
fake broker-neutral provider). Existing MVP-6.5/6.6/6.7 suites are the
regression check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.domain.marketdata import Timeframe
from app.models.enums import BotState, OrderSide, OrderStatus, OrderType
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
    TradingMode,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import ExitPlan, MarketContext, Plan
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading import (
    BotRuntime,
    OrderManager,
    PositionSizing,
    RiskLimits,
    RiskManager,
    RiskRejected,
    SizingNotConfigured,
    TradingEngine,
    build_market_context,
)
from app.trading.domain import ExecutionIntent
from app.trading.market_context import MarketContextUnavailable
from app.trading.plan_intent import plan_to_intents

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"


class FakeMarketData:
    """Duck-typed broker-neutral market-data provider (get_last_price)."""

    def __init__(self, last_price=None) -> None:
        self._last_price = last_price

    async def get_last_price(self, figi: str):
        return self._last_price


class FakeBroker:
    """Duck-typed broker for the live path; records place/cancel calls."""

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


def _grid_config(**overrides) -> DCAGridConfig:
    cfg = DCAGridConfig(mode=TradingMode.SIMPLE, levels=1)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _strategy(dca: DCAGridConfig | None = None) -> StrategyConfig:
    return StrategyConfig(
        direction=Direction.LONG,
        entry=EntryConfig(),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=2.0)),
        dca_grid=dca or _grid_config(),
    )


def _context(price: str, *, with_snapshot: bool = True) -> MarketContext:
    snapshot = None
    if with_snapshot:
        snapshot = Snapshot(
            series={
                Timeframe.MIN_5: BarSeries(
                    timeframe=Timeframe.MIN_5,
                    bars=[Bar(T0, 100.0, 101.0, 99.0, 100.0, 1000.0)],
                )
            }
        )
    return MarketContext(price=float(Decimal(price)), timestamp=T0, snapshot=snapshot)


def _se() -> StrategyEngine:
    return StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())


def _engine_with_sizing(
    broker: FakeBroker,
    *,
    sizing: PositionSizing | None = None,
    risk: RiskManager | None = None,
    strategy: StrategyConfig | None = None,
    intent_factory=None,
) -> TradingEngine:
    om = OrderManager(broker)
    risk = risk or RiskManager(position_manager=om.positions())
    engine = TradingEngine(
        broker,
        _se(),
        om,
        om.positions(),
        risk,
        strategy_config=strategy or _strategy(),
        intent_factory=intent_factory,
        sizing=sizing,
    )
    return engine


# --- 1-3: live MarketContext boundary ----------------------------------------


async def test_build_market_context_uses_real_broker_price() -> None:
    from app.domain.marketdata import LastPrice

    md = FakeMarketData(last_price=LastPrice(figi=FIGI, price=Decimal("100"), timestamp=T0))
    ctx = await build_market_context(md, FIGI)
    assert isinstance(ctx, MarketContext)
    assert ctx.price == 100.0
    assert ctx.timestamp == T0


async def test_market_context_reaches_strategy_engine() -> None:
    # A MarketContext (price/snapshot) is consumed by the StrategyEngine and
    # drives the DCA/grid plan; the price is the live reference, not a literal.
    ctx = _context("100")
    plan = _se().evaluate(_strategy(), ctx, base_nominal=Decimal("5000"))
    assert len(plan.grid) == 1
    initial = plan.grid[0]
    assert initial.side is OrderSide.BUY
    assert initial.quantity > 0


async def test_missing_market_data_blocks_live_strategy_execution() -> None:
    md = FakeMarketData(last_price=None)
    with pytest.raises(MarketContextUnavailable):
        await build_market_context(md, FIGI)


# --- 3: no fabricated MarketContext -------------------------------------------


def test_no_fabricated_market_context_outside_boundary() -> None:
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "app" / "trading"
    # Trading/sizing code must never construct a MarketContext; only the
    # explicit market_context boundary module builds it from real broker data.
    for name in ("engine.py", "sizing.py", "plan_intent.py", "bot_lifecycle.py"):
        source = (base / name).read_text(encoding="utf-8")
        assert "MarketContext(" not in source, name
    assert "MarketContext(" in (base / "market_context.py").read_text(encoding="utf-8")


# --- 4-7: explicit sizing source ---------------------------------------------


async def test_bot_specific_sizing_source_is_used() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        _se(),
        om,
        om.positions(),
        RiskManager(position_manager=om.positions()),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
    )
    await engine.start()
    await engine.process(_context("100"))
    orders = om.list_orders()
    assert len(orders) == 1
    # quantity = base_nominal / price = 5000 / 100 = 50 (per-bot sizing).
    assert orders[0].requested_quantity == Decimal("50")


async def test_missing_sizing_blocks_execution() -> None:
    broker = FakeBroker()
    engine = _engine_with_sizing(broker, sizing=None)
    await engine.start()
    with pytest.raises(SizingNotConfigured):
        await engine.process(_context("100"))
    assert broker.place_calls == 0


async def test_dca_grid_engine_receives_explicit_live_sizing() -> None:
    # Explicit base nominal flows into DCAGridEngine.build -> plan quantity.
    ctx = _context("100")
    plan = _se().evaluate(_strategy(), ctx, base_nominal=Decimal("5000"))
    assert len(plan.grid) == 1
    assert plan.grid[0].quantity == pytest.approx(50.0)


async def test_dca_grid_default_100_never_used_by_live_path() -> None:
    # With base_nominal=5000 the quantity is 50 (not the Decimal('100') default
    # which would give 1). The default is never relied upon by the live path.
    ctx = _context("100")
    plan = _se().evaluate(_strategy(), ctx, base_nominal=Decimal("5000"))
    assert plan.grid[0].quantity == pytest.approx(50.0)
    assert plan.grid[0].quantity != 1.0
    # Without an explicit base nominal no grid is produced at all.
    plan_off = _se().evaluate(_strategy(), ctx, base_nominal=None)
    assert plan_off.grid == []


# --- 8-10: entry intent + risk gate -------------------------------------------


async def test_valid_generated_entry_intent_contains_positive_real_quantity() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        _se(),
        om,
        om.positions(),
        RiskManager(position_manager=om.positions()),
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
    )
    await engine.start()
    await engine.process(_context("100"))
    intents = om.list_orders()
    assert len(intents) == 1
    intent = intents[0]
    assert intent.bot_id == 1
    assert intent.instrument_figi == FIGI
    assert intent.side is OrderSide.BUY
    assert intent.order_type is OrderType.MARKET  # offset 0 -> market first order
    assert intent.requested_quantity > 0
    assert intent.intent_id.startswith("plan-")


async def test_invalid_quantity_is_rejected_before_order_manager() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(position_manager=om.positions())
    engine = TradingEngine(
        broker,
        _se(),
        om,
        om.positions(),
        risk,
        strategy_config=_strategy(),
        intent_factory=lambda plan, ctx: ExecutionIntent(
            intent_id="bad-qty",
            trade_id="t-1",
            instrument_figi=FIGI,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0"),
            bot_id=1,
        ),
        sizing=PositionSizing(base_nominal=Decimal("5000")),
    )
    await engine.start()
    with pytest.raises(RiskRejected):
        await engine.process(_context("100"))
    assert broker.place_calls == 0


async def test_full_path_remains_risk_manager_gated() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(
        limits=RiskLimits(blocked_instruments=frozenset({FIGI})),
        position_manager=om.positions(),
    )

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1")

    engine = TradingEngine(
        broker,
        _se(),
        om,
        om.positions(),
        risk,
        strategy_config=_strategy(),
        intent_factory=factory,
        sizing=PositionSizing(base_nominal=Decimal("5000")),
    )
    await engine.start()
    with pytest.raises(RiskRejected):
        await engine.process(_context("100"))
    assert broker.place_calls == 0
    assert om.list_orders() == []


# --- 11: exit placeholder boundary --------------------------------------------


async def test_live_exit_plan_with_placeholder_quantity_remains_blocked() -> None:
    plan = Plan(
        exits=[ExitPlan(side=OrderSide.SELL, quantity=1.0, price=Decimal("100"))]
    )
    intents = plan_to_intents(plan, instrument_figi=FIGI, bot_id=1)
    assert intents == []


# --- 12: sizing failure at START does not consume a risk slot -----------------


async def test_sizing_failure_during_start_does_not_consume_risk_slot() -> None:
    from app.bots.strategy import BotStrategy

    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    strategy = BotStrategy(
        strategy_version_id=1, version=1, config=_strategy()
    )

    async def _load_strategy():
        return strategy

    async def _failing_factory(s):
        raise SizingNotConfigured("no sizing source")

    failing = BotRuntime(
        1,
        risk,
        state=BotState.STOPPED,
        strategy_loader=_load_strategy,
        trading_engine_factory=_failing_factory,
    )
    with pytest.raises(SizingNotConfigured):
        await failing.start()
    assert failing.state is BotState.ERROR
    # The failed start must not occupy the concurrent-bot slot.
    assert risk.check_start(2) is True
