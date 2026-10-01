# Veles-MOEX — Independent Review: MVP-6.13

## Verdict (round 1)

**REJECTED — three corrections required (B1–B3); B1 includes an owner-approved contract change (S6)**

Reviewed implementation: `0c12cf18718ef8be7e72e93db41603ee54968684` (`agent/review/mvp-6.13`, pushed, in sync with origin)
Base: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e` (merge-base verified)
Report: `.agent/REPORT-MVP-6.13.md` (`agent/control @ b28269d`)
Reviewer: Claude (independent review), 2026-09-30

## Independent re-run (clean environment, Python 3.12)

| Check | Result |
|---|---|
| `pytest` (full) | **472 passed, 1 skipped** — matches the REPORT |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` (no migration, as expected) |
| push rule | review branch and REPORT pushed; the REPORT cites the pushed SHA ✓ |

## Blocking findings

### B1. Bars that close outside the trading session never produce a cycle (a gap in the reviewer's S3 contract)

S3 (as written by the reviewer) says "not tradable → the tick is skipped, not counted". The implementation follows it literally. For `AT_BAR_CLOSE` the only tick of a bar is at its UTC close. For `HOUR_4`, `DAY_1`, `WEEK_1` and `MONTH_1` the close usually falls when MOEX is closed. `DAY_1` closes at 00:00 UTC = 03:00 MSK every day. The tick is skipped, not counted, and never retried. **Such a bot silently never trades.** This is a defect of the reviewer's contract, not of the implementation's fidelity to it.

The bar identity is also fragile. `_closed_bar_confirmed()` requires a candle whose timestamp **equals** the UTC-epoch-aligned bar start. T-Invest's start times for day, 4-hour, week and month candles are not verified anywhere in the project. If they differ from the epoch alignment (e.g. a day candle stamped at the session start), the bar is never confirmed.

**Owner decision (2026-09-30) → new contract S6 (see the task):** an `AT_BAR_CLOSE` tick that falls while the instrument is not tradable is **deferred**, not dropped.

**Required correction**

1. Implement S6: the pending tick runs **once**, as soon as the instrument becomes tradable, on the latest closed bar. Only the latest pending boundary is kept (no catch-up of several missed bars). Deferral is not a failure and is not counted.
2. Closed-bar confirmation by **range**, not exact equality: a candle with `is_complete is True` whose start lies in `[bar_start(boundary − 1 s), boundary)`.
3. Record in the REPORT the actual T-Invest candle start times for `HOUR_4` / `DAY_1` / `WEEK_1` / `MONTH_1` (from the sandbox or the official docs, with the source). If they cannot be verified, say so explicitly.
4. Tests: a `DAY_1` bot whose boundary falls in a closed session → one cycle at the next tradable moment on the closed bar; several closed-session boundaries in a row → one deferred cycle, not several; a day candle stamped at a non-midnight start → still confirmed.

### B2. Concurrent per-bot passes share one long-lived `AsyncSession`

`build_live_service()` creates **one** `SessionLocal()`, used by the `BotRepository` (deposit reads, `update_state` on ERROR), the `SqlAlchemyDealStore`, the instrument lookups and the stream path. MVP-6.13 now runs every bot's pass in its **own concurrent task**. All M5 bots tick at the same second, so they use that single session concurrently. SQLAlchemy documents `AsyncSession` as not safe for concurrent tasks.

Reproduced on **PostgreSQL 16 + asyncpg** (the production driver) with the project's `BotRepository` and the app's session config (`expire_on_commit=False`). Three bots concurrently read the deposit and persist ERROR (`get_deposit` + `update_state`), 20 rounds:

```
ResourceClosedError, IllegalStateChangeError, InterfaceError (x many)
first error: "This transaction is closed"
```

In the scheduler these surface as **unexpected exceptions → immediate bot ERROR**, and state persistence becomes unreliable. The defect did not exist before 6.13, because nothing ran bot work concurrently on the live session. SQLite/aiosqlite hides it, which is why the suite is green.

**Required correction**

1. Make DB access of the live runtime safe under concurrent bot passes. Either give the repositories and stores used from bot passes short-lived sessions from `SessionLocal` per operation, or serialise every use of the long-lived session behind one `asyncio.Lock` (the stream path included). Pick one, apply it consistently, and document it in §31.
2. The MVP-6.11 B2 guarantee must still hold: the deposit read sees the latest committed value.
3. A regression test that runs several bots' passes at the same boundary against a session that **detects concurrent use** (a wrapper that fails on overlapping operations), or against a real PostgreSQL if available in CI. It must fail on `0c12cf1` and pass after the fix.

### B3. The consecutive-failure counter survives an ERROR and a restart of the bot

