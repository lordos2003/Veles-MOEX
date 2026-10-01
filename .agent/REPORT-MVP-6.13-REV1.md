# Veles-MOEX — REPORT: MVP-6.13 REV1 (round-1 correction)

## Correction commits

1. `a945b103c7bff7b5be472749fe60ca07ce8d5f6d` — "review: implement MVP-6.13
   round-1 correction (B1 + S6, B2, B3)" (correction on
   `agent/review/mvp-6.13`, **pushed, in sync with origin** — verified with
   `git ls-remote origin agent/review/mvp-6.13 agent/control`).

- Round-1 implementation reviewed: `0c12cf18718ef8be7e72e93db41603ee54968684`.
  Round-1 review: `.agent/REVIEW-MVP-6.13.md` (REJECTED: B1 → new owner
  contract S6, B2, B3; one non-blocking observation on DealError
  double-handling).
- Base before MVP-6.13: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`
  (contains the accepted MVP-6.12, merge `566d792`); branch base confirmed by
  `git merge-base agent/review/mvp-6.13 origin/master = eb08fbf`.
- Correction diff vs round-1 HEAD: 7 files changed, 752 insertions (+),
  119 deletions (-) — `backend/app/trading/scheduler.py`,
  `backend/app/bots/repository.py`, `backend/app/persistence/deal_store.py`,
  `backend/app/persistence/execution_state.py`,
  `backend/app/trading/live_execution.py`, `backend/tests/test_mvp613_scheduler.py`,
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`.
- No changes to `master`; publication requires independent acceptance first.
- Issue #9 stays open until acceptance and publication.

## What changed (B1 + S6, B2, B3; observation 1 implemented)

### B1 + S6. Deferred `AT_BAR_CLOSE` tick + range confirmation (owner contract, 2026-09-30)

`backend/app/trading/scheduler.py`:

- **S6 deferral (S3 replacement for `AT_BAR_CLOSE`)**. When an `AT_BAR_CLOSE`
  tick falls while the instrument is not tradable (`get_trading_status` says
  not tradable), the tick is **deferred** — not dropped and not counted. The
  `_BotTicker` gains `deferred: bool` + `pending_boundary`. The deferred
  boundary is **fixed** (recomputed boundaries are not used while deferred,
  because a closed session passes no newer closed bar). Every scheduler pass
  re-checks the status at the normal cadence: still not tradable → stays
  deferred; FAILED / unknown status → the tick counts as a transient failure
  (S3 preserved, S4 policy unchanged); tradable again → one snapshot fetch,
  one cycle on the closed bar of the deferred boundary, then the deferral is
  cleared. Only the **latest** pending boundary is kept: a newer boundary that
  becomes due while an old one is pending supersedes the old one **silently**
  (no failure count, no catch-up). `_conclude_boundary` clears the deferral on
  every conclusion.
- **B1 range confirmation.** `_closed_bar_confirmed` accepts a candle with
  `is_complete is True` whose start lies in
  `[bar_start(boundary − 1 s), boundary)`, instead of exact equality with the
  epoch-aligned boundary — so a broker that stamps day/week/month bars at a
  non-epoch-aligned start still confirms. Boundary recomputation itself is
  unchanged (epoch intervals for MIN_1..DAY_1, calendar for WEEK_1/MONTH_1;
  see limitations).
- **S2/S6 interaction.** `bar_close_max_wait_seconds` applies only to the
  non-deferred confirmation path. A deferred tick that becomes tradable is
  exempt: it was deferred, not lost; if the bar is not yet confirmed it
  retries on the next pass (no `max_wait` failure while deferred). The S2
  “expired window → skip + count” stays for non-deferred ticks.
- `backend/tests/test_mvp613_scheduler.py`: `test_s6_day1_boundary_outside_session_defers_to_next_tradable`
  (Friday `DAY_1` close at Sat 00:00 UTC outside the session → deferred →
  one cycle Monday on the Friday bar), `test_s6_several_closed_session_boundaries_produce_one_deferred_cycle`
  (M5: three closed-session boundaries → one deferred cycle),
  `test_b1_closed_bar_confirmed_by_range_not_exact_equality` (day candle
  stamped 03:00 UTC confirms).

### B2. Shared live-session serialization

One long-lived `AsyncSession` was used concurrently by per-bot pass tasks
(PostgreSQL + asyncpg reproduced `IllegalStateChangeError` / `InterfaceError`).
Chosen approach: **serialize every use of the long-lived session behind one
`asyncio.Lock`** (short-lived sessions per operation would change the
composed graph and the MVP-6.11 B2 fresh-read guarantee):

