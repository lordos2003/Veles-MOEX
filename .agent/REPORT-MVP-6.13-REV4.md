# Veles-MOEX — REPORT: MVP-6.13 REV4 (round-4 correction B6)

## Correction commits

1. `db09a392048bd1a001d3b2db3cac6632a06d1963` —
   "review: implement MVP-6.13 round-4 correction (B6)"
   (correction on `agent/review/mvp-6.13`, **pushed, in sync with origin** —
   verified with `git ls-remote origin agent/review/mvp-6.13 agent/control`:
   `db09a39…` = `refs/heads/agent/review/mvp-6.13`,
   `3ff4284…` = `refs/heads/agent/control` (the round-4 verdict; this REPORT
   and the PROJECT_STATE update are committed on top of it)).

- Round-3 implementation reviewed: `b46c5e2b88f4712caa63573a9c75d9976a5530e0`.
  Round-4 review: `.agent/REVIEW-MVP-6.13.md` (REJECTED: B6 — failures counted
  per retry slot; the B4 bound fires at the reopen; 1-s deferred status
  polling storm).
- Base before MVP-6.13: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`
  (contains the accepted MVP-6.12, merge `566d792`); branch base confirmed by
  `git merge-base agent/review/mvp-6.13 origin/master = eb08fbf`.
- Correction diff vs round-3 HEAD: 3 files changed, 393 insertions (+),
  50 deletions (-) — `backend/app/trading/scheduler.py`,
  `backend/tests/test_mvp613_scheduler.py`,
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`.
- No changes to `master`; publication requires independent acceptance first.
- Issue #9 stays open until acceptance and publication. The reviewer's note
  on `agent/control @ 5abd376` (mirror the owner's `AGENTS.md` handoff section
  to `master` with the MVP-6.13 publication) is recorded for the publication
  step; not actioned here.

## What changed (B6)

### B6. One transient failure per tick; deferred poll cadence; bound relative to reopen

`backend/app/trading/scheduler.py`:

- **B6.1 — at most one transient failure per tick** (`_confirm_boundary`).
  Root cause: the snapshot provider was called without handling, so a
  `MarketDataUnavailable` or broker transport error on a **retry attempt** was
  routed to `_handle_exception` and counted on **every 5-s retry slot**. Per
  S2/S4 "3 consecutive transient failures" means three **ticks**, not three
  retries of one tick — so one quiet bar (no trades yet, e.g. right after the
  open or on a thin instrument) put the bot into ERROR in ~15 s. Fix: inside
  the retry window a transient data failure (`MarketDataUnavailable`,
  transport error, or a still-unconfirmed bar) is **"not confirmed yet"** — no
  count; the retry slot re-checks. Exactly **one** transient is counted when
  `max_wait` expires without a successful cycle, then the boundary is
  concluded. A **non-transient** error still fails the bot immediately (S4).
  `PER_MINUTE` was already at most one failure per minute tick (one attempt
  claimed per minute); unchanged.
