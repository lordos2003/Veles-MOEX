"""MVP-6.15 Market snapshot by bar count across trading breaks (L1-L4) tests.

Focused on the new snapshot boundary (contracts L1-L4 of
TASK-MVP-6.15-SNAPSHOT-BY-BAR-COUNT): ``MarketDataService.get_snapshot`` now
returns the newest ``lookback_bars`` candles that actually exist at the broker
regardless of night/weekend/holiday breaks, extending the search backwards up
to the configured depth when the initial wall-clock window is not enough. The
missing candles are never fabricated: less history than ``lookback_bars`` is
returned as-is (L3) and a completely empty search raises |NoTradesInWindow|
whose ``window_start`` is the depth start (L4). Deterministic and
broker-neutral: an injected clock, a fixed-history broker fake whose candles
exist only inside weekday sessions, and the S6 deferred-tick regression (the
MVP-6.13 reviewer probe: an intraday bot deferred at the session close runs
its cycle on the pre-close bar at the next open instead of being concluded by
the B4 bound).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.domain.instrument import TradingStatus
from app.domain.marketdata import (
    Candle,
    LastPrice,
    MarketSnapshot,
    NoTradesInWindow,
    Timeframe,
)
from app.models.enums import BotState
from app.services.market_data import MarketDataService
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.filters import CalculationMethod
from app.trading import BotRuntimeManager, LiveCycleScheduler, RiskManager

FIGI = "BBG004730N88"
TF = Timeframe.MIN_5

# MOEX-like weekday sessions in UTC (10:00-18:45 MSK). Friday 2026-05-01 is the
# last session before the weekend; Monday 2026-05-04 is the first one after.
_SESSION_START = datetime(2026, 5, 1, 7, 0, tzinfo=UTC).time()
_SESSION_END = datetime(2026, 5, 1, 15, 45, tzinfo=UTC).time()

# Monday 07:30:30 UTC - mid-session for the "enough in the first window" case.
NOW_SESSION = datetime(2026, 5, 4, 7, 30, 30, tzinfo=UTC)
# Monday 07:10:30 UTC - 10 minutes after the open (after the night/weekend gap).
NOW_OPEN = datetime(2026, 5, 4, 7, 10, 30, tzinfo=UTC)
# Tuesday 07:10:30 UTC - 10 minutes after the open, after an ordinary night.
NOW_OPEN_TUE = datetime(2026, 5, 5, 7, 10, 30, tzinfo=UTC)
FRIDAY = date(2026, 5, 1)
SATURDAY = date(2026, 5, 2)
SUNDAY = date(2026, 5, 3)
MONDAY = date(2026, 5, 4)
TUESDAY = date(2026, 5, 5)


def _m5_candle(start: datetime, complete: bool = True) -> Candle:
    return Candle(
        figi=FIGI,
        timeframe=TF,
        timestamp=start,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=1000,
        is_complete=complete,
    )


def _session_candles(*days: date) -> list[Candle]:
    """M5 candles for the full weekday sessions of the given days."""
    candles: list[Candle] = []
    for day in days:
        t = datetime(day.year, day.month, day.day, _SESSION_START.hour,
                     _SESSION_START.minute, tzinfo=UTC)
        end = datetime(day.year, day.month, day.day, _SESSION_END.hour,
                       _SESSION_END.minute, tzinfo=UTC)
        while t + timedelta(seconds=300) <= end:
            candles.append(_m5_candle(t))
            t += timedelta(seconds=300)
    return candles


def _weekdays(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


class FakeClock:
    """Injectable clock: tests set the current time explicitly."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt

    async def sleep(self, seconds: float) -> None:  # scheduler S5: no real sleep
        self._now += timedelta(seconds=seconds)


class FixedHistoryBroker:
    """Broker fake: candles only in its history, requests recorded.

    ``get_candles`` returns exactly the candles whose timestamps fall into the
    requested half-open range ``[from_, to)`` — the historical facts a real
    broker exposes. Candle history is finite (session-only trading), so the
    service's backward fill is exercised for real.
    """

    def __init__(
        self,
        candles: list[Candle],
        *,
        last_timestamp: datetime | None = None,
    ) -> None:
        self._candles = candles
        self._last = LastPrice(
            figi=FIGI, price=Decimal("100.5"), timestamp=last_timestamp
        )
        self.candle_calls: list[tuple[Timeframe, datetime, datetime]] = []

    async def get_candles(
        self, figi: str, timeframe: Timeframe, from_: datetime, to: datetime,
        limit=None,
    ) -> list[Candle]:
        self.candle_calls.append((timeframe, from_, to))
        return [c for c in self._candles if from_ <= c.timestamp < to]

    async def get_last_price(self, figi: str) -> LastPrice:
        return self._last


