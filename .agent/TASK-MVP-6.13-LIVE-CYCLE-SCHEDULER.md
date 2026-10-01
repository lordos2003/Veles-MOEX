# TASK-MVP-6.13 — Live Cycle Scheduler

## Status

**IN REVIEW — round 3 REJECTED (B5); correction round 3 assigned to Кодер**

Control branch: `agent/control`
Implementation branch: `agent/review/mvp-6.13` (create from current `master` @ `eb08fbf`)
Base: `master` @ `eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e` (contains accepted MVP-6.12, merge `566d792`)
Date: 2026-09-30

## Why this MVP

After MVP-6.12 a bot can conduct a whole deal, but nothing runs its strategy. `BotRuntime.execute_strategy()` (`backend/app/trading/bot_lifecycle.py`) is only called explicitly. The application lifespan (`backend/app/main.py`) starts the recovery and the OrderStateStream, but no strategy cycle. A RUNNING bot therefore never enters a deal by itself.

MVP-6.13 adds the scheduler that runs each RUNNING bot's strategy cycle at the moments defined by the Veles calculation method of that bot.

## Veles sources (documented behaviour)

Project reference `Veles Help Center — engineering reference.md` → "Filter engine" (source: Veles Help Center, filters/general):

1. **At bar close** — calculate on a closed candle; a condition met at close leads to the action on the next candle.
2. **Once per minute** — evaluate inside the candle every minute (Veles: mainly for channel / price-change indicators).

The method is already modelled as `EntryConfig.method: CalculationMethod` (`AT_BAR_CLOSE` / `PER_MINUTE`, `backend/app/strategies/filters.py`). `FilterEvaluator._current_index()` already skips a non-complete last bar for `AT_BAR_CLOSE`. The per-bot timeframe is `StrategyConfig.timeframe` (MVP-6.10).

## Approved contracts (project owner, 2026-09-30)

Do not generalise or extend them. Anything not covered → stop at the boundary, document it in the REPORT, ask.

### S1. Scheduler and ownership

- A broker-neutral `LiveCycleScheduler` (under `app/trading/`) runs **one strategy cycle per tick per RUNNING bot** by calling the existing `BotRuntime.execute_strategy()` (no new strategy path).
- It is started by the application lifespan **only after a SAFE startup recovery**, next to the stream task. It is stopped on shutdown, and it does not tick while the live service is not SAFE (e.g. after a blocked reconnect recovery).
- Bots are scheduled independently: one bot's slow or failing cycle never delays or fails another bot.
- **At most one cycle per bot at a time.** If a cycle is still running when the next tick is due, that tick is skipped. There is no catch-up of missed ticks.
- Only RUNNING bots are ticked. STOP_REQUESTED, STOPPED, ERROR and EMERGENCY_STOP bots are not; a state change stops the ticks from the next tick on.

### S2. Tick timing by calculation method

- **`AT_BAR_CLOSE`**: one tick per bar of the bot's timeframe, at the bar boundary (UTC boundaries of the T-Invest candle intervals) **+ 5 s**. Before the cycle is evaluated, the just-closed bar must be present in the snapshot with `is_complete is True` (read from the raw `MarketSnapshot` candles; `None` counts as **not confirmed**). If it is not confirmed yet, retry every **5 s**, but no later than **60 s** after the boundary. After that the tick is skipped and counts as a transient failure (S4).
- **`PER_MINUTE`**: one tick at every minute boundary (UTC). The forming bar is used as-is; `FilterEvaluator` already handles `PER_MINUTE`.
- The four values (5 s delay, 5 s retry, 60 s max wait, and the failure threshold in S4) are application settings (`scheduler_bar_close_delay_seconds`, `scheduler_bar_close_retry_seconds`, `scheduler_bar_close_max_wait_seconds`, `scheduler_max_consecutive_failures`), with the owner-approved values above as defaults. They are timing and ops parameters, not financial ones.

