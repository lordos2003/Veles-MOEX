"""Live cycle scheduler (MVP-6.13, contracts S1-S6).

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
  Confirmation is a timestamp **range** check, not exact equality (B1): a
  complete candle whose start lies inside the bar interval is accepted, so a
  broker that stamps day/week/month bars at a non-epoch-aligned start is
  still confirmed.
- ``PER_MINUTE`` (S2): one tick at every UTC minute boundary; the forming bar
  is used as-is (|FilterEvaluator| already handles it).

Before every cycle the scheduler asks the broker whether the instrument is
tradable *now* (S3). When the tick falls while the instrument is not tradable
the tick is **deferred** — not dropped and not counted — and runs exactly once
at the next tradable moment, on the closed bar of the deferred boundary (S6).
An unknown/failed status skips the tick and counts a transient failure (S3
preserved).

Failure policy (S4): transient failures (|MarketDataUnavailable|, broker
transport errors, confirmation timeout, unknown trading status) are counted per
bot in memory; after ``max_consecutive_failures`` consecutive ones the bot goes
to ERROR through |BotRuntime.fail|. Non-transient failures (configuration and
engine errors, unexpected exceptions) fail the bot immediately. A successful
cycle resets the counter. The last failure reason stays observable via
:meth:`LiveCycleScheduler.last_error_for`. ``DealError`` is exempt: the Deal
layer already surfaced every deal failure to the bot lifecycle (MVP-6.12 B2)
before re-raising, so the scheduler does not double-handle it (S4).

Correctness guards (S1): bots are scheduled independently (each bot's pass runs
in its own task, so a slow/failing bot never delays another); at most one cycle
per bot at a time — a pass that is still in flight when the next tick is due is
skipped, with no catch-up of missed ticks; only RUNNING bots are ticked; the
scheduler does not tick while the safety gate (the live service being SAFE) is
closed. Clock and sleeping are injectable (:class:`Clock`); tests never use
real sleeps (S5).

Round-1 review corrections: B1 (range confirmation, above) with the new S6
(AT_BAR_CLOSE deferral: a DAY_1 boundary falls at 00:00 UTC — outside the MOEX
session — so without a deferral such a bot would never tick); B2 — the live
long-lived AsyncSession is shared by concurrent bot passes and must be
serialized (see ``app/persistence`` and ``app/bots``); B3 — a bot state change
(in particular a restart after ERROR) resets the per-bot scheduler state
(:meth:`LiveCycleScheduler.advance`).

Round-2 review correction (B4): the deferred tick runs on the **latest closed
bar** (a complete candle that started before the deferred boundary), not on a
candle inside the deferred bar's own range — a bar without trades has no
candle, so the old rule could stall the bot in ``deferred`` forever. The
deferral is also bounded: while tradable, if no such candle exists and a newer
bar boundary has passed, the deferral is concluded with one transient failure
and normal boundary processing resumes.

Round-3 review correction (B5): while the deferred tick waits for its first
tradable moment, an unavailable snapshot (|MarketDataUnavailable| — the
wall-clock lookback window is empty right after a session reopen, lying inside
the night/weekend gap) counts as **"not confirmed yet"**, not as a per-pass
failure; only the B4 bound concludes the deferral (one transient failure).

Round-4 review correction (B6): a tick is **at most one transient failure**, so
a transient data failure inside a retry window (|MarketDataUnavailable|,
transport error or a still-unconfirmed bar) never counts per retry slot — the
tick stays pending and exactly one transient is counted only when ``max_wait``
expires without a successful cycle (non-transient errors still fail the bot
immediately). The B4 bound is relative to the **first tradable moment** after
the deferral: it may conclude only after a full bar of trading has passed plus
the normal ``max_wait``, so a session reopen (e.g. after a night/weekend gap)
gives the data a chance before the deferral is dropped. While deferred, the
trading status is polled at the retry cadence (5 s), not on every 1-s pass, and
a failed/rate-limited status counts at most once per bar boundary.

MVP-6.14 (N1/N3, approved contract): a bar **proven** to contain no trades
(no candle in the target bar and either a newer candle or a last trade before
the bar start) is a **skipped tick** — no cycle, no failure count, the
consecutive-failure counter is not reset — and the reason is observable via
:meth:`LiveCycleScheduler.last_skip_reason_for` (``GET /api/bots/{id}``). The
proof uses only broker facts (|NoTradesInWindow| / ``MarketSnapshot.last_trade_at``
per N2); unproven cases keep the MVP-6.13 behaviour unchanged. The deferred S6
path is unchanged: a no-trade bar while deferred stays "not confirmed yet".
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
    NoTradesInWindow,
    Timeframe,
)
from app.models.enums import BotState
from app.strategies.config import StrategyConfig
from app.strategies.filters import CalculationMethod
from app.trading.bot_lifecycle import BotRuntime, BotRuntimeManager
from app.trading.deal import DealError
from app.trading.market_context import (
    LookbackNotConfigured,
    TimeframeNotConfigured,
    market_snapshot_to_context,
)

# Scheduler pass cadence. S2/S3 timing checks are event-driven per bot (delay /
# retry / boundaries), so a 1 s loop only decides *when* a bot is re-examined.
_LOOP_STEP_SECONDS = 1.0

# Simple timeframes are aligned on fixed UTC intervals; WEEK_1 / MONTH_1 use
# calendar boundaries (ISO Monday / the 1st of the month). WEEK_1 / MONTH_1
# durations are nominal (7 / 30 days) — only used for the B6.2 bound timing.
_TIMEFRAME_SECONDS = {
    Timeframe.MIN_1: 60,
    Timeframe.MIN_5: 300,
    Timeframe.MIN_15: 900,
    Timeframe.MIN_30: 1800,
    Timeframe.HOUR_1: 3600,
    Timeframe.HOUR_4: 14400,
    Timeframe.DAY_1: 86400,
    Timeframe.WEEK_1: 7 * 86400,
    Timeframe.MONTH_1: 30 * 86400,
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
    """Per-bot scheduler state (in memory; S4 counter restarts on restart).

    B3 (review round 1): the state below is reset on bot state changes
    (:meth:`LiveCycleScheduler._reset_ticker_state`), except
    ``last_done_boundary``: a concluded bar must never be ticked twice.
    """

    runtime: BotRuntime
    figi: str
    failures: int = 0
    # S2/S6 (AT_BAR_CLOSE): bar-boundary processing state. A boundary is
    # claimed when it first becomes due and concluded once its tick ran / was
    # skipped. ``deferred`` marks an S6 deferral: the tick fell while the
    # instrument was not tradable and waits for the next tradable moment.
    pending_boundary: datetime | None = None
    deferred: bool = False
    last_attempt_index: int = -1
    last_done_boundary: datetime | None = None
    # B6.3 (review round 4): deferred status polling cadence — the trading
    # status is re-checked at the retry cadence, not on every 1-s pass, and a
    # failed/rate-limited status counts at most once per bar boundary.
    deferred_status_check_at: datetime | None = None
    deferred_failed_bar: datetime | None = None
    # B6.2 (review round 4): the first moment the deferred tick observed the
    # instrument tradable — the B4 bound is relative to it, so a session
    # reopen gives the data a full bar (+ max_wait) before the conclusion.
    deferred_first_tradable: datetime | None = None
    # S2 (PER_MINUTE): the last minute boundary claimed for a single attempt.
    last_minute: datetime | None = None
    # B3: the last state observed by advance(); a change resets the state above.
    last_seen_state: BotState | None = None
    # MVP-6.14 (N1): the last skipped no-trade tick's reason (None until the
    # first proven no-trade tick). Read-only observability via
    # :meth:`LiveCycleScheduler.last_skip_reason_for`; reset with the rest of
    # the ticker state on a bot state change (B3).
    last_skip_reason: str | None = None


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

    def last_skip_reason_for(self, bot_id: int) -> str | None:
        """The last proven no-trade skip reason (MVP-6.14 N1 observability)."""
        ticker = self._tickers.get(bot_id)
        return ticker.last_skip_reason if ticker is not None else None

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
            ticker = self._tickers.get(runtime.bot_id)
            if ticker is not None and ticker.last_seen_state != runtime.state:
                # B3 (review round 1): a bot state change — in particular a
                # restart after ERROR — resets the per-bot scheduler state
                # (failure counter, pending/deferred boundary, PER_MINUTE
                # claim). The last concluded boundary is kept so a finished
                # bar is never ticked twice.
                self._reset_ticker_state(ticker)
                ticker.last_seen_state = runtime.state
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
                        runtime=runtime,
                        figi=await self._figi_provider(runtime),
                        last_seen_state=runtime.state,
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

    # --- AT_BAR_CLOSE (S2 + S6) -------------------------------------------------

    async def _process_at_bar_close(
        self, ticker: _BotTicker, config: StrategyConfig, now: datetime
    ) -> None:
        tf = config.timeframe
        if ticker.deferred:
            # S6 (B1): the deferred boundary is fixed — a closed session passes
            # no newer closed bar, so the clock must not advance the deferral.
            await self._process_deferred(ticker, config, now)
            return
        boundary = self._bar_start(
            now - timedelta(seconds=self._settings.bar_close_delay_seconds), tf
        )
        if boundary == ticker.last_done_boundary:
            return  # this boundary's tick already ran / was concluded
        if ticker.pending_boundary is not None:
            if boundary > ticker.pending_boundary:
                # S6/S2: a newer boundary is due while an older one is still
                # pending -> only the latest pending boundary is kept (no
                # catch-up of missed bars).
                self._supersede_pending(ticker)
            elif boundary < ticker.pending_boundary:
                return  # clock moved back: defensive, never observed normally
        if ticker.pending_boundary != boundary:
            ticker.pending_boundary = boundary
            ticker.last_attempt_index = -1
        idx = self._attempt_index(now, boundary)
        if idx <= ticker.last_attempt_index:
            return  # no new retry slot is due yet
        ticker.last_attempt_index = idx
        verdict = await self._status_verdict(ticker)
        if verdict is _StatusVerdict.UNAVAILABLE:
            # S6 (B1): the tick fell while the instrument is not tradable (a
            # DAY_1 boundary falls at 00:00 UTC, always outside the MOEX
            # session). The tick is deferred — not dropped, not counted — and
            # runs once at the next tradable moment, on the closed bar of this
            # boundary.
            ticker.deferred = True
            return
        if verdict is _StatusVerdict.FAILED:
            self._conclude_boundary(ticker, boundary)  # counted in _status_verdict
            return
        # Tradable now: the raw snapshot must confirm the just-closed bar (S2).
        await self._confirm_boundary(ticker, config, tf, now, boundary)

    async def _process_deferred(
        self, ticker: _BotTicker, config: StrategyConfig, now: datetime
    ) -> None:
        """S6 (B1) + B4: re-check the session for a deferred tick at the cadence.

        While the instrument is not tradable the deferral persists (it is never
        a failure count). An unknown/failed status is counted as a transient
        (S3) but does not drop the deferral. The moment the instrument is
        tradable again the deferred tick runs exactly once, on the **latest
        closed bar** (B4): a complete candle that started **before** the
        deferred boundary. A bar without trades has no candle, so the tick
        must not wait for a candle inside the deferred bar's own range — the
        S2 max-wait timeout does not apply (the tick was deferred, not lost).

        B4 bound (B6.2, review round 4): the deferral is concluded with one
        transient failure and normal boundary processing resumes only after a
        **full bar of trading has passed since the first tradable moment, plus
        the normal ``max_wait``** — a session reopen (night/weekend gap) gives
        the data that full bar before the conclusion, so a bot is never stuck
        while trading is open, but also is never dropped within seconds of the
        reopen.

        B5 (review round 3) + B6.1: an unavailable snapshot (|MarketDataUnavailable|
        — the wall-clock lookback window is empty right after a session reopen,
        lying inside the night/weekend gap) or a snapshot with no closed bar
        before the boundary is **"not confirmed yet"**, never a per-pass
        failure; the B4 bound above is the only conclusion.

        B6.3 (review round 4): while deferred, the trading status is polled at
        the retry cadence (5 s) instead of on every 1-s pass (a rate-limit
        storm on |get_trading_status|), and a failed/rate-limited status counts
        at most once per bar boundary.
        """
        boundary = ticker.pending_boundary
        assert boundary is not None
        tf = config.timeframe
        retry = self._settings.bar_close_retry_seconds
        check_at = ticker.deferred_status_check_at
        if check_at is not None and now < check_at:
            return  # B6.3: status poll not due yet (5 s cadence)
        ticker.deferred_status_check_at = now + timedelta(seconds=retry)
        # B6.3: a failed/rate-limited status counts at most once per bar boundary.
        bar = self._bar_start(now, tf)
        count_status_fail = ticker.deferred_failed_bar != bar
        verdict = await self._status_verdict(ticker, count_on_fail=count_status_fail)
        if verdict is not _StatusVerdict.AVAILABLE:
            if verdict is _StatusVerdict.FAILED and count_status_fail:
                ticker.deferred_failed_bar = bar
            return  # UNAVAILABLE: deferral persists; FAILED: counted (S3, capped)
        if ticker.deferred_first_tradable is None:
            # B6.2: remember the first tradable moment — the bound is relative
            # to it, so the reopen gets a full bar (+ max_wait) of data time.
            ticker.deferred_first_tradable = now
        try:
            snapshot = await self._snapshot_provider(ticker.figi, config)
        except Exception as exc:  # noqa: BLE001 - classified by S4 policy
            if not isinstance(exc, self._transient_error_types):
                await self._fail_bot(ticker, f"live cycle failed: {exc}")
                return
            # B5/B6.1: "not confirmed yet" — the provider cannot return a
            # snapshot (empty window after the gap) or had a transport hiccup;
            # the B6.2 bound below decides.
            snapshot = None
        if snapshot is not None and self._latest_closed_bar_before(snapshot, boundary):
            ticker.deferred = False
            success = await self._run_cycle(ticker, snapshot)
            if success:
                ticker.failures = 0
            self._conclude_boundary(ticker, boundary)
            return
        first_tradable = ticker.deferred_first_tradable
        assert first_tradable is not None  # set above on the AVAILABLE branch
        bound_at = (
            self._bar_start(first_tradable, tf)
            + timedelta(
                seconds=_TIMEFRAME_SECONDS[tf]
                + self._settings.bar_close_max_wait_seconds
            )
        )
        if now >= bound_at:
            await self._count_transient(
                ticker,
                f"deferred tick not confirmed (no closed bar before "
                f"{boundary.isoformat()}); a full bar of trading passed since "
                f"{first_tradable.isoformat()}",
            )
            self._conclude_boundary(ticker, boundary)

    async def _confirm_boundary(
        self, ticker: _BotTicker, config: StrategyConfig, tf: Timeframe,
        now: datetime, boundary: datetime,
    ) -> None:
        """S2: confirm the just-closed bar in the raw snapshot, then one cycle.

        Retry slots keep re-checking until ``max_wait``; past it the tick is
        skipped and counted as one transient failure (S2/S4). While not
        confirmed no failure is counted (the tick is simply pending).

        B6.1 (review round 4): a transient data failure inside the retry
        window — an unavailable snapshot (empty wall-clock window after a
        session open), a transport error or a still-unconfirmed bar — is
        **"not confirmed yet"**, never a per-retry-slot failure: the tick stays
        pending and exactly one transient is counted when ``max_wait`` expires.
        A non-transient data failure is a real error and fails the bot
        immediately (S4).

        MVP-6.14 (N1): a bar **proven** to contain no trades (no candle in the
        target range and a newer candle or a last trade before the bar start —
        see :meth:`_proven_no_trade_bar`) concludes the tick as a **skip** at
        once: no cycle, no failure count, no max-wait wait. The same applies to
        an empty window proven quiet (|NoTradesInWindow| with a last trade
        before the window started). An unproven no-trade case keeps the
        behaviour above (a lagging feed must still be detected).
        """
        if now > boundary + timedelta(seconds=self._settings.bar_close_max_wait_seconds):
            await self._count_transient(
                ticker,
                f"closed bar not confirmed within max wait (boundary {boundary.isoformat()})",
            )
            self._conclude_boundary(ticker, boundary)
            return
        try:
            snapshot = await self._snapshot_provider(ticker.figi, config)
        except Exception as exc:  # noqa: BLE001 - classified by S4 policy
            if isinstance(exc, NoTradesInWindow) and self._proven_no_trade_window(exc):
                # MVP-6.14 (N1): an empty window proven quiet (last trade before
                # the window started) concludes the tick as a skip at once.
                self._skip_no_trade_bar(
                    ticker, boundary, self._empty_window_skip_reason(exc)
                )
                return
            if not isinstance(exc, self._transient_error_types):
                await self._fail_bot(ticker, f"live cycle failed: {exc}")
                return
            return  # B6.1: transient -> "not confirmed yet", retry slot re-checks
        if self._proven_no_trade_bar(snapshot, boundary, tf):
            # MVP-6.14 (N1): a proven no-trade bar is a skipped tick — no cycle,
            # no failure count, the counter is not reset.
            self._skip_no_trade_bar(
                ticker, boundary, self._bar_skip_reason(snapshot, boundary, tf)
            )
            return
        if self._closed_bar_confirmed(snapshot, boundary, tf):
            success = await self._run_cycle(ticker, snapshot)
            if success:
                ticker.failures = 0
            self._conclude_boundary(ticker, boundary)
        # else: not confirmed yet -> the next retry slot re-checks (S2).

    def _proven_no_trade_bar(
        self, snapshot: MarketSnapshot, boundary: datetime, tf: Timeframe
    ) -> bool:
        """MVP-6.14 (N1): the target bar is proven to contain no trades.

        The target bar is ``[bar_start(boundary - 1 s), boundary)`` — the same
        range B1 confirms from. Proven only from broker facts: **no candle**
        lies in the range (a candle present, even incomplete, disproves it)
        **and** either a candle starting at/after ``boundary`` exists (the
        broker's data is already past the target bar) or the broker's last
        trade time is known and earlier than the bar start. A lagging feed (no
        newer candle, unknown or in-bar last trade) is not proven and keeps
        the MVP-6.13 max-wait behaviour.
        """
        range_start = self._bar_start(boundary - timedelta(seconds=1), tf)
        for candle in snapshot.candles:
            if range_start <= candle.timestamp < boundary:
                return False
        if any(candle.timestamp >= boundary for candle in snapshot.candles):
            return True
        return (
            snapshot.last_trade_at is not None
            and snapshot.last_trade_at < range_start
        )

    def _proven_no_trade_window(self, exc: NoTradesInWindow) -> bool:
        """MVP-6.14 (N1): an empty window is proven quiet only from facts.

        The broker's last trade time is known and earlier than the window
        start. An unknown last-trade time proves nothing — the empty window
        keeps the existing |MarketDataUnavailable| handling.
        """
        return exc.last_trade_at is not None and exc.last_trade_at < exc.window_start

    def _bar_skip_reason(
        self, snapshot: MarketSnapshot, boundary: datetime, tf: Timeframe
    ) -> str:
        """Human-readable reason for a proven no-trade bar (N1 observability)."""
        range_start = self._bar_start(boundary - timedelta(seconds=1), tf)
        if snapshot.last_trade_at is not None and snapshot.last_trade_at < range_start:
            return (
                f"no-trade bar skipped: no candle in "
                f"[{range_start.isoformat()}, {boundary.isoformat()}) and last "
                f"trade at {snapshot.last_trade_at.isoformat()} is before the "
                f"bar start"
            )
        return (
            f"no-trade bar skipped: no candle in "
            f"[{range_start.isoformat()}, {boundary.isoformat()}) and a newer "
            f"candle exists"
        )

    def _empty_window_skip_reason(self, exc: NoTradesInWindow) -> str:
        """Human-readable reason for a proven-quiet empty window (N1)."""
        return (
            f"no-trade bar skipped: empty candle window since "
            f"{exc.window_start.isoformat()} and last trade at "
            f"{exc.last_trade_at.isoformat()} is before the window start"
        )

    def _record_skip(self, ticker: _BotTicker, reason: str) -> None:
        """MVP-6.14 (N1): record a skipped no-trade tick.

        No failure count, no counter reset (a skip is neither a success nor a
        failure); the reason stays observable via
        :meth:`last_skip_reason_for`.
        """
        ticker.last_skip_reason = reason

    def _skip_no_trade_bar(
        self, ticker: _BotTicker, boundary: datetime, reason: str
    ) -> None:
        """MVP-6.14 (N1): a proven no-trade AT_BAR_CLOSE tick is concluded.

        The boundary is concluded (the bar is never retried) and the skip is
        recorded. No cycle ran.
        """
        self._record_skip(ticker, reason)
        self._conclude_boundary(ticker, boundary)

    def _supersede_pending(self, ticker: _BotTicker) -> None:
        """S6/S2: a newer boundary supersedes an older pending one (no catch-up).

        Only the latest pending boundary is kept. The older pending is dropped
        without a failure count — a confirming pending that was never concluded
        is only reachable when the confirmation window spans more than one bar
        (MIN_1-scale settings), and the newer boundary's own S2/S3/S6 rules
        govern from here. A deferred boundary never reaches this path: the
        deferred tick is fixed to its own boundary.
        """
        self._conclude_boundary(ticker, ticker.pending_boundary)

    def _attempt_index(self, now: datetime, boundary: datetime) -> int:
        """Which retry slot ``now`` falls into for the boundary (0 = first)."""
        delay = self._settings.bar_close_delay_seconds
        retry = self._settings.bar_close_retry_seconds
        elapsed = (now - boundary).total_seconds() - delay
        return int(elapsed // retry) if elapsed >= 0 else -1

    def _closed_bar_confirmed(
        self, snapshot: MarketSnapshot, boundary: datetime, tf: Timeframe
    ) -> bool:
        """S2/B1: the bar that closed at ``boundary`` is present and complete.

        Confirmed from the *raw* snapshot: ``is_complete is True`` counts, and
        ``None`` (or False) counts as not confirmed — |market_snapshot_to_context|
        maps ``None`` to True, so S2 must not rely on that mapping.

        B1 correction: confirmation is a timestamp **range** check, not exact
        equality — a candle that starts anywhere inside the bar interval
        (``[bar_start(boundary - 1 s), boundary)``) is accepted, so a broker
        stamping day/week/month bars at a non-epoch-aligned start (e.g. a day
        candle at 03:00 UTC) is still confirmed.
        """
        range_start = self._bar_start(boundary - timedelta(seconds=1), tf)
        for candle in snapshot.candles:
            if (
                candle.is_complete is True
                and range_start <= candle.timestamp < boundary
            ):
                return True
        return False

    def _latest_closed_bar_before(
        self, snapshot: MarketSnapshot, boundary: datetime
    ) -> bool:
        """B4: a complete candle that started before ``boundary`` exists.

        The S6 deferred tick runs on the **latest closed bar**: any complete
        candle started before the deferred boundary confirms it. The deferred
        bar's own range is deliberately not required — a bar without trades
        has no candle, and waiting for one would stall the bot silently.
        """
        for candle in snapshot.candles:
            if candle.is_complete is True and candle.timestamp < boundary:
                return True
        return False

    def _conclude_boundary(self, ticker: _BotTicker, boundary: datetime) -> None:
        ticker.pending_boundary = None
        ticker.deferred = False
        ticker.last_attempt_index = -1
        ticker.last_done_boundary = boundary
        # B6 (review round 4): deferred-mode bookkeeping is per-deferral.
        ticker.deferred_status_check_at = None
        ticker.deferred_failed_bar = None
        ticker.deferred_first_tradable = None

    def _reset_ticker_state(self, ticker: _BotTicker) -> None:
        """B3 (review round 1): reset the per-bot scheduler state on restart.

        A bot that left RUNNING (ERROR/STOP/...) must not carry its failure
        counter, its pending/deferred boundary or its PER_MINUTE claim into
        its next START. ``last_done_boundary`` is intentionally kept: a
        concluded bar is never ticked twice.
        """
        ticker.failures = 0
        ticker.pending_boundary = None
        ticker.deferred = False
        ticker.last_attempt_index = -1
        ticker.last_minute = None
        ticker.last_skip_reason = None
        # B6 (review round 4): deferred-mode bookkeeping is per-deferral.
        ticker.deferred_status_check_at = None
        ticker.deferred_failed_bar = None
        ticker.deferred_first_tradable = None

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
        try:
            snapshot = await self._snapshot_provider(ticker.figi, config)
        except Exception as exc:  # noqa: BLE001 - classified by S4 policy
            if isinstance(exc, NoTradesInWindow) and self._proven_no_trade_window(exc):
                # MVP-6.14 (N3): a window proven quiet is a skip, not a failure
                # — the forming bar without any candle is not a failure.
                self._record_skip(ticker, self._empty_window_skip_reason(exc))
                return
            raise  # not proven -> counted as before (S4 classification)
        if await self._run_cycle(ticker, snapshot):
            ticker.failures = 0

    # --- shared building blocks -------------------------------------------------

    async def _status_verdict(
        self, ticker: _BotTicker, *, count_on_fail: bool = True
    ) -> _StatusVerdict:
        """S3: ask the broker whether the instrument is tradable right now.

        The verdict itself is side-effect free; the transient count is
        controlled by ``count_on_fail`` (B6.3): while deferred, a failed or
        rate-limited status counts at most once per bar boundary.
        """
        try:
            status = await self._broker.get_trading_status(ticker.figi)
        except Exception as exc:  # noqa: BLE001 - S3: request failure = transient
            if count_on_fail:
                await self._count_transient(
                    ticker, f"trading status request failed: {exc}"
                )
            return _StatusVerdict.FAILED
        if status is TradingStatus.TRADING_AVAILABLE:
            return _StatusVerdict.AVAILABLE
        if status is TradingStatus.TRADING_UNAVAILABLE:
            return _StatusVerdict.UNAVAILABLE
        if count_on_fail:
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
        """S4: transient failures are counted; everything else is immediate ERROR.

        ``DealError`` is exempt: the Deal layer already surfaced every deal
        failure to the bot lifecycle (MVP-6.12 B2 ``_fail_deal`` /
        ``assert_deal_for_open_position``) *before* re-raising, so the scheduler
        must not double-handle it or overwrite the deal reason (S4, review
        round-1 observation 1).
        """
        if isinstance(exc, DealError):
            return
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

        Assumption (not confirmed by the official T-Invest docs — see the
        REPORT / §31 limitations): minute .. day intervals are fixed-length
        from the epoch, WEEK_1 bars start Monday 00:00 UTC and MONTH_1 bars
        on the 1st 00:00 UTC. The B1 range-confirmation rule does not depend
        on exact equality, so a non-epoch-aligned broker stamp still confirms.
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