- `backend/app/bots/repository.py` — `BotRepository(..., lock: asyncio.Lock | None = None)`;
  every public method (`get`, `list`, `update_state`, `update_deposit`,
  `get_deposit`) runs inside an `asynccontextmanager` `_session_guard()` that
  holds the lock for the whole operation, **including** `commit`/`refresh`.
  The `populate_existing=True` fresh-read guarantee (MVP-6.11 B2) is
  preserved. `None` default keeps per-request sessions / existing tests
  unchanged.
- `backend/app/persistence/deal_store.py` —
  `SqlAlchemyDealStore(..., lock=None)`; `save` / `get` / `list_unclosed` are
  wrapped (`_save_locked` / `_get_locked` / `_list_unclosed_locked`), so the
  upsert + flush sequence runs atomically under the lock.
- `backend/app/persistence/execution_state.py` —
  `SqlAlchemyLiveStateStore(..., lock=None)`; `save_snapshot` / `load_snapshot`
  are wrapped.
- `backend/app/trading/live_execution.py` — one `session_lock = asyncio.Lock()`
  is created in `build_live_service()` and passed to all three components
  above, and the **same** lock covers direct `session.get(...)` reads in
  `_make_market_context` / `_make_bot_engine` / `_scheduler_figi` (via a local
  `_session_get` helper) and `load_bot_strategy_by_id` in `_load_strategy`.
  The stream path uses the same session; the MVP-6.11 B2 guarantee is intact —
  all bot-pass DB work is serialized against each other and against the stream
  reads.
- `backend/tests/test_mvp613_scheduler.py`: `test_b2_shared_session_without_lock_overlaps_under_concurrent_passes`
  (regression: `BotRepository(session)` without a lock + 3 bots at the same
  boundary against an `_OverlapDetectingSession` → overlapping operations
  detected, `max_active >= 2` — fails on `0c12cf1`, passes after the fix) and
  `test_b2_shared_session_with_lock_stays_serialised_under_concurrent_passes`
  (same scenario with `lock=asyncio.Lock()` → all 3 bots still execute,
  `max_active == 1`).
