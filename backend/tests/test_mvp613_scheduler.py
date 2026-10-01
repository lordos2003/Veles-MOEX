"""MVP-6.13 Live Cycle Scheduler tests.

Focused on the new scheduler boundary (contracts S1-S6 of TASK-MVP-6.13):
tick timing by calculation method (AT_BAR_CLOSE / PER_MINUTE), the
trading-session gate (S3, with the S6 deferral — B1 round-1 correction), the
confirmation range check (B1), the failure policy (S4), the correctness guards
(S1) and the round-1 corrections B2 (shared live-session serialization) and B3
(state reset on restart), plus the S4 DealError exemption (a deal failure is
already surfaced by the Deal layer). Deterministic and broker-neutral: a fake
Clock (no real sleeps), duck-typed bot runtimes and broker/snapshot fakes. The
T-Invest status mapping is tested against the fake client at the end (adapter
boundary, not the scheduler).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.broker import BacktestBroker
from app.bots.repository import BotRepository
from app.brokers.tinvest import TInvestAdapter
from app.brokers.tinvest_errors import BrokerApiError, MarketDataError
from app.domain.instrument import TradingStatus
from app.domain.marketdata import (
    Candle,
    MarketDataUnavailable,
    MarketSnapshot,
    Timeframe,
)
from app.models.enums import BotState
from app.strategies.config import (
    DCAGridConfig,
    Direction,
    EntryConfig,
    ExitConfig,
    FixedPercentageTP,
    StrategyConfig,
)
from app.strategies.filters import CalculationMethod
from app.trading import (
    BotRuntimeManager,
    LiveCycleScheduler,
    RiskManager,
    SchedulerSettings,
)
from app.trading.deal import DealBlocked
from app.trading.live_execution import LiveExecutionBlocked, LiveExecutionService
from tests.fakes import TInvestFakeClient

# --- fixtures / fakes ----------------------------------------------------------

T0 = datetime(2026, 5, 1, 9, 30, tzinfo=UTC)  # an M5 UTC boundary (bar close)
FIGI = "BBG004730N88"
TF = Timeframe.MIN_5
STATUS_PATH = (
    "tinkoff.public.invest.api.contract.v1.MarketDataService/GetTradingStatus"
)
# Fixed-length bar intervals for building test snapshots (WEEK_1/MONTH_1 use
# calendar boundaries and are not needed here).
_BAR_SECONDS = {
    Timeframe.MIN_1: 60,
    Timeframe.MIN_5: 300,
    Timeframe.MIN_15: 900,
    Timeframe.MIN_30: 1800,
    Timeframe.HOUR_1: 3600,
    Timeframe.HOUR_4: 14400,
    Timeframe.DAY_1: 86400,
}


class FakeClock:
    """Injectable clock: tests set the current time explicitly."""

    def __init__(self, start: datetime) -> None:
        self._now = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += timedelta(seconds=seconds)
        # Yield once so an outer producer/consumer (e.g. task cancellation)
        # can interleave; this fake never sleeps real time (S5).
        await asyncio.sleep(0)


class FakeTradingStatusBroker:
    """Returns a fixed status, or raises a fixed error, per request."""

    def __init__(
        self,
        status: TradingStatus = TradingStatus.TRADING_AVAILABLE,
        error: Exception | None = None,
    ) -> None:
        self._status = status
        self._error = error
        self.calls: list[str] = []

    async def get_trading_status(self, figi: str) -> TradingStatus:
        self.calls.append(figi)
        if self._error is not None:
            raise self._error
        return self._status


class ProgrammedTradingStatusBroker:
    """Replays a scripted sequence of statuses/errors (last step repeats)."""

    def __init__(self, *steps: object) -> None:
        self._steps = list(steps)
        self.calls: list[str] = []

    async def get_trading_status(self, figi: str) -> TradingStatus:
        self.calls.append(figi)
        step = self._steps[0]
        if len(self._steps) > 1:
            self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeStrategy:
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config


class FakeRuntime:
    """Duck-typed BotRuntime: records executions/failures, can block."""

    def __init__(
        self,
        bot_id: int,
        strategy: FakeStrategy,
        state: BotState = BotState.RUNNING,
    ) -> None:
        self.bot_id = bot_id
        self._strategy = strategy
        self._state = state
        self.executions: list[object] = []
        self.execute_starts = 0
        self.fail_reasons: list[str] = []
        self.started_event: asyncio.Event | None = None
        self.execute_gate: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._state is BotState.RUNNING

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def strategy(self) -> FakeStrategy:
        return self._strategy

    def set_state(self, state: BotState) -> None:
        self._state = state

    def fail(self, reason: str) -> None:
        self.fail_reasons.append(reason)
        self._state = BotState.ERROR

    async def execute_strategy(self, context=None):
        self.execute_starts += 1
        if self.started_event is not None:
            self.started_event.set()
        if self.execute_gate is not None:
            await self.execute_gate.wait()
        self.executions.append(context)


class FakeSnapshotProvider:
    """Returns the current snapshot; tests mutate fields to script the flow."""

    def __init__(self, snapshot: MarketSnapshot | None = None) -> None:
        self.snapshot = snapshot if snapshot is not None else _single_candle_snapshot()
        self.requests: list[tuple[str, StrategyConfig]] = []
        self.unconfirmed_attempts = 0
        self.error: Exception | None = None

    async def __call__(self, figi: str, config: StrategyConfig) -> MarketSnapshot:
        self.requests.append((figi, config))
        if self.error is not None:
            raise self.error
        if self.unconfirmed_attempts > 0:
            self.unconfirmed_attempts -= 1
            return _single_candle_snapshot(None)
        return self.snapshot


def _strategy(
    method: CalculationMethod = CalculationMethod.AT_BAR_CLOSE,
    timeframe: Timeframe | None = TF,
    lookback_bars: int | None = 5,
) -> StrategyConfig:
    return StrategyConfig(
        direction=Direction.LONG,
        timeframe=timeframe,
        lookback_bars=lookback_bars,
        entry=EntryConfig(method=method),
        exit=ExitConfig(take_profit=FixedPercentageTP(percent=10.0)),
        dca_grid=DCAGridConfig(levels=1),
    )


def _single_candle_snapshot(
    start: datetime | None = None,
    complete: bool | None = True,
) -> MarketSnapshot:
    """Snapshot whose single candle starts at ``start`` (None = no candle)."""
    candles: tuple[Candle, ...] = ()
    if start is not None:
        candles = (
            Candle(
                figi=FIGI,
                timeframe=TF,
                timestamp=start,
                open=Decimal(100),
                high=Decimal(101),
                low=Decimal(99),
                close=Decimal("100.5"),
                volume=1000,
                is_complete=complete,
            ),
        )
    return MarketSnapshot(
        figi=FIGI,
        timeframe=TF,
        timestamp=T0,
        last_price=Decimal("100.5"),
        candles=candles,
    )


def _session_snapshot(first_start: datetime, count: int) -> MarketSnapshot:
    """Candles on consecutive M5 boundaries (covers multi-bar tests)."""
    candles = tuple(
        Candle(
            figi=FIGI,
            timeframe=TF,
            timestamp=first_start + timedelta(seconds=300 * i),
            open=Decimal(100) + i,
            high=Decimal(101) + i,
            low=Decimal(99) + i,
            close=Decimal("100.5") + i,
            volume=1000,
            is_complete=True,
        )
        for i in range(count)
    )
    return MarketSnapshot(
        figi=FIGI, timeframe=TF, timestamp=T0, last_price=Decimal("100.5"), candles=candles
    )


def _bars_ending_at(
    close: datetime,
    tf: Timeframe,
    count: int = 2,
    *,
    offset: timedelta = timedelta(0),
) -> MarketSnapshot:
    """Snapshot of ``tf`` candles whose last bar closes at ``close``.

    Each candle starts ``offset`` into its interval (``offset`` > 0 simulates
    a non-epoch-aligned broker stamp, e.g. a day candle at 03:00 UTC — the
    B1 range-confirmation case).
    """
    length = timedelta(seconds=_BAR_SECONDS[tf])
    candles = tuple(
        Candle(
            figi=FIGI,
            timeframe=tf,
            timestamp=close - length * (i + 1) + offset,
            open=Decimal(100) + i,
            high=Decimal(101) + i,
            low=Decimal(99) + i,
            close=Decimal("100.5") + i,
            volume=1000,
            is_complete=True,
        )
        for i in range(count)
    )
    return MarketSnapshot(
        figi=FIGI, timeframe=tf, timestamp=close, last_price=Decimal("100.5"),
        candles=candles,
    )


class _BotStub:
    """Minimal duck-typed Bot row for the B2 session stand-in."""

    def __init__(self, bot_id: int, deposit: Decimal | None) -> None:
        self.id = bot_id
        self.deposit = deposit
        self.status = BotState.RUNNING.value


class _OverlapDetectingSession:
    """Session stand-in that exposes overlapping operations (B2 regression).

    The reviewer reproduced the production defect on PostgreSQL: one
    long-lived AsyncSession used by concurrent bot passes raises
    (ResourceClosedError / IllegalStateChangeError). This stand-in detects the
    *condition* directly — more than one operation in flight at once — so the
    regression test needs no database, while the repository is exercised with
    the same call pattern as production ``_scheduler_figi`` /
    ``_persist_bot_error`` (get + get_deposit + update_state).
    """

    def __init__(self) -> None:
        self._active = 0
        self.max_active = 0
        self.deposit = Decimal("1000")

    async def get(self, model, bot_id, **kwargs):
        async with self._in_progress():
            return _BotStub(bot_id, self.deposit)

    async def commit(self):
        async with self._in_progress():
            return None

    async def refresh(self, obj):
        async with self._in_progress():
            return obj

    @asynccontextmanager
    async def _in_progress(self):
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        try:
            await asyncio.sleep(0)  # let concurrent owners interleave
            yield
        finally:
            self._active -= 1


def _runtime(
    bot_id: int,
    *,
    state: BotState = BotState.RUNNING,
    **strategy_kwargs,
) -> FakeRuntime:
    return FakeRuntime(bot_id, FakeStrategy(_strategy(**strategy_kwargs)), state=state)


def _make_scheduler(
    clock: FakeClock,
    runtimes: list[FakeRuntime],
    *,
    broker: FakeTradingStatusBroker | ProgrammedTradingStatusBroker | None = None,
    snapshot_provider: FakeSnapshotProvider | None = None,
    figi_provider=None,
    gate=None,
    on_bot_error=None,
    settings: SchedulerSettings | None = None,
    transient_error_types=None,
) -> LiveCycleScheduler:
    manager = BotRuntimeManager(RiskManager())
    for runtime in ([runtimes] if isinstance(runtimes, FakeRuntime) else runtimes):
        manager.register(runtime)
    if transient_error_types is None:
        from app.trading.scheduler import _DEFAULT_TRANSIENT_ERRORS

        transient_error_types = _DEFAULT_TRANSIENT_ERRORS

    if figi_provider is None:

        async def _figi(runtime) -> str:
            return FIGI

        figi_provider = _figi

    return LiveCycleScheduler(
        bot_runtime_manager=manager,
        broker=broker or FakeTradingStatusBroker(),
        figi_provider=figi_provider,
        snapshot_provider=snapshot_provider
        or FakeSnapshotProvider(
            _single_candle_snapshot(T0 - timedelta(minutes=5))
        ),
        clock=clock,
        settings=settings,
        safety_gate=gate,
        on_bot_error=on_bot_error,
        transient_error_types=transient_error_types,
    )


def _repo_figi(repo: BotRepository):
    """figi_provider shaped like production ``_scheduler_figi``.

    Every scheduler pass of a live bot touches the shared session exactly like
    this (``bot_repository.get`` + a fresh ``get_deposit`` read), which is the
    B2 concurrent-use surface.
    """

    async def _figi(runtime) -> str:
        bot = await repo.get(runtime.bot_id)
        assert bot is not None
        await repo.get_deposit(runtime.bot_id)
        return FIGI

    return _figi


async def _poll_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


# --- S2: tick timing -----------------------------------------------------------


def test_scheduler_settings_defaults() -> None:
    settings = SchedulerSettings()
    assert settings.bar_close_delay_seconds == 5.0
    assert settings.bar_close_retry_seconds == 5.0
    assert settings.bar_close_max_wait_seconds == 60.0
    assert settings.max_consecutive_failures == 3


async def test_at_bar_close_ticks_at_boundary_plus_delay_only() -> None:
    # Bar [09:20, 09:25) closed at 09:25:00; its tick is due at 09:25:05.
    clock = FakeClock(T0 - timedelta(minutes=5) + timedelta(seconds=5))
    rt = _runtime(1)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0 - timedelta(minutes=10)))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1  # ticked at boundary + 5s

    # Just after the 09:30:00 close the next tick is not due yet: boundary+5
    # (and the previous boundary is already done -> nothing runs at all).
    for offset in (1, 4):
        clock.set(T0 + timedelta(seconds=offset))
        snaps.snapshot = _single_candle_snapshot(T0 - timedelta(minutes=5))
        await sched.advance()
        await sched.settle()
        assert len(rt.executions) == 1

    # At exactly boundary + 5s the just-closed bar ticks exactly once.
    clock.set(T0 + timedelta(seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 2

    # Later in the same bar no second tick happens.
    clock.set(T0 + timedelta(seconds=30))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 2


async def test_at_bar_close_retries_every_retry_seconds_until_confirmed() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0 - timedelta(minutes=5)))
    snaps.unconfirmed_attempts = 2  # attempts at +5 and +10 are not confirmed
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []

    clock.set(T0 + timedelta(seconds=10))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []

    # Confirmed at +15 -> exactly one cycle for the bar.
    clock.set(T0 + timedelta(seconds=15))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 3


async def test_at_bar_close_skips_and_counts_transient_after_max_wait() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(None))  # never confirmed
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []

    # Retries inside the window never count a failure and the tick is pending.
    for offset in (10, 30, 55):
        clock.set(T0 + timedelta(seconds=offset))
        await sched.advance()
        await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None

    # Past boundary + max_wait: skip and count exactly one transient.
    clock.set(T0 + timedelta(seconds=61))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # 1 < max_consecutive_failures -> still RUNNING
    # The boundary is concluded: no further retries for the same bar.
    clock.set(T0 + timedelta(seconds=90))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert len(snaps.requests) == 4  # +5, +10, +30, +55 only


async def test_at_bar_close_none_completeness_is_not_confirmed() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    # The target candle is present but is_complete=None => not confirmed (S2).
    snaps = FakeSnapshotProvider(
        _single_candle_snapshot(T0 - timedelta(minutes=5), complete=None)
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []

    # Once the broker marks the same bar complete, the pending tick runs.
    clock.set(T0 + timedelta(seconds=10))
    snaps.snapshot = _single_candle_snapshot(T0 - timedelta(minutes=5), complete=True)
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1


async def test_per_minute_ticks_once_per_minute_boundary() -> None:
    clock = FakeClock(T0)
    rt = _runtime(1, method=CalculationMethod.PER_MINUTE)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1

    # Same UTC minute: no second tick.
    clock.set(T0 + timedelta(seconds=30))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1

    # Next minute boundary: exactly one more tick.
    clock.set(T0 + timedelta(minutes=1))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 2
    assert len(snaps.requests) == 2


# --- S3: trading-session gate + S6 deferral (B1) -------------------------------


async def test_s3_not_tradable_defers_tick_without_counting() -> None:
    # B1/S6: the tick fell while the instrument is not tradable -> deferred,
    # not dropped and not counted; it runs exactly once at the next tradable
    # moment, on the closed bar of the deferred boundary.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # boundary tick: deferral
        TradingStatus.TRADING_UNAVAILABLE,  # still closed a bit later
        TradingStatus.TRADING_AVAILABLE,    # tradable -> the deferred tick runs
    )
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0 - timedelta(minutes=5)))
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []  # the snapshot is never fetched while deferred
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None  # a deferral is NOT a failure

    # Still closed: the deferral persists (no conclusion, no count).
    clock.set(T0 + timedelta(seconds=30))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert len(snaps.requests) == 0
    assert rt.fail_reasons == []

    # Tradable: exactly one cycle on the closed bar (no earlier attempts).
    clock.set(T0 + timedelta(seconds=35))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 1
    assert rt.fail_reasons == []


async def test_s6_day1_boundary_outside_session_defers_to_next_tradable() -> None:
    # B1: a DAY_1 bar closes at 00:00 UTC = 03:00 MSK — always outside the
    # MOEX session. Without the S6 deferral such a bot would never tick. The
    # Friday bar [2026-05-01 00:00, 2026-05-02 00:00) closes at Sat 00:00 UTC;
    # the tick is deferred and runs exactly once at the next tradable moment
    # (Monday 07:00 UTC = 10:00 MSK) on the Friday closed bar.
    friday_bar_close = datetime(2026, 5, 2, 0, 0, tzinfo=UTC)  # Sat 00:00 UTC
    clock = FakeClock(friday_bar_close + timedelta(seconds=5))
    rt = _runtime(1, timeframe=Timeframe.DAY_1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # Sat 00:00:05 -> deferral
        TradingStatus.TRADING_UNAVAILABLE,  # Sunday: still closed
        TradingStatus.TRADING_AVAILABLE,    # Monday session open -> run once
    )
    snaps = FakeSnapshotProvider(_bars_ending_at(friday_bar_close, Timeframe.DAY_1))
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []
    assert rt.fail_reasons == []

    # Sunday 00:00:05 (another day boundary passed in the closed session).
    clock.set(friday_bar_close + timedelta(days=1, seconds=5))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []
    assert rt.fail_reasons == []

    # Monday 07:00 UTC: tradable -> one deferred cycle on the Friday bar.
    clock.set(friday_bar_close + timedelta(days=2, hours=7))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 1
    assert rt.fail_reasons == []


async def test_s6_several_closed_session_boundaries_produce_one_deferred_cycle() -> None:
    # Several bar boundaries pass in a row while the session is closed; the
    # deferred tick stays fixed to the boundary that fell first (the last bar
    # that actually closed) and produces exactly ONE cycle, no catch-up.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # boundary B: deferred
        TradingStatus.TRADING_UNAVAILABLE,  # B + 5m boundary passed
        TradingStatus.TRADING_UNAVAILABLE,  # B + 10m boundary passed
        TradingStatus.TRADING_AVAILABLE,    # tradable -> one deferred cycle
    )
    snaps = FakeSnapshotProvider(_session_snapshot(T0 - timedelta(minutes=5), 5))
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    for minutes in (0, 5, 10):
        clock.set(T0 + timedelta(minutes=minutes, seconds=5))
        await sched.advance()
        await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []
    assert rt.fail_reasons == []

    clock.set(T0 + timedelta(minutes=15, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 1
    assert rt.fail_reasons == []


async def test_s6_deferred_tick_runs_on_latest_closed_bar_when_deferred_bar_has_no_candle() -> None:
    # B4 (review round 2, reproduction): the deferred bar itself has no candle
    # (a bar without trades has none), but a complete candle that started
    # BEFORE the deferred boundary exists. The deferred tick must run exactly
    # once on that latest closed bar at the first tradable moment — not wait
    # forever for a candle inside the deferred bar's own range.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # boundary tick: deferral
        TradingStatus.TRADING_AVAILABLE,    # tradable at +14h -> run
    )
    # The last closed bar is [T0-10m, T0-5m); the deferred bar [T0-5m, T0) has
    # no candle (the reviewer's reproduction shape).
    snaps = FakeSnapshotProvider(
        _single_candle_snapshot(T0 - timedelta(minutes=10))
    )
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []
    assert rt.fail_reasons == []

    clock.set(T0 + timedelta(hours=14))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 1
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None


async def test_s6_deferred_tick_is_bounded_when_no_candle_and_newer_boundary_passes() -> None:
    # B4 (review round 2, item 2): tradable + no closed bar before the
    # deferred boundary + a newer bar boundary has passed -> the deferral is
    # concluded with ONE transient failure and normal boundary processing
    # resumes. The bound counts exactly one: two further transient failures on
    # the following boundaries trigger the S4 ERROR at 3.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # boundary tick: deferral
        TradingStatus.TRADING_AVAILABLE,    # +15m: bound -> 1 transient, conclude
        "SOME_FUTURE_STATUS",               # +15m+10s: 2nd transient (normal path)
        "SOME_FUTURE_STATUS",               # +20m+5s: 3rd transient -> ERROR
    )
    snaps = FakeSnapshotProvider(_single_candle_snapshot(None))  # no candles at all
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []

    clock.set(T0 + timedelta(minutes=15, seconds=5))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []  # the bound itself never runs a cycle
    assert rt.fail_reasons == []  # 1 transient < 3

    clock.set(T0 + timedelta(minutes=15, seconds=10))
    await sched.advance()
    await sched.settle()
    assert rt.fail_reasons == []

    clock.set(T0 + timedelta(minutes=20, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.fail_reasons) == 1
    assert "consecutive transient cycle failures" in rt.fail_reasons[0]
    assert rt.state is BotState.ERROR
    assert rt.executions == []


async def test_b5_deferred_reopen_empty_snapshot_is_not_counted_until_bound() -> None:
    # B5 (review round 3, reproduction): right after a session reopens the
    # wall-clock snapshot window (MVP-6.10: (lookback_bars + 1) x timeframe
    # before 'now') lies inside the night/weekend gap, so the snapshot
    # provider raises MarketDataUnavailable on every 1-s scheduler pass. In
    # the deferred path that is "not confirmed yet", not a per-pass failure:
    # the bot must stay RUNNING through the reopen seconds (before B5 it went
    # to ERROR within ~3 s). Only the B4 bound (a newer boundary passed)
    # counts exactly one transient; normal boundary processing then resumes.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        TradingStatus.TRADING_UNAVAILABLE,  # boundary tick: deferral
        TradingStatus.TRADING_AVAILABLE,    # session reopens: window empty
        TradingStatus.TRADING_AVAILABLE,
        TradingStatus.TRADING_AVAILABLE,
        TradingStatus.TRADING_AVAILABLE,
        TradingStatus.TRADING_AVAILABLE,    # +5m: the B4 bound fires
        TradingStatus.TRADING_AVAILABLE,    # +10m: normal processing resumes
    )
    snaps = FakeSnapshotProvider()
    snaps.error = MarketDataUnavailable("no candle history (night gap)")
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []  # S6: no snapshot while not tradable
    assert rt.fail_reasons == []

    # Reopen: every 1-s pass fetches, but the window is still empty.
    for second in (6, 7, 8, 9):
        clock.set(T0 + timedelta(seconds=second))
        await sched.advance()
        await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # B5: an empty snapshot is not a failure
    assert rt.state is BotState.RUNNING  # before B5: ERROR within ~3 s
    assert sched.last_error_for(1) is None
    assert len(snaps.requests) == 4

    # The B4 bound: a newer boundary has passed -> exactly one transient.
    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # 1 transient < 3 -> still RUNNING
    assert rt.state is BotState.RUNNING
    assert sched.last_error_for(1) is None

    # Normal boundary processing resumes; the next bar confirms, the cycle
    # runs and the S4 counter resets on success.
    snaps.error = None
    snaps.snapshot = _single_candle_snapshot(T0 + timedelta(minutes=5))
    clock.set(T0 + timedelta(minutes=10, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert rt.fail_reasons == []
    assert rt.state is BotState.RUNNING
    assert sched.last_error_for(1) is None


async def test_b1_closed_bar_confirmed_by_range_not_exact_equality() -> None:
    # B1: the closed bar is confirmed by a timestamp *range*, not exact
    # equality. A day candle stamped at a non-midnight start (03:00 UTC) still
    # confirms the bar that closed at 00:00 UTC.
    friday_bar_close = datetime(2026, 5, 2, 0, 0, tzinfo=UTC)
    clock = FakeClock(friday_bar_close + timedelta(seconds=5))
    rt = _runtime(1, timeframe=Timeframe.DAY_1)
    snaps = FakeSnapshotProvider(
        _bars_ending_at(friday_bar_close, Timeframe.DAY_1, offset=timedelta(hours=3))
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(snaps.requests) == 1


async def test_s3_unknown_status_is_counted_transient() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        "SOME_FUTURE_STATUS",
        "SOME_FUTURE_STATUS",
        "SOME_FUTURE_STATUS",
    )
    sched = _make_scheduler(clock, rt, broker=broker)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # 1 transient < 3

    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    assert rt.fail_reasons == []

    # Third consecutive unknown status -> terminal failure (S4).
    clock.set(T0 + timedelta(minutes=10, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.fail_reasons) == 1
    assert "consecutive transient cycle failures" in rt.fail_reasons[0]
    assert sched.last_error_for(1) == rt.fail_reasons[0]
    assert rt.state is BotState.ERROR


async def test_s3_failed_status_request_is_counted_transient() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = FakeTradingStatusBroker(error=MarketDataUnavailable("no session data"))
    sched = _make_scheduler(clock, rt, broker=broker)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # 1 transient < 3; the tick is skipped
    assert sched.last_error_for(1) is None


# --- S4: failure policy --------------------------------------------------------


async def test_s4_three_consecutive_transients_fail_bot() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = FakeTradingStatusBroker(error=MarketDataUnavailable("no session data"))
    reported: list[tuple[int, str]] = []

    async def _on_bot_error(bot_id: int, reason: str) -> None:
        reported.append((bot_id, reason))

    sched = _make_scheduler(
        clock, rt, broker=broker, on_bot_error=_on_bot_error
    )

    await sched.advance()
    await sched.settle()
    assert reported == []

    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    assert reported == []

    clock.set(T0 + timedelta(minutes=10, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(reported) == 1
    assert reported[0][0] == 1
    assert "consecutive transient cycle failures" in reported[0][1]
    assert sched.last_error_for(1) == reported[0][1]
    # The production callback is responsible for runtime.fail + persistence;
    # when no callback is wired the scheduler falls back to runtime.fail.
    assert rt.fail_reasons == []


async def test_s4_two_failures_then_success_resets_counter() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        "SOME_FUTURE_STATUS",  # 1st transient
        "SOME_FUTURE_STATUS",  # 2nd transient
        TradingStatus.TRADING_AVAILABLE,  # success -> reset
        "SOME_FUTURE_STATUS",  # 1st transient after reset
        "SOME_FUTURE_STATUS",  # 2nd
        "SOME_FUTURE_STATUS",  # 3rd -> terminal failure
    )
    snaps = FakeSnapshotProvider(_session_snapshot(T0 - timedelta(minutes=5), 8))
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    assert rt.executions == [] and rt.fail_reasons == []

    # Third bar: tradable -> the cycle succeeds and resets the counter.
    clock.set(T0 + timedelta(minutes=10, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert rt.fail_reasons == []
    assert rt.state is BotState.RUNNING

    # Three failures again -> terminal error (the reset mattered).
    clock.set(T0 + timedelta(minutes=15, seconds=5))
    await sched.advance()
    await sched.settle()
    clock.set(T0 + timedelta(minutes=20, seconds=5))
    await sched.advance()
    await sched.settle()
    clock.set(T0 + timedelta(minutes=25, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1
    assert len(rt.fail_reasons) == 1
    assert "consecutive transient cycle failures" in rt.fail_reasons[0]
    assert rt.state is BotState.ERROR


async def test_s4_non_transient_config_error_fails_bot_immediately() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1, lookback_bars=None)  # LookbackNotConfigured (non-transient)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0 - timedelta(minutes=5)))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert snaps.requests == []  # failed before any broker snapshot
    assert len(rt.fail_reasons) == 1
    assert "lookback_bars is not configured" in rt.fail_reasons[0]
    assert sched.last_error_for(1) == rt.fail_reasons[0]
    assert rt.state is BotState.ERROR


class _DealErrorRuntime(FakeRuntime):
    """Runtime whose cycle raises a DealError (already surfaced by the Deal layer)."""

    def __init__(self, bot_id: int, exc: Exception) -> None:
        super().__init__(bot_id, FakeStrategy(_strategy()))
        self._exc = exc

    async def execute_strategy(self, context=None):
        self.execute_starts += 1
        raise self._exc


async def test_s4_deal_error_is_not_double_handled() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _DealErrorRuntime(1, DealBlocked("bot 1 already has an open deal"))
    sched = _make_scheduler(clock, rt)

    await sched.advance()
    await sched.settle()

    # The Deal layer already moved the bot to ERROR with the deal reason (B2);
    # the scheduler must not fail it again or overwrite last_error (S4).
    assert rt.execute_starts == 1
    assert rt.fail_reasons == []
    assert rt.state is not BotState.ERROR
    assert sched.last_error_for(1) is None


# --- S1: correctness guards ----------------------------------------------------
async def test_s1_overlap_skips_tick_no_parallel_cycles() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    rt.execute_gate = asyncio.Event()
    rt.started_event = asyncio.Event()
    sched = _make_scheduler(clock, rt)

    await sched.advance()
    await asyncio.wait_for(rt.started_event.wait(), timeout=2)
    assert rt.execute_starts == 1

    # The cycle is still in flight: the next tick is skipped (no catch-up).
    clock.set(T0 + timedelta(seconds=10))
    await sched.advance()
    assert rt.execute_starts == 1
    assert rt.executions == []

    rt.execute_gate.set()
    await sched.settle()
    assert rt.execute_starts == 1
    assert len(rt.executions) == 1


async def test_s1_slow_bot_does_not_delay_another_bot() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    slow = _runtime(1)
    slow.execute_gate = asyncio.Event()
    slow.started_event = asyncio.Event()
    fast = _runtime(2)
    sched = _make_scheduler(clock, [slow, fast])

    await sched.advance()
    await asyncio.wait_for(slow.started_event.wait(), timeout=2)
    await _poll_until(lambda: len(fast.executions) == 1)

    assert fast.executions != []
    assert slow.execute_starts == 1
    assert slow.executions == []  # still blocked; the other bot is not delayed

    slow.execute_gate.set()
    await sched.settle()
    assert len(slow.executions) == 1


async def test_s1_failing_bot_does_not_block_other_bots() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    failing = _runtime(1, lookback_bars=None)  # fails immediately (non-transient)
    healthy = _runtime(2)
    sched = _make_scheduler(clock, [failing, healthy])

    await sched.advance()
    await sched.settle()
    assert len(failing.fail_reasons) == 1
    assert len(healthy.executions) == 1  # processed in the same pass


async def test_s1_only_running_bots_are_ticked() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    runtimes = [
        _runtime(0, state=BotState.STOPPED),
        _runtime(1, state=BotState.RUNNING),
        _runtime(2, state=BotState.ERROR),
        _runtime(3, state=BotState.EMERGENCY_STOP),
    ]
    sched = _make_scheduler(clock, runtimes)

    await sched.advance()
    await sched.settle()
    assert [len(rt.executions) for rt in runtimes] == [0, 1, 0, 0]
    assert all(rt.fail_reasons == [] for rt in runtimes)


async def test_s1_stopped_bot_is_not_ticked_anymore() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    sched = _make_scheduler(clock, rt)

    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1

    rt.set_state(BotState.STOPPED)
    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1


async def test_s1_no_ticks_while_safety_gate_closed() -> None:
    gate = [False]
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    snaps = FakeSnapshotProvider(_single_candle_snapshot(T0 - timedelta(minutes=5)))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps, gate=lambda: gate[0])

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert snaps.requests == []

    # Reopening the gate (service SAFE again) lets the same tick run.
    gate[0] = True
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1


async def test_run_forever_cancellation_stops_per_bot_tasks() -> None:
    # Application shutdown cancels run_forever while a per-bot pass is in
    # flight; the finally-shutdown must cancel that pass too (it uses the same
    # DB session the live stream shutdown closes next).
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    rt.execute_gate = asyncio.Event()
    rt.started_event = asyncio.Event()
    sched = _make_scheduler(clock, rt)

    task = asyncio.create_task(sched.run_forever())
    await asyncio.wait_for(rt.started_event.wait(), timeout=2)
    assert sched._tasks  # the per-bot pass is in flight
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sched._tasks == set()
    assert sched._inflight == set()


async def test_scheduler_not_started_before_safe_recovery() -> None:
    # Production: the application lifespan starts the scheduler only when the
    # startup recovery result is SAFE (see app/main.py); the service enforces it.
    service = LiveExecutionService(
        broker=None, store=None, order_manager=None, position_manager=None
    )
    with pytest.raises(LiveExecutionBlocked):
        await service.run_scheduler_forever()

    # Even when a scheduler is wired, it must not run before a SAFE recovery.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    scheduler = _make_scheduler(clock, rt)
    service._scheduler = scheduler
    with pytest.raises(LiveExecutionBlocked):
        await service.run_scheduler_forever()
    assert rt.executions == []


# --- B2/B3: review round-1 corrections ----------------------------------------


async def test_b3_failures_reset_after_error_and_restart() -> None:
    # B3: a bot that went ERROR must not carry its failure counter (nor its
    # pending/deferred boundary) into its next START. Without the reset the
    # first failure after the restart would already be the 4th -> ERROR again.
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime(1)
    broker = ProgrammedTradingStatusBroker(
        "SOME_FUTURE_STATUS",  # 1st transient
        "SOME_FUTURE_STATUS",  # 2nd transient
        "SOME_FUTURE_STATUS",  # 3rd transient -> terminal ERROR
        "SOME_FUTURE_STATUS",  # after restart: 1st transient only
    )
    sched = _make_scheduler(clock, rt, broker=broker)

    await sched.advance()
    await sched.settle()
    clock.set(T0 + timedelta(minutes=5, seconds=5))
    await sched.advance()
    await sched.settle()
    clock.set(T0 + timedelta(minutes=10, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.fail_reasons) == 1
    assert rt.state is BotState.ERROR

    # The scheduler observes the ERROR state on its next pass (B3 reset).
    clock.set(T0 + timedelta(minutes=10, seconds=30))
    await sched.advance()
    await sched.settle()

    # Owner restarts the bot: one failure after the restart stays transient.
    rt.set_state(BotState.RUNNING)
    clock.set(T0 + timedelta(minutes=15, seconds=5))
    await sched.advance()
    await sched.settle()
    assert len(rt.fail_reasons) == 1  # the old error only
    assert rt.state is BotState.RUNNING  # 1 failure < 3 -> bot still runs


async def test_b2_shared_session_without_lock_overlaps_under_concurrent_passes() -> None:
    # The 0c12cf1 wiring (one long-lived session, no serialization): several
    # bot passes touch the shared session at once — the exact condition the
    # reviewer reproduced on PostgreSQL (ResourceClosedError). The stand-in
    # detects overlapping operations directly (no database needed).
    session = _OverlapDetectingSession()
    repo = BotRepository(session)  # no lock: the reviewed wiring
    clock = FakeClock(T0 + timedelta(seconds=5))
    runtimes = [_runtime(i) for i in (1, 2, 3)]
    sched = _make_scheduler(clock, runtimes, figi_provider=_repo_figi(repo))

    await sched.advance()
    await sched.settle()
    assert session.max_active >= 2  # the B2 defect condition was reproduced


async def test_b2_shared_session_with_lock_stays_serialised_under_concurrent_passes() -> None:
    # Fix: BotRepository is given the single live-session lock; concurrent
    # passes keep working and no operation ever overlaps on the session.
    session = _OverlapDetectingSession()
    repo = BotRepository(session, lock=asyncio.Lock())
    clock = FakeClock(T0 + timedelta(seconds=5))
    runtimes = [_runtime(i) for i in (1, 2, 3)]
    sched = _make_scheduler(clock, runtimes, figi_provider=_repo_figi(repo))

    await sched.advance()
    await sched.settle()
    assert [len(rt.executions) for rt in runtimes] == [1, 1, 1]
    assert session.max_active == 1  # serialized by the live session lock


# --- S3 adapter boundary (T-Invest mapping) ------------------------------------


async def test_tinvest_adapter_maps_trading_status() -> None:
    adapter = TInvestAdapter(client=TInvestFakeClient())
    client: TInvestFakeClient = adapter._client  # type: ignore[attr-defined]

    def respond(status, flag=True):
        client.calls.clear()
        client.responses[STATUS_PATH] = {
            "trading_status": status,
            "api_trade_available_flag": flag,
        }

    # Normal trading with API trading available -> tradable.
    respond("SECURITY_TRADING_STATUS_NORMAL_TRADING", True)
    assert await adapter.get_trading_status(FIGI) is TradingStatus.TRADING_AVAILABLE
    assert client.calls[0] == (STATUS_PATH, {"instrumentId": FIGI})

    # Normal trading but API trading disabled -> not tradable (S3 skip).
    respond("SECURITY_TRADING_STATUS_NORMAL_TRADING", False)
    assert await adapter.get_trading_status(FIGI) is TradingStatus.TRADING_UNAVAILABLE

    # Every documented non-trading state -> not tradable, never a failure.
    for state in (
        "SECURITY_TRADING_STATUS_CLOSING_PERIOD",
        "SECURITY_TRADING_STATUS_BREAK_IN_TRADING",
        "SECURITY_TRADING_STATUS_NOT_AVAILABLE_FOR_TRADING",
        "SECURITY_TRADING_STATUS_OPENING_PERIOD",
        "SECURITY_TRADING_STATUS_SESSION_CLOSE",
    ):
        respond(state, True)
        assert (
            await adapter.get_trading_status(FIGI) is TradingStatus.TRADING_UNAVAILABLE
        ), state

    # Numeric status values (the raw investAPI proto) map the same way.
    respond(5, True)
    assert await adapter.get_trading_status(FIGI) is TradingStatus.TRADING_AVAILABLE
    respond(4, True)
    assert await adapter.get_trading_status(FIGI) is TradingStatus.TRADING_UNAVAILABLE

    # An unknown/UNSPECIFIED state must raise (never silently "not tradable").
    for unknown in ("SECURITY_TRADING_STATUS_UNSPECIFIED", "SECURITY_TRADING_STATUS_X"):
        respond(unknown, True)
        with pytest.raises(BrokerApiError):
            await adapter.get_trading_status(FIGI)

    # A failed request propagates to the scheduler as a transient (S3).
    client.responses.clear()
    client.errors[STATUS_PATH] = MarketDataError("status unavailable")
    with pytest.raises(MarketDataError):
        await adapter.get_trading_status(FIGI)


async def test_backtest_broker_has_no_session_restriction() -> None:
    broker = BacktestBroker()
    assert await broker.get_trading_status(FIGI) is TradingStatus.TRADING_AVAILABLE