- **B6.2 — B4 bound relative to the first tradable moment** (`_process_deferred`).
  Root cause: the B4 bound concluded as soon as `_bar_start(now - delay) >
  boundary` while tradable; after a night/weekend gap many boundaries had
  already passed, so the bound fired on the **first tradable pass**, counted a
  failure and handed off to the normal path where B6.1 added the rest (the
  reviewer's copy of the reopen probe still ended in ERROR within seconds).
  Fix: the deferred tick records **`deferred_first_tradable`** — the first
  moment it observes the instrument tradable — and the bound may conclude the
  deferral only after **a full bar of trading has passed since that moment plus
  the normal `max_wait`** (`_bar_start(first_tradable) + timeframe +
  max_wait`). The reopen so gets a full bar (+ max_wait) of data time; the bot
  is still never stuck while trading is open (three consecutive concluded
  ticks still trip S4).
- **B6.3 — deferred status polling cadence and per-bar failure cap**
  (`_process_deferred`, `_status_verdict`). Root cause: the deferred path
  re-checked `GetTradingStatus` on every **1-s** pass for the whole closed
  session — a rate-limit storm; and a rate-limit error was counted as a
  transient per pass, so an ERROR was possible during the night/weekend. Fix:
  the status is polled at **`bar_close_retry_seconds` (5 s)** — `deferred_status_check_at`
  gates every re-check, with the same cadence applying to the snapshot fetch —
  and a failed/rate-limited status counts **at most once per bar boundary**
  (`deferred_failed_bar`, via the new `count_on_fail` switch on
  `_status_verdict`; the verdict itself stays side-effect free by default for
  the normal paths, so S3 counting there is unchanged). Three consecutive bar
  boundaries of a failing status still trip the S4 threshold.
- The three new `_BotTicker` fields (`deferred_status_check_at`,
  `deferred_failed_bar`, `deferred_first_tradable`) are per-deferral: cleared
  in `_conclude_boundary` and in `_reset_ticker_state` (B3). `_TIMEFRAME_SECONDS`
  now also carries WEEK_1 / MONTH_1 nominal durations (7 / 30 days) — used only
  by the B6.2 bound timing; the calendar-aligned `_bar_start` assumption is
  unchanged and documented.

### Tests

`backend/tests/test_mvp613_scheduler.py` — 4 new tests, 2 updated:

- `test_b6_reopen_without_data_stays_running_through_full_bar_then_recovers`
  (reviewer's probe 1): deferred M5 bot; session reopens with the snapshot
  provider raising `MarketDataUnavailable` on every pass; **300 s of open
  session with one pass per second → no failures, bot RUNNING**, exactly 60
  snapshot polls (5-s cadence, B6.3); then data appears, the bound concludes
  the deferral with one transient and normal processing runs the cycle exactly
  once. (Fails on `b46c5e2` with ERROR within seconds.)
- `test_b6_quiet_bar_retries_do_not_count_per_retry_slot` (reviewer's probe 2):
  one boundary, session open, provider raises on every retry slot; retries at
  +5..+30 s → no failures, 6 requests (not failures); at `max_wait` (+65 s) →
  exactly one transient, bot RUNNING; next bar confirms and the cycle runs.
  (Fails on `b46c5e2`: snapshot_calls 3 → 3 failures → ERROR.)
- `test_b6_three_consecutive_quiet_ticks_still_error`: the S4 threshold still
  works — three consecutive ticks each timing out count one transient each →
  ERROR at the third (before B6.1 three retry slots of one tick sufficed).
- `test_b6_deferred_status_polled_at_cadence_and_failure_capped_per_bar`:
  deferred with the broker raising `RuntimeError("rate limited")` on every
  poll; a full bar (60 polls) → **one** failure, bot RUNNING (before B6.3:
  ERROR in ~15 s); the next two bar boundaries add one failure each → ERROR at
  the third, proving "at most once per bar boundary". `len(broker.calls) == 61`
  proves the 5-s cadence (1 deferral + 60 polls, not 300).
- `test_s6_deferred_tick_is_bounded_when_no_candle_and_newer_boundary_passes`
  (updated to B6.2): first tradable at +15 min → deferral persists (no count);
  bound at +21 min (full bar + max_wait) → exactly one transient; normal
  processing resumes; two more unknown-status ticks → ERROR at the third.
- `test_b5_deferred_reopen_empty_snapshot_is_not_counted_until_bound` (updated):
  same B5 reproduction, but now the reopen poll happens at the 5-s cadence
  (requests == 1 over +6..+9 s) and the bound fires at +6 min (full bar +
  max_wait after the first tradable moment at +6 s).
- All round-1/2/3 tests stay green: **36/36 in the scheduler file**.

## Tests / validation

- `pytest` (backend, full suite): **486 passed, 1 skipped** (was 482 + 1 in
  round-3 REV3; the single skip is the opt-in live sandbox integration test).
- `pytest tests/test_mvp613_scheduler.py -q`: **36 passed** (was 32 in REV3;
  +4 B6 tests).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes;
  built in 5.54 s).

## Known limitations (documented, not changed)

- **Owner observation (B4 review, non-blocking), now resolved in part by
  B6.1**: the non-deferred S2 path still counts **one transient per
  unconfirmed bar** after `bar_close_max_wait_seconds` — three consecutive
  no-trade bars → bot ERROR. That is exactly the per-tick S4 semantics the
  reviewer required for B6 (three ticks, not three retries); the follow-up
  question for the owner (bars without trades on thin instruments) remains
  **open on purpose — NOT implemented**.
- **Consequence of the MVP-6.10 wall-clock snapshot window (documented in
  §31)**: for intraday bots the pre-close bars are usually **outside**
  `(lookback_bars + 1) × timeframe` before "now" at reopen, so in practice a
  deferred intraday tick is **concluded by the B4 bound** (one transient) after
  the full bar + max_wait, rather than run on the latest closed bar. `DAY_1`
  (window ≈ `lookback_bars` days) is unaffected. Fetching the snapshot **by
  bar count across session gaps** is a separate follow-up — it also affects
  indicator input right after gaps (out of scope of MVP-6.13).
- **Carried from REV1–REV3**: `market_snapshot_to_context()` maps
  `is_complete is None → True`; S2 confirms from the raw `MarketSnapshot`.
- **Epoch/calendar start assumption** (REV1, unchanged): MIN_1..DAY_1
  boundaries are fixed UTC intervals from the epoch, WEEK_1 Monday 00:00 UTC,
  MONTH_1 the 1st 00:00 UTC — not confirmed by T-Invest docs; the B1 range
  rule, the B4 latest-closed-bar rule and the B6.2 bound-vs-boundary formula
  keep confirmation robust regardless.
- S6 scope: deferral applies to `AT_BAR_CLOSE` only; `PER_MINUTE` keeps the S3
  skip-without-count on a not-tradable minute.
- Deferred state is per-bot in memory and resets with B3 (a restart after
  ERROR clears the deferral; `last_done_boundary` is kept). A deferred
  boundary does not leak across a process restart.

## Documentation & specification gaps

- B6 semantics are recorded in
  `docs/architecture/TASK-09` §31 («### B6. One transient failure per tick;
  deferred poll cadence and bound-relative-to-reopen (round-4 correction)»),
  which also amends the B4/B5 wording (the bound is now relative to the first
  tradable moment; the B5 "one transient" applies only via that bound).
- The only unverified spec point remains the T-Invest candle start-stamp rule
  for HOUR_4/WEEK_1/MONTH_1 (REV1, explicitly stated, not silently assumed).
- Out of scope (unchanged): multi-timeframe filter series, Veles "trading by
  schedule" filter, Backtest changes, new exit modes, the S2 no-trade
  follow-up, snapshot-by-bar-count across gaps.

## Constraints honoured

- Broker neutrality: `app/trading` imports only `app.brokers.base` /
  `app.trading.deal`; T-Invest types stay inside the adapter;
  `MarketDataUnavailable` is already a domain-level (`app.domain.marketdata`)
  type imported by the scheduler today.
- No hard-coded MOEX schedule; no invented financial defaults; no new Veles
  semantics (B6 is the reviewer's required correction; S6 stays the
  owner-approved contract). The fixes narrow failure counting and polling
  cadence — they do not change any trading decision. S3/S4 thresholds are
  preserved (three **ticks** → ERROR).
- `Decimal` / UTC semantics, strategy / Deal / Risk semantics unchanged;
  MVP-6.11/6.12 gates remain authoritative; the B2 fix preserves the MVP-6.11
  B2 fresh-deposit-read guarantee.
- Correction pushed to `agent/review/mvp-6.13` (plain push, no force/rebase),
  REPORT committed and pushed to `agent/control` (fast-forwarded to the
  reviewer's `3ff4284` first); no `master` changes; no self-declared
  acceptance.

## Review request

Ready for the round-5 decision on `agent/review/mvp-6.13`
(`db09a392048bd1a001d3b2db3cac6632a06d1963` against round-3 head
`b46c5e2b88f4712caa63573a9c75d9976a5530e0`, ultimately against `master @
eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`). No merge into `master` has been
performed; publication requires acceptance first. Issue #9 stays open.