### S3. Trading-session gate

- Before each tick the scheduler asks the broker whether the instrument is tradable **now**. Add a broker-neutral `BrokerAdapter.get_trading_status(figi)`, implemented in `TInvestAdapter` via the official T-Invest `MarketDataService/GetTradingStatus` (mapping stays inside the adapter). If the instrument is not tradable (session closed, clearing, halt, API trading not available), the tick is **skipped**. This is not a failure and is not counted in S4.
- If the status is unknown or the request fails, the tick is skipped and **counts** as a transient failure (S4).
- Do **not** hard-code a MOEX session schedule.

### S4. Failure policy

- **Transient** failures: `MarketDataUnavailable`, broker network or timeout errors, closed-bar confirmation not received within the max wait (S2), unknown trading status (S3). The tick is skipped. After **3 consecutive** transient failures the bot goes to **ERROR** through the existing `BotRuntime.fail()`, persisted via `BotRepository`, with the reason observable in the API.
- **Non-transient** failures go to **ERROR immediately**: configuration and contract errors (`TimeframeNotConfigured`, `LookbackNotConfigured`, `SizingNotConfigured`, `SizingError` family, `DealConfigUnsupported`), Deal errors (already surfaced by MVP-6.12 B2; do not double-handle them), `RiskRejected`, `BotStateError` and any unexpected exception.
- A successful cycle resets the consecutive-failure counter. The counter is per bot and in memory; it restarts at 0 after a process restart.
- The reason field: reuse `deal_error` if it fits, or add a generic read-only `last_error` to `GET /api/bots/{id}`. Document the choice.

### S5. Correctness guards (no new trading semantics)

- The scheduler only decides **when** a cycle runs. It must not change entry, grid, TP, Deal, Risk or position semantics. The MVP-6.11/6.12 gates (UNKNOWN / FLAT / OPEN, active orders, Deal ownership) stay authoritative.
- Clock and sleeping are injectable (e.g. a `Clock` protocol). Tests must not use real sleeps.

## Known gap to record (do not change in 6.13)

`market_context.market_snapshot_to_context()` maps `candle.is_complete is None` to `True`. S2 therefore confirms the closed bar from the raw snapshot and does not rely on that mapping. Record this in the REPORT; changing the mapping is a separate decision.

## Scope

1. `LiveCycleScheduler` + settings + lifespan wiring (S1, S2, S5).
2. `BrokerAdapter.get_trading_status()` + T-Invest implementation and mapping (S3). Update the fakes in the existing tests only where the abstract interface requires it.
3. Failure policy + bot ERROR + API reason (S4).
4. Docs: `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md §31 MVP-6.13`.

## Tests (focused, `backend/tests/test_mvp613_scheduler.py`, fake clock)

1. `AT_BAR_CLOSE` M5: ticks at `boundary + 5 s` only; no tick inside the bar.
2. Closed bar not yet `is_complete` → retries every 5 s; confirmed at +15 s → exactly one cycle; never confirmed by +60 s → tick skipped and counted.
3. `is_complete is None` → not confirmed.
4. `PER_MINUTE`: one tick per minute boundary.
5. Trading status not tradable → no cycle, not counted; status unknown or failing → counted.
6. 3 consecutive transient failures → bot ERROR (runtime + DB + API reason); 2 failures then a success → counter reset, bot still RUNNING.
7. Non-transient error (e.g. `LookbackNotConfigured`) → ERROR on the first occurrence.
8. Overlap: a cycle still running at the next tick → tick skipped; no parallel cycles for one bot.
9. Bot isolation: a failing or slow bot does not delay or fail another bot's tick.
10. Only RUNNING bots ticked; STOP / ERROR / EMERGENCY_STOP → no further ticks.
11. Scheduler not started when the startup recovery is not SAFE; no ticks while the service is not SAFE.
12. `TInvestAdapter.get_trading_status` mapping (normal trading → tradable; break / closing / not available → not tradable).
13. Full suite green; MVP-6.9 … 6.12 suites unchanged.

