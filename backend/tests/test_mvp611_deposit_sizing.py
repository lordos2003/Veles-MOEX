"""MVP-6.11 Bot Deposit Sizing & Entry from Confirmed Flat tests.

Focused, deterministic, broker-neutral coverage of the approved contracts:

- C2: deposit -> base nominal per SIMPLE / CUSTOM / SIGNAL mode
  (``deposit_to_base_nominal``);
- C3: MOEX lot rounding down; a level below one lot blocks the whole entry
  (``SizingBelowLot``); missing lot/currency blocks explicitly;
- C4: the three-valued live position state (UNKNOWN / FLAT / OPEN /
  SIGN_MISMATCH) fed by the successful reconciliation; entry only from FLAT
  without active bot orders; exits only while OPEN; UNKNOWN/sign-mismatch
  block everything (MVP-6.9 regression);
- C5: ``Bot.deposit`` persistence surface and API validation (> 0, no default);
  an unset deposit keeps the ``SizingNotConfigured`` behavior.

No real orders, no T-Invest, no fabricated market data or financial defaults.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_bot_repository
from app.bots.repository import BotRepository
from app.bots.schemas import BotDepositUpdate
from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.domain.marketdata import Timeframe
from app.main import app
from app.models.base import Base
from app.models.bot import Bot
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    CustomLevel,
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
    TradingMode,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import GridOrder, MarketContext
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading import (
    CurrencyUnavailable,
    CustomDepositExceeded,
    LivePositionState,
    LotSizeUnavailable,
    OrderManager,
    PositionManager,
    PositionSizing,
    RiskManager,
    SignalSizingUnsupported,
    SizingBelowLot,
    SizingNotConfigured,
    TradingEngine,
    deposit_to_base_nominal,
    round_grid_to_lot,
)
from app.trading.domain import (
    TERMINAL_STATES,
    ExecutionIntent,
    Fill,
    OrderState,
    OrderUpdate,
)
from app.trading.live_execution import make_deposit_provider
from app.trading.plan_intent import plan_to_intents

T0 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"


class FakeBroker:
    """Duck-typed broker; records place/cancel calls."""

    def __init__(self) -> None:
        self.place_calls = 0

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
        pass


def _strategy(**overrides) -> StrategyConfig:
    cfg = dict(
        direction=Direction.LONG,
        timeframe=Timeframe.MIN_5,
        entry=EntryConfig(),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )
    cfg.update(overrides)
    return StrategyConfig(**cfg)


def _context(price: float = 100.0) -> MarketContext:
    return MarketContext(
        price=price,
        timestamp=T0,
        snapshot=Snapshot(
            series={
                Timeframe.MIN_5: BarSeries(
                    timeframe=Timeframe.MIN_5,
                    bars=[Bar(T0, 100.0, 101.0, 99.0, 100.0, 1000.0)],
                )
            }
        ),
    )


def _se() -> StrategyEngine:
    return StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())


def _live_engine(
    broker: FakeBroker,
    *,
    om: OrderManager | None = None,
    positions: PositionManager | None = None,
    sizing: PositionSizing | None = None,
    strategy: StrategyConfig | None = None,
    bot_id: int | None = 1,
    deposit_provider=None,
) -> TradingEngine:
    om = om or OrderManager(broker)
    pm = positions if positions is not None else om.positions()

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=bot_id, account_id="acc-1")

    engine = TradingEngine(
        broker,
        _se(),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=strategy or _strategy(),
        intent_factory=factory,
        sizing=sizing or PositionSizing(base_nominal=Decimal("5000"), lot_size=1, currency="RUB"),
        instrument_figi=FIGI,
        bot_id=bot_id,
        deposit_provider=deposit_provider,
    )
    return engine


class DepositHolder:
    """Mutable async deposit source: the value read at each FLAT entry (C6)."""

    def __init__(self, value: Decimal | None) -> None:
        self.value = value

    async def __call__(self) -> Decimal | None:
        return self.value


# --- 1: SIMPLE deposit -> nominals ---------------------------------------------


def test_simple_deposit_split_with_martingale() -> None:
    # D=10000, n=3, martingale 20% -> k=1.2, sum(k^i)=3.64.
    dca = DCAGridConfig(mode=TradingMode.SIMPLE, levels=3, martingale_percent=20.0)
    first = deposit_to_base_nominal(Decimal("10000"), dca)
    assert first == Decimal("10000") / Decimal("3.64")
    # The unchanged DCAGridEngine martingale math applied to the derived base
    # nominal yields the C2 level nominals; their sum equals the deposit.
    state = DCAGridEngine().build(dca, Decimal("100"), Direction.LONG, base_nominal=first)
    nominals = [lvl.nominal for lvl in state.levels]
    assert len(nominals) == 3
    assert nominals[0] == first
    assert nominals[1] == first * Decimal("1.2")
    assert nominals[2] == first * Decimal("1.2") ** 2
    assert float(nominals[0]) == pytest.approx(2747.25, abs=0.01)
    assert float(nominals[1]) == pytest.approx(3296.70, abs=0.01)
    assert float(nominals[2]) == pytest.approx(3956.04, abs=0.01)
    total = sum(nominals, Decimal("0"))
    assert abs(total - Decimal("10000")) < Decimal("0.01")


def test_simple_deposit_split_without_martingale_is_equal() -> None:
    dca = DCAGridConfig(mode=TradingMode.SIMPLE, levels=3)
    first = deposit_to_base_nominal(Decimal("10000"), dca)
    assert first == Decimal("10000") / Decimal("3")
    state = DCAGridEngine().build(dca, Decimal("100"), Direction.LONG, base_nominal=first)
    assert all(lvl.nominal == Decimal("10000") / Decimal("3") for lvl in state.levels)


# --- 3: CUSTOM deposit -> nominals ---------------------------------------------


def test_custom_deposit_split_by_percent() -> None:
    dca = DCAGridConfig(
        mode=TradingMode.CUSTOM,
        custom_levels=[
            CustomLevel(offset_percent=0.0, nominal_percent=30.0),
            CustomLevel(offset_percent=1.0, nominal_percent=70.0),
        ],
    )
    base = deposit_to_base_nominal(Decimal("10000"), dca)
    assert base == Decimal("10000")
    state = DCAGridEngine().build(dca, Decimal("100"), Direction.LONG, base_nominal=base)
    assert state.levels[0].nominal == Decimal("3000")
    assert state.levels[1].nominal == Decimal("7000")


def test_custom_percent_sum_over_100_is_blocked() -> None:
    dca = DCAGridConfig(
        mode=TradingMode.CUSTOM,
        custom_levels=[
            CustomLevel(offset_percent=0.0, nominal_percent=60.0),
            CustomLevel(offset_percent=1.0, nominal_percent=50.0),
        ],
    )
    with pytest.raises(CustomDepositExceeded):
        deposit_to_base_nominal(Decimal("10000"), dca)


# --- 4: SIGNAL sizing -----------------------------------------------------------


def test_signal_sizing_is_blocked_with_explicit_error() -> None:
    # The existing SIGNAL engine does not use DCAGridConfig.levels as a maximum
    # order-count limit (subsequent averaging orders are unbounded), so no
    # limit is invented: live SIGNAL sizing blocks with an explicit error.
    dca = DCAGridConfig(mode=TradingMode.SIGNAL, levels=3)
    with pytest.raises(SignalSizingUnsupported):
        deposit_to_base_nominal(Decimal("10000"), dca)


# --- 5: sizing independent of DCAGridEngine math --------------------------------


def test_sizing_function_is_independent_of_grid_engine_math() -> None:
    # deposit_to_base_nominal is a pure function of (deposit, config); it does
    # not read or mutate any DCAGridEngine state, and the engine math is
    # unchanged: building with the derived base nominal reproduces the split.
    dca = DCAGridConfig(mode=TradingMode.SIMPLE, levels=2)
    first = deposit_to_base_nominal(Decimal("1000"), dca)
    assert first == Decimal("500")
    state = DCAGridEngine().build(dca, Decimal("100"), Direction.LONG, base_nominal=first)
    assert [lvl.nominal for lvl in state.levels] == [Decimal("500"), Decimal("500")]


def test_grid_order_carries_nominal_into_plan() -> None:
    plan = _se().evaluate(_strategy(), _context(), base_nominal=Decimal("5000"))
    assert len(plan.grid) == 1
    assert plan.grid[0].nominal == pytest.approx(5000.0)
    assert plan.grid[0].quantity == pytest.approx(50.0)


# --- 6: lot rounding down; below-lot blocks the whole entry ---------------------


def test_lot_rounding_down_to_whole_lots() -> None:
    grid = [GridOrder(side=OrderSide.BUY, quantity=25.5, price=100.0, nominal=2550.0)]
    rounded = round_grid_to_lot(grid, lot_size=10, currency="RUB")
    assert len(rounded) == 1
    assert rounded[0].quantity == 20.0  # 25.5 units -> 2 whole lots of 10


def test_level_below_one_lot_blocks_the_whole_entry() -> None:
    grid = [
        GridOrder(side=OrderSide.BUY, quantity=25.5, price=100.0, nominal=2550.0),
        GridOrder(side=OrderSide.BUY, quantity=0.5, price=100.0, nominal=50.0),
    ]
    with pytest.raises(SizingBelowLot) as excinfo:
        round_grid_to_lot(grid, lot_size=10, currency="RUB")
    message = str(excinfo.value)
    assert "level 1" in message
    assert "nominal 50.0" in message
    assert "at 100.0" in message
    assert "lot size 10" in message


# --- 7: missing lot / currency block --------------------------------------------


def test_missing_lot_size_blocks() -> None:
    grid = [GridOrder(side=OrderSide.BUY, quantity=100.0, price=1.0, nominal=100.0)]
    with pytest.raises(LotSizeUnavailable):
        round_grid_to_lot(grid, lot_size=None, currency="RUB")
    with pytest.raises(LotSizeUnavailable):
        round_grid_to_lot(grid, lot_size=0, currency="RUB")


def test_missing_currency_blocks() -> None:
    grid = [GridOrder(side=OrderSide.BUY, quantity=100.0, price=1.0, nominal=100.0)]
    with pytest.raises(CurrencyUnavailable):
        round_grid_to_lot(grid, lot_size=10, currency=None)
    with pytest.raises(CurrencyUnavailable):
        round_grid_to_lot(grid, lot_size=10, currency="   ")


# --- 8: Bot.deposit None/0/negative + API validation ----------------------------


def test_deposit_none_zero_negative_raises_sizing_not_configured() -> None:
    dca = DCAGridConfig(mode=TradingMode.SIMPLE, levels=1)
    for bad in (None, Decimal("0"), Decimal("-5")):
        sizing = PositionSizing(deposit=bad)
        with pytest.raises(SizingNotConfigured):
            sizing.resolve_base_nominal(dca)


def test_position_sizing_deposit_applies_c2() -> None:
    dca = DCAGridConfig(mode=TradingMode.SIMPLE, levels=3, martingale_percent=20.0)
    sizing = PositionSizing(deposit=Decimal("10000"))
    assert sizing.resolve_base_nominal(dca) == Decimal("10000") / Decimal("3.64")


def test_position_sizing_base_nominal_path_unchanged() -> None:
    sizing = PositionSizing(base_nominal=Decimal("5000"))
    assert sizing.resolve_base_nominal(DCAGridConfig()) == Decimal("5000")
    with pytest.raises(SizingNotConfigured):
        PositionSizing().resolve_base_nominal(DCAGridConfig())
    with pytest.raises(SizingNotConfigured):
        PositionSizing(deposit=Decimal("100")).resolve_base_nominal(None)


def test_bot_deposit_schema_validation() -> None:
    with pytest.raises(ValidationError):
        BotDepositUpdate(deposit=Decimal("0"))
    with pytest.raises(ValidationError):
        BotDepositUpdate(deposit=Decimal("-1"))
    # Review observation 2 (C6 round): the deposit key is required — a PATCH
    # without it must not silently clear the deposit.
    with pytest.raises(ValidationError):
        BotDepositUpdate()
    assert BotDepositUpdate(deposit=None).deposit is None
    assert BotDepositUpdate(deposit=Decimal("100")).deposit == Decimal("100")


class _FakeBotRepository:
    """In-memory repository stand-in for the deposit API tests (no DB)."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def get(self, bot_id: int) -> Bot | None:
        return self._bot if bot_id == self._bot.id else None

    async def update_deposit(self, bot: Bot, deposit: Decimal | None) -> Bot:
        bot.deposit = deposit
        return bot


