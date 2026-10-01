# Veles-MOEX — REPORT: MVP-6.13 REV2 (round-2 correction B4)

## Correction commits

1. `5b1a30084d22964781eede17e4310ad7c16b07cf` — "review: implement MVP-6.13
   round-2 correction (B4)" (correction on `agent/review/mvp-6.13`, **pushed,
   in sync with origin** — verified with
   `git ls-remote origin agent/review/mvp-6.13 agent/control`:
   `5b1a300…` = `refs/heads/agent/review/mvp-6.13`, `9dca9b4…` =
   `refs/heads/agent/control`).

- Round-1 implementation reviewed: `a945b103c7bff7b5be472749fe60ca07ce8d5f6d`.
  Round-2 review: `.agent/REVIEW-MVP-6.13.md` (REJECTED: B4 — the deferred
  tick can stall forever; B2, B3, B1 range confirmation, Observation 1 CLOSED;
  one non-blocking owner observation on the non-deferred S2 no-trade path).
- Base before MVP-6.13: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`
  (contains the accepted MVP-6.12, merge `566d792`); branch base confirmed by
  `git merge-base agent/review/mvp-6.13 origin/master = eb08fbf`.
- Correction diff vs round-1 HEAD: 3 files changed, 157 insertions (+),
  13 deletions (-) — `backend/app/trading/scheduler.py`,
  `backend/tests/test_mvp613_scheduler.py`,
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`.
- No changes to `master`; publication requires independent acceptance first.
- Issue #9 stays open until acceptance and publication.

## What changed (B4)

### B4. Deferred tick runs on the latest closed bar, with a bound

`backend/app/trading/scheduler.py`:

- **Root cause.** Round-1 confirmed the deferred tick only when a complete
  candle existed **inside** `[bar_start(boundary − 1 s), boundary)`. A bar
  without trades has **no candle** on MOEX/T-Invest, so a no-trade last bar
  before a session close left the deferral unconfirmed forever: no failure
  count, no limit, and `_process_at_bar_close()` short-circuits into
  `_process_deferred()` while `ticker.deferred` is set, so normal boundary
  processing never resumed. Reproduced by the reviewer on `a945b10`: M5 bot,
  last candle `[T0−10m, T0−5m)`, session closed at `T0`, status
  `TRADING_AVAILABLE` at +14 h/+15 h/+16 h/+20 h/+48 h →
  `executions=0, fail_reasons=[], snapshot_requests=5`.
- **Fix 1 — confirm the latest closed bar.** `_process_deferred()` now, once
  the instrument is tradable, runs the cycle when the snapshot contains **any**
  candle with `is_complete is True` and `timestamp < deferred boundary`
  (`_latest_closed_bar_before`): a complete candle that started **before** the
  deferred boundary is the "latest closed bar". The deferred bar's own range
  is deliberately **not** required. The cycle runs exactly once on that data,
  then `_conclude_boundary` clears the deferral and failure counters reset on
  success (unchanged).
- **Fix 2 — bound.** While the instrument is tradable, if no such candle
  exists yet and a **newer** bar boundary has already passed (the boundary
  recomputed from `now − bar_close_delay` starts after the deferred boundary),
  the deferral is concluded with **one transient failure** (S4-counted,
  same per-bot counter as the non-deferred path) and normal boundary
  processing resumes on the next pass. A deferred bot is never stuck while
  trading is open; the S2 max-wait still does not apply to the deferred path
  (it was deferred, not lost), but the bound replaces the stall with a bounded
  single transient.
- **Order.** Fix 1 takes priority over Fix 2: when a latest-closed-bar candle
  exists the cycle runs and no transient is counted; only an unconfirmed
  deferral with a passed newer boundary counts the transient.
- **Non-deferred S2 path unchanged** — an unconfirmed non-deferred bar still
  retries up to `bar_close_max_wait_seconds`, then counts one transient.
  (The owner observation about three consecutive no-trade bars → ERROR on the
  S2 path is a follow-up decision, not implemented here.)
