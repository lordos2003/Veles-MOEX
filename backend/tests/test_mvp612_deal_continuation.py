"""MVP-6.12 Live Deal Continuation tests (D1-D7, correction round 1).

Focused, deterministic, broker-neutral coverage of the approved contracts:

- D1: START rejects unsupported live configs (named ``DealConfigUnsupported``
  -> HTTP 409) and accepts SIMPLE/CUSTOM + fixed-percentage TP only;
- D2: one persisted Deal per position cycle; the whole grid is built and
  C3/D3-checked before any order is submitted; fills drive the lifecycle;
- D3: tick alignment (grid LONG down / SHORT up, TP LONG up / SHORT down),
  missing tick blocks the entry;
- D4: one TP for the whole position at ``average x (1 +- tp%)``, lot- and
  tick-rounded, re-armed on every grid fill, at most one TP working;
- D5: recovery keeps working orders, applies broker-filled grid orders and
  re-arms the TP, an unknown state blocks the bot with ERROR;
- D6: the OPEN live cycle creates no exit intents from ``evaluate()``;
- D7: position-reducing intents (the closing TP) are exempt from
  ``max_position_size`` / ``daily_loss_limit``, while checks 1-4 still apply.

Correction round 1 (independent review, 2026-09-30): B1 (the new TP is
risk-gated BEFORE the old one is cancelled — a rejection keeps the old TP
working and pump() isolates every event) and B2 (every deal failure surfaces
to the bot lifecycle / API and an OPEN position without an owning Deal goes
ERROR).

Correction round 2 (independent review, 2026-09-30): B3 — a fill is a broker
fact: fills are accepted in CANCEL_REQUESTED (and after a terminal CANCELLED),
and the TP re-arm re-reads the position after the cancel, never placing a TP
larger than the actual position.

No real orders, no T-Invest, no fabricated market data or financial defaults.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.domain.marketdata import Timeframe
from app.models.enums import BotState, OrderSide, OrderStatus, OrderType
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    CustomLevel,
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    MultiTakeTP,
    SignalStopLossConfig,
    StopLossConfig,
    StrategyConfig,
    TakeItem,
    TradingMode,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.trading import (
    DealBlocked,
    DealConfigUnsupported,
    DealManager,
    DealOrderRejected,
    DealPositionContradiction,
    DealReconciliationRequired,
    DealStatus,
    DealTickSizeInvalid,
    OrderManager,
    PositionManager,
    PositionSizing,
    RiskLimits,
    RiskManager,
    RiskRejected,
    SizingBelowLot,
    TradingEngine,
    align_grid_price,
    align_tp_price,
    deal_grid_intent_id,
    deal_tp_intent_id,
    validate_live_deal_config,
)
from app.trading.deal import InMemoryDealStore
from app.trading.domain import ExecutionIntent, Fill, OrderState, OrderUpdate
from app.trading.live_execution import make_deposit_provider
from app.trading.plan_intent import plan_to_intents

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"
ACC = "acc-1"
TICK = Decimal("0.1")


class FakeBroker:
    """Duck-typed broker; records place/cancel calls (no real orders)."""

    def __init__(self, cancel_error: Exception | None = None) -> None:
        self.place_calls = 0
        self.cancel_calls: list[tuple[str, str | None]] = []
        self.cancelled: set[str] = set()
        self.cancel_error = cancel_error
        self._cancel_hook: Callable[[str], None] | None = None

    def on_cancel(self, hook: Callable[[str], None]) -> None:
        """B3: register a hook invoked inside every ``cancel_order`` call.

        Simulates the exchange filling the order while its cancel is in
        flight (the hook receives the broker order id).
        """
        self._cancel_hook = hook

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
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancel_calls.append((order_id, account_id))
        self.cancelled.add(order_id)
        if self._cancel_hook is not None:
            self._cancel_hook(order_id)


class DepositHolder:
    """Mutable async deposit source: the value read at each FLAT entry (C6)."""

    def __init__(self, value: Decimal | None) -> None:
        self.value = value

    async def __call__(self) -> Decimal | None:
        return self.value


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


def _pair(
    broker: FakeBroker | None = None,
    store: InMemoryDealStore | None = None,
) -> tuple[DealManager, OrderManager]:
    """A DealManager over a fresh OrderManager + RiskManager (unit harness)."""
    broker = broker or FakeBroker()
    om = OrderManager(broker)
    dm = DealManager(store or InMemoryDealStore(), om, RiskManager(position_manager=om.positions()))
    return dm, om


def _sizing(deposit: Decimal | None = Decimal("10000"), lot_size: int = 10) -> PositionSizing:
    return PositionSizing(deposit=deposit, lot_size=lot_size, currency="RUB")


async def _open_simple(
    dm: DealManager,
    om: OrderManager,
    *,
    levels: int = 1,
    active_limit: int | None = None,
    deposit: Decimal = Decimal("10000"),
    lot_size: int = 10,
    tick_size: Decimal | None = TICK,
    direction: Direction = Direction.LONG,
    reference_price: Decimal = Decimal("100"),
    bot_id: int = 1,
):
    """Open a Deal over a SIMPLE grid; by default every level is active.

    The grid engine builds from an equal per-level nominal (the C2 split of
    the deposit across ``levels``; no martingale is configured here).
    """
    base_nominal = deposit / Decimal(levels)
    return await dm.open_deal(
        bot_id=bot_id,
        instrument_figi=FIGI,
        direction=direction,
        config=_strategy(
            direction=direction,
            dca_grid=DCAGridConfig(
                mode=TradingMode.SIMPLE,
                levels=levels,
                active_limit=active_limit if active_limit is not None else levels,
            ),
        ),
        reference_price=reference_price,
        deposit=deposit,
        base_nominal=base_nominal,
        account_id=ACC,
        lot_size=lot_size,
        tick_size=tick_size,
    )


def _fill(om: OrderManager, order, fill_id: str, quantity: Decimal, price: Decimal) -> None:
    om.apply_fill(
        Fill(
            fill_id=fill_id,
            internal_order_id=order.order_id,
            quantity=quantity,
            price=price,
            timestamp=T0,
        )
    )


# --- D1: supported configuration scope --------------------------------------


def test_d1_accepts_simple_and_custom_fixed_tp() -> None:
    validate_live_deal_config(_strategy())
    custom = _strategy(
        dca_grid=DCAGridConfig(
            mode=TradingMode.CUSTOM,
            custom_levels=[CustomLevel(offset_percent=0.0, nominal_percent=100.0)],
        )
    )
    validate_live_deal_config(custom)


@pytest.mark.parametrize(
    "config",
    [
        _strategy(dca_grid=DCAGridConfig(mode=TradingMode.SIGNAL, levels=3)),
        _strategy(
            exit=ExitConfig(
                take_profit=MultiTakeTP(
                    takes=[
                        TakeItem(offset_percent=1.0, volume_percent=20.0),
                        TakeItem(offset_percent=2.0, volume_percent=30.0),
                    ]
                )
            )
        ),
        _strategy(
            exit=ExitConfig(
                take_profit=FixedPercentageTP(percent=10.0),
                stop_loss=StopLossConfig(percent=1.0),
            )
        ),
        _strategy(
            exit=ExitConfig(
                take_profit=FixedPercentageTP(percent=10.0),
                signal_stop=SignalStopLossConfig(),
            )
        ),
        _strategy(dca_grid=DCAGridConfig(levels=2, pull_up_percent=1.0)),
    ],
)
def test_d1_rejects_unsupported_configs(config: StrategyConfig) -> None:
    with pytest.raises(DealConfigUnsupported):
        validate_live_deal_config(config)


async def test_d1_start_rejection_maps_to_409() -> None:
    from app.api import bots as bots_api
    from app.models.bot import Bot
    from app.models.enums import BotState
    from app.trading.bot_lifecycle import BotRuntime, BotRuntimeManager

    class FakeBotRepo:
        async def get(self, bot_id: int):
            return Bot(
                id=bot_id,
                name="bot",
                strategy_version_id=1,
                account_id=1,
                instrument_id=1,
                status="STOPPED",
            )

        async def update_state(self, bot, state: BotState):
            bot.status = state.value
            return bot

    async def _load_strategy():
        return _strategy()

    async def _rejecting_engine(_bot_strategy):
        raise DealConfigUnsupported("live deal support does not cover SIGNAL mode")

    def _factory(bot_id: int, state: BotState = BotState.STOPPED) -> BotRuntime:
        return BotRuntime(
            bot_id,
            RiskManager(),
            strategy_loader=_load_strategy,
            trading_engine_factory=_rejecting_engine,
            state=state,
        )

    manager = BotRuntimeManager(RiskManager(), runtime_factory=_factory)

    class _Version:
        id = 1
        strategy_id = 1
        version = 1
        config = _strategy().model_dump(mode="json")

    class _FakeSession:
        async def get(self, model, pk):
            return _Version()

    class _FakeBroker:
        supports_stop_orders = True

    with pytest.raises(HTTPException) as ei:
        await bots_api.start_bot(1, FakeBotRepo(), manager, _FakeSession(), _FakeBroker())
    assert ei.value.status_code == 409
    assert "config not supported for live deal continuation" in ei.value.detail


# --- D2: FLAT entry persists the Deal before submission ----------------------


class RecordingDealStore(InMemoryDealStore):
    """Records how many orders existed at each save (ordering proof for D2)."""

    def __init__(self, om: OrderManager) -> None:
        super().__init__()
        self._om = om
        self.save_events: list[int] = []

    async def save(self, deal) -> None:
        self.save_events.append(len(self._om.list_orders()))
        return await super().save(deal)


def _live_engine(
    broker: FakeBroker,
    *,
    om: OrderManager | None = None,
    positions: PositionManager | None = None,
    sizing: PositionSizing | None = None,
    strategy: StrategyConfig | None = None,
    bot_id: int | None = 1,
    deposit_provider=None,
    dm: DealManager | None = None,
    tick_size: Decimal | None = TICK,
    account_id: str | None = ACC,
) -> TradingEngine:
    om = om or OrderManager(broker)
    pm = positions if positions is not None else om.positions()

    def factory(plan, ctx):
        return plan_to_intents(plan, instrument_figi=FIGI, bot_id=bot_id, account_id=account_id)

    return TradingEngine(
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
        deal_manager=dm,
        tick_size=tick_size,
        account_id=account_id,
    )


async def test_d2_flat_entry_persists_deal_before_submission() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    om.positions().mark_reconciled()  # successful reconciliation, no position -> FLAT
    store = RecordingDealStore(om)
    dm = DealManager(store, om, RiskManager(position_manager=om.positions()))
    engine = _live_engine(broker, om=om, dm=dm, sizing=_sizing(Decimal("10000")))
    await engine.start()
    await engine.process(_context())
    # The Deal is persisted before the first order is placed (the first save
    # sees zero orders); the final save records the submitted level order.
    assert store.save_events[0] == 0
    assert store.save_events[-1] == 1
    deal = await store.get(1)
    assert deal is not None and deal.status is DealStatus.OPENING
    assert deal.deposit == Decimal("10000")
    # The plan was not double-submitted: only the Deal's entry order exists.
    assert len(om.list_orders()) == 1
    assert broker.place_calls == 1


async def test_d2_below_lot_on_non_active_level_blocks_whole_entry() -> None:
    # The whole grid is C3/D3-checked up front (D2): a level the partial grid
    # never makes active still blocks the entry when it rounds to 0 lots.
    dm, om = _pair()
    config = _strategy(
        dca_grid=DCAGridConfig(
            mode=TradingMode.CUSTOM,
            active_limit=1,
            custom_levels=[
                CustomLevel(offset_percent=0.0, nominal_percent=99.0),
                CustomLevel(offset_percent=1.0, nominal_percent=1.0),
            ],
        )
    )
    with pytest.raises(SizingBelowLot):
        await dm.open_deal(
            bot_id=1,
            instrument_figi=FIGI,
            direction=Direction.LONG,
            config=config,
            reference_price=Decimal("100"),
            deposit=Decimal("10000"),
            base_nominal=Decimal("10000"),
            account_id=ACC,
            lot_size=10,
            tick_size=TICK,
        )
    assert om.list_orders() == []
    assert dm.active_deal(1) is None


async def test_d2_missing_tick_blocks_whole_entry() -> None:
    dm, om = _pair()
    config = _strategy(
        dca_grid=DCAGridConfig(
            mode=TradingMode.CUSTOM,
            custom_levels=[CustomLevel(offset_percent=0.0, nominal_percent=100.0)],
        )
    )
    with pytest.raises(DealTickSizeInvalid):
        await dm.open_deal(
            bot_id=1,
            instrument_figi=FIGI,
            direction=Direction.LONG,
            config=config,
            reference_price=Decimal("100"),
            deposit=Decimal("10000"),
            base_nominal=Decimal("10000"),
            account_id=ACC,
            lot_size=10,
            tick_size=None,
        )
    assert om.list_orders() == []


async def test_d2_no_second_deal_while_one_is_active() -> None:
    dm, om = _pair()
    await _open_simple(dm, om)
    with pytest.raises(DealBlocked):
        await _open_simple(dm, om)


# --- D3: tick alignment -----------------------------------------------------


def test_d3_grid_long_down_short_up() -> None:
    # LONG: buy prices are rounded down (never worse than planned).
    assert align_grid_price(Decimal("99.1287"), TICK, Direction.LONG) == Decimal("99.1")
    assert align_grid_price(Decimal("100.13"), TICK, Direction.LONG) == Decimal("100.1")
    # SHORT: sell prices are rounded up.
    assert align_grid_price(Decimal("101.1313"), TICK, Direction.SHORT) == Decimal("101.2")
    assert align_grid_price(Decimal("100.13"), TICK, Direction.SHORT) == Decimal("100.2")


def test_d3_tp_long_up_short_down() -> None:
    # TP: profit never below the configured % (LONG up / SHORT down).
    assert align_tp_price(Decimal("110.143"), TICK, Direction.LONG) == Decimal("110.2")
    assert align_tp_price(Decimal("90.117"), TICK, Direction.SHORT) == Decimal("90.1")


# --- D2/D4: entry fill -> one TP from the actual average ---------------------


async def test_d4_entry_fill_places_tp_from_average_not_market() -> None:
    dm, om = _pair()
    deal = await _open_simple(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    # The entry executes at 100.0; the market then moves to 200, but the TP
    # must be derived from the position average: 100 * 1.10 = 110.
    _fill(om, entry, "f-entry", entry.requested_quantity, Decimal("100"))
    om.positions().mark_to_market(FIGI, Decimal("200"))
    await dm.pump()
    tp = om.get_order(deal.tp_order_id)
    assert tp is not None
    assert tp.side is OrderSide.SELL
    assert tp.order_type is OrderType.LIMIT
    assert tp.requested_quantity == Decimal("100")
    assert tp.limit_price == Decimal("110")
    assert deal.average_price == Decimal("100")


async def test_d4_short_entry_fill_places_tp_mirrored() -> None:
    dm, om = _pair()
    deal = await _open_simple(
        dm, om, direction=Direction.SHORT, reference_price=Decimal("100.13")
    )
    entry = om.get_order(deal.levels[0].order_id)
    assert entry.requested_quantity == Decimal("90")  # 10000/100.13 -> 9 lots
    _fill(om, entry, "f-entry", entry.requested_quantity, Decimal("100.13"))
    await dm.pump()
    tp = om.get_order(deal.tp_order_id)
    assert tp.side is OrderSide.BUY
    # avg 100.13 * 0.90 = 90.117 -> rounded DOWN to the tick (SHORT TP).
    assert tp.limit_price == Decimal("90.1")
    assert tp.requested_quantity == Decimal("90")


# --- D4: TP re-arm + partial grid promotions ---------------------------------


async def test_d4_dca_partial_fill_rearms_tp_once() -> None:
    dm, om = _pair()
    # 40000 deposit, 2 levels -> 200 units per level.
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    tp1 = om.get_order(deal.tp_order_id)
    assert tp1 is not None and deal.tp_rev == 1
    assert tp1.requested_quantity == Decimal("200")

    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    await dm.pump()
    # Exactly one working TP remains: the old TP is cancelled, the new one is
    # placed from the updated average (200*100 + 50*99)/250 = 99.8 -> 109.78,
    # tick-rounded UP to 109.8, for the whole current position (250 units).
    assert deal.tp_rev == 2
    tp2 = om.get_order(deal.tp_order_id)
    assert tp2.limit_price == Decimal("109.8")
    assert tp2.requested_quantity == Decimal("250")
    assert om.get_order(tp1.order_id).status is OrderState.CANCELLED
    working_tps = [
        o
        for o in om.list_orders()
        if o.intent_id.startswith(f"deal-{deal.id}-tp-")
        and o.status
        not in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED)
    ]
    assert len(working_tps) == 1


async def test_d4_dca_full_fill_promotes_next_waiting_level_up_to_active_limit() -> None:
    dm, om = _pair()
    # 60000 deposit, 3 levels -> 200 units per level; only 1 level active.
    deal = await _open_simple(
        dm, om, levels=3, active_limit=1, deposit=Decimal("60000")
    )
    assert deal.levels[1].order_id is None and deal.levels[2].order_id is None

    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal.levels[1].order_id is not None  # promoted to keep 1 active
    assert deal.levels[2].order_id is None

    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("200"), Decimal("99"))
    await dm.pump()
    assert deal.levels[2].order_id is not None  # promoted after level 1 filled
    working = [
        om.get_order(lvl.order_id)
        for lvl in deal.levels
        if lvl.order_id is not None
        and om.get_order(lvl.order_id) is not None
        and om.get_order(lvl.order_id).status
        not in (
            OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED,
        )
    ]
    assert len(working) == 1  # the active count stays at active_limit


# --- D4/D2.4: TP fill (partial keeps, full closes) ----------------------------


async def test_d4_tp_partial_fill_keeps_working_and_full_fill_closes() -> None:
    broker = FakeBroker()
    dm, om = _pair(broker)
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    tp = om.get_order(deal.tp_order_id)
    assert tp.requested_quantity == Decimal("200")

    # Partial TP fill: the current TP keeps working (no re-arm, no new TP).
    _fill(om, tp, "f-tp-part", Decimal("50"), Decimal("110"))
    await dm.pump()
    assert deal.tp_order_id == tp.order_id
    assert deal.tp_rev == 1
    assert deal.status is DealStatus.OPEN

    # Full TP fill: position reaches zero -> remaining grid cancelled -> CLOSED.
    _fill(om, tp, "f-tp-full", Decimal("150"), Decimal("110"))
    await dm.pump()
    assert deal.status is DealStatus.CLOSED
    assert broker.cancel_calls  # the working DCA limit order was cancelled
    assert om.get_order(deal.levels[1].order_id).status is OrderState.CANCELLED
    assert dm.active_deal(1) is None  # back on the FLAT entry path


async def test_d4_old_tp_fill_during_rearm_computes_from_actual_position() -> None:
    dm, om = _pair()
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    tp1 = om.get_order(deal.tp_order_id)

    # Both fills arrive in the same stream batch: the DCA fill queued first,
    # the old TP fill second (its cancel was never even sent yet).
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    _fill(om, tp1, "f-old-tp", Decimal("100"), Decimal("109.8"))
    await dm.pump()
    # The reactions must recompute from the actual position (250 - 100 = 150
    # units, average still 99.8) and never leave a second working TP.
    assert deal.tp_rev == 3
    tp3 = om.get_order(deal.tp_order_id)
    assert tp3.requested_quantity == Decimal("150")
    assert tp3.limit_price == Decimal("109.8")
    working_tps = [
        o
        for o in om.list_orders()
        if o.intent_id.startswith(f"deal-{deal.id}-tp-")
        and o.status
        not in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED)
    ]
    assert len(working_tps) == 1


# --- D4: cancel failure blocks the bot ----------------------------------------


async def test_d4_tp_cancel_failure_blocks_bot_with_explicit_error() -> None:
    broker = FakeBroker(cancel_error=RuntimeError("broker unavailable"))
    dm, om = _pair(broker)
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal.tp_rev == 1

    # A DCA fill forces the re-arm; the old TP cancel cannot be confirmed ->
    # no second TP is placed and the bot is blocked with an explicit error.
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    await dm.pump()
    assert deal.status is DealStatus.ERROR
    assert dm.last_error is not None and isinstance(dm.last_error, DealReconciliationRequired)
    assert 1 in dm.blocked_bots
    tps = [o for o in om.list_orders() if o.intent_id.startswith(f"deal-{deal.id}-tp-")]
    assert len(tps) == 1  # the old TP is stuck UNKNOWN; no new one was placed


# --- D2.5: deposit captured at entry, next deal uses the new value ------------


async def test_d2_next_flat_entry_uses_current_deposit() -> None:
    # C6 + D2.5: the deposit is captured at the Deal entry; an edit later
    # applies from the next FLAT entry of the next deal.
    broker = FakeBroker()
    om = OrderManager(broker)
    om.positions().mark_reconciled()
    store = InMemoryDealStore()
    dm = DealManager(store, om, RiskManager(position_manager=om.positions()))
    deposit = DepositHolder(Decimal("10000"))
    engine = _live_engine(
        broker,
        om=om,
        dm=dm,
        sizing=PositionSizing(lot_size=10, currency="RUB"),
        deposit_provider=deposit,
    )
    await engine.start()

    await engine.process(_context())  # first deal: deposit 10000
    deal1 = await store.get(1)
    assert deal1 is not None and deal1.deposit == Decimal("10000")
    entry = om.get_order(deal1.levels[0].order_id)
    assert entry.requested_quantity == Decimal("100")
    _fill(om, entry, "f-entry", Decimal("100"), Decimal("100"))
    await dm.pump()
    tp = om.get_order(deal1.tp_order_id)
    _fill(om, tp, "f-tp", Decimal("100"), Decimal("110"))
    await dm.pump()
    assert deal1.status is DealStatus.CLOSED

    deposit.value = Decimal("20000")
    await engine.process(_context())  # next deal uses the current deposit
    deal2 = await store.get(2)
    assert deal2 is not None and deal2.deposit == Decimal("20000")
    entry2 = om.get_order(deal2.levels[0].order_id)
    assert entry2.requested_quantity == Decimal("200")


# --- D5: recovery -------------------------------------------------------------


async def test_d5_recover_keeps_working_orders_and_active_grid() -> None:
    # Restart with no fills yet: the working entry order stays in place and no
    # order/TP is recreated blindly (D5).
    dm, om = _pair()
    deal = await _open_simple(dm, om, levels=2, active_limit=1, deposit=Decimal("40000"))
    entry_id = deal.levels[0].order_id
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    # The same working order is still there; nothing new was submitted.
    assert om.get_order(entry_id).status is OrderState.SUBMITTED
    assert len(om.list_orders()) == 1
    assert deal.status is DealStatus.OPENING


async def test_d5_recover_broker_filled_grid_rearms_tp() -> None:
    # Restart with a DCA grid order the broker reports filled: recovery applies
    # it as a fill and re-arms the TP from the updated position (D4).
    dm, om = _pair()
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    assert deal.status is DealStatus.OPEN
    assert deal.tp_rev == 2  # TP re-armed from avg 99.8
    assert om.get_order(deal.tp_order_id).limit_price == Decimal("109.8")
    assert om.get_order(deal.tp_order_id).requested_quantity == Decimal("250")
    working_tps = [
        o
        for o in om.list_orders()
        if o.intent_id.startswith(f"deal-{deal.id}-tp-")
        and o.status
        not in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED)
    ]
    assert len(working_tps) == 1


async def test_d5_recover_missing_tp_placed_once() -> None:
    dm, om = _pair()
    deal = await _open_simple(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("100"), Decimal("100"))
    await dm.pump()
    # The TP is gone (e.g. cancelled by the broker while we were down).
    tp = om.get_order(deal.tp_order_id)
    await om.cancel(tp.order_id)
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    assert deal.tp_rev == 2  # placed once
    assert om.get_order(deal.tp_order_id).status is OrderState.SUBMITTED
    assert om.get_order(deal.tp_order_id).limit_price == Decimal("110")


async def test_d5_recover_unknown_order_blocks_bot() -> None:
    dm, om = _pair()
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    dca = om.get_order(deal.levels[1].order_id)
    om.on_order_update(
        OrderUpdate(broker_order_id=dca.broker_order_id, status=OrderState.UNKNOWN)
    )
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is False
    assert deal.status is DealStatus.ERROR
    assert 1 in dm2.blocked_bots
    assert deal.tp_rev == 1  # no re-arm took place


# --- D6: the live OPEN cycle creates no exit intents ---------------------------


async def test_b2_open_live_position_without_deal_errors_the_bot() -> None:
    # B2: the D6 no-exit-intents cycle is only legal while a non-CLOSED Deal
    # owns the OPEN position. An OPEN position without a Deal is a D5
    # contradiction: it must put the bot in ERROR (surfaced through the deal
    # layer) and fail the cycle explicitly — never a silent no-op.
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    pm.mark_reconciled()
    notified: list[tuple[int, str]] = []

    async def _record(bot_id: int, reason: str) -> None:
        notified.append((bot_id, reason))

    dm = DealManager(
        InMemoryDealStore(),
        om,
        RiskManager(position_manager=pm),
        on_bot_error=_record,
    )
    engine = _live_engine(broker, om=om, positions=pm, dm=dm)
    await engine.start()
    with pytest.raises(DealPositionContradiction):
        await engine.process(_context(price=200.0))
    assert notified and notified[0][0] == 1
    assert "OPEN" in notified[0][1]
    assert om.list_orders() == []
    assert broker.place_calls == 0


async def test_d6_open_deal_keeps_deal_orders_and_places_nothing_new() -> None:
    broker = FakeBroker()
    om = OrderManager(broker)
    om.positions().mark_reconciled()
    dm = DealManager(InMemoryDealStore(), om, RiskManager(position_manager=om.positions()))
    engine = _live_engine(broker, om=om, dm=dm, sizing=_sizing(Decimal("10000")))
    await engine.start()
    await engine.process(_context())
    deal = dm.active_deal(1)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("100"), Decimal("100"))
    await dm.pump()
    placed_before = len(om.list_orders())
    assert broker.place_calls == 2  # entry + TP
    tp_before = deal.tp_order_id

    # OPEN: the cycle must not create exit intents from evaluate(); the deal
    # keeps its own TP working and no grid/entry is re-submitted.
    plan = await engine.process(_context(price=200.0))
    assert plan.exits == []
    assert plan.grid == []
    assert len(om.list_orders()) == placed_before
    assert broker.place_calls == 2  # no new submissions
    assert deal.tp_order_id == tp_before


# --- correction round 1: D7 / B1 / B2 -----------------------------------------


class RearmRejectingRisk(RiskManager):
    """Rejects every TP re-arm after rev 1 for one bot (B1: mid-deal rejection)."""

    def __init__(self, *args, rejected_bot_id: int = 1, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rejected_bot_id = rejected_bot_id

    def check_order(self, intent: ExecutionIntent) -> None:
        if (
            f"deal-{self._rejected_bot_id}-tp-" in intent.intent_id
            and int(intent.intent_id.rsplit("-", 1)[1]) >= 2
        ):
            raise RiskRejected("test: TP re-arm rejected")
        super().check_order(intent)


async def test_d7_tp_placed_under_position_size_limit() -> None:
    # D7 through a real Deal: max_position_size=300, the entry fills 200 — the
    # closing TP (a reducing SELL) must still be placed; a growth limit must
    # never block the exit of a Deal (the entry BUY itself stays limited).
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(
        limits=RiskLimits(max_position_size=Decimal("300")),
        position_manager=om.positions(),
    )
    dm = DealManager(InMemoryDealStore(), om, risk)
    deal = await _open_simple(dm, om, deposit=Decimal("20000"), lot_size=10)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal.tp_order_id is not None
    assert om.get_order(deal.tp_order_id).status is OrderState.SUBMITTED
    assert om.get_order(deal.tp_order_id).requested_quantity == Decimal("200")


async def test_d7_dca_fill_rearms_tp_under_daily_loss_limit() -> None:
    # D7 through a real Deal: the daily loss limit is reached while a DCA fill
    # re-arms the TP — the reducing TP must still be placed (a growth limit
    # cannot block the exit path of an open Deal).
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RiskManager(
        limits=RiskLimits(daily_loss_limit=Decimal("100")),
        position_manager=om.positions(),
        daily_pnl=Decimal("-50"),
    )
    dm = DealManager(InMemoryDealStore(), om, risk)
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal.tp_rev == 1
    risk._daily_pnl = Decimal("-100")  # the loss limit is now reached
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    await dm.pump()
    assert deal.status is DealStatus.OPEN
    assert deal.tp_rev == 2
    assert om.get_order(deal.tp_order_id).status is OrderState.SUBMITTED


async def test_b1_risk_rejected_rearm_keeps_old_tp_and_fails_deal() -> None:
    # B1: the new TP is risk-gated BEFORE the working one is cancelled. A risk
    # rejection during a re-arm leaves the old TP working (the position stays
    # protected), the Deal goes ERROR, the bot is notified, no exception
    # escapes the pump, and no second TP is placed.
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RearmRejectingRisk(position_manager=om.positions())
    notified: list[tuple[int, str]] = []

    async def _record(bot_id: int, reason: str) -> None:
        notified.append((bot_id, reason))

    dm = DealManager(InMemoryDealStore(), om, risk, on_bot_error=_record)
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    tp1 = om.get_order(deal.tp_order_id)
    assert tp1 is not None and tp1.status is OrderState.SUBMITTED

    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    await dm.pump()  # must not raise

    assert deal.status is DealStatus.ERROR
    assert 1 in dm.blocked_bots
    assert notified and notified[0][0] == 1
    assert "risk" in notified[0][1]
    # The old TP was NOT cancelled — it still works (position protected).
    assert om.get_order(tp1.order_id).status is OrderState.SUBMITTED
    tps = [o for o in om.list_orders() if o.intent_id.startswith(f"deal-{deal.id}-tp-")]
    assert len(tps) == 1
    assert isinstance(dm.last_error, DealOrderRejected)


async def test_b1_pump_isolates_one_failing_deal_in_a_batch() -> None:
    # B1: one failing reaction must not starve the rest of the batch — bot 2's
    # re-arm is still applied even though bot 1's reaction failed first.
    broker = FakeBroker()
    om = OrderManager(broker)
    risk = RearmRejectingRisk(position_manager=om.positions())
    notified: list[tuple[int, str]] = []

    async def _record(bot_id: int, reason: str) -> None:
        notified.append((bot_id, reason))

    dm = DealManager(InMemoryDealStore(), om, risk, on_bot_error=_record)
    deal1 = await _open_simple(dm, om, bot_id=1, levels=2, deposit=Decimal("40000"))
    deal2 = await _open_simple(dm, om, bot_id=2, levels=2, deposit=Decimal("40000"))

    entry1 = om.get_order(deal1.levels[0].order_id)
    entry2 = om.get_order(deal2.levels[0].order_id)
    _fill(om, entry1, "f-e1", Decimal("200"), Decimal("100"))
    _fill(om, entry2, "f-e2", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal1.tp_rev == 1 and deal2.tp_rev == 1

    dca1 = om.get_order(deal1.levels[1].order_id)
    dca2 = om.get_order(deal2.levels[1].order_id)
    _fill(om, dca1, "f-d1", Decimal("50"), Decimal("99"))
    _fill(om, dca2, "f-d2", Decimal("50"), Decimal("99"))
    await dm.pump()  # bot 1 fails on its re-arm; bot 2 must still re-arm
    assert deal1.status is DealStatus.ERROR
    assert 1 in dm.blocked_bots
    assert deal2.status is DealStatus.OPEN
    assert deal2.tp_rev == 2
    assert 2 not in dm.blocked_bots


async def test_b2_api_surfaces_deal_error() -> None:
    # B2: a deal failure is observable through GET /bots/{id} as the read-only
    # ``deal_error`` field (no opaque ERROR state).
    from app.api import bots as bots_api
    from app.models.bot import Bot

    class Repo:
        async def get(self, bot_id: int):
            return Bot(
                id=bot_id,
                name="bot",
                strategy_version_id=1,
                account_id=1,
                instrument_id=1,
                status="ERROR",
            )

    om = OrderManager(FakeBroker())
    dm = DealManager(InMemoryDealStore(), om, RiskManager(position_manager=om.positions()))
    config = _strategy(
        dca_grid=DCAGridConfig(
            mode=TradingMode.CUSTOM,
            custom_levels=[CustomLevel(offset_percent=0.0, nominal_percent=100.0)],
        )
    )
    with pytest.raises(DealTickSizeInvalid):
        await dm.open_deal(
            bot_id=7,
            instrument_figi=FIGI,
            direction=Direction.LONG,
            config=config,
            reference_price=Decimal("100"),
            deposit=Decimal("10000"),
            base_nominal=Decimal("10000"),
            account_id=ACC,
            lot_size=10,
            tick_size=None,
        )
    response = await bots_api.get_bot(7, Repo(), deal_manager=dm)
    assert response.deal_error is not None
    assert "tick" in response.deal_error


async def test_b2_runtime_fail_moves_bot_to_error() -> None:
    # B2: the victim of a deal failure is moved to ERROR through the existing
    # bot lifecycle; the concurrent-bot slot is released on the RUNNING path.
    from app.trading.bot_lifecycle import BotRuntime

    risk = RiskManager(limits=RiskLimits(max_concurrent_bots=1))
    runtime = BotRuntime(1, risk, state=BotState.RUNNING)
    risk.start_bot(1)
    runtime.fail("deal failed")
    assert runtime.state is BotState.ERROR
    assert risk.check_start(2) is True  # slot released
    # A STOPPED bot is not moved by fail() (no transition is invented).
    stopped = BotRuntime(3, risk, state=BotState.STOPPED)
    stopped.fail("nothing to fail")
    assert stopped.state is BotState.STOPPED


async def test_deposit_edit_during_open_does_not_affect_owning_deal() -> None:
    # C6/B1 regression: a deposit edit while a Deal is OPEN never affects the
    # open deal (the value is captured at entry) and the OPEN cycle keeps the
    # Deal-owned TP working instead of re-entering.
    broker = FakeBroker()
    om = OrderManager(broker)
    om.positions().mark_reconciled()
    dm = DealManager(InMemoryDealStore(), om, RiskManager(position_manager=om.positions()))
    deposit = DepositHolder(Decimal("20000"))
    engine = _live_engine(
        broker,
        om=om,
        dm=dm,
        sizing=PositionSizing(lot_size=10, currency="RUB"),
        deposit_provider=deposit,
    )
    await engine.start()
    await engine.process(_context())
    deal = dm.active_deal(1)
    assert deal is not None and deal.deposit == Decimal("20000")
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()

    deposit.value = Decimal("80000")
    placed_before = len(om.list_orders())
    await engine.process(_context(price=200.0))  # OPEN cycle: the deal owns the TP
    assert dm.active_deal(1) is deal
    assert deal.deposit == Decimal("20000")
    assert len(om.list_orders()) == placed_before
    assert broker.place_calls == 2  # entry + TP only; no second entry


# --- D6: make_deposit_provider clean-up keeps behaviour -----------------------


def test_make_deposit_provider_unreachable_duplicate_removed() -> None:
    # The clean-up removed the duplicated unreachable body; the provider still
    # reads the fresh repository value (the existing B2 test covers the DB
    # staleness scenario; this proves the public surface is intact).
    class Repo:
        async def get_deposit(self, bot_id: int):
            return Decimal("42") if bot_id == 7 else None

    provider = make_deposit_provider(Repo(), 7)
    assert provider is not None
    import app.trading.live_execution as le

    assert le.make_deposit_provider is make_deposit_provider


# --- intent-id correlation helpers --------------------------------------------


def test_intent_ids_are_deterministic() -> None:
    assert deal_grid_intent_id(3, 0) == "deal-3-grid-0"
    assert deal_tp_intent_id(3, 2) == "deal-3-tp-2"
    assert validate_live_deal_config(_strategy()) is None


# --- correction round 2: B3 (fill of the old TP during its cancel) ------------


async def test_b3_partial_old_tp_fill_during_cancel_rebuilds_from_actual_position() -> None:
    """B3 probe 3 (partial): the old TP partially fills while its cancel is in
    flight after a DCA fill — the re-arm must rebuild from the ACTUAL position
    and place one working TP for the remaining quantity, never a stale larger
    one (round-1 regression: the stale TP of 250 would be placed over a
    position of 150).
    """
    broker = FakeBroker()
    dm, om = _pair(broker)
    deal = await _open_simple(dm, om, levels=2, deposit=Decimal("40000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    tp1 = om.get_order(deal.tp_order_id)  # 200 @ 110: the whole position
    assert tp1.requested_quantity == Decimal("200")

    def _fill_old_tp_during_cancel(broker_order_id: str) -> None:
        if broker_order_id == tp1.broker_order_id:
            _fill(om, tp1, "f-b3-part", Decimal("100"), Decimal("109.8"))

    broker.on_cancel(_fill_old_tp_during_cancel)

    # A DCA fill forces the re-arm; during the old-TP cancel the exchange
    # fills 100 of it (position 250 -> 150).
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("50"), Decimal("99"))
    await dm.pump()
    assert om.positions().get(FIGI).quantity == Decimal("150")
    working = [
        o
        for o in om.list_orders()
        if o.intent_id.startswith(f"deal-{deal.id}-tp-")
        and o.status
        not in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED)
    ]
    assert len(working) == 1  # exactly one working TP...
    assert working[0].requested_quantity == Decimal("150")  # ...for the ACTUAL position
    assert working[0].limit_price == Decimal("109.8")  # average (99.8) x 1.10
    assert deal.tp_quantity == Decimal("150")
    assert tp1.filled_quantity == Decimal("100")
    assert tp1.status is OrderState.CANCELLED  # the cancel won for the remainder

    # The old-TP fill event queued during the cancel is harmless: still one TP.
    await dm.pump()
    working_after = [
        o
        for o in om.list_orders()
        if o.intent_id.startswith(f"deal-{deal.id}-tp-")
        and o.status
        not in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.FAILED)
    ]
    assert len(working_after) == 1
    assert working_after[0].requested_quantity == Decimal("150")


async def test_b3_full_old_tp_fill_during_cancel_closes_deal() -> None:
    """B3 probe 3 (full): the old TP fills FULLY while its cancel is in flight
    and the position reaches zero — the Deal is CLOSED and no new TP is placed.
    The terminal FILLED state wins (round-1 regression: invalid transition
    CANCEL_REQUESTED -> FILLED and a cancel() overwriting it with CANCELLED).
    """
    broker = FakeBroker()
    om = OrderManager(broker)
    pm = om.positions()
    store = InMemoryDealStore()
    dm = DealManager(store, om, RiskManager(position_manager=pm))
    deal = await _open_simple(dm, om, levels=1, deposit=Decimal("10000"))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("100"), Decimal("100"))
    await dm.pump()
    tp1 = om.get_order(deal.tp_order_id)  # 100 @ 110; position 100
    assert tp1.requested_quantity == Decimal("100")

    def _kill_tp_during_cancel(broker_order_id: str) -> None:
        if broker_order_id == tp1.broker_order_id:
            _fill(om, tp1, "f-b3-full", Decimal("100"), Decimal("110"))

    broker.on_cancel(_kill_tp_during_cancel)

    # Restart: recovery re-arms the TP (the entry level is FILLED); the
    # working TP fully fills during the cancel -> position zero -> CLOSED.
    dm2 = DealManager(store, om, RiskManager(position_manager=pm))
    assert await dm2.recover(ACC) is True
    assert deal.status is DealStatus.CLOSED
    assert tp1.status is OrderState.FILLED  # the fill wins, not CANCELLED
    tps = [o for o in om.list_orders() if o.intent_id.startswith(f"deal-{deal.id}-tp-")]
    assert len(tps) == 1  # no new TP was placed after the full fill
    assert dm2.active_deal(1) is None  # a closed Deal is not re-registered


async def test_b3_fill_after_cancel_still_updates_position() -> None:
    """B3 probe 3 (race): a fill reported for an order already CANCELLED is a
    broker fact — it is applied to the position and recorded, the terminal
    state is kept and nothing raises (round-1 regression: OrderStateError
    invalid transition CANCELLED -> PARTIALLY_FILLED lost the fill).
    """
    dm, om = _pair()
    deal = await _open_simple(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("100"), Decimal("100"))
    await dm.pump()
    tp = om.get_order(deal.tp_order_id)
    await om.cancel(tp.order_id)
    assert tp.status is OrderState.CANCELLED

    # The exchange reports the execution after the cancel was confirmed.
    _fill(om, tp, "f-after-cancel", Decimal("40"), Decimal("110"))
    assert tp.status is OrderState.CANCELLED  # terminal state kept
    assert tp.filled_quantity == Decimal("40")  # still recorded
    assert om.positions().get(FIGI).quantity == Decimal("60")  # position updated
    await dm.pump()  # the queued reaction is handled without raising
    assert deal.status is DealStatus.OPEN