def test_bot_deposit_api_endpoint_validation() -> None:
    bot = Bot(id=1, name="bot", strategy_version_id=1, account_id=1, instrument_id=1)
    bot.status = "STOPPED"
    bot.deposit = None
    app.dependency_overrides[get_bot_repository] = (
        lambda: _FakeBotRepository(bot)
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/bots/1")
            assert response.status_code == 200
            assert response.json()["deposit"] is None

            assert client.patch("/api/bots/1", json={"deposit": 0}).status_code == 422
            assert client.patch("/api/bots/1", json={"deposit": -5}).status_code == 422

            response = client.patch("/api/bots/1", json={"deposit": "10000"})
            assert response.status_code == 200
            assert response.json()["deposit"] == "10000"
            assert bot.deposit == Decimal("10000")

            # Review observation 2 (C6 round): a PATCH without the deposit key
            # must not silently clear the deposit — the key is required (422)
            # and the stored value stays unchanged.
            response = client.patch("/api/bots/1", json={})
            assert response.status_code == 422
            assert bot.deposit == Decimal("10000")

            response = client.patch("/api/bots/1", json={"deposit": None})
            assert response.status_code == 200
            assert response.json()["deposit"] is None
            assert bot.deposit is None
    finally:
        app.dependency_overrides.pop(get_bot_repository, None)


# --- 9: UNKNOWN -> no intents (MVP-6.9 regression) ------------------------------


async def test_unknown_position_state_blocks_all_intents() -> None:
    broker = FakeBroker()
    engine = _live_engine(broker)
    await engine.start()
    await engine.process(_context())
    assert engine.order_manager.list_orders() == []
    assert broker.place_calls == 0


# --- 10: FLAT + no active orders -> entry via the Risk Manager ------------------


async def test_flat_without_active_orders_allows_entry() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()  # successful reconciliation with no positions -> FLAT
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(deposit=Decimal("10000"), lot_size=10, currency="RUB"),
    )
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].side is OrderSide.BUY
    # 10000 RUB / 100 price = 100 units; 100 // 10 lots = 10 lots -> 100 units.
    assert orders[0].requested_quantity == Decimal("100")
    assert broker.place_calls == 1


