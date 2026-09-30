"""Live cycle scheduler (MVP-6.13, contracts S1-S5).

The scheduler decides *when* a RUNNING bot's strategy cycle runs: it calls the
existing |BotRuntime.execute_strategy| with a broker-neutral |MarketContext|
built from the raw |MarketSnapshot|, and nothing else. It does not change
entry/grid/TP/Deal/Risk/position semantics (S5): the MVP-6.11/6.12 gates stay
authoritative.

Timing is driven by the Veles calculation method of the bot
(``EntryConfig.method``, :data:`CalculationMethod`):

- ``AT_BAR_CLOSE`` (S2): one tick per bar of the bot's timeframe, at the UTC
  bar boundary + ``delay``. The just-closed bar must be present in the raw
  snapshot with ``is_complete is True`` (``None`` counts as not confirmed);
  otherwise the tick is retried every ``retry`` seconds up to ``max_wait``
  after the boundary, then skipped and counted as a transient failure (S4).
- ``PER_MINUTE`` (S2): one tick at every UTC minute boundary; the forming bar
  is used as-is (|FilterEvaluator| already handles it).

Before every cycle the scheduler asks the broker whether the instrument is
tradable *now* (S3): not tradable skips the tick without counting it; an
unknown/failed status skips it and counts a transient failure.

Failure policy (S4): transient failures (|MarketDataUnavailable|, broker
transport errors, confirmation timeout, unknown trading status) are counted per
bot in memory; after ``max_consecutive_failures`` consecutive ones the bot goes
to ERROR through |BotRuntime.fail|. Non-transient failures (configuration and
engine errors, unexpected exceptions) fail the bot immediately. A successful
cycle resets the counter. The last failure reason stays observable via
:meth:`LiveCycleScheduler.last_error_for`.

Correctness guards (S1): bots are scheduled independently (each bot's pass runs
in its own task, so a slow/failing bot never delays another); at most one cycle
per bot at a time — a pass that is still in flight when the next tick is due is
skipped, with no catch-up of missed ticks; only RUNNING bots are ticked; the
scheduler does not tick while the safety gate (the live service being SAFE) is
closed. Clock and sleeping are injectable (:class:`Clock`); tests never use
real sleeps (S5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Protocol

from app.brokers.base import BrokerAdapter, BrokerTransportError
from app.domain.instrument import TradingStatus
from app.domain.marketdata import (
    MarketDataUnavailable,
    MarketSnapshot,
    Timeframe,
)
from app.strategies.config import StrategyConfig
from app.strategies.filters import CalculationMethod
from app.trading.bot_lifecycle import BotRuntime, BotRuntimeManager
from app.trading.market_context import (
    LookbackNotConfigured,
    TimeframeNotConfigured,
    market_snapshot_to_context,
)

# Scheduler pass cadence. S2/S3 timing checks are event-driven per bot (delay /
# retry / boundaries), so a 1 s loop only decides *when* a bot is re-examined.
_LOOP_STEP_SECONDS = 1.0

# Simple timeframes are aligned on fixed UTC intervals; WEEK_1 / MONTH_1 use
# calendar boundaries (ISO Monday / the 1st of the month).
_TIMEFRAME_SECONDS = {
    Timeframe.MIN_1: 60,
    Timeframe.MIN_5: 300,
    Timeframe.MIN_15: 900,
    Timeframe.MIN_30: 1800,
    Timeframe.HOUR_1: 3600,
    Timeframe.HOUR_4: 14400,
    Timeframe.DAY_1: 86400,
}

# Broker-neutral transient failures (S4). Broker-specific transient errors
# derive from |BrokerTransportError| so no broker package is imported here.
_DEFAULT_TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    MarketDataUnavailable,
    BrokerTransportError,
    TimeoutError,
    ConnectionError,
)


class Clock(Protocol):
    """Injectable clock (S5): no real sleeps in tests."""

    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Production clock: UTC now and real asyncio sleeps."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FigiProvider(Protocol):
    """Resolves the broker FIGI for a runtime (broker-neutral)."""

    async def __call__(self, runtime: BotRuntime) -> str: ...


class SnapshotProvider(Protocol):
    """Fetches the raw |MarketSnapshot| used for confirmation and the cycle."""

    async def __call__(
        self, figi: str, config: StrategyConfig
    ) -> MarketSnapshot: ...


class BotErrorCallback(Protocol):
    """Production persistence hook: runtime.fail + BotRepository (S4)."""

    async def __call__(self, bot_id: int, reason: str) -> None: ...


@dataclass(frozen=True)
class SchedulerSettings:
    """Owner-approved ops parameters (MVP-6.13 S2/S4). Not financial values."""

    bar_close_delay_seconds: float = 5.0
    bar_close_retry_seconds: float = 5.0
    bar_close_max_wait_seconds: float = 60.0
    max_consecutive_failures: int = 3


@dataclass
class _BotTicker:
    """Per-bot scheduler state (in memory; S4 counter restarts on restart)."""

    runtime: BotRuntime
    figi: str
    failures: int = 0
    # S2 (AT_BAR_CLOSE): bar-boundary processing state. A boundary is claimed
    # when it first becomes due and concluded once its tick ran / was skipped.
    pending_boundary: datetime | None = None
    last_attempt_index: int = -1
    last_done_boundary: datetime | None = None
    # S2 (PER_MINUTE): the last minute boundary claimed for a single attempt.
    last_minute: datetime | None = None


class _StatusVerdict(Enum):
    AVAILABLE = auto()
    UNAVAILABLE = auto()
    FAILED = auto()


class LiveCycleScheduler:
    """Runs one strategy cycle per tick per RUNNING bot (S1)."""

    def __init__(
        self,
        *,
        bot_runtime_manager: BotRuntimeManager,
        broker: BrokerAdapter,
        figi_provider: FigiProvider,
        snapshot_provider: SnapshotProvider,
        clock: Clock | None = None,
        settings: SchedulerSettings | None = None,
        safety_gate: Callable[[], bool] | None = None,
        on_bot_error: BotErrorCallback | None = None,
        transient_error_types: tuple[type[Exception], ...] = _DEFAULT_TRANSIENT_ERRORS,
    ) -> None:
        self._manager = bot_runtime_manager
        self._broker = broker
        self._figi_provider = figi_provider
        self._snapshot_provider = snapshot_provider
        self._clock = clock or SystemClock()
        self._settings = settings or SchedulerSettings()
        self._safety_gate = safety_gate
        self._on_bot_error = on_bot_error
        self._transient_error_types = transient_error_types
        self._tickers: dict[int, _BotTicker] = {}
        self._tasks: set[asyncio.Task] = set()
        # S1: bot ids with a pass task in flight. Set synchronously in
        # :meth:`advance` (the per-bot ticker is created inside the pass task,
        # so it cannot carry the in-flight marker itself).
        self._inflight: set[int] = set()
        self._last_errors: dict[int, str] = {}
        self._stop_requested = False

    # --- public surface ---------------------------------------------------------

    @property
    def settings(self) -> SchedulerSettings:
        return self._settings

    def last_error_for(self, bot_id: int) -> str | None:
        """The last scheduler failure reason for the bot (S4 observability)."""
        return self._last_errors.get(bot_id)

    async def run_forever(self) -> None:
        """Serve the scheduler until :meth:`shutdown` (production loop).

        Cancelling the task (application shutdown) still runs
        :meth:`shutdown`: the per-bot pass tasks use the same long-lived DB
        session as the live stream, so they must be cancelled before that
        session is closed (see ``app/main.py`` lifespan).
        """
        try:
            while not self._stop_requested:
                await self.advance()
                await self._clock.sleep(_LOOP_STEP_SECONDS)
        finally:
            await self.shutdown()

    async def advance(self) -> None:
        """One scheduling pass over all RUNNING bots at the current clock time.

        Each bot's pass runs in its own task (S1: bot independence). A bot with
        a pass already in flight is skipped — at most one cycle per bot at a
        time, no catch-up of missed ticks.
        """
        for runtime in self._manager.list():
            if runtime.bot_id in self._inflight:
                continue  # S1: overlap -> this tick is skipped
            if not runtime.running:
                continue  # S1: only RUNNING bots are ticked
            self._inflight.add(runtime.bot_id)
            task = asyncio.create_task(self._process_ticker(runtime))
            task.add_done_callback(self._tasks.discard)
            self._tasks.add(task)

    async def settle(self) -> None:
        """Wait for all in-flight passes (tests / shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        """Cancel in-flight passes (application shutdown)."""
        self._stop_requested = True
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._inflight.clear()

    # --- per-bot pass -----------------------------------------------------------

    async def _process_ticker(self, runtime: BotRuntime) -> None:
        try:
            ticker = self._tickers.get(runtime.bot_id)
            try:
                if ticker is None:
                    ticker = _BotTicker(
                        runtime=runtime, figi=await self._figi_provider(runtime)
                    )
                    self._tickers[runtime.bot_id] = ticker
                if not runtime.running or not self._is_safe():
                    return  # S1: state change / service not SAFE -> no tick
                strategy = runtime.strategy
                if strategy is None:
                    raise RuntimeError(f"bot {runtime.bot_id} has no loaded strategy")
                config = strategy.config
                self._require_config(ticker, config)
                now = self._clock.now()
                if config.entry.method is CalculationMethod.AT_BAR_CLOSE:
                    await self._process_at_bar_close(ticker, config, now)
                else:
                    await self._process_per_minute(ticker, config, now)
            except Exception as exc:  # noqa: BLE001 - classified by S4 policy
                await self._handle_exception(ticker, exc)
        finally:
            self._inflight.discard(runtime.bot_id)

    def _is_safe(self) -> bool:
        return self._safety_gate is None or self._safety_gate()

    def _require_config(self, ticker: _BotTicker, config: StrategyConfig) -> None:
        """S4: missing timeframe / lookback are non-transient config errors."""
        if config.timeframe is None:
            raise TimeframeNotConfigured(
                f"bot {ticker.runtime.bot_id}: strategy timeframe is not configured"
            )
        if config.lookback_bars is None:
            raise LookbackNotConfigured(
                f"bot {ticker.runtime.bot_id}: strategy lookback_bars is not configured"
            )

    # --- AT_BAR_CLOSE (S2) ------------------------------------------------------

    async def _process_at_bar_close(
        self, ticker: _BotTicker, config: StrategyConfig, now: datetime
    ) -> None:
        tf = config.timeframe
        boundary = self._bar_start(
            now - timedelta(seconds=self._settings.bar_close_delay_seconds), tf
        )
        if boundary == ticker.last_done_boundary:
            return  # this boundary's tick already ran / was concluded
        if (
            boundary == ticker.pending_boundary
            and ticker.last_attempt_index >= self._attempt_index(now, boundary)
        ):
            return  # no new retry is due yet
        if now > boundary + timedelta(seconds=self._settings.bar_close_max_wait_seconds):
            # S2: the confirmation window for this tick has already expired.
            await self._handle_stale_boundary(ticker, boundary)
            return
        if ticker.pending_boundary != boundary:
            ticker.pending_boundary = boundary
            ticker.last_attempt_index = -1
        idx = self._attempt_index(now, boundary)
        if idx <= ticker.last_attempt_index:
            return
        ticker.last_attempt_index = idx
        verdict = await self._status_verdict(ticker)
        if verdict is _StatusVerdict.UNAVAILABLE:
            self._conclude_boundary(ticker, boundary)  # S3: skip, not counted
            return
        if verdict is _StatusVerdict.FAILED:
            self._conclude_boundary(ticker, boundary)  # counted in _status_verdict
            return
        # Tradable now: the raw snapshot must confirm the just-closed bar (S2).
        snapshot = await self._snapshot_provider(ticker.figi, config)
        if self._closed_bar_confirmed(snapshot, boundary, tf):
            success = await self._run_cycle(ticker, snapshot)
            if success:
                ticker.failures = 0
            self._conclude_boundary(ticker, boundary)
        # else: not confirmed yet -> the next retry (every ``retry`` seconds,
        # no later than ``max_wait``) re-checks; no failure is counted here.

    async def _handle_stale_boundary(self, ticker: _BotTicker, boundary: datetime) -> None:
        """The tick is late (S2 skip after max wait) — ask S3 first, then count."""
        verdict = await self._status_verdict(ticker)
        if verdict is _StatusVerdict.UNAVAILABLE:
            self._conclude_boundary(ticker, boundary)  # S3: not a failure
            return
        if verdict is _StatusVerdict.FAILED:
            self._conclude_boundary(ticker, boundary)  # counted already
            return
        await self._count_transient(
            ticker,
            f"closed bar not confirmed within max wait (boundary {boundary.isoformat()})",
        )
        self._conclude_boundary(ticker, boundary)

    def _attempt_index(self, now: datetime, boundary: datetime) -> int:
        """Which retry slot ``now`` falls into for the boundary (0 = first)."""
        delay = self._settings.bar_close_delay_seconds
        retry = self._settings.bar_close_retry_seconds
        elapsed = (now - boundary).total_seconds() - delay
        return int(elapsed // retry) if elapsed >= 0 else -1

    def _closed_bar_confirmed(
        self, snapshot: MarketSnapshot, boundary: datetime, tf: Timeframe
    ) -> bool:
        """S2: the bar that closed at ``boundary`` is present and complete.

        Confirmed from the *raw* snapshot: ``is_complete is True`` counts, and
        ``None`` (or False) counts as not confirmed — |market_snapshot_to_context|
        maps ``None`` to True, so S2 must not rely on that mapping.
        """
        target_start = self._bar_start(boundary - timedelta(seconds=1), tf)
        for candle in snapshot.candles:
            if candle.timestamp == target_start and candle.is_complete is True:
                return True
        return False

    def _conclude_boundary(self, ticker: _BotTicker, boundary: datetime) -> None:
        ticker.pending_boundary = None
        ticker.last_attempt_index = -1
        ticker.last_done_boundary = boundary

    # --- PER_MINUTE (S2) --------------------------------------------------------

    async def _process_per_minute(
        self, ticker: _BotTicker, config: StrategyConfig, now: datetime
    ) -> None:
        minute = self._bar_start(now, Timeframe.MIN_1)
        if minute == ticker.last_minute:
            return
        # Claim the minute before any await: exactly one attempt per minute.
        ticker.last_minute = minute
        verdict = await self._status_verdict(ticker)
        if verdict is _StatusVerdict.UNAVAILABLE:
            return  # S3: skip, not counted
        if verdict is _StatusVerdict.FAILED:
            return  # counted in _status_verdict
        snapshot = await self._snapshot_provider(ticker.figi, config)
        if await self._run_cycle(ticker, snapshot):
            ticker.failures = 0

    # --- shared building blocks -------------------------------------------------

    async def _status_verdict(self, ticker: _BotTicker) -> _StatusVerdict:
        """S3: ask the broker whether the instrument is tradable right now."""
        try:
            status = await self._broker.get_trading_status(ticker.figi)
        except Exception as exc:  # noqa: BLE001 - S3: request failure = transient
            await self._count_transient(
                ticker, f"trading status request failed: {exc}"
            )
            return _StatusVerdict.FAILED
        if status is TradingStatus.TRADING_AVAILABLE:
            return _StatusVerdict.AVAILABLE
        if status is TradingStatus.TRADING_UNAVAILABLE:
            return _StatusVerdict.UNAVAILABLE
        await self._count_transient(ticker, f"unknown trading status: {status!r}")
        return _StatusVerdict.FAILED

    async def _run_cycle(self, ticker: _BotTicker, snapshot: MarketSnapshot) -> bool:
        """Run one strategy cycle for the bot (S1/S5), True on success."""
        try:
            context = market_snapshot_to_context(snapshot)
            await ticker.runtime.execute_strategy(context=context)
        except Exception as exc:  # noqa: BLE001 - classified by S4 policy
            await self._handle_exception(ticker, exc)
            return False
        return True

    async def _handle_exception(self, ticker: _BotTicker | None, exc: Exception) -> None:
        """S4: transient failures are counted; everything else is immediate ERROR."""
        if isinstance(exc, self._transient_error_types):
            await self._count_transient(ticker, str(exc))
        else:
            await self._fail_bot(ticker, f"live cycle failed: {exc}")

    async def _count_transient(self, ticker: _BotTicker | None, reason: str) -> None:
        """Transient failure: skip the tick, count it, ERROR at the threshold."""
        if ticker is None:
            return
        ticker.failures += 1
        if ticker.failures >= self._settings.max_consecutive_failures:
            await self._fail_bot(
                ticker,
                f"bot {ticker.runtime.bot_id}: {ticker.failures} consecutive "
                f"transient cycle failures (last: {reason})",
            )

    async def _fail_bot(self, ticker: _BotTicker | None, reason: str) -> None:
        """Move the bot to ERROR (S4) and keep the reason observable."""
        if ticker is None:
            return
        self._last_errors[ticker.runtime.bot_id] = reason
        if self._on_bot_error is not None:
            await self._on_bot_error(ticker.runtime.bot_id, reason)
        else:
            ticker.runtime.fail(reason)

    # --- UTC bar boundaries -----------------------------------------------------

    def _bar_start(self, dt: datetime, tf: Timeframe) -> datetime:
        """Start of the T-Invest bar interval containing ``dt`` (UTC boundaries).

        Minute .. day intervals are fixed-length from the epoch; WEEK_1 bars
        start Monday 00:00 UTC, MONTH_1 bars on the 1st 00:00 UTC.
        """
        if tf is Timeframe.WEEK_1:
            day = dt.date() - timedelta(days=dt.weekday())
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        if tf is Timeframe.MONTH_1:
            return dt.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        seconds = _TIMEFRAME_SECONDS[tf]
        epoch = int(dt.timestamp())  # tz-aware UTC: floor is exact
        return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)