class _Strategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config


class _Runtime:
    """Duck-typed BotRuntime: records executions/failures."""

    def __init__(self, bot_id: int, config: StrategyConfig) -> None:
        self.bot_id = bot_id
        self._config = config
        self.executions: list[object] = []
        self.fail_reasons: list[str] = []
        self._state = BotState.RUNNING

    @property
    def running(self) -> bool:
        return self._state is BotState.RUNNING

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def strategy(self) -> _Strategy:
        return _Strategy(self._config)

    def fail(self, reason: str) -> None:
        self.fail_reasons.append(reason)
        self._state = BotState.ERROR

    async def execute_strategy(self, context=None) -> None:
        self.executions.append(context)


class _StatusBroker:
    """Replays a scripted sequence of trading statuses (last step repeats)."""

    def __init__(self, *steps: TradingStatus) -> None:
        self._steps = list(steps)
        self.calls: list[str] = []

    async def get_trading_status(self, figi: str) -> TradingStatus:
        self.calls.append(figi)
        step = self._steps[0]
        if len(self._steps) > 1:
            self._steps.pop(0)
        return step


def _strategy() -> StrategyConfig:
    return StrategyConfig(
        direction=Direction.LONG,
        timeframe=TF,
        lookback_bars=50,
        entry=EntryConfig(method=CalculationMethod.AT_BAR_CLOSE),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )


def _service(
    broker: FixedHistoryBroker,
    clock: FakeClock,
    *,
    settings: Settings | None = None,
) -> MarketDataService:
    return MarketDataService(
        broker,
        settings=settings
        or Settings(snapshot_min_search_days=14, snapshot_search_factor=4),
        clock=clock,
    )


# --- L1: enough candles in the first window -> one request ----------------------


async def test_enough_candles_in_first_window_single_request() -> None:
    # Monday 07:30:30 UTC, lookback 5: the initial wall-clock window (lookback
    # + 1 = 6 bars wide) already contains 6 candles -> exactly one broker
    # request, and the snapshot is trimmed to the newest 5, chronological.
    clock = FakeClock(NOW_SESSION)
    history = _session_candles(*_weekdays(date(2026, 4, 20), MONDAY))
    broker = FixedHistoryBroker(history, last_timestamp=NOW_SESSION)
    snap = await _service(broker, clock).get_snapshot(FIGI, TF, lookback_bars=5)

    assert len(broker.candle_calls) == 1
    tf, from_, to = broker.candle_calls[0]
    assert tf is TF
    assert from_ == NOW_SESSION - timedelta(seconds=300 * 6)
    assert to == NOW_SESSION
    assert len(snap.candles) == 5
    assert snap.candles[0].timestamp == datetime(2026, 5, 4, 7, 10, tzinfo=UTC)
    assert snap.candles[-1].timestamp == NOW_SESSION - timedelta(seconds=30)
    assert [c.timestamp for c in snap.candles] == sorted(
        c.timestamp for c in snap.candles
    )


# --- L2: morning after the night break ------------------------------------------


async def test_morning_after_night_fills_to_lookback() -> None:
    # Tuesday 07:10:30 UTC (trades started 10 minutes ago), M5, lookback 50.
    # The first window (4 h 15 m) holds only the first 3 candles of the new day;
    # the fill extends backwards one 7-day chunk and collects Monday's session:
    # 2 requests total, exactly 50 candles, the newest are today's, the rest
    # are yesterday's. No candles are fabricated for the break.
    history = _session_candles(*_weekdays(date(2026, 4, 20), TUESDAY))
    broker = FixedHistoryBroker(history, last_timestamp=NOW_OPEN_TUE)
    clock = FakeClock(NOW_OPEN_TUE)
    snap = await _service(broker, clock).get_snapshot(FIGI, TF, lookback_bars=50)

    assert len(broker.candle_calls) == 2
    assert len(snap.candles) == 50
    assert snap.candles[-1].timestamp == NOW_OPEN_TUE - timedelta(seconds=30)  # 07:10
    assert snap.candles[0].timestamp == datetime(2026, 5, 4, 11, 50, tzinfo=UTC)
    dates = {c.timestamp.date() for c in snap.candles}
    assert dates == {MONDAY, TUESDAY}
    assert [c.timestamp for c in snap.candles] == sorted(
        c.timestamp for c in snap.candles
    )