async def test_flat_entry_quantities_round_down_to_lots() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(deposit=Decimal("10000"), lot_size=10, currency="RUB"),
    )
    await engine.start()
    # 10000 / 30 = 333.33 units -> 33 whole lots -> 330 units.
    await engine.process(_context(price=30.0))
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].requested_quantity == Decimal("330")


async def test_flat_entry_blocked_when_below_lot() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(deposit=Decimal("10"), lot_size=10, currency="RUB"),
    )
    await engine.start()
    with pytest.raises(SizingBelowLot):
        await engine.process(_context())
    assert om.list_orders() == []
    assert broker.place_calls == 0


async def test_flat_entry_blocked_when_lot_size_unavailable() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(
        broker, om=om, positions=pm, sizing=PositionSizing(base_nominal=Decimal("5000"))
    )
    await engine.start()
    with pytest.raises(LotSizeUnavailable):
        await engine.process(_context())
    assert om.list_orders() == []


async def test_flat_entry_blocked_when_currency_unavailable() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(base_nominal=Decimal("5000"), lot_size=1),
    )
    await engine.start()
    with pytest.raises(CurrencyUnavailable):
        await engine.process(_context())
    assert om.list_orders() == []


async def test_flat_entry_blocked_when_bot_cannot_be_correlated() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm, bot_id=None)
    await engine.start()
    await engine.process(_context())
    assert om.list_orders() == []
    assert broker.place_calls == 0