## Explicit constraints (AGENTS.md)

- Broker neutrality: T-Invest types only inside the adapter.
- No hard-coded MOEX schedule, no invented financial defaults. The timing defaults above are owner-approved ops parameters.
- `Decimal` / UTC unchanged; the strategy, Deal and Risk semantics are unchanged.
- Out of scope: multi-timeframe filter series, the Veles "trading by schedule" filter, Backtest, the new exit modes.

## Validation & REPORT

Full `pytest`, `ruff check app tests scripts`, `alembic heads` (unchanged unless a migration is justified), `npm run build`, actual diff review against the merge-base.

REPORT → `agent/control:.agent/REPORT-MVP-6.13.md` with: task, branch, **pushed** commit SHA ("pushed, in sync with origin"), exact changes, validation results, known limitations, documentation/specification gaps, AGENTS.md compliance.

Do not publish to `master`. Do not self-declare acceptance.

## Correction round 1 (review 2026-09-30)

Review: `.agent/REVIEW-MVP-6.13.md` — **REJECTED**:
- **B1**: bars that close outside the session (4h / day / week / month) never produce a cycle. This is a gap in S3; fixed by S6 below. The closed-bar confirmation must use a timestamp range, not exact equality.
- **B2**: concurrent per-bot passes share one long-lived `AsyncSession`. Reproduced on PostgreSQL + asyncpg: `IllegalStateChangeError` / `InterfaceError`.
- **B3**: the failure counter survives an ERROR and a restart.

Fix exactly as described in the review. REPORT → `.agent/REPORT-MVP-6.13-REV1.md`.

### S6. Deferred bar-close tick (owner decision, 2026-09-30; supersedes the S3 "skip" rule for `AT_BAR_CLOSE`)

- When an `AT_BAR_CLOSE` tick falls while the instrument is **not tradable**, the tick is **deferred**, not dropped. It runs **once**, at the first moment the instrument is tradable again, on the latest closed bar. This is Veles semantics: the condition is met at the bar close, and the action happens on the next candle.
- Only the **latest** pending boundary is kept. Several boundaries that pass while the session is closed produce **one** deferred cycle, not a catch-up.
- Deferral is not a failure and is not counted. While deferred, the S3 status is re-checked at the normal scheduler cadence.
- `PER_MINUTE` keeps the S3 rule: not tradable → skip, not counted.

## Correction round 2 (review 2026-10-01)

Review: `.agent/REVIEW-MVP-6.13.md` → "Round 2" — **REJECTED**, one blocking finding (B4). The deferred tick requires a candle inside the deferred boundary's own range. A bar without trades has no candle, so the bot can stall in `deferred` forever, silently. Per S6 the deferred tick must run on the **latest closed bar**, and the deferral must be bounded. Fix exactly as described in the review. REPORT → `.agent/REPORT-MVP-6.13-REV2.md`.

## Correction round 3 (review 2026-10-01)

Review: `.agent/REVIEW-MVP-6.13.md` → "Round 3" — **REJECTED**, one blocking finding (B5). In the deferred path an empty snapshot right after the session reopens (the wall-clock lookback window is inside the night gap) is counted as a transient failure on every 1-s pass, so the bot goes to ERROR within ~3 s. Treat it as "not confirmed yet" and count only via the B4 bound. Fix exactly as described in the review. REPORT → `.agent/REPORT-MVP-6.13-REV3.md`.

## Publication (mandatory, see `AGENTS.md` §6 and `.agent/CODER-WORKFLOW.md` → "Mandatory push rule")

```
git push origin agent/review/mvp-6.13
git push origin agent/control
git ls-remote origin agent/review/mvp-6.13 agent/control
```

No `--force`, no rebase. If rejected: `git fetch origin`, `git merge origin/<branch>`, push again. Never push `master`.
