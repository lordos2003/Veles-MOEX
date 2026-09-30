# Veles-MOEX — REPORT: MVP-6.13 Live Cycle Scheduler

## Implementation commits

1. `0c12cf18718ef8be7e72e93db41603ee54968684` — "feat: implement MVP-6.13 live
   cycle scheduler (S1-S5)" (implementation on `agent/review/mvp-6.13`,
   **pushed, in sync with origin** — verified with
   `git ls-remote origin agent/review/mvp-6.13 agent/control`).

- Base before MVP-6.13: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`
  (contains the accepted MVP-6.12, merge `566d792`); branch base confirmed by
  `git merge-base agent/review/mvp-6.13 origin/master = eb08fbf`.
- Diff vs base: 15 files changed, 1693 insertions (+), 18 deletions (-) —
  13 modified files, 2 new files (`backend/app/trading/scheduler.py`,
  `backend/tests/test_mvp613_scheduler.py`).
- No changes to `master`; publication requires independent acceptance first.
- Issue #9 stays open until acceptance and publication.

## Objective

After MVP-6.12 a bot can conduct a whole deal, but nothing runs its strategy
cycle: `BotRuntime.execute_strategy()` was only called explicitly, so a
RUNNING bot could never enter a deal by itself. MVP-6.13 adds the broker-
neutral scheduler that runs each RUNNING bot's strategy cycle at the moments
defined by the Veles calculation method of that bot (AT_BAR_CLOSE / PER_MINUTE).

## What was implemented

### S1. Scheduler and ownership — `backend/app/trading/scheduler.py`

- New `LiveCycleScheduler` (broker-neutral; imports only
  `app.brokers.base` types — same composition boundary as `recovery.py` /
  `order_manager.py`; no `app.brokers.tinvest*` import in `app/trading`).
- One strategy cycle per tick per RUNNING bot via the existing
  `BotRuntime.execute_strategy()` — no new strategy path.
- Started by the application lifespan **only after a SAFE startup recovery**
  (`backend/app/main.py`): `service.run_scheduler_forever()` raises
  `LiveExecutionBlocked` unless the live service is SAFE, and the task is
  created next to the stream task inside the `result.safe` branch. No ticks
  while the service is not SAFE.
- Stopped on shutdown: `main.py` cancels the scheduler task first (shared DB
  session), and `run_forever()` shuts down per-bot tasks in a `finally`
  (regression-tested: cancellation stops per-bot pass tasks).
- At most one cycle per bot: an in-flight guard set is claimed synchronously
  in `advance()` before the per-bot pass task is created; overlapping ticks
  are skipped (no catch-up, no parallelism for one bot).
- Only RUNNING bots are ticked; STOP_REQUESTED / STOPPED / ERROR /
  EMERGENCY_STOP bots are not ticked from the next tick on.
- Injectable `Clock` protocol (`SystemClock` default); no real sleeps in
  tests. `SchedulerSettings` carries the timing parameters.

### S2. Tick timing by calculation method

- `AT_BAR_CLOSE`: one tick per bar at the UTC candle boundary **+ 5 s**. The
  just-closed bar must be present in the raw `MarketSnapshot` candles with
  `is_complete is True` (`None` counts as **not confirmed**). Retry every 5 s,
  no later than 60 s after the boundary; after that the tick is skipped and
  counts as a transient failure (S4).
- `PER_MINUTE`: one tick at every UTC minute boundary; forming bar used
  as-is (`FilterEvaluator` already handles PER_MINUTE).
- Settings: `scheduler_bar_close_delay_seconds = 5.0`,
  `scheduler_bar_close_retry_seconds = 5.0`,
  `scheduler_bar_close_max_wait_seconds = 60.0`,
  `scheduler_max_consecutive_failures = 3`
  (`backend/app/core/config.py`).

### S3. Trading-session gate — broker-neutral `BrokerAdapter.get_trading_status()`

- `BrokerAdapter.get_trading_status(figi)` added to
  `backend/app/brokers/base.py` (abstract).
- `TInvestAdapter.get_trading_status(figi)` calls the official T-Invest
  `MarketDataService/GetTradingStatus` through the existing HTTP client; the
  `SecurityTradingStatus` mapping is **inside the adapter**:
  `SECURITY_TRADING_STATUS_NORMAL_TRADING` with `api_trade_available_flag is
  True` → `TRADING_AVAILABLE`; every other documented exchange state (opening/
  closing periods, breaks, auctions, dealer-only states, session close/open,
  not available) → `TRADING_UNAVAILABLE` (tick skipped, not counted);
  `UNSPECIFIED` or an unrecognized value raises `BrokerApiError` (counted as
  transient — an unknown state is never silently treated as "not tradable").
- `BacktestBroker.get_trading_status()` returns `TRADING_AVAILABLE`
  (backtest keeps its no-session-restriction behavior).
- No hard-coded MOEX session schedule anywhere.

### S4. Failure policy — transient vs non-transient

- `BrokerTransportError` marker added to `app/brokers/base.py` and exported
  from `app/brokers`; `BrokerConnectionError` (503), `RateLimitError` (429),
  `BrokerApiError` (502) and `MarketDataError` are transport errors
  (`backend/app/brokers/tinvest_errors.py`, multiple inheritance keeps
  `isinstance(..., TInvestError)` true).
- Transient (skip + count, 3 consecutive → bot ERROR through
  `BotRuntime.fail()` + `BotRepository` persistence): `MarketDataUnavailable`,
  broker transport errors, closed-bar not confirmed within max wait, unknown
  trading status / failed `get_trading_status` request.
- Non-transient (ERROR immediately): `TimeframeNotConfigured`,
  `LookbackNotConfigured`, `SizingNotConfigured`, `SizingError` family,
  `DealConfigUnsupported`, `RiskRejected`, `BotStateError`, unexpected
  exceptions. Deal errors are not double-handled (already surfaced by
  MVP-6.12 B2).
- A successful cycle resets the counter; the counter is per bot, in memory.
- **Reason field choice**: a new generic read-only `last_error` on
  `GET /api/bots/{id}` (`BotResponse.last_error`, `backend/app/api/bots.py` +
  `backend/app/bots/schemas.py`) — `deal_error` stays deal-specific.

### S5. Correctness guards

- The scheduler decides only **when** a cycle runs; entry / grid / TP / Deal /
  Risk / position semantics are untouched (MVP-6.11/6.12 gates stay
  authoritative). Diff review confirms no semantic changes outside the
  scheduler wiring and the new observability field.

### Wiring & observability

- `backend/app/trading/live_execution.py`: `BotRuntime` import,
  `scheduler` kwarg/property, `run_scheduler_forever()` raising
  `LiveExecutionBlocked`, `_persist_bot_error` (renamed from
  `_deal_bot_error`, shared by DealManager and the scheduler), scheduler
  construction in `build_live_service` with `safety_gate=service.can_execute`
  and `on_bot_error=_persist_bot_error`.
- `backend/app/api/deps.py`: `get_live_scheduler` dependency (read-only; no
  fallback scheduling; field absent when the live service is not running).
- `backend/app/trading/__init__.py`: exports `Clock`, `LiveCycleScheduler`,
  `SchedulerSettings`, `SystemClock`.

## Tests

`backend/tests/test_mvp613_scheduler.py` — 22 tests, fake clock (no real
sleeps), covering all 13 task cases:

1. `AT_BAR_CLOSE` M5: ticks at `boundary + 5 s` only (no tick inside the bar);
2. closed-bar retry every 5 s, one cycle when confirmed at +15 s, skip +
   count when never confirmed by +60 s;
3. `is_complete is None` is not confirmation;
4. `PER_MINUTE`: one tick per minute boundary;
5. not-tradable → skip without counting; unknown / failing status → counted;
6. 3 consecutive transient failures → bot ERROR (runtime callback +
   persistence + `last_error` observable); 2 failures + success → counter
   reset, bot still RUNNING;
7. non-transient (`LookbackNotConfigured`) → ERROR on first occurrence;
8. overlap: running cycle skips the next tick, no parallel cycles;
9. bot isolation: slow/failing bot does not delay or fail another bot;
10. only RUNNING bots ticked; STOP/ERROR state → no further ticks;
11. scheduler not startable when the startup recovery is not SAFE
    (`LiveExecutionBlocked`); safety gate closed → no ticks, resumes on open;
12. `TInvestAdapter.get_trading_status` mapping (normal + api flag → tradable;
    flag false / closing / break / not-available / opening / session_close /
    numeric 5/4 → not tradable; UNSPECIFIED / unrecognized → `BrokerApiError`;
    `MarketDataError` propagates);
13. `run_forever` cancellation stops per-bot tasks (regression), backtest
    broker returns `TRADING_AVAILABLE`.

## Commands / results

- `pytest` (backend, full suite): **472 passed, 1 skipped** (the single skip
  is the opt-in live sandbox integration test).
- `pytest tests/test_mvp613_scheduler.py -q`: **22 passed**.
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes).

## Known limitations (documented, not changed in 6.13)

- **Task-known gap**: `market_context.market_snapshot_to_context()` maps
  `candle.is_complete is None` to `True`; S2 confirms the closed bar from the
  raw `MarketSnapshot` and does not rely on that mapping. Changing the
  mapping is a separate decision and stays out of 6.13.
- WEEK_1 / MONTH_1 timeframes: boundary alignment uses the UTC calendar
  boundary of the T-Invest candle interval (no separate week/month-start
  rule is invented).
- Fresh start: the first bar of an already-started window that is already
  past the confirm window by the time the scheduler starts counts one
  transient failure for that bar (documented; not a semantic change).
- The consecutive-failure counter is in memory and resets on restart
  (per contract).

## Documentation & specification gaps

- No gaps beyond the known limitation above: S1–S5 as approved were
  implemented without inventing Veles semantics; the only new timing values
  are the owner-approved ops defaults (5/5/60/3).
- Out of scope (unchanged): multi-timeframe filter series, Veles "trading by
  schedule" filter, Backtest changes, new exit modes.

## Constraints honoured

- Broker neutrality: `app/trading` imports only `app.brokers.base`; T-Invest
  types stay inside the adapter. T-Invest remains read-only boundary
  (PostOrder only behind the accepted MVP-6.2 Risk/Order path).
- No hard-coded MOEX schedule; no invented financial defaults.
- `Decimal` / UTC semantics, strategy / Deal / Risk semantics unchanged;
  MVP-6.11/6.12 gates remain authoritative.
- Implementation pushed, REPORT on `agent/control` pushed, plain push only,
  `agent/control` fast-forwarded to origin before the REPORT commit; no
  `master` changes; no self-declared acceptance.

## Review request

Ready for independent review on `agent/review/mvp-6.13`
(`0c12cf18718ef8be7e72e93db41603ee54968684` against base
`eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`). No merge into `master` has
been performed; publication requires acceptance first. Issue #9 stays open.