# --- 11: FLAT + active bot orders -> no entry -----------------------------------


async def test_flat_with_active_bot_orders_blocks_entry() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm)
    await engine.start()
    active = ExecutionIntent(
        intent_id="active-1",
        trade_id="",
        instrument_figi=FIGI,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        limit_price=Decimal("99"),
        account_id="acc-1",
        bot_id=1,
    )
    order = await om.submit(active)
    assert order.status not in TERMINAL_STATES
    await engine.process(_context())
    # No new entry while the bot's limit order is still working.
    assert [o for o in om.list_orders() if o.order_id != order.order_id] == []


async def test_flat_after_active_order_filled_allows_entry() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm)
    await engine.start()
    active = ExecutionIntent(
        intent_id="active-1",
        trade_id="",
        instrument_figi=FIGI,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        limit_price=Decimal("99"),
        account_id="acc-1",
        bot_id=1,
    )
    order = await om.submit(active)
    om.on_order_update(
        OrderUpdate(broker_order_id=order.broker_order_id, status=OrderState.FILLED)
    )
    assert order.status in TERMINAL_STATES
    await engine.process(_context())
    # The only non-terminal order is gone: entry proceeds.
    entries = [o for o in om.list_orders() if o.order_id != order.order_id]
    assert len(entries) == 1
    assert entries[0].side is OrderSide.BUY