- `backend/tests/test_mvp613_scheduler.py` — two new tests:
  - `test_s6_deferred_tick_runs_on_latest_closed_bar_when_deferred_bar_has_no_candle`:
    the reviewer's reproduction. M5 bot, last candle `[T0−10m, T0−5m)` (no
    candle inside the deferred range), boundary `T0`, `TRADING_UNAVAILABLE`
    at `T0+5 s` → deferred; `TRADING_AVAILABLE` at `+14 h` → **exactly one**
    execution, one snapshot request, no failures, `last_error_for(1) is None`.
    (Fails on `a945b10` with `executions=0`, passes after the fix.)
  - `test_s6_deferred_tick_is_bounded_when_no_candle_and_newer_boundary_passes`:
    no candles in the snapshot at all, `TRADING_AVAILABLE` at `+15 min`
    (the `T0+15 min` boundary passed) → the bound concludes the deferral with
    **exactly one** transient; two more unknown-status passes then reach the
    S4 threshold (3 consecutive) → the bot errors. Without the bound only two
    transients would be counted and the bot would not error, so the test
    proves the single transient without touching internals.
- Round-1 S6/B1 tests stay green (all carry a complete candle starting before
  the deferred boundary, which Fix 1 accepts).
- Documented in `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §31: the S6
  subsection now states the round-2 B4 semantics, plus a new subsection
  «### B4. Deferred tick runs on the latest closed bar, with a bound
  (round-2 correction)» (motivation, both fixes, order, S2 unchanged).

## Tests / validation

- `pytest` (backend, full suite): **481 passed, 1 skipped** (was 479 + 1 in
  round-1 REV1; the single skip is the opt-in live sandbox integration test).
- `pytest tests/test_mvp613_scheduler.py -q`: **31 passed** (was 29 in REV1;
  +2 B4 tests).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes;
  built in 14.96 s).

## Known limitations (documented, not changed)

- **Owner observation (B4 review, non-blocking)** — the non-deferred S2 path
  still counts a transient per unconfirmed bar after `bar_close_max_wait_seconds`.
  Three consecutive no-trade bars → bot ERROR (S2 contract as written). The
  reviewer deferred the fix ("no trades in the bar" as a skipped, uncounted
  tick) to an owner decision for a follow-up. Not implemented in REV2.
- **Carried from REV1**: `market_snapshot_to_context()` maps
  `is_complete is None → True`; S2 confirms from the raw `MarketSnapshot`.
- **Epoch/calendar start assumption** (REV1, unchanged): MIN_1..DAY_1
  boundaries are fixed UTC intervals from the epoch, WEEK_1 Monday 00:00 UTC,
  MONTH_1 the 1st 00:00 UTC — not confirmed by T-Invest docs; the B1 range
  rule and the B4 latest-closed-bar rule keep confirmation robust regardless.
- S6 scope: deferral applies to `AT_BAR_CLOSE` only; `PER_MINUTE` keeps the S3
  skip-without-count on a not-tradable minute.
- Deferred state is per-bot in memory and resets with B3 (a restart after
  ERROR clears the deferral; `last_done_boundary` is kept). A deferred
  boundary does not leak across a process restart.

## Documentation & specification gaps

- S6 + B4 semantics are recorded in `.agent/TASK-MVP-6.13-LIVE-CYCLE-SCHEDULER.md`
  (owner contract, round-1 correction) and in `docs/architecture/TASK-09` §31
  («### S6. AT_BAR_CLOSE deferral» + «### B4. … (round-2 correction)»).
- The only unverified spec point remains the T-Invest candle start-stamp rule
  for HOUR_4/WEEK_1/MONTH_1 (REV1, explicitly stated, not silently assumed).
- Out of scope (unchanged): multi-timeframe filter series, Veles "trading by
  schedule" filter, Backtest changes, new exit modes, the S2 no-trade
  follow-up.

## Constraints honoured

- Broker neutrality: `app/trading` imports only `app.brokers.base` /
  `app.trading.deal`; T-Invest types stay inside the adapter.
- No hard-coded MOEX schedule; no invented financial defaults; no new Veles
  semantics (B4 is the reviewer's required correction, S6 stays the
  owner-approved contract).
- `Decimal` / UTC semantics, strategy / Deal / Risk semantics unchanged;
  MVP-6.11/6.12 gates remain authoritative; the B2 fix preserves the MVP-6.11
  B2 fresh-deposit-read guarantee.
- Correction pushed to `agent/review/mvp-6.13` (plain push, no force/rebase),
  REPORT committed and pushed to `agent/control` (fast-forwarded to the
  reviewer's `9dca9b4` first); no `master` changes; no self-declared
  acceptance.

## Review request

Ready for the round-3 decision on `agent/review/mvp-6.13`
(`5b1a30084d22964781eede17e4310ad7c16b07cf` against round-1 head
`a945b103c7bff7b5be472749fe60ca07ce8d5f6d`, ultimately against `master @
eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`). No merge into `master` has been
performed; publication requires acceptance first. Issue #9 stays open.