`_BotTicker` is kept per `bot_id` for the process lifetime (`BotRuntimeManager` reuses the runtime object). `failures` is reset only by a successful cycle. After a bot goes to ERROR with 3 transient failures and the owner restarts it, the **first** transient failure puts it into ERROR again. The same happens after a non-transient ERROR and a restart.

**Required correction:** reset the per-bot scheduler state (failure counter, pending or deferred boundary) whenever the bot leaves RUNNING, or on its next START. Add a test: 3 failures → ERROR → START → 1 failure → still RUNNING.

## Accepted in round 1 (no change requested)

- **S1**: independent per-bot tasks, a synchronous in-flight guard, only RUNNING bots, the `safety_gate` = service SAFE, started in the lifespan only after a SAFE recovery and cancelled first on shutdown.
- **S2** (apart from B1): boundary + 5 s, retry 5 s, max 60 s, `None` → not confirmed, `PER_MINUTE` once per minute. Settings are in `config.py`.
- **S3** (apart from B1): `BrokerAdapter.get_trading_status()` with `GetTradingStatus` mapping inside the adapter; `UNSPECIFIED`/unknown → error → counted; no hard-coded schedule.
- **S4** (apart from B3): the transient vs non-transient classification via the `BrokerTransportError` marker; ERROR through `BotRuntime.fail()` + persistence; generic `last_error` in the API.
- **S5**: no trading semantics changed; injectable `Clock`, no real sleeps in tests.

## Observations (non-blocking)

1. Deal errors raised from `execute_strategy` (`open_deal` re-raises after its own B2 handling) are handled a second time as "unexpected" by the scheduler. This is harmless (the bot is already ERROR), but `last_error` overwrites the deal reason. Consider skipping `DealError` in `_handle_exception`.
2. The scheduler fetches a snapshot for confirmation and passes it to the cycle. Good: one snapshot per tick, no double fetch.

## Acceptance conditions (round 2)

1. S6 + B1, B2, B3 corrected with the listed tests.
2. Full `pytest`, `ruff`, `alembic heads`, `npm run build`.
3. Commit pushed to `agent/review/mvp-6.13`; `.agent/REPORT-MVP-6.13-REV1.md` committed and pushed to `agent/control`, citing the pushed SHA.
4. `master` unchanged.

**No publication to master.**

---

## Round 2 — Verdict

**REJECTED — one correction required (B4).** B1 (range confirmation), B2, B3 and observation 1 are closed.

Reviewed: `a945b10` (`agent/review/mvp-6.13`, pushed, in sync with origin), base `master @ eb08fbf`.
Report: `.agent/REPORT-MVP-6.13-REV1.md` (`agent/control @ 026b276`). Reviewer: Claude, 2026-10-01.

### Independent re-run (clean environment, Python 3.12)

| Check | Result |
|---|---|
| `pytest` (full) | **479 passed, 1 skipped** — matches REV1 |
| `ruff check app tests scripts` | All checks passed |
| `alembic heads` | single head `0005_deal_continuation` |

### Closed

- **B2 — CLOSED.** One `asyncio.Lock` covers every use of the long-lived live session: `BotRepository` (whole operation, commit and refresh included), `SqlAlchemyDealStore`, `SqlAlchemyLiveStateStore`, the direct `session.get` reads and `load_bot_strategy_by_id`. No locked region calls another locked operation (no deadlock path found). The round-1 probe was re-run on **PostgreSQL 16 + asyncpg**: three bots × 20 rounds of `get_deposit` + `update_state`. Without the lock → `ResourceClosedError` / `IllegalStateChangeError` / `InterfaceError`; with the round-2 lock → **60/60 succeed, no errors**. The MVP-6.11 B2 fresh read (`populate_existing`) is kept. The overlap-detecting session test fails without the lock and passes with it.
- **B3 — CLOSED.** The per-bot state (failures, pending/deferred boundary, minute claim) is reset on any observed bot state change; `last_done_boundary` is kept so a bar is not evaluated twice. Tested ERROR → START → one failure → still RUNNING.
- **B1 range confirmation — CLOSED.** The confirmation range is `[bar_start(boundary − 1 s), boundary)`. The REPORT documents the T-Invest candle times with sources: interval start, UTC, `DAY_1` = calendar day. `HOUR_4` / `WEEK_1` / `MONTH_1` are explicitly marked as unverified.
- **Observation 1 — closed.** `DealError` is no longer double-handled.

### Blocking finding

#### B4. A deferred tick can stall the bot forever, silently

`_process_deferred()` fixes the deferral to the first boundary that fell in the closed session. It runs the cycle only when a complete candle exists **in that boundary's own range**; otherwise it returns and retries on the next pass, with no limit and no failure count. While `ticker.deferred` is set, `_process_at_bar_close()` short-circuits into `_process_deferred()`, so normal boundary processing never resumes.