# --- 12: absent position without reconciliation -> UNKNOWN -----------------------


def test_absent_position_without_successful_reconciliation_is_unknown() -> None:
    pm = PositionManager()
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.UNKNOWN
    # Fill-driven positions do not establish the live state either.
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.UNKNOWN
    # Only a successful reconciliation does.
    pm.mark_reconciled()
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.OPEN
    # A failed reconciliation invalidates the state again.
    pm.invalidate_reconciliation()
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.UNKNOWN
    # Restoring durable (snapshot) state is not a reconciliation.
    pm.mark_reconciled()
    pm.load_state([])
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.UNKNOWN


# --- 13: OPEN -> exits only, no new grid (MVP-6.9 regression) -------------------


async def test_open_position_submits_exit_only() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm)
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].requested_quantity == Decimal("10")
    assert orders[0].limit_price == Decimal("110")  # 10% TP from 100


# --- 14: sign mismatch -> no intents ----------------------------------------------


async def test_sign_mismatch_blocks_all_intents() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.SELL, Decimal("5"), Decimal("100"))
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm)
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.SIGN_MISMATCH
    await engine.start()
    await engine.process(_context())
    assert om.list_orders() == []
    assert broker.place_calls == 0


# --- 15: backtest semantics unchanged ---------------------------------------------


def test_backtest_style_evaluate_unchanged() -> None:
    # The Backtest engine calls evaluate(config, context) without a position
    # quantity and without the live sizing source: the call must not error and
    # must produce no exits/grid.
    plan = _se().evaluate(_strategy(), _context())
    assert plan.entry is not None
    assert plan.exits == []
    assert plan.grid == []
    # With an explicit base nominal the DCA math is unchanged (MVP-6.8).
    plan = _se().evaluate(_strategy(), _context(), base_nominal=Decimal("5000"))
    assert len(plan.grid) == 1
    assert plan.grid[0].quantity == pytest.approx(50.0)


async def test_repository_update_deposit_persists_value() -> None:
    # The repository write path used by the API (C5) updates the ORM entity.
    bot = Bot(id=1, name="bot", strategy_version_id=1, account_id=1, instrument_id=1)
    bot.deposit = None
    assert bot.deposit is None
    repo = _FakeBotRepository(bot)
    updated = await repo.update_deposit(bot, Decimal("123"))
    assert updated.deposit == Decimal("123")
    assert bot.deposit == Decimal("123")