# --- L2: Monday after the weekend -----------------------------------------------


async def test_monday_after_weekend_returns_friday_and_monday() -> None:
    # Monday 07:10:30 UTC: the last sessions were Friday. The snapshot has
    # exactly 50 candles drawn from Friday and Monday only (the weekend has no
    # candles and none are invented); chronological, newest last.
    history = _session_candles(*_weekdays(date(2026, 4, 20), MONDAY))
    broker = FixedHistoryBroker(history, last_timestamp=NOW_OPEN)
    clock = FakeClock(NOW_OPEN)
    snap = await _service(broker, clock).get_snapshot(FIGI, TF, lookback_bars=50)

    assert len(broker.candle_calls) == 2
    assert len(snap.candles) == 50
    assert snap.candles[-1].timestamp == datetime(2026, 5, 4, 7, 10, tzinfo=UTC)
    assert snap.candles[0].timestamp == datetime(2026, 5, 1, 11, 50, tzinfo=UTC)
    dates = {c.timestamp.date() for c in snap.candles}
    assert dates == {FRIDAY, MONDAY}
    assert all(c.timestamp.date() != SATURDAY and c.timestamp.date() != SUNDAY
               for c in snap.candles)


# --- L3: less history than lookback ----------------------------------------------


async def test_new_listing_returns_what_exists_no_error() -> None:
    # A new listing has only 10 candles (Friday morning) against lookback 50.
    # The fill walks the whole depth (3 requests: initial + 2 seven-day chunks,
    # the last reaching the depth start) and then returns the 10 candles as-is:
    # not an error, no fabricated bar.
    history = [c for c in _session_candles(FRIDAY) if c.timestamp <
               datetime(2026, 5, 1, 7, 50, tzinfo=UTC)]
    broker = FixedHistoryBroker(history, last_timestamp=NOW_OPEN)
    clock = FakeClock(NOW_OPEN)
    snap = await _service(broker, clock).get_snapshot(FIGI, TF, lookback_bars=50)

    assert len(broker.candle_calls) == 3
    _, last_from, _ = broker.candle_calls[-1]
    assert last_from == NOW_OPEN - timedelta(days=14)
    assert len(snap.candles) == 10
    assert snap.candles[-1].timestamp == datetime(2026, 5, 1, 7, 45, tzinfo=UTC)


# --- L4: no candles at all on the depth ------------------------------------------


async def test_no_candles_over_depth_raises_with_depth_start() -> None:
    # The search covers the whole depth (initial window + 2 seven-day chunks)
    # and finds nothing: NoTradesInWindow, window_start = the depth start
    # (now - 14 days for M5 lookback 50), last_trade_at carried as in
    # MVP-6.14. It is a MarketDataUnavailable subclass: existing handlers keep
    # working.
    broker = FixedHistoryBroker([], last_timestamp=NOW_OPEN)
    clock = FakeClock(NOW_OPEN)
    with pytest.raises(NoTradesInWindow) as exc_info:
        await _service(broker, clock).get_snapshot(FIGI, TF, lookback_bars=50)
    exc = exc_info.value
    assert exc.window_start == NOW_OPEN - timedelta(days=14)
    assert exc.last_trade_at == NOW_OPEN
    assert len(broker.candle_calls) == 3


# --- L2: depth formula and settings ---------------------------------------------


async def test_depth_formula_m5_min_search_days_wins() -> None:
    # M5 lookback 50: 4 x 50 x 300 s = 16.7 h < 14 days -> depth = 14 days.
    clock = FakeClock(NOW_OPEN)
    with pytest.raises(NoTradesInWindow) as exc_info:
        await _service(FixedHistoryBroker([], last_timestamp=NOW_OPEN), clock).get_snapshot(
            FIGI, TF, lookback_bars=50
        )
    assert exc_info.value.window_start == NOW_OPEN - timedelta(days=14)


async def test_depth_formula_d1_search_factor_wins() -> None:
    # DAY_1 lookback 200: 4 x 200 x 86400 s = 800 days > 14 days -> depth =
    # 800 days. The fill adds one 6-year chunk behind the 201-day window.
    broker = FixedHistoryBroker([], last_timestamp=NOW_OPEN)
    clock = FakeClock(NOW_OPEN)
    with pytest.raises(NoTradesInWindow) as exc_info:
        await _service(broker, clock).get_snapshot(
            FIGI, Timeframe.DAY_1, lookback_bars=200
        )
    assert exc_info.value.window_start == NOW_OPEN - timedelta(days=800)
    assert len(broker.candle_calls) == 2