On MOEX/T-Invest a bar without trades has **no candle** (there are no empty candles). If the last bar before the session close (or before a clearing break) had no trades, which is common for less liquid instruments on M1/M5, the deferred range never gets a candle. **The bot stops trading permanently, with no error.**

Reproduced on `a945b10` with the MVP-6.13 harness. M5 bot, last candle `[T0−10m, T0−5m)`, session closed at `T0` → deferred. Then the status is `TRADING_AVAILABLE` at +14 h, +15 h, +16 h, +20 h and +48 h:

```
executions=0  fail_reasons=[]  snapshot_requests=5
```

S6 requires the deferred tick to run "once at the first tradable moment **on the latest closed bar**", not on a candle that must sit inside the deferred boundary's range.

**Required correction**

1. In the deferred path, once the instrument is tradable, confirm **the latest closed bar**: the snapshot contains at least one candle with `is_complete is True` and `start < deferred boundary`. Then run the cycle once and conclude.
2. Bound the deferral: if the instrument is tradable and a **newer** bar boundary has passed while the deferred tick is still unconfirmed, conclude the deferral (count one transient failure) and resume normal boundary processing. The bot must never be stuck in `deferred` while trading is open.
3. Tests: the reproduction above (no candle in the deferred range → the cycle runs on the latest closed bar); the bound in item 2; the existing S6 tests still green.
4. REPORT → `.agent/REPORT-MVP-6.13-REV2.md`, pushed, citing the pushed SHA.

### Observation for the owner (non-blocking, contract S2)

The same "no candle for a bar without trades" fact affects the **non-deferred** S2 path. For a bar with no trades the confirmation times out after 60 s and counts a transient failure, so **three consecutive no-trade bars → bot ERROR**. This is fine for liquid instruments, but an M1/M5 bot on a thin instrument would be put into ERROR during quiet periods. This follows the S2 contract as written. Changing it (e.g. treating "no trades in the bar" as a skipped, uncounted tick when the broker otherwise answers normally) is an owner decision for a follow-up.

**No publication to master.**

---

## Round 3 — Verdict

**REJECTED — one correction required (B5).** B4 is closed.

Reviewed: `5b1a300` (`agent/review/mvp-6.13`, pushed, in sync with origin), base `master @ eb08fbf`.
Report: `.agent/REPORT-MVP-6.13-REV2.md` (`agent/control @ db2d8ac`). Reviewer: Claude, 2026-10-01.

### Independent re-run

`pytest` **481 passed, 1 skipped**; `ruff` clean.

### B4 — CLOSED

`_latest_closed_bar_before()` accepts any complete candle that started before the deferred boundary. The deferral is bounded: while tradable, once a newer boundary passes without a closed bar, the deferral is concluded with **one** transient failure and normal processing resumes. The round-2 stall probe now runs the cycle.

### Blocking finding

#### B5. At session reopen a deferred bot goes to ERROR within ~3 seconds

In the deferred path every scheduler pass (`_LOOP_STEP_SECONDS = 1`) calls the snapshot provider once the status is tradable. The production provider is `MarketDataService.get_snapshot()`. It requests candles in a **wall-clock window** of `(lookback_bars + 1) × timeframe` before *now* (MVP-6.10) and raises `MarketDataUnavailable("no candle history")` when the window is empty.

Right after a session reopens, that window lies inside the night or weekend gap for intraday bots. M5 with `lookback_bars = 50` gives a window of ≈ 4 h 15 m, against a night gap of 7–10 h. The window is empty, so `MarketDataUnavailable` is raised on each pass and counted as a transient failure **every second**. Three consecutive failures → bot ERROR.

Reproduced on `5b1a300` with the MVP-6.13 harness: M5 bot deferred at the close, session reopens, the snapshot provider raises `MarketDataUnavailable`, passes at +0/+1/+2/+3 s:

```
fail_reasons = ['bot 1: 3 consecutive transient cycle failures (last: no candle history (night gap))']
```

In practice every intraday bot whose last tick fell at the session close would be put into ERROR at the next open.

**Required correction**

1. In the deferred path, while the instrument is tradable, an unavailable/empty snapshot (`MarketDataUnavailable`) or a snapshot with no closed bar before the boundary is **"not confirmed yet"**, not a per-pass failure. Apply only the B4 bound: count **one** transient failure when a newer boundary has passed, conclude the deferral and resume normal processing.
2. A regression test: the reproduction above, where the bot stays RUNNING during the reopen seconds; then, after the next boundary, exactly one transient failure is counted and normal ticks resume.
3. Record in the REPORT the consequence of the MVP-6.10 wall-clock snapshot window. For intraday bots the pre-close bars are usually outside the window at reopen, so the deferred tick is usually concluded by the B4 bound rather than run. `DAY_1` (window ≈ `lookback` days) is unaffected. Fetching the snapshot **by bar count across session gaps** is a separate follow-up (it also affects indicator input right after gaps).
4. REPORT → `.agent/REPORT-MVP-6.13-REV3.md`, pushed, citing the pushed SHA.