- Documented in `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §31 (new
  subsection «B2. Shared live-session serialization (round-1 correction)»).

### B3. Per-bot scheduler state reset on a bot state change

`backend/app/trading/scheduler.py`:

- `_BotTicker` gains `last_seen_state: BotState | None`. `_process_ticker`
  records it at ticker creation; `advance()` compares it with the current
  runtime state **before** the in-flight / running guards and calls the new
  `_reset_ticker_state(ticker)` on any observed change — so the reset happens
  regardless of which pass observes the ERROR→START transition (airtight even
  if the state changes while no tick is due).
- `_reset_ticker_state` resets `failures`, `pending_boundary`, `deferred`,
  `last_attempt_index` and `last_minute`, and **keeps `last_done_boundary`**
  (the deal/cycle boundary already run must not re-run after a restart, so a
  bar close is not evaluated twice on the same closed bar).
- `backend/tests/test_mvp613_scheduler.py`: `test_b3_failures_reset_after_error_and_restart`
  (3 transient failures → ERROR → the observer sees ERROR → restart to RUNNING →
  a new transient failure does not re-ERROR the bot; counter starts from 0).

### Observation 1 (non-blocking) — DealError is not double-handled

The Deal layer already surfaces every deal failure before re-raising
(`DealManager._fail_deal` → `on_bot_error` for `open_deal`; the same notify +
raise in `assert_deal_for_open_position`). `_handle_exception` now returns
immediately on `DealError` — no transient count, no second `_fail_bot`, no
`last_error` overwrite of the deal reason (this also implements S4's own
“do not double-handle them” line). Test:
`test_s4_deal_error_is_not_double_handled`.

## T-Invest candle start times (B1 review requirement)

Verified from the **official T-Invest API documentation** (repository
`RussianInvestments/investAPI`, branch `main`; the API docs site
`tinkoff.github.io/investAPI` renders the same sources):

- `marketdata.proto`, stream `Candle.time`: «Время начала интервала свечи по
  UTC.» — the candle time is the **start of the interval**, UTC. Verified
  verbatim.
- `marketdata.proto`, `HistoricCandle.time` (GetCandles): «Время свечи в
  часовом поясе UTC.» — UTC candle time.
- `faq_marketdata.md` (FAQ): «При запросе дневных свечей
  `CANDLE_INTERVAL_DAY` время, которое передаётся в полях `from` и `to`,
  игнорируется. … при запросе дневной свечи по интервалу с 12:00 01.01.2021
  по 07:00 02.01.2021 вернутся две дневные свечи за 01.01.2021 и за
  02.01.2021.» — `DAY_1` candles are **whole calendar days** (start 00:00
  UTC), their `time` is the interval start. Verified verbatim.
- `CandleInterval` enum comments state only validity ranges and limits
  («От 2 часов до 3 месяцев», «От 4 часов до 3 месяцев», «От 1 недели до 5
  лет», «От 1 месяца до 10 лет» …) — they do **not** define start times.

**Explicitly not verified (cannot be fully verified from the official
documentation):** the exact start-stamp rule for `HOUR_4` / `WEEK_1` /
`MONTH_1` candles. The documentation does not state that 2h/4h candles are
counted from 00:00 UTC (an earlier draft claim of a proto comment to that
effect was disproved and removed), and it does not state that week candles
start Monday 00:00 UTC or month candles on the 1st 00:00 UTC. The project
therefore treats the epoch/calendar alignment of `_bar_start` as an
**assumption**, and relies on the B1 range-confirmation rule — the scheduler
never requires exact equality, so a broker-side non-epoch-aligned stamp still
confirms a bar. This is recorded in §31 limitations and in the
`scheduler._bar_start` docstring.

## Tests / validation

- `pytest` (backend, full suite): **479 passed, 1 skipped** (was 472 + 1 in
  round 1; the single skip is the opt-in live sandbox integration test).
- `pytest tests/test_mvp613_scheduler.py -q`: **29 passed** (was 22 in round 1;
  +7 round-1 tests: S6 ×2, B1, B2 ×2, B3, DealError exemption).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes;
  built in 3.41 s).

## Known limitations (documented, not changed)

- **Carried from round 1**: `market_snapshot_to_context()` maps
  `is_complete is None → True`; S2 confirms the closed bar from the raw
  `MarketSnapshot` and does not rely on that mapping (separate decision).
- **Epoch/calendar start assumption** (see above): MIN_1..DAY_1 boundaries
  are fixed UTC intervals from the epoch, WEEK_1 Monday 00:00 UTC, MONTH_1 the
  1st 00:00 UTC — an assumption not confirmed by T-Invest docs; the B1 range
  rule keeps confirmation robust regardless.
- S6 scope: deferral applies to `AT_BAR_CLOSE` only; `PER_MINUTE` keeps the S3
  skip-without-count on a not-tradable minute.
- Deferred state is per-bot in memory and resets with B3 (a restart after
  ERROR clears the deferral; `last_done_boundary` is kept). A deferred
  boundary does not leak across a process restart (same in-memory policy as
  the S4 counter, per contract).
- Non-deferred expired windows still skip + count one transient (unchanged);
  the scheduler cannot know whether that tick ran before a restart.

## Documentation & specification gaps

- S6 is the owner-approved contract from the round-1 review (recorded in
  `.agent/TASK-MVP-6.13-LIVE-CYCLE-SCHEDULER.md` “Correction round 1” +
  `docs/architecture/TASK-09` §31 «### S6. AT_BAR_CLOSE deferral»).
- The only unverified spec point is the T-Invest candle start-stamp rule for
  HOUR_4/WEEK_1/MONTH_1 (above) — explicitly stated, not silently assumed.
- Out of scope (unchanged): multi-timeframe filter series, Veles "trading by
  schedule" filter, Backtest changes, new exit modes.

## Constraints honoured

- Broker neutrality: `app/trading` imports only `app.brokers.base` /
  `app.trading.deal`; T-Invest types stay inside the adapter.
- No hard-coded MOEX schedule; no invented financial defaults; no new Veles
  semantics (S6 is an owner-approved contract).
- `Decimal` / UTC semantics, strategy / Deal / Risk semantics unchanged;
  MVP-6.11/6.12 gates remain authoritative; the B2 fix preserves the MVP-6.11
  B2 fresh-deposit-read guarantee.
- Correction pushed to `agent/review/mvp-6.13`, REPORT committed and pushed to
  `agent/control` (plain push only; `agent/control` fast-forwarded to the
  reviewer's `174680d` before the REPORT commit); no `master` changes; no
  self-declared acceptance.

## Review request

Ready for the round-2 decision on `agent/review/mvp-6.13`
(`a945b103c7bff7b5be472749fe60ca07ce8d5f6d` against round-1 base
`0c12cf18718ef8be7e72e93db41603ee54968684`, ultimately against `master @
eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`). No merge into `master` has been
performed; publication requires acceptance first. Issue #9 stays open.