async def test_depth_reads_custom_settings() -> None:
    # The values come from the application settings: with
    # snapshot_min_search_days = 2 and snapshot_search_factor = 1 the M5 depth
    # is max(2 days, 4.17 h) = 2 days.
    settings = Settings(snapshot_min_search_days=2, snapshot_search_factor=1)
    clock = FakeClock(NOW_OPEN)
    with pytest.raises(NoTradesInWindow) as exc_info:
        await _service(
            FixedHistoryBroker([], last_timestamp=NOW_OPEN), clock, settings=settings
        ).get_snapshot(FIGI, TF, lookback_bars=50)
    assert exc_info.value.window_start == NOW_OPEN - timedelta(days=2)


# --- L4 + S6: regression (MVP-6.13 reviewer probe) ------------------------------


async def test_s6_deferred_tick_at_reopen_runs_on_bar_before_close() -> None:
    # The MVP-6.13 reviewer probe: an intraday M5 bot's last tick fell at the
    # session close (Friday 15:45 UTC) and was deferred (S6). Before MVP-6.15
    # the wall-clock window at the Monday open lay inside the gap, so
    # get_snapshot raised MarketDataUnavailable, "not confirmed yet" (B5), and
    # the deferred tick was concluded by the B4 bound without a cycle. With the
    # bar-count snapshot the Monday open returns Friday's candles, the
    # deferred tick runs exactly once on the closed bar that ended at 15:45,
    # and no failure is counted at all.
    clock = FakeClock(datetime(2026, 5, 1, 15, 45, 5, tzinfo=UTC))
    history = _session_candles(*_weekdays(date(2026, 4, 20), MONDAY))
    broker = FixedHistoryBroker(
        history, last_timestamp=datetime(2026, 5, 1, 15, 44, 30, tzinfo=UTC)
    )
    service = _service(broker, clock)
    runtime = _Runtime(1, _strategy())
    manager = BotRuntimeManager(RiskManager())
    manager.register(runtime)

    async def _figi(runtime_) -> str:
        return FIGI

    async def _snapshot(figi: str, config: StrategyConfig) -> MarketSnapshot:
        return await service.get_snapshot(figi, config.timeframe, config.lookback_bars)

    statuses = _StatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # Friday 15:45:05: deferral
        TradingStatus.TRADING_UNAVAILABLE,  # Saturday: still closed
        TradingStatus.TRADING_UNAVAILABLE,  # Sunday: still closed
        TradingStatus.TRADING_AVAILABLE,    # Monday 07:00:05: the deferred tick runs
    )
    sched = LiveCycleScheduler(
        bot_runtime_manager=manager,
        broker=statuses,
        figi_provider=_figi,
        snapshot_provider=_snapshot,
        clock=clock,
    )

    # Friday close: the tick is deferred, nothing is fetched or counted.
    await sched.advance()
    await sched.settle()
    assert runtime.executions == []
    assert broker.candle_calls == []
    assert runtime.fail_reasons == []
    assert sched.last_error_for(1) is None

    # The weekend stays closed: the deferral persists.
    clock.set(datetime(2026, 5, 2, 12, 0, tzinfo=UTC))
    await sched.advance()
    await sched.settle()
    clock.set(datetime(2026, 5, 3, 12, 0, tzinfo=UTC))
    await sched.advance()
    await sched.settle()
    assert runtime.executions == []
    assert runtime.fail_reasons == []

    # Monday 07:00:05 UTC (session reopens): one deferred cycle on the Friday
    # closed bar [15:40, 15:45) — the bar before the close — not the B4 bound
    # conclusion.
    clock.set(datetime(2026, 5, 4, 7, 0, 5, tzinfo=UTC))
    await sched.advance()
    await sched.settle()
    assert len(runtime.executions) == 1
    assert runtime.fail_reasons == []
    assert sched.last_error_for(1) is None
    bars = runtime.executions[0].snapshot.get(TF).bars
    assert any(
        b.timestamp == datetime(2026, 5, 1, 15, 40, tzinfo=UTC) for b in bars
    )
    # No second cycle on the next pass: the deferred boundary is concluded.
    await sched.advance()
    await sched.settle()
    assert len(runtime.executions) == 1
