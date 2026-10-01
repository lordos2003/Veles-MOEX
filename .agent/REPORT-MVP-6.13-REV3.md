# Veles-MOEX — REPORT: MVP-6.13 REV3 (round-3 correction B5)

## Correction commits

1. `b46c5e2b88f4712caa63573a9c75d9976a5530e0` —
   "review: implement MVP-6.13 round-3 correction (B5)"
   (correction on `agent/review/mvp-6.13`, **pushed, in sync with origin** —
   verified with `git ls-remote origin agent/review/mvp-6.13 agent/control`:
   `b46c5e2…` = `refs/heads/agent/review/mvp-6.13`, `593888f…` =
   `refs/heads/agent/control`).

- Round-2 implementation reviewed: `5b1a30084d22964781eede17e4310ad7c16b07cf`.
  Round-3 review: `.agent/REVIEW-MVP-6.13.md` (REJECTED: B5 — a deferred bot
  goes to ERROR within ~3 s at session reopen; B4 CLOSED).
- Base before MVP-6.13: `master @ eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`
  (contains the accepted MVP-6.12, merge `566d792`); branch base confirmed by
  `git merge-base agent/review/mvp-6.13 origin/master = eb08fbf`.
- Correction diff vs round-2 HEAD: 3 files changed, 108 insertions (+),
  2 deletions (-) — `backend/app/trading/scheduler.py`,
  `backend/tests/test_mvp613_scheduler.py`,
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md`.
- No changes to `master`; publication requires independent acceptance first.
- Issue #9 stays open until acceptance and publication. The reviewer's note
  on `agent/control @ 5abd376` (mirror the owner's `AGENTS.md` handoff section
  to `master` with the MVP-6.13 publication) is recorded for the publication
  step; not actioned here.

## What changed (B5)

### B5. Empty snapshot in the deferred path is "not confirmed yet"

`backend/app/trading/scheduler.py` (`_process_deferred`):

- **Root cause.** Once the instrument is tradable, the deferred path fetched
  the snapshot on **every 1-s scheduler pass** and any provider failure
  propagated to `_handle_exception`, where `MarketDataUnavailable` is a
  transient (S4) → counted per pass. The production provider
  (`MarketDataService.get_snapshot`, MVP-6.10/C7) requests candles in a
  **wall-clock window** of `(lookback_bars + 1) × timeframe` before "now" and
  raises `MarketDataUnavailable("no candle history")` when the window is
  empty. Right after a session reopens that window lies inside the
  night/weekend gap (M5 with `lookback_bars = 50` → ≈ 4 h 15 m against a
  7–10 h night gap), so a deferred intraday bot collected three consecutive
  transients within ~3 s and went to ERROR at the next open. Reproduced by
  the reviewer on `5b1a300`: passes at +0/+1/+2/+3 s →
  `fail_reasons = ['bot 1: 3 consecutive transient cycle failures (last: no
  candle history (night gap))']`.
- **Fix.** In `_process_deferred`, the snapshot fetch is wrapped: a
  `MarketDataUnavailable` exception is treated as **"not confirmed yet"** —
  `snapshot = None`, no failure counted, the deferral persists. The
  not-confirmed cases (unavailable/empty snapshot, or a snapshot with no
  closed bar before the deferred boundary) are exactly the same: only the
  **B4 bound** may conclude the deferral with *one* transient failure when a
  newer bar boundary has passed, after which normal boundary processing
  resumes. The rest of the deferred path is unchanged (Fix 1 of B4 still
  runs the cycle on the latest closed bar when one exists; while not tradable
  the deferral still persists; a failed/unknown trading status is still
  counted per S3).
- The **non-deferred S2 path is unchanged**: there an unconfirmed/empty
  snapshot still counts a transient via the normal S4 path (the S2 contract
  as written; the round-2 owner observation stands).
- `backend/tests/test_mvp613_scheduler.py` — one new test:
  `test_b5_deferred_reopen_empty_snapshot_is_not_counted_until_bound`: the
  reviewer's reproduction. M5 bot, boundary `T0`, `TRADING_UNAVAILABLE` at
  `T0+5 s` → deferred; session reopens, the snapshot provider raises
  `MarketDataUnavailable("no candle history (night gap)")` on every pass →
  four passes at `+6/+7/+8/+9 s` → **no failures, bot stays RUNNING**
  (before B5: ERROR within ~3 s), `last_error_for(1) is None`; then at
  `+5 min` (the next M5 boundary passed) the B4 bound fires → **exactly one**
  transient, bot still RUNNING; then the provider recovers and the next bar
  confirms, the cycle runs and the counter resets on success. (Fails on
  `5b1a300` with `state is ERROR` after the reopen passes.)
- Round-1/round-2 S6/B4 tests stay green (32/32 in the scheduler file).

## Tests / validation

- `pytest` (backend, full suite): **482 passed, 1 skipped** (was 481 + 1 in
  round-2 REV2; the single skip is the opt-in live sandbox integration test).
- `pytest tests/test_mvp613_scheduler.py -q`: **32 passed** (was 31 in REV2;
  +1 B5 test).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes;
  built in 5.59 s).

## Known limitations (documented, not changed)

- **Consequence of the MVP-6.10 wall-clock snapshot window (review B5 item 3,
  documented in §31)**: for intraday bots the pre-close bars are usually
  **outside** `(lookback_bars + 1) × timeframe` before "now" at reopen, so in
  practice a deferred intraday tick is **concluded by the B4 bound** (one
  transient) rather than run on the latest closed bar. `DAY_1`
  (window ≈ `lookback_bars` days) is unaffected. Fetching the snapshot **by
  bar count across session gaps** is a separate follow-up — it also affects
  indicator input right after gaps (out of scope of MVP-6.13).
- **Owner observation (B4 review, non-blocking)** — the non-deferred S2 path
  still counts a transient per unconfirmed bar after `bar_close_max_wait_seconds`.
  Three consecutive no-trade bars → bot ERROR (S2 contract as written). Not
  implemented in REV3.
- **Carried from REV1/REV2**: `market_snapshot_to_context()` maps
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

- B5 semantics are recorded in `.agent/TASK-MVP-6.13-LIVE-CYCLE-SCHEDULER.md`
  (owner contract, correction-round-3 section) and in
  `docs/architecture/TASK-09` §31 («### B5. Empty snapshot in the deferred
  path is "not confirmed yet" (round-3 correction)»), including the
  wall-clock-window consequence and the bar-count-across-gaps follow-up.
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
  semantics (B5 is the reviewer's required correction; S6 stays the
  owner-approved contract). The fix narrows failure counting — it does not
  change any trading decision.
- `Decimal` / UTC semantics, strategy / Deal / Risk semantics unchanged;
  MVP-6.11/6.12 gates remain authoritative; the B2 fix preserves the MVP-6.11
  B2 fresh-deposit-read guarantee.
- Correction pushed to `agent/review/mvp-6.13` (plain push, no force/rebase),
  REPORT committed and pushed to `agent/control` (fast-forwarded to the
  reviewer's `593888f` first); no `master` changes; no self-declared
  acceptance.

## Review request

Ready for the round-4 decision on `agent/review/mvp-6.13`
(`b46c5e2b88f4712caa63573a9c75d9976a5530e0` against round-2 head
`5b1a30084d22964781eede17e4310ad7c16b07cf`, ultimately against `master @
eb08fbff5ddd1e525bb0bcf89884cbf5e0fab30e`). No merge into `master` has been
performed; publication requires acceptance first. Issue #9 stays open.
