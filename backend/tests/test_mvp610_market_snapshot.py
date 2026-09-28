"""MVP-6.10 Live Market Snapshot & Per-Bot Timeframe tests.

Focused on the new live market-data boundary: the broker-neutral
MarketSnapshot, ``MarketDataService.get_snapshot``, the per-bot timeframe
propagation from the bot's own strategy configuration, the correct snapshot
retrieval request, the explicit failure on a missing/invalid timeframe, the
blocking on a missing/invalid market snapshot, and the preservation of the
MVP-6.9 position-state invariant. Deterministic and broker-neutral: no real
orders, no T-Invest, no fabricated market data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.bots.strategy import BotStrategy, StrategyLoadError, load_bot_strategy
from app.brokers.base import BrokerOrder, BrokerOrderRequest
from app.brokers.tinvest_errors import (
    InstrumentNotFoundError,
    ResourceNotFoundError,
)
from app.domain.marketdata import (
    Candle,
    LastPrice,
    MarketDataUnavailable,
    MarketSnapshot,
    Timeframe,
)
from app.models.account import Account
from app.models.base import Base
from app.models.bot import Bot
from app.models.enums import BotState, OrderSide, OrderStatus
from app.models.instrument import Instrument
from app.models.strategy import Strategy, StrategyVersion
from app.services.market_data import MarketDataService
from app.strategies.bars import Bar, BarSeries, Snapshot
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.dca_grid import DCAGridEngine
from app.strategies.domain import MarketContext
from app.strategies.engine import StrategyEngine
from app.strategies.entry import EntryEngine
from app.strategies.exit import ExitEngine
from app.strategies.filters import (
    ConstantValue,
    FilterCondition,
    FilterGroup,
    IndicatorSpec,
    Operator,
)
from app.trading import (
    BotRuntime,
    LookbackNotConfigured,
    OrderManager,
    PositionSizing,
    RiskManager,
    TimeframeNotConfigured,
    TradingEngine,
    build_market_snapshot_context,
    market_snapshot_to_context,
)
from app.trading.plan_intent import plan_to_intents

T0 = datetime(2026, 5, 1, 9, 30, tzinfo=UTC)
FIGI = "BBG004730N88"
TF = Timeframe.MIN_5


def _candles(n: int) -> list[Candle]:
    # The newest candle is timestamped exactly at T0 (the snapshot timestamp).
    return [
        Candle(
            figi=FIGI,
            timeframe=TF,
            timestamp=T0 - timedelta(minutes=5 * (n - 1 - i)),
            open=Decimal(100) + i,
            high=Decimal(101) + i,
            low=Decimal(99) + i,
            close=Decimal("100.5") + i,
            volume=1000,
            is_complete=True,
        )
        for i in range(n)
    ]


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        figi=FIGI,
        timeframe=TF,
        timestamp=T0,
        last_price=Decimal("100.5"),
        candles=tuple(_candles(3)),
    )


def _strategy(timeframe: Timeframe | None = TF, **overrides) -> StrategyConfig:
    cfg = dict(
        direction=Direction.LONG,
        timeframe=timeframe,
        entry=EntryConfig(),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )
    cfg.update(overrides)
    return StrategyConfig(**cfg)


def _strategy_with_sma(period: int = 20, lookback_bars: int | None = None) -> StrategyConfig:
    groups = [
        FilterGroup(
            conditions=[
                FilterCondition(
                    arg1=IndicatorSpec(
                        kind="indicator", name="SMA", timeframe=TF, period=period
                    ),
                    operator=Operator.GREATER_THAN,
                    arg2=ConstantValue(kind="constant", value=0.0),
                )
            ]
        )
    ]
    overrides = dict(entry=EntryConfig(groups=groups))
    if lookback_bars is not None:
        overrides["lookback_bars"] = lookback_bars
    return _strategy(**overrides)


def _context(timeframe: Timeframe = TF, *, bars: int = 1, price: float = 100.0) -> MarketContext:
    return MarketContext(
        price=price,
        timestamp=T0,
        snapshot=Snapshot(
            series={
                timeframe: BarSeries(
                    timeframe=timeframe,
                    bars=[Bar(T0, 100.0, 101.0, 99.0, 100.0, 1000.0) for _ in range(bars)],
                )
            }
        ),
    )


class RecordingBroker:
    """Duck-typed BrokerAdapter: deterministic market data, recorded requests."""

    def __init__(
        self,
        last_price: LastPrice | None = None,
        candles: list[Candle] | None = None,
    ) -> None:
        self._last_price = last_price
        self._candles = candles or []
        self.last_price_calls: list[str] = []
        self.candle_calls: list[tuple[str, Timeframe, datetime, datetime]] = []
        self.place_calls = 0

    async def get_last_price(self, figi: str) -> LastPrice:
        self.last_price_calls.append(figi)
        if self._last_price is None:
            raise ResourceNotFoundError(f"instrument not found: {figi}")
        return self._last_price

    async def get_candles(
        self, figi: str, timeframe: Timeframe, from_: datetime, to: datetime, limit=None
    ) -> list[Candle]:
        self.candle_calls.append((figi, timeframe, from_, to))
        return list(self._candles)

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


class FakeSnapshotProvider:
    """Duck-typed broker-neutral snapshot provider (get_snapshot)."""

    def __init__(self, snapshot: MarketSnapshot | None = None, error=None) -> None:
        self._snapshot = snapshot
        self._error = error
        self.requests: list[tuple[str, Timeframe, int]] = []

    async def get_snapshot(self, figi: str, timeframe: Timeframe, lookback_bars: int):
        self.requests.append((figi, timeframe, lookback_bars))
        if self._error is not None:
            raise self._error
        return self._snapshot


def _live_engine(
    broker: RecordingBroker, *, strategy: StrategyConfig | None = None, positions=None
) -> TradingEngine:
    om = OrderManager(broker)
    pm = positions if positions is not None else om.positions()
    return TradingEngine(
        broker,
        StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
        om,
        pm,
        RiskManager(position_manager=pm),
        strategy_config=strategy or _strategy(),
        intent_factory=lambda plan, ctx: plan_to_intents(
            plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1"
        ),
        sizing=PositionSizing(base_nominal=Decimal("5000")),
        instrument_figi=FIGI,
    )


# --- 1: valid MarketSnapshot ---------------------------------------------------


async def test_valid_market_snapshot_from_broker_data() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("104.5"), timestamp=T0),
        candles=_candles(10),
    )
    snap = await MarketDataService(broker).get_snapshot(FIGI, TF, lookback_bars=10)
    assert snap.figi == FIGI
    assert snap.timeframe is TF
    assert snap.last_price == Decimal("104.5")
    assert snap.timestamp == T0
    assert snap.timestamp.tzinfo is not None
    assert len(snap.candles) == 10
    assert snap.candles[-1].timestamp == T0
    assert all(isinstance(c.close, Decimal) for c in snap.candles)
    assert all(c.timestamp.tzinfo is not None for c in snap.candles)
    assert all(c.figi == FIGI and c.timeframe is TF for c in snap.candles)


def test_market_snapshot_to_context_preserves_values() -> None:
    ctx = market_snapshot_to_context(_snapshot())
    assert ctx.price == 100.5
    assert ctx.timestamp == T0
    series = ctx.snapshot.get(TF)
    assert series is not None
    assert len(series.bars) == 3
    assert series.bars[-1].timestamp == T0
    assert series.bars[-1].is_complete is True


# --- 2: timeframe propagation from bot/strategy configuration ------------------


async def test_timeframe_propagates_from_strategy_config() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("100"), timestamp=T0),
        candles=_candles(5),
    )
    ctx = await build_market_snapshot_context(
        MarketDataService(broker),
        FIGI,
        _strategy(timeframe=Timeframe.MIN_15, lookback_bars=5),
    )
    assert broker.candle_calls[0][1] is Timeframe.MIN_15
    series = ctx.snapshot.get(Timeframe.MIN_15)
    assert series is not None
    assert len(series.bars) == 5


async def test_timeframe_propagates_from_bot_runtime() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    bot_strategy = BotStrategy(
        strategy_version_id=1, version=1, config=_strategy(timeframe=Timeframe.MIN_15)
    )
    requested: list[Timeframe | None] = []

    async def _provider(bs: BotStrategy) -> MarketContext:
        requested.append(bs.config.timeframe)
        return _context(Timeframe.MIN_15)

    async def _load() -> BotStrategy:
        return bot_strategy

    async def _make_engine(s: BotStrategy) -> TradingEngine:
        engine = TradingEngine(
            broker,
            StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
            om,
            om.positions(),
            RiskManager(position_manager=om.positions()),
            strategy_config=s.config,
            intent_factory=lambda plan, ctx: plan_to_intents(
                plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1"
            ),
            sizing=PositionSizing(base_nominal=Decimal("5000")),
        )
        await engine.start()
        return engine

    rt = BotRuntime(
        1,
        RiskManager(),
        state=BotState.STOPPED,
        strategy_loader=_load,
        trading_engine_factory=_make_engine,
        market_context_provider=_provider,
    )
    await rt.start()
    assert rt.state is BotState.RUNNING
    await rt.execute_strategy()
    # The provider received the bot's own strategy with its own timeframe.
    assert requested == [Timeframe.MIN_15]


# --- 3: correct snapshot retrieval request -------------------------------------


async def test_correct_snapshot_retrieval_request() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("100"), timestamp=T0),
        candles=_candles(5),
    )
    await MarketDataService(broker).get_snapshot(FIGI, TF, lookback_bars=10)
    assert broker.last_price_calls == [FIGI]
    assert len(broker.candle_calls) == 1
    req_figi, req_tf, from_, to = broker.candle_calls[0]
    assert req_figi == FIGI
    assert req_tf is TF
    # 10 requested bars + 1 forming bar of width, in the bot's timeframe.
    assert to - from_ == timedelta(seconds=300 * 11)


async def test_snapshot_request_uses_explicit_lookback_from_config() -> None:
    provider = FakeSnapshotProvider(snapshot=_snapshot())
    config = _strategy(lookback_bars=7)
    await build_market_snapshot_context(provider, FIGI, config)
    # The lookback is the strategy's own explicitly configured parameter,
    # never derived from indicator periods/shifts.
    assert provider.requests == [(FIGI, TF, 7)]


async def test_lookback_is_not_inferred_from_indicator_period_or_shift() -> None:
    # The lookback must not be derivable from the strategy's filter contract:
    # a config with indicator period/shift but no explicit lookback is missing
    # a lookback, and the boundary must fail explicitly instead of computing
    # one (no warmup, no period-as-history, no cross-operator +1).
    groups = [
        FilterGroup(
            conditions=[
                FilterCondition(
                    arg1=IndicatorSpec(
                        kind="indicator", name="EMA", timeframe=TF, period=9, shift=3
                    ),
                    operator=Operator.GREATER_THAN,
                    arg2=ConstantValue(kind="constant", value=0.0),
                )
            ]
        )
    ]
    config = _strategy(entry=EntryConfig(groups=groups))
    assert config.lookback_bars is None
    with pytest.raises(LookbackNotConfigured):
        await build_market_snapshot_context(
            FakeSnapshotProvider(snapshot=_snapshot()), FIGI, config
        )


def test_non_positive_lookback_rejected_by_strategy_config() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig(
            lookback_bars=0,
            exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        )


# --- 4: missing timeframe -------------------------------------------------------


async def test_missing_timeframe_fails_snapshot_context_explicitly() -> None:
    broker = RecordingBroker()
    with pytest.raises(TimeframeNotConfigured):
        await build_market_snapshot_context(
            MarketDataService(broker), FIGI, _strategy(timeframe=None)
        )
    # No broker request is issued: the cycle fails before any data fetch.
    assert broker.last_price_calls == []
    assert broker.candle_calls == []


async def test_missing_timeframe_fails_live_cycle_explicitly() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    engine = _live_engine(broker, strategy=_strategy(timeframe=None), positions=pm)
    om = engine.order_manager
    await engine.start()
    with pytest.raises(TimeframeNotConfigured):
        await engine.process(_context())
    assert broker.place_calls == 0
    assert om.list_orders() == []


# --- 4b: missing explicit lookback ----------------------------------------------


async def test_missing_lookback_fails_snapshot_context_explicitly() -> None:
    broker = RecordingBroker()
    with pytest.raises(LookbackNotConfigured):
        await build_market_snapshot_context(
            MarketDataService(broker), FIGI, _strategy()
        )
    # No broker request is issued: the cycle fails before any data fetch.
    assert broker.last_price_calls == []
    assert broker.candle_calls == []


async def test_missing_lookback_fails_live_cycle_explicitly() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    bot_strategy = BotStrategy(
        strategy_version_id=1, version=1, config=_strategy()
    )

    async def _provider(bs: BotStrategy) -> MarketContext:
        raise LookbackNotConfigured("no explicit snapshot lookback configured")

    async def _load() -> BotStrategy:
        return bot_strategy

    async def _make_engine(s: BotStrategy) -> TradingEngine:
        engine = TradingEngine(
            broker,
            StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
            om,
            om.positions(),
            RiskManager(position_manager=om.positions()),
            strategy_config=s.config,
            intent_factory=lambda plan, ctx: plan_to_intents(
                plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1"
            ),
            sizing=PositionSizing(base_nominal=Decimal("5000")),
        )
        await engine.start()
        return engine

    rt = BotRuntime(
        1,
        RiskManager(),
        state=BotState.STOPPED,
        strategy_loader=_load,
        trading_engine_factory=_make_engine,
        market_context_provider=_provider,
    )
    await rt.start()
    with pytest.raises(LookbackNotConfigured):
        await rt.execute_strategy()
    assert broker.place_calls == 0


# --- 5: invalid timeframe -------------------------------------------------------


def test_invalid_timeframe_rejected_by_strategy_config() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig(
            timeframe="bogus",
            exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        )


# --- 6: missing / invalid market snapshot ---------------------------------------


async def test_unknown_instrument_raises_not_found() -> None:
    broker = RecordingBroker(last_price=None)
    with pytest.raises(InstrumentNotFoundError):
        await MarketDataService(broker).get_snapshot(FIGI, TF, lookback_bars=5)


async def test_non_positive_last_price_raises_unavailable() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("0"), timestamp=T0),
        candles=_candles(5),
    )
    with pytest.raises(MarketDataUnavailable):
        await MarketDataService(broker).get_snapshot(FIGI, TF, lookback_bars=5)


async def test_empty_candle_history_raises_unavailable() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("100"), timestamp=T0),
        candles=[],
    )
    with pytest.raises(MarketDataUnavailable):
        await MarketDataService(broker).get_snapshot(FIGI, TF, lookback_bars=5)


async def test_missing_snapshot_blocks_runtime_cycle() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    bot_strategy = BotStrategy(
        strategy_version_id=1, version=1, config=_strategy()
    )

    async def _provider(bs: BotStrategy) -> MarketContext:
        raise MarketDataUnavailable("no usable live price")

    async def _load() -> BotStrategy:
        return bot_strategy

    async def _make_engine(s: BotStrategy) -> TradingEngine:
        engine = TradingEngine(
            broker,
            StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine()),
            om,
            om.positions(),
            RiskManager(position_manager=om.positions()),
            strategy_config=s.config,
            intent_factory=lambda plan, ctx: plan_to_intents(
                plan, instrument_figi=FIGI, bot_id=1, account_id="acc-1"
            ),
            sizing=PositionSizing(base_nominal=Decimal("5000")),
        )
        await engine.start()
        return engine

    rt = BotRuntime(
        1,
        RiskManager(),
        state=BotState.STOPPED,
        strategy_loader=_load,
        trading_engine_factory=_make_engine,
        market_context_provider=_provider,
    )
    await rt.start()
    with pytest.raises(MarketDataUnavailable):
        await rt.execute_strategy()
    assert broker.place_calls == 0


async def test_snapshot_without_bot_timeframe_series_blocks_intents() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    engine = _live_engine(broker, positions=pm)
    om = engine.order_manager
    await engine.start()
    # A snapshot series for a different timeframe is not a usable snapshot
    # for this bot.
    await engine.process(_context(timeframe=Timeframe.MIN_15))
    assert om.list_orders() == []
    assert broker.place_calls == 0


async def test_empty_snapshot_series_blocks_intents() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    engine = _live_engine(broker, positions=pm)
    om = engine.order_manager
    await engine.start()
    await engine.process(_context(bars=0))
    assert om.list_orders() == []
    assert broker.place_calls == 0


async def test_missing_snapshot_blocks_intents() -> None:
    broker = RecordingBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    engine = _live_engine(broker, positions=pm)
    om = engine.order_manager
    await engine.start()
    await engine.process(MarketContext(price=100.0, timestamp=T0))
    assert om.list_orders() == []
    assert broker.place_calls == 0


# --- 7: MVP-6.9 position-state invariant preserved ------------------------------


async def test_position_invariant_valid_snapshot_no_position() -> None:
    # A valid snapshot must not bypass the MVP-6.9 invariant: without a
    # resolvable position, no live order at all.
    broker = RecordingBroker()
    engine = _live_engine(broker)
    om = engine.order_manager
    await engine.start()
    await engine.process(_context())
    assert om.list_orders() == []
    assert broker.place_calls == 0


async def test_position_invariant_valid_snapshot_and_position() -> None:
    # With a valid snapshot and a valid position, execution proceeds and the
    # exit quantity is still the authoritative real position quantity.
    broker = RecordingBroker()
    om = OrderManager(broker)
    pm = om.positions()
    pm.apply_fill(FIGI, OrderSide.BUY, Decimal("10"), Decimal("100"))
    engine = _live_engine(broker, positions=pm)
    om = engine.order_manager
    await engine.start()
    await engine.process(_context())
    orders = om.list_orders()
    sells = [o for o in orders if o.side is OrderSide.SELL]
    assert len(orders) == 2  # grid BUY + exit SELL
    assert len(sells) == 1
    assert sells[0].requested_quantity == Decimal("10")


# --- 8: snapshot bars drive the entry filter evaluation -------------------------


async def test_snapshot_bars_drive_entry_filter_evaluation() -> None:
    broker = RecordingBroker(
        last_price=LastPrice(figi=FIGI, price=Decimal("104.5"), timestamp=T0),
        candles=_candles(25),
    )
    config = _strategy_with_sma(20, lookback_bars=25)
    ctx = await build_market_snapshot_context(MarketDataService(broker), FIGI, config)
    se = StrategyEngine(EntryEngine(), DCAGridEngine(), ExitEngine())
    plan = se.evaluate(config, ctx, base_nominal=Decimal("5000"))
    assert plan.entry is not None
    assert len(plan.grid) == 1


# --- strategy load: invalid / missing timeframe ---------------------------------


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw) -> str:
    return "JSON"


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


async def _seed_bot(session: AsyncSession, config: dict) -> Bot:
    # Explicit ids: SQLite does not autoincrement BigInteger primary keys.
    account = Account(name="acc", broker="tinvest")
    account.id = 1
    instrument = Instrument(figi="BBG000", ticker="SBER", trading_status="TRADING_AVAILABLE")
    instrument.id = 1
    strategy = Strategy(name="s", config={})
    strategy.id = 1
    session.add_all([account, instrument, strategy])
    await session.flush()
    version = StrategyVersion(strategy_id=strategy.id, version=1, config=config)
    version.id = 1
    session.add(version)
    await session.flush()
    bot = Bot(
        name="bot",
        strategy_version_id=version.id,
        account_id=account.id,
        instrument_id=instrument.id,
    )
    bot.id = 1
    session.add(bot)
    await session.commit()
    return bot


async def test_invalid_timeframe_blocks_strategy_load(db_session: AsyncSession) -> None:
    cfg = {
        "name": "grid-test",
        "direction": "LONG",
        "timeframe": "bogus",
        "entry": {"method": "at_bar_close", "groups": []},
        "dca_grid": {"mode": "simple", "levels": 1},
        "exit": {"take_profit": {"kind": "fixed_percentage", "percent": 2.0}},
    }
    bot = await _seed_bot(db_session, cfg)
    with pytest.raises(StrategyLoadError):
        await load_bot_strategy(db_session, bot)


async def test_missing_timeframe_loads_but_blocks_live_cycle(
    db_session: AsyncSession,
) -> None:
    cfg = {
        "name": "grid-test",
        "direction": "LONG",
        "entry": {"method": "at_bar_close", "groups": []},
        "dca_grid": {"mode": "simple", "levels": 1},
        "exit": {"take_profit": {"kind": "fixed_percentage", "percent": 2.0}},
    }
    bot = await _seed_bot(db_session, cfg)
    loaded = await load_bot_strategy(db_session, bot)
    assert loaded.config.timeframe is None
    with pytest.raises(TimeframeNotConfigured):
        await build_market_snapshot_context(
            FakeSnapshotProvider(), "BBG000", loaded.config
        )