### Note on `agent/control @ 5abd376`

The owner's commit `docs: mirror AGENTS.md to control; enable handoff pickup from .ai/context.md` adds a "Контекстная передача (handoff)" section to `AGENTS.md` on `agent/control`. It is a workflow addition by the owner, with no conflict with the review process. Mirror it to `master` with the MVP-6.13 publication.

**No publication to master.**

---

## Round 4 — Verdict

**REJECTED — one correction required (B6).** The B5 code change is correct in isolation, but the reopen scenario still ends in ERROR through two other paths. One of them (B6.1) has existed since round 1 and was missed by the reviewer in earlier rounds.

Reviewed: `b46c5e2` (`agent/review/mvp-6.13`, pushed, in sync with origin), base `master @ eb08fbf`.
Report: `.agent/REPORT-MVP-6.13-REV3.md` (`agent/control @ 9e71175`). Reviewer: Claude, 2026-10-01.

### Independent re-run

`pytest` **482 passed, 1 skipped**; `ruff` clean; alembic head `0005_deal_continuation`.

### Probes on `b46c5e2`

1. **Reopen** (the round-3 scenario, extended to 5 minutes of open session with no data yet):
   `fail_reasons = ['bot 1: 3 consecutive transient cycle failures (last: no candle history (night gap))']` — still ERROR within seconds.
2. **Normal path, single boundary**, session open, `MarketDataUnavailable` until trades appear, 25 s:
   `snapshot_calls = 3, fail_reasons = ['bot 1: 3 consecutive transient cycle failures …']`. **One tick produced three failures.**

### Blocking finding

#### B6. Failure counting is per retry attempt, and the B4 bound fires immediately at reopen

- **B6.1 (since round 1).** In `_confirm_boundary()` the snapshot provider is called without handling. A `MarketDataUnavailable` or broker transport error on a retry attempt goes to `_handle_exception()` and is counted **on every retry slot (5 s)**. S2/S4 say an unconfirmed tick is retried until `max_wait` and then counts **one** transient failure. "3 consecutive transient failures" means three **ticks**, not three retries of one tick. Today one quiet bar (no trades yet, e.g. right after the open or on a thin instrument) puts the bot into ERROR in ~15 s.
- **B6.2 (B4 bound).** `_process_deferred()` concludes the deferral as soon as `newer_boundary > boundary` while tradable. After a night or weekend, many boundaries have **already** passed during the closed session, so the bound fires on the first tradable pass. It counts one failure and hands over to the normal path, where B6.1 adds the rest.
- **B6.3 (reviewer's S6 wording).** In deferred mode the trading status is re-checked on **every 1-s scheduler pass** for the whole night or weekend. With many bots this is a GetTradingStatus storm against the T-Invest rate limits. A rate-limit error is transient and counted per pass, so it can again lead to ERROR.

**Required correction**

1. **At most one transient failure per tick** (`AT_BAR_CLOSE`): a `MarketDataUnavailable`, transport error or unconfirmed bar during the retry window is "not confirmed yet". Count exactly **one** transient failure when `max_wait` expires without a successful cycle. Non-transient errors still go to ERROR immediately. Do the same per minute for `PER_MINUTE` (one failure per minute tick at most).
2. **B4 bound relative to the reopen:** record when the deferred tick first sees the instrument tradable. The bound may conclude the deferral only after a bar boundary has passed **after** that moment, plus the normal `max_wait` (i.e. trading has been open for a full bar and data still has not confirmed).
3. **Deferred status polling** at `bar_close_retry_seconds` (5 s), not every 1-s pass. A failed or rate-limited status during deferral counts at most once per bar boundary.
4. Tests:
   - the two probes above, with the bot staying RUNNING;
   - reopen with no data for the first bar, then data appears → normal cycles run, at most one failure counted;
   - three consecutive **ticks** that each time out → ERROR (the S4 threshold still works);
   - deferred status polling cadence = 5 s.
5. REPORT → `.agent/REPORT-MVP-6.13-REV4.md`, pushed, citing the pushed SHA.

### Still open for the owner (from round 2)

Bars without trades on thin instruments: after B6.1 such a bar costs one transient failure per tick, so three quiet bars in a row → ERROR. Whether a no-trade bar should be an uncounted skip remains an owner decision for a follow-up.

**No publication to master.**