# --- B1: entry sizing is an entry-only precondition (round-1 correction) ---------


async def test_open_without_deposit_submits_exit_only() -> None:
    # B1 regression 1: an open deal must keep its exit even when the deposit
    # is unset — the base nominal is resolved only on the FLAT entry path.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm, sizing=PositionSizing())
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].requested_quantity == Decimal("10")
    assert orders[0].limit_price == Decimal("110")


async def test_open_signal_mode_submits_exit_only() -> None:
    # B1 regression 2: SIGNAL grid mode has no deposit->nominal rule, but the
    # open deal's exit must not depend on it.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(deposit=Decimal("10000"), lot_size=10, currency="RUB"),
        strategy=_strategy(dca_grid=DCAGridConfig(mode=TradingMode.SIGNAL, levels=3)),
    )
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].requested_quantity == Decimal("10")


async def test_open_custom_over_100_submits_exit_only() -> None:
    # B1 regression 3: a CUSTOM percent sum > 100% blocks entries only — the
    # open deal's exit still proceeds.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(deposit=Decimal("10000"), lot_size=10, currency="RUB"),
        strategy=_strategy(
            dca_grid=DCAGridConfig(
                mode=TradingMode.CUSTOM,
                custom_levels=[
                    CustomLevel(offset_percent=0.0, nominal_percent=60.0),
                    CustomLevel(offset_percent=1.0, nominal_percent=50.0),
                ],
            )
        ),
    )
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].requested_quantity == Decimal("10")


async def test_flat_without_deposit_blocked_explicitly() -> None:
    # B1 regression 4: a FLAT entry with no deposit still fails explicitly
    # (no fabricated quantity) and places nothing.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    engine = _live_engine(broker, om=om, positions=pm, sizing=PositionSizing())
    await engine.start()
    with pytest.raises(SizingNotConfigured):
        await engine.process(_context())
    assert om.list_orders() == []
    assert broker.place_calls == 0


# --- C6: deposit edits apply from the next deal -----------------------------------


async def test_deposit_edit_applies_from_next_flat_entry() -> None:
    # C6: the deposit is read at each FLAT entry, so an edit while the bot is
    # RUNNING (no restart) applies from the next deal.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.mark_reconciled()
    deposit = DepositHolder(Decimal("10000"))
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(lot_size=10, currency="RUB"),
        deposit_provider=deposit,
    )
    await engine.start()
    await engine.process(_context())  # 10000 RUB -> 100 units
    first = om.list_orders()[0]
    assert first.side is OrderSide.BUY
    assert first.requested_quantity == Decimal("100")
    # Terminate the first order without a fill so the position stays FLAT.
    om.on_order_update(
        OrderUpdate(broker_order_id=first.broker_order_id, status=OrderState.FILLED)
    )
    deposit.value = Decimal("20000")
    await engine.process(_context())  # 20000 RUB -> 200 units
    orders = om.list_orders()
    assert len(orders) == 2
    assert orders[1].side is OrderSide.BUY
    assert orders[1].requested_quantity == Decimal("200")


async def test_deposit_edit_while_open_affects_only_next_deal() -> None:
    # C6: a deposit edit while a deal is OPEN must not change the open deal's
    # exit; the new deposit is used only when the next FLAT entry happens.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    deposit = DepositHolder(Decimal("10000"))
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(lot_size=10, currency="RUB"),
        deposit_provider=deposit,
    )
    await engine.start()
    await engine.process(_context())
    exit_order = om.list_orders()[0]
    assert exit_order.side is OrderSide.SELL
    assert exit_order.requested_quantity == Decimal("10")
    # Edit while OPEN: repeated cycles keep the same exit (stable intent id)
    # and never read the deposit.
    deposit.value = Decimal("20000")
    await engine.process(_context())
    assert len(om.list_orders()) == 1
    assert broker.place_calls == 1
    # Close the deal: the exit fill returns the position to FLAT.
    om.apply_fill(
        Fill(
            fill_id="fill-1",
            internal_order_id=exit_order.order_id,
            quantity=Decimal("10"),
            price=Decimal("110"),
            timestamp=T0,
        )
    )
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.FLAT
    await engine.process(_context())  # next deal uses the new deposit
    orders = om.list_orders()
    assert len(orders) == 2
    assert orders[1].side is OrderSide.BUY
    assert orders[1].requested_quantity == Decimal("200")


