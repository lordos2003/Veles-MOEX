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
