"""MVP-6.16 Simple Stop-Loss tests (E1-E5, live + backtest regression).

Focused, deterministic, broker-neutral coverage of the approved contracts:

- E1: the stop level is ``P0 x (1 -+ combined_offset/100)`` where the
  combined offset is ``(last grid level offset - level 0 offset) + SL%``
  (for the simple grid: the overlap + SL), P0 is the actual average fill
  price of the level-0 Deal order; the trigger is tick-aligned LONG up /
  SHORT down (the early-trigger direction); no tick size is an explicit
  error; the stop is armed only after ALL grid levels are filled;
- E2: one broker stop order covering the whole position (rounded down to
  whole lots, never more than the position), risk-gated first (a rejection
  keeps the old stop and errors the Deal), cancel-then-confirm-then-re-read
  (an executed-in-flight stop closes the Deal with ``stop_loss``), a
  TP-full close cancels the stop, an unknown cancel blocks the bot (ERROR),
  a stop execution is correlated via GetStopOrders + positions;
- E3: ``stop_bot_after`` propagates to the production callback (true ->
  bot STOPPED with a persisted reason; false -> the bot can open the next
  FLAT entry), None and non-percent stops are rejected at START (409);
- E4: simple stop + simple TP + SIMPLE/CUSTOM grid is the only new
  accepted live combination;
- E5: the backtest uses the same E1 formula and the same assembly gate
  (regression tests in test_exit_integration.py).

No real orders, no T-Invest, no fabricated market data or financial
defaults. Amounts are test fixtures, not recommendations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.brokers.base import (
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    BrokerStopOrder,
    BrokerStopOrderRequest,
    StopOrderStatus,
)
from app.domain.marketdata import Timeframe
from app.models.enums import BotState, OrderSide, OrderStatus
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
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine, simple_stop_level, stop_distance_percent
from app.trading import (
    DealConfigUnsupported,
    DealManager,
    DealStatus,
    DealTickSizeInvalid,
    OrderManager,
    RiskManager,
    validate_live_deal_config,
)
from app.trading.deal import Deal, InMemoryDealStore, align_stop_price
from app.trading.domain import Fill, OrderState

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
FIGI = "BBG004730N88"
ACC = "acc-1"
TICK = Decimal("0.1")
# Deposit 40000 over 2 levels -> 20000 per level; level-0 market entry at 100
# (200 units), level-1 limit at 85 (235 units after lot rounding), 15% overlap.
DEPOSIT = Decimal("40000")


class StopBroker:
    """Duck-typed broker with the MVP-6.16 stop-order surface (no real orders)."""

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls: list[str] = []
        self.stop_place_calls = 0
        self.stop_cancel_calls: list[str] = []
        self.stops: dict[str, BrokerStopOrder] = {}
        self.positions: list[BrokerPosition] = []
        self.cancel_stop_error: Exception | None = None
        self.get_stop_error: Exception | None = None

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
        self.cancel_calls.append(order_id)

    async def place_stop_order(self, request: BrokerStopOrderRequest) -> BrokerStopOrder:
        self.stop_place_calls += 1
        order_id = f"stop-{self.stop_place_calls}"
        stop = BrokerStopOrder(
            order_id=order_id,
            status=StopOrderStatus.ACTIVE,
            account_id=request.account_id,
            instrument_figi=request.instrument_figi,
            side=request.side,
            quantity=request.quantity,
            stop_price=request.stop_price,
        )
        self.stops[order_id] = stop
        return stop

    async def cancel_stop_order(self, order_id: str, account_id: str | None = None) -> None:
        self.stop_cancel_calls.append(order_id)
        if self.cancel_stop_error is not None:
            raise self.cancel_stop_error
        stop = self.stops.get(order_id)
        if stop is not None:
            stop.status = StopOrderStatus.CANCELLED

    async def get_stop_orders(self, account_id: str | None = None) -> list[BrokerStopOrder]:
        if self.get_stop_error is not None:
            raise self.get_stop_error
        return list(self.stops.values())

    async def get_open_positions(self, account_id: str | None = None) -> list[BrokerPosition]:
        return list(self.positions)

    def active_stops(self) -> list[BrokerStopOrder]:
        return [s for s in self.stops.values() if s.status is StopOrderStatus.ACTIVE]


def _strategy(sl: tuple[float, bool] | None = None, **overrides) -> StrategyConfig:
    exit_cfg = dict(take_profit=FixedPercentageTP(percent=10.0))
    if sl is not None:
        exit_cfg["stop_loss"] = StopLossConfig(percent=sl[0], stop_bot_after=sl[1])
    cfg = dict(
        direction=Direction.LONG,
        timeframe=Timeframe.MIN_5,
        entry=EntryConfig(),
        exit=ExitConfig(**exit_cfg),
        dca_grid=DCAGridConfig(levels=1),
    )
    cfg.update(overrides)
    return StrategyConfig(**cfg)


def _se() -> StrategyEngine:
    return StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())


def _pair(
    broker: StopBroker | None = None,
    store: InMemoryDealStore | None = None,
    risk: RiskManager | None = None,
    on_stop_loss=None,
) -> tuple[DealManager, OrderManager, StopBroker]:
    broker = broker or StopBroker()
    om = OrderManager(broker)
    dm = DealManager(
        store or InMemoryDealStore(),
        om,
        risk or RiskManager(position_manager=om.positions()),
        on_stop_loss=on_stop_loss,
    )
    return dm, om, broker


async def _open(
    dm: DealManager,
    om: OrderManager,
    *,
    levels: int = 2,
    overlap: float = 15.0,
    sl: tuple[float, bool] = (5.0, False),
    direction: Direction = Direction.LONG,
    bot_id: int = 1,
) -> Deal:
    """Open a Deal over a SIMPLE grid with a simple stop (default fixtures)."""
    base_nominal = DEPOSIT / Decimal(levels)
    return await dm.open_deal(
        bot_id=bot_id,
        instrument_figi=FIGI,
        direction=direction,
        config=_strategy(
            sl=sl,
            direction=direction,
            dca_grid=DCAGridConfig(
                mode=TradingMode.SIMPLE,
                levels=levels,
                overlap_percent=overlap,
                active_limit=levels,
            ),
        ),
        reference_price=Decimal("100"),
        deposit=DEPOSIT,
        base_nominal=base_nominal,
        account_id=ACC,
        lot_size=1,
        tick_size=TICK,
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


async def _assembled(dm: DealManager, om: OrderManager) -> tuple[Deal, object, object]:
    """Entry + DCA fill; the grid is assembled and the stop is armed."""
    deal = await _open(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    assert deal.sl_order_id is None  # not assembled yet: no stop
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("235"), Decimal("85"))
    await dm.pump()
    return deal, entry, dca


# --- E1: formula and tick alignment -------------------------------------------


def test_e1_formula_combined_offset_matches_veles_example() -> None:
    # Veles example: overlap 15% + SL 5% -> the stop sits at -20% from P0.
    assert stop_distance_percent(0.0, 15.0, 5.0) == 20.0
    assert simple_stop_level(Decimal("100"), Direction.LONG, 20.0) == Decimal("80")
    assert simple_stop_level(Decimal("100"), Direction.SHORT, 20.0) == Decimal("120")
    # A grid-less case (single order, no overlap) is plain SL%.
    assert stop_distance_percent(0.0, 0.0, 5.0) == 5.0
    assert simple_stop_level(Decimal("100"), Direction.LONG, 5.0) == Decimal("95")


def test_e1_formula_from_deal_uses_p0_and_grid_component() -> None:
    long_deal = Deal(
        direction=Direction.LONG,
        p0_price=Decimal("100"),
        sl_offset=Decimal("15"),
        sl_percent=5.0,
    )
    assert long_deal.sl_price_from_p0() == Decimal("80")
    short_deal = Deal(
        direction=Direction.SHORT,
        p0_price=Decimal("100"),
        sl_offset=Decimal("15"),
        sl_percent=5.0,
    )
    assert short_deal.sl_price_from_p0() == Decimal("120")
    # CUSTOM ladder: (6 - (-3)) + 4 = 13% from P0.
    custom = Deal(
        direction=Direction.LONG,
        p0_price=Decimal("100"),
        sl_offset=Decimal("9"),
        sl_percent=4.0,
    )
    assert custom.sl_price_from_p0() == Decimal("87")


def test_e1_tick_alignment_early_trigger_and_missing_tick() -> None:
    # LONG stop rounds UP (triggers earlier), SHORT rounds DOWN.
    assert align_stop_price(Decimal("80.05"), TICK, Direction.LONG) == Decimal("80.1")
    assert align_stop_price(Decimal("80.05"), TICK, Direction.SHORT) == Decimal("80.0")
    # An already-tick-aligned level is unchanged.
    assert align_stop_price(Decimal("80.0"), TICK, Direction.LONG) == Decimal("80.0")
    with pytest.raises(DealTickSizeInvalid):
        align_stop_price(Decimal("80.0"), None, Direction.LONG)
    with pytest.raises(DealTickSizeInvalid):
        align_stop_price(Decimal("80.0"), Decimal("0"), Direction.LONG)


# --- E1: activation and the single-stop invariant ------------------------------


async def test_e1_stop_armed_only_after_full_grid_assembly() -> None:
    dm, om, broker = _pair()
    deal = await _open(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    # Only the entry level is filled: no stop at the broker yet (E1).
    assert deal.sl_order_id is None
    assert broker.stops == {}
    assert deal.status is DealStatus.OPEN

    dca = om.get_order(deal.levels[1].order_id)
    assert dca.limit_price == Decimal("85")
    _fill(om, dca, "f-dca", Decimal("235"), Decimal("85"))
    await dm.pump()
    # The grid is assembled: exactly one stop, P0=100, 15% overlap + 5% SL
    # -> -20% -> 80.0 (already tick-aligned), for the whole position 435.
    assert deal.p0_price == Decimal("100")
    assert deal.sl_offset == Decimal("15")
    assert deal.sl_rev == 1
    assert deal.sl_quantity == Decimal("435")
    assert deal.sl_price == Decimal("80.0")
    assert deal.sl_order_id is not None
    assert len(broker.active_stops()) == 1
    stop = broker.active_stops()[0]
    assert stop.quantity == Decimal("435")
    assert stop.stop_price == Decimal("80.0")
    assert stop.side is OrderSide.SELL
    tp = om.get_order(deal.tp_order_id)
    assert tp.requested_quantity == Decimal("435")
    assert tp.limit_price == Decimal("101.1")  # avg 91.8965... x 1.10


async def test_e2_partial_tp_rearms_stop_to_new_position_once() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    old_id = deal.sl_order_id
    tp = om.get_order(deal.tp_order_id)
    _fill(om, tp, "f-tp-part", Decimal("100"), Decimal("101.1"))
    await dm.pump()
    # After 100 units hit the TP the position is 335: exactly one ACTIVE stop
    # for 335 units (the old stop is cancelled), never more than the position.
    assert deal.sl_rev == 2
    assert deal.sl_order_id != old_id
    assert deal.sl_quantity == Decimal("335")
    assert len([s for s in broker.stops.values() if s.status is StopOrderStatus.CANCELLED]) == 1
    assert len(broker.active_stops()) == 1
    assert broker.active_stops()[0].quantity == Decimal("335")
    assert broker.active_stops()[0].stop_price == Decimal("80.0")


async def test_e2_risk_rejection_keeps_working_stop_and_errors_bot() -> None:
    status = {"trading_allowed": True}

    def instrument_status(figi: str) -> bool | None:
        return status["trading_allowed"]

    broker = StopBroker()
    om = OrderManager(broker)
    risk = RiskManager(position_manager=om.positions(), instrument_status_check=instrument_status)
    dm = DealManager(InMemoryDealStore(), om, risk)
    deal = await _open(dm, om)
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("235"), Decimal("85"))
    await dm.pump()
    old_id = deal.sl_order_id
    # The protecting stop is denied by the risk gate during a re-arm: the old
    # stop must stay working and the bot must see the failure (B1/E2).
    status["trading_allowed"] = False
    tp = om.get_order(deal.tp_order_id)
    _fill(om, tp, "f-tp-part", Decimal("100"), Decimal("101.1"))
    await dm.pump()
    assert deal.status is DealStatus.ERROR
    assert dm.last_error_for(deal.bot_id) is not None
    assert "rejected by risk" in dm.last_error_for(deal.bot_id)
    assert deal.bot_id in dm.blocked_bots
    assert broker.stop_cancel_calls == []  # the working stop was never touched
    assert broker.active_stops() == [broker.stops[old_id]]
    assert broker.active_stops()[0].quantity == Decimal("435")


async def test_e2_unknown_cancel_blocks_bot_without_second_stop() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    broker.cancel_stop_error = RuntimeError("network down")
    tp = om.get_order(deal.tp_order_id)
    _fill(om, tp, "f-tp-part", Decimal("100"), Decimal("101.1"))
    await dm.pump()
    # The cancel could not be confirmed (the stop is still ACTIVE): the Deal
    # is ERROR and no second stop is ever placed.
    assert deal.status is DealStatus.ERROR
    assert "could not be confirmed" in dm.last_error_for(deal.bot_id)
    assert deal.bot_id in dm.blocked_bots
    assert broker.stop_place_calls == 1
    assert len(broker.active_stops()) == 1
    assert broker.active_stops()[0].quantity == Decimal("435")


async def test_e2_full_tp_close_cancels_stop_and_marks_take_profit() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    tp = om.get_order(deal.tp_order_id)
    _fill(om, tp, "f-tp-full", Decimal("435"), Decimal("101.1"))
    await dm.pump()
    assert deal.status is DealStatus.CLOSED
    assert deal.close_reason == "take_profit"
    assert dm.active_deal(deal.bot_id) is None
    assert deal.bot_id not in dm.blocked_bots
    # The stop was cancelled (never left working under a closed Deal).
    assert broker.active_stops() == []
    assert len(broker.stops) == 1
    assert list(broker.stops.values())[0].status is StopOrderStatus.CANCELLED


async def test_e2_stop_execution_cancels_tp_and_closes_with_stop_loss() -> None:
    calls: list[tuple[int, bool]] = []

    async def on_stop_loss(bot_id: int, stop_bot_after: bool) -> None:
        calls.append((bot_id, stop_bot_after))

    dm, om, broker = _pair(on_stop_loss=on_stop_loss)
    deal, entry, dca = await _assembled(dm, om)
    # A stop execution is a REST fact, never a stream fill: GetStopOrders
    # reports EXECUTED and the broker position is flat.
    broker.stops[deal.sl_order_id].status = StopOrderStatus.EXECUTED
    await dm.pump()
    assert deal.status is DealStatus.CLOSED
    assert deal.close_reason == "stop_loss"
    assert deal.bot_id not in dm.blocked_bots
    assert dm.active_deal(deal.bot_id) is None
    assert om.get_order(deal.tp_order_id).status is OrderState.CANCELLED
    assert calls == [(deal.bot_id, False)]  # stop_bot_after=false (E3 propagation)


async def test_e3_stop_bot_after_true_propagates_to_callback() -> None:
    calls: list[tuple[int, bool]] = []

    async def on_stop_loss(bot_id: int, stop_bot_after: bool) -> None:
        calls.append((bot_id, stop_bot_after))

    dm, om, broker = _pair(on_stop_loss=on_stop_loss)
    deal = await _open(dm, om, sl=(5.0, True))
    entry = om.get_order(deal.levels[0].order_id)
    _fill(om, entry, "f-entry", Decimal("200"), Decimal("100"))
    await dm.pump()
    dca = om.get_order(deal.levels[1].order_id)
    _fill(om, dca, "f-dca", Decimal("235"), Decimal("85"))
    await dm.pump()
    broker.stops[deal.sl_order_id].status = StopOrderStatus.EXECUTED
    await dm.pump()
    assert deal.status is DealStatus.CLOSED
    assert deal.close_reason == "stop_loss"
    assert calls == [(deal.bot_id, True)]
    # false is the default: the bot stays unblocked for the next FLAT entry.
    dm2, om2, broker2 = _pair()
    deal2 = await _open(dm2, om2)
    entry2 = om2.get_order(deal2.levels[0].order_id)
    _fill(om2, entry2, "f-entry", Decimal("200"), Decimal("100"))
    await dm2.pump()
    dca2 = om2.get_order(deal2.levels[1].order_id)
    _fill(om2, dca2, "f-dca", Decimal("235"), Decimal("85"))
    await dm2.pump()
    broker2.stops[deal2.sl_order_id].status = StopOrderStatus.EXECUTED
    await dm2.pump()
    assert deal2.status is DealStatus.CLOSED
    assert dm2.active_deal(deal2.bot_id) is None
    assert deal2.bot_id not in dm2.blocked_bots
    # The next FLAT entry opens a new Deal (C6) — nothing stays blocked.
    deal3 = await _open(dm2, om2)
    assert deal3.id != deal2.id


async def test_e2_executed_stop_with_remaining_position_errors() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    # The stop is EXECUTED but the broker still reports the position: the
    # execution cannot be correlated -> explicit ERROR, never a silent close.
    broker.stops[deal.sl_order_id].status = StopOrderStatus.EXECUTED
    broker.positions = [
        BrokerPosition(
            account_id=ACC,
            instrument_figi=FIGI,
            quantity=Decimal("435"),
            average_price=Decimal("91.9"),
            current_price=Decimal("80.0"),
        )
    ]
    await dm.pump()
    assert deal.status is DealStatus.ERROR
    assert "still reports position" in dm.last_error_for(deal.bot_id)
    assert deal.bot_id in dm.blocked_bots


# --- E3/E4: configuration scope at START -----------------------------------------


def test_e3_start_rejects_missing_stop_bot_after() -> None:
    with pytest.raises(DealConfigUnsupported) as ei:
        validate_live_deal_config(
            _strategy(
                exit=ExitConfig(
                    take_profit=FixedPercentageTP(percent=10.0),
                    stop_loss=StopLossConfig(percent=5.0),  # stop_bot_after=None
                )
            )
        )
    assert "stop_bot_after" in str(ei.value)


def test_e4_accepts_simple_stop_with_simple_tp_and_grids() -> None:
    # Simple stop + simple TP on SIMPLE and CUSTOM grids is accepted (E1/E4).
    validate_live_deal_config(_strategy(sl=(5.0, False), dca_grid=DCAGridConfig(levels=2)))
    validate_live_deal_config(
        _strategy(
            sl=(5.0, False),
            dca_grid=DCAGridConfig(
                mode=TradingMode.CUSTOM,
                custom_levels=[CustomLevel(offset_percent=0.0, nominal_percent=100.0)],
            ),
        )
    )
    # signal_stop, multi-take and SIGNAL mode stay rejected (D1/E4).
    for bad in [
        _strategy(sl=(5.0, False), exit=ExitConfig(
            take_profit=FixedPercentageTP(percent=10.0),
            signal_stop=SignalStopLossConfig(),
        )),
        _strategy(sl=(5.0, False), exit=ExitConfig(
            take_profit=MultiTakeTP(
                takes=[TakeItem(offset_percent=1.0, volume_percent=20.0)],
            )
        )),
        _strategy(sl=(5.0, False), dca_grid=DCAGridConfig(mode=TradingMode.SIGNAL, levels=3)),
    ]:
        with pytest.raises(DealConfigUnsupported):
            validate_live_deal_config(bad)


# --- D5: recovery reconciliation ------------------------------------------------


async def test_d5_recovery_keeps_active_stop_untouched() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    armed_id = deal.sl_order_id
    # Restart with unchanged facts: the ACTIVE stop must stay (E2/D5) — the
    # recovery re-arms only the TP (D5), never replaces a working stop.
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    assert deal.status is DealStatus.OPEN
    assert deal.sl_order_id == armed_id
    assert broker.stop_place_calls == 1
    assert len(broker.active_stops()) == 1
    assert broker.active_stops()[0].quantity == Decimal("435")


async def test_d5_recovery_missing_stop_placed_once() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    del broker.stops[deal.sl_order_id]
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    # The assembled grid re-arms the missing stop exactly once.
    assert deal.sl_order_id is not None
    assert broker.stop_place_calls == 2
    assert len(broker.active_stops()) == 1
    assert broker.active_stops()[0].quantity == Decimal("435")
    assert broker.active_stops()[0].stop_price == Decimal("80.0")


async def test_d5_recovery_position_changed_rearms_stop() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    # While "down", a part of the position was taken by the TP: the stop must
    # be re-armed for the actual post-fill position (E2 "любое изменение позиции").
    tp = om.get_order(deal.tp_order_id)
    _fill(om, tp, "f-tp-part", Decimal("100"), Decimal("101.1"))
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is True
    assert len(broker.active_stops()) == 1
    assert broker.active_stops()[0].quantity == Decimal("335")
    assert deal.sl_quantity == Decimal("335")
    assert broker.stop_place_calls == 2


async def test_d5_recovery_unknown_stop_state_errors() -> None:
    dm, om, broker = _pair()
    deal, entry, dca = await _assembled(dm, om)
    broker.stops[deal.sl_order_id].status = StopOrderStatus.UNKNOWN
    dm2 = DealManager(dm._store, om, RiskManager(position_manager=om.positions()))
    assert await dm2.recover(ACC) is False
    assert deal.status is DealStatus.ERROR
    assert deal.bot_id in dm2.blocked_bots


# --- E3: production persistence of the stop reason -------------------------------


async def test_e3_stop_reason_persisted_on_stopped_bot() -> None:
    from app.bots.repository import BotRepository
    from app.models.bot import Bot

    class _Session:
        def __init__(self) -> None:
            self.commits = 0

        async def commit(self) -> None:
            self.commits += 1

        async def refresh(self, bot) -> None:
            return bot

    bot = Bot(
        id=7,
        name="bot",
        strategy_version_id=1,
        account_id=1,
        instrument_id=1,
        status=BotState.RUNNING.value,
    )
    repo = BotRepository(_Session())
    await repo.update_state(bot, BotState.STOPPED, stop_reason="stop-loss")
    assert bot.status == BotState.STOPPED.value
    assert bot.stop_reason == "stop-loss"