async def test_deposit_cleared_while_open_exit_continues_then_flat_blocks() -> None:
    # C6: clearing the deposit while a deal is OPEN keeps the exit alive; the
    # next FLAT entry then fails explicitly (no deposit, no fabricated value).
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    deposit = DepositHolder(Decimal("10000"))
    engine = _live_engine(
        broker,
        om=om,
        positions=pm,
        sizing=PositionSizing(lot_size=10, currency="RUB"),
        deposit_provider=deposit,
    )
    await engine.start()
    await engine.process(_context())
    exit_order = om.list_orders()[0]
    assert exit_order.side is OrderSide.SELL
    # Clear the deposit while OPEN: the exit is unaffected.
    deposit.value = None
    await engine.process(_context())
    assert len(om.list_orders()) == 1
    assert broker.place_calls == 1
    # Close the deal; the next FLAT entry cannot be sized -> explicit failure.
    om.apply_fill(
        Fill(
            fill_id="fill-1",
            internal_order_id=exit_order.order_id,
            quantity=Decimal("10"),
            price=Decimal("110"),
            timestamp=T0,
        )
    )
    assert pm.position_state(FIGI, Direction.LONG) is LivePositionState.FLAT
    with pytest.raises(SizingNotConfigured):
        await engine.process(_context())
    assert len(om.list_orders()) == 1


# --- B2: the production deposit provider must read the current DB value ---------


async def test_production_deposit_provider_reads_fresh_value_after_other_session_commit(
    tmp_path,
) -> None:
    # B2 (round-2 review): the live service uses a long-lived session
    # (expire_on_commit=False); a deposit edit arrives through a different
    # per-request session. The provider wired in production must return the
    # current database value, not the identity-map copy of the bot.
    #
    # A file-based database gives each session its own connection (as in
    # production). The long-lived session keeps a strong reference to the
    # loaded Bot: the Session identity map is a WeakInstanceDict, so a plain
    # get would silently re-read the row once the transient result is
    # collected — holding the instance makes the staleness scenario
    # deterministic and proves the provider needs the fresh read.
    db_path = tmp_path / "b2.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Bot.__table__]))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as seed:
            seed.add(
                Bot(
                    id=1,
                    name="bot",
                    strategy_version_id=1,
                    account_id=1,
                    instrument_id=1,
                    deposit=Decimal("10000"),
                )
            )
            await seed.commit()

        # Session A: the long-lived live session, loaded at startup.
        async with maker() as live:
            live_repo = BotRepository(live)
            bot = await live_repo.get(1)
            assert bot.deposit == Decimal("10000")
            # End the live read transaction (the live session does commit
            # between cycles); expire_on_commit=False keeps the identity-map
            # copy of the Bot cached in this session.
            await live.commit()

            # Session B: the per-request API session edits the deposit.
            async with maker() as api:
                api_repo = BotRepository(api)
                await api_repo.update_deposit(await api_repo.get(1), Decimal("20000"))
            # A plain get still returns the cached copy (the B2 staleness
            # scenario); the production provider must not — it is wired to a
            # fresh database read.
            assert bot.deposit == Decimal("10000")
            assert (await live_repo.get(1)).deposit == Decimal("10000")
            provider = make_deposit_provider(live_repo, 1)
            assert await provider() == Decimal("20000")

            # A clearing edit through the API session is visible the same way.
            await live.commit()
            async with maker() as api2:
                api2_repo = BotRepository(api2)
                await api2_repo.update_deposit(await api2_repo.get(1), None)
            assert await provider() is None
    finally:
        await engine.dispose()
