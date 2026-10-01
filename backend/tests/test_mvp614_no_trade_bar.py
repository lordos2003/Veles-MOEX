"""MVP-6.14 no-trade bar tests (contracts N1-N3 of TASK-MVP-6.14).

On T-Invest a bar interval without trades has no candle. The scheduler must
not treat a *proven* no-trade bar as a failure: the tick is skipped (no cycle,
no failure count, the consecutive-failure counter is not reset) and the reason
is observable via ``last_skip_reason``. Proof is only ever from broker facts
(N1/N2); an unproven no-trade case keeps the MVP-6.13 behaviour (one transient
at ``max_wait``). Deterministic and broker-neutral: the same fake Clock,
broker and snapshot providers as the MVP-6.13 scheduler tests; no real sleeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.instrument import TradingStatus
from app.domain.marketdata import (
    Candle,
    LastPrice,
    MarketDataUnavailable,
    MarketSnapshot,
    NoTradesInWindow,
)
from app.models.enums import BotState
from app.services.market_data import MarketDataService
from app.strategies.filters import CalculationMethod
from tests.test_mvp613_scheduler import (
    FIGI,
    T0,
    TF,
    FakeClock,
    FakeRuntime,
    FakeSnapshotProvider,
    FakeStrategy,
    FakeTradingStatusBroker,
    _make_scheduler,
    _strategy,
)

# The target bar of boundary ``B`` (M5) is ``[B - 300 s, B)`` (B1 range).
_BAR_SECONDS = 300
_PROVEN_REASON_NEWER = "and a newer candle exists"
_PROVEN_REASON_TRADE = "is before the bar start"
_PROVEN_REASON_WINDOW = "empty candle window"


def _candle(start: datetime, complete: bool = True) -> Candle:
    return Candle(
        figi=FIGI,
        timeframe=TF,
        timestamp=start,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=1000,
        is_complete=complete,
    )


def _snapshot(
    candles: tuple[Candle, ...] = (),
    *,
    timestamp: datetime | None = None,
    last_trade_at: datetime | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        figi=FIGI,
        timeframe=TF,
        timestamp=timestamp or T0,
        last_price=Decimal("100.5"),
        candles=candles,
        last_trade_at=last_trade_at,
    )


def _not_proven_snapshot(boundary: datetime) -> MarketSnapshot:
    """No candle in the target bar, no newer candle, no last trade (N1 unproven)."""
    return _snapshot((_candle(boundary - timedelta(seconds=600)),))


def _proven_snapshot(boundary: datetime) -> MarketSnapshot:
    """Forming candle at the boundary: target bar quiet, data already past it."""
    return _snapshot((_candle(boundary, complete=False),))


def _runtime(
    method: CalculationMethod = CalculationMethod.AT_BAR_CLOSE,
) -> FakeRuntime:
    return FakeRuntime(1, FakeStrategy(_strategy(method=method)))


def _snap(snapshot: MarketSnapshot | None = None) -> FakeSnapshotProvider:
    return FakeSnapshotProvider(snapshot)


# --- N1: AT_BAR_CLOSE, proven no-trade bar ----------------------------------


async def test_n1_no_candle_in_target_bar_with_newer_candle_is_skipped() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap(_proven_snapshot(T0))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None
    reason = sched.last_skip_reason_for(1)
    assert reason is not None and _PROVEN_REASON_NEWER in reason
    assert sched._tickers[1].failures == 0

    # The boundary is concluded: the bar is never retried.
    clock.set(T0 + timedelta(seconds=10))
    await sched.advance()
    await sched.settle()
    assert len(snaps.requests) == 1
    assert sched.last_skip_reason_for(1) == reason


async def test_n1_no_candle_in_target_bar_with_last_trade_before_bar_is_skipped() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    # Only an old candle; the last trade time is before the target bar start.
    snaps = _snap(
        _snapshot(
            (_candle(T0 - timedelta(seconds=600)),),
            last_trade_at=T0 - timedelta(seconds=400),
        )
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None
    reason = sched.last_skip_reason_for(1)
    assert reason is not None and _PROVEN_REASON_TRADE in reason
    assert sched._tickers[1].failures == 0


async def test_n1_unproven_no_candle_keeps_max_wait_transient() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap(_not_proven_snapshot(T0))  # last trade unknown, no newer candle
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []

    for offset in (10, 30, 55):
        clock.set(T0 + timedelta(seconds=offset))
        await sched.advance()
        await sched.settle()
    assert rt.fail_reasons == []
    assert sched.last_skip_reason_for(1) is None

    # Past boundary + max_wait: exactly one transient (MVP-6.13 behaviour).
    clock.set(T0 + timedelta(seconds=61))
    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []  # 1 < 3 -> still RUNNING
    assert sched.last_skip_reason_for(1) is None
    assert sched._tickers[1].failures == 1


async def test_n1_lagging_feed_last_trade_inside_bar_is_not_proven() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    # No candle in the target bar, no newer candle, but the last trade is
    # inside/after the bar: trades happened, the data is lagging.
    snaps = _snap(
        _snapshot(
            (_candle(T0 - timedelta(seconds=600)),),
            last_trade_at=T0 - timedelta(seconds=120),
        )
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert sched.last_skip_reason_for(1) is None

    clock.set(T0 + timedelta(seconds=61))
    await sched.advance()
    await sched.settle()
    assert sched.last_skip_reason_for(1) is None
    assert sched._tickers[1].failures == 1


async def test_n1_ten_proven_skips_neither_increment_nor_reset_counter() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap(_not_proven_snapshot(T0))
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    async def _conclude_one_bar(boundary: datetime, offset: int) -> None:
        clock.set(boundary + timedelta(seconds=offset))
        await sched.advance()
        await sched.settle()

    # Two quiet (unproven) bars -> two transient failures.
    for i in (0, 1):
        boundary = T0 + timedelta(seconds=_BAR_SECONDS * i)
        await _conclude_one_bar(boundary, 5)
        await _conclude_one_bar(boundary, 61)
    assert sched._tickers[1].failures == 2

    # Ten proven no-trade bars: skipped, never counted, never reset.
    for i in range(2, 12):
        boundary = T0 + timedelta(seconds=_BAR_SECONDS * i)
        snaps.snapshot = _proven_snapshot(boundary)
        await _conclude_one_bar(boundary, 5)
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert rt.state is BotState.RUNNING
    assert sched._tickers[1].failures == 2  # neither incremented nor reset
    assert sched.last_skip_reason_for(1) is not None

    # One more quiet (unproven) bar -> the 3rd failure -> ERROR.
    boundary = T0 + timedelta(seconds=_BAR_SECONDS * 12)
    await _conclude_one_bar(boundary, 5)
    await _conclude_one_bar(boundary, 61)
    assert rt.state is BotState.ERROR
    assert len(rt.fail_reasons) == 1
    assert "3 consecutive transient cycle failures" in rt.fail_reasons[0]


# --- N1/N3: empty window (NoTradesInWindow) ---------------------------------


async def test_n1_empty_window_proven_quiet_is_skipped_at_bar_close() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap()
    snaps.error = NoTradesInWindow(
        "no candle history for BBG004730N88 @ 5m",
        last_trade_at=T0 - timedelta(seconds=400),  # before the window start
        window_start=T0 - timedelta(seconds=300),
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None
    reason = sched.last_skip_reason_for(1)
    assert reason is not None and _PROVEN_REASON_WINDOW in reason
    assert sched._tickers[1].failures == 0

    # Concluded at once: no max_wait wait, no retries for this bar.
    clock.set(T0 + timedelta(seconds=10))
    await sched.advance()
    await sched.settle()
    assert len(snaps.requests) == 1


async def test_n1_empty_window_proven_quiet_is_skipped_per_minute() -> None:
    clock = FakeClock(T0)
    rt = _runtime(CalculationMethod.PER_MINUTE)
    snaps = _snap()
    snaps.error = NoTradesInWindow(
        "no candle history",
        last_trade_at=T0 - timedelta(seconds=400),
        window_start=T0 - timedelta(seconds=300),
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None
    reason = sched.last_skip_reason_for(1)
    assert reason is not None and _PROVEN_REASON_WINDOW in reason
    assert sched._tickers[1].failures == 0


async def test_n1_empty_window_unproven_keeps_market_data_unavailable_behaviour() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap()
    snaps.error = NoTradesInWindow(
        "no candle history", last_trade_at=None, window_start=T0 - timedelta(seconds=300)
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert sched.last_skip_reason_for(1) is None

    # An unknown last-trade time proves nothing: one transient at max_wait.
    clock.set(T0 + timedelta(seconds=61))
    await sched.advance()
    await sched.settle()
    assert sched.last_skip_reason_for(1) is None
    assert sched._tickers[1].failures == 1


async def test_n1_empty_window_unproven_counts_per_minute_like_before() -> None:
    clock = FakeClock(T0)
    rt = _runtime(CalculationMethod.PER_MINUTE)
    snaps = _snap()
    snaps.error = NoTradesInWindow(
        "no candle history", last_trade_at=None, window_start=T0 - timedelta(seconds=60)
    )
    sched = _make_scheduler(clock, rt, snapshot_provider=snaps)

    # Three consecutive minutes with an unproven empty window: S4 -> ERROR.
    for minute in range(3):
        clock.set(T0 + timedelta(minutes=minute))
        await sched.advance()
        await sched.settle()
    assert rt.executions == []
    assert rt.state is BotState.ERROR
    assert len(rt.fail_reasons) == 1
    assert "3 consecutive transient cycle failures" in rt.fail_reasons[0]


# --- N3: deferred (S6) path unchanged ---------------------------------------


async def test_n3_deferred_path_treats_no_trades_window_as_not_confirmed() -> None:
    clock = FakeClock(T0 + timedelta(seconds=5))
    rt = _runtime()
    snaps = _snap()
    broker = FakeTradingStatusBroker(status=TradingStatus.TRADING_UNAVAILABLE)
    sched = _make_scheduler(clock, rt, broker=broker, snapshot_provider=snaps)

    await sched.advance()
    await sched.settle()
    assert rt.executions == []
    assert sched.last_error_for(1) is None  # a deferral is not a failure

    # The session reopens; the provider reports an empty window. Proven quiet
    # or not, the deferred path keeps "not confirmed yet" — no skip conclusion,
    # no count (B5/B6.1 unchanged).
    broker._status = TradingStatus.TRADING_AVAILABLE
    snaps.error = NoTradesInWindow(
        "no candle history",
        last_trade_at=T0 - timedelta(seconds=400),
        window_start=T0 - timedelta(seconds=300),
    )
    for offset in (6, 11, 16):
        clock.set(T0 + timedelta(seconds=offset))
        await sched.advance()
        await sched.settle()
    assert rt.executions == []
    assert rt.fail_reasons == []
    assert sched.last_error_for(1) is None
    assert sched.last_skip_reason_for(1) is None  # deferred: no skip recorded
    assert sched._tickers[1].failures == 0

    # The provider recovers: the deferred tick runs once on the latest closed
    # bar (B4), and the normal cycle resumes.
    snaps.error = None
    snaps.snapshot = _snapshot((_candle(T0 - timedelta(seconds=300)),))
    clock.set(T0 + timedelta(seconds=21))
    await sched.advance()
    await sched.settle()
    assert len(rt.executions) == 1


# --- N2: get_snapshot broker facts ------------------------------------------


class _NoCandleBroker:
    def __init__(self, *, last_timestamp: datetime | None) -> None:
        self._last_timestamp = last_timestamp

    async def get_candles(self, figi, timeframe, from_, to, limit=None):
        return []

    async def get_last_price(self, figi: str) -> LastPrice:
        return LastPrice(
            figi=figi,
            price=Decimal("300.5"),
            timestamp=self._last_timestamp,
            ticker="SBER",
        )


async def test_n2_empty_window_with_usable_last_price_raises_no_trades_in_window() -> None:
    ts = datetime(2026, 5, 1, 9, 29, tzinfo=UTC)
    service = MarketDataService(_NoCandleBroker(last_timestamp=ts))
    with pytest.raises(NoTradesInWindow) as exc_info:
        await service.get_snapshot(FIGI, TF, lookback_bars=5)
    exc = exc_info.value
    # A subclass: every existing MarketDataUnavailable handler still works.
    assert isinstance(exc, MarketDataUnavailable)
    assert "no candle history" in str(exc)
    assert exc.last_trade_at == ts
    assert exc.window_start is not None
    assert exc.window_start < datetime.now(UTC)  # the window started in the past
    assert exc.window_start > ts  # the last trade predates the window


async def test_n2_snapshot_carries_last_trade_at_separate_from_timestamp() -> None:
    ts = datetime(2026, 5, 1, 9, 20, tzinfo=UTC)

    class _Broker(_NoCandleBroker):
        async def get_candles(self, figi, timeframe, from_, to, limit=None):
            return [_candle(T0 - timedelta(seconds=600))]

    snap = await MarketDataService(_Broker(last_timestamp=ts)).get_snapshot(
        FIGI, TF, lookback_bars=5
    )
    assert snap.last_trade_at == ts  # the broker's last-trade timestamp
    assert snap.timestamp == ts  # MVP-6.10 meaning kept


async def test_n2_unknown_last_trade_time_keeps_none_and_old_timestamp_fallback() -> None:
    class _Broker(_NoCandleBroker):
        async def get_candles(self, figi, timeframe, from_, to, limit=None):
            return [_candle(T0 - timedelta(seconds=600))]

    snap = await MarketDataService(_Broker(last_timestamp=None)).get_snapshot(
        FIGI, TF, lookback_bars=5
    )
    assert snap.last_trade_at is None
    # Existing fallback: timestamp comes from the newest candle when the broker
    # gave no last-price time (MVP-6.10).
    assert snap.timestamp == T0 - timedelta(seconds=600)
