# Veles-MOEX — REPORT: MVP-6.14 (no-trade bars skipped, not failures)

## Implementation commit

1. `c1558bde659df94a42689a8f658650e7b254acd3` —
   "review: implement MVP-6.14 no-trade bars skipped, not failures (N1-N3)"
   (on `agent/review/mvp-6.14`, **pushed, in sync with origin** — verified with
   `git ls-remote origin agent/review/mvp-6.14 agent/control`:
   `c1558bd…` = `refs/heads/agent/review/mvp-6.14`).

- Task: `.agent/TASK-MVP-6.14-NO-TRADE-BAR.md` (owner-approved contract
  N1–N3, 2026-10-01; opened on `agent/control @ dd400d7`).
- Base: `master @ bb52d368c82ae5e32ff8fa3cae41ba5439191321` (contains the
  accepted MVP-6.13, merge `0279507`); branch base confirmed by
  `git merge-base agent/review/mvp-6.14 origin/master = bb52d36`.
- Diff vs merge-base: 7 files changed, 714 insertions (+), 5 deletions (-) —
  `backend/app/domain/marketdata.py`, `backend/app/services/market_data.py`,
  `backend/app/trading/scheduler.py`, `backend/app/api/bots.py`,
  `backend/app/bots/schemas.py`,
  `backend/tests/test_mvp614_no_trade_bar.py` (new),
  `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` (new §32).
- No changes to `master`; publication requires independent acceptance first.
- Issue #11 stays open until acceptance and publication.

## What changed

### N2. Broker facts (no inference)

- `app/domain/marketdata.py`: `MarketSnapshot` gains
  `last_trade_at: datetime | None = None` — the broker's last-trade timestamp,
  `None` when the broker gave none. It is a **separate** field: the existing
  `timestamp` keeps its MVP-6.10 meaning and fallback
  (`last.timestamp or newest candle timestamp`).
- `NoTradesInWindow(MarketDataUnavailable)` — carries `last_trade_at`
  (broker's last-trade timestamp) and `window_start` (the snapshot window
  start). A subclass, so **every existing `MarketDataUnavailable` handler
  keeps working unchanged** (the scheduler's transient classification, the
  B5/B6.1 "not confirmed yet" deferred path, the strategy/MarketContext
  boundary).
- `app/services/market_data.py` `get_snapshot`: the window start is captured;
  an empty window raises `NoTradesInWindow` (same message as before) with the
  two facts; a successful snapshot carries `last_trade_at = last.timestamp`.
  The C7 trim and the lookback contract are untouched.
- Source (documented in §32): `TInvestAdapter._to_last_price` fills
  `LastPrice.timestamp` from `GetLastPrices.lastPrices[].time` (T-Invest
  official last-trade time, decoded to timezone-aware UTC).

### N1. A proven no-trade bar is a skipped tick (AT_BAR_CLOSE, normal path)

`LiveCycleScheduler._confirm_boundary`:

- On a returned snapshot: `_proven_no_trade_bar(snapshot, boundary, tf)`
  proves the target bar `[bar_start(boundary − 1 s), boundary)` (the B1 range)
  when (a) **no candle** lies in it (a candle present, even incomplete,
  disproves it) **and** (b) either a candle with `start ≥ boundary` exists
  (the broker's data is already past the target bar — the forming next-bar
  candle counts) or `snapshot.last_trade_at` is known and `< bar_start`.
- Proven → `_skip_no_trade_bar`: the tick is concluded as a **skip at once** —
  no strategy cycle, no failure count, the consecutive-failure counter is
  **not reset** (a skip is neither a success nor a failure), no `max_wait`
  wait; the boundary is concluded (`last_done_boundary` set, the bar is never
  retried) and `ticker.last_skip_reason` records a human-readable reason.
- On `NoTradesInWindow` (empty window): `_proven_no_trade_window`
  (`last_trade_at` known and `< window_start`) → same skip; otherwise the
  exception keeps the existing classification (transient → "not confirmed
  yet", B6.1 one transient at `max_wait`; non-transient → immediate ERROR).
- Unproven cases (no newer candle, last trade unknown or inside/after the
  bar) → MVP-6.13 behaviour unchanged: retry until `max_wait`, then exactly
  one transient (B6.1). A lagging data feed is still detected.

### N3. Where it applies

- `AT_BAR_CLOSE`, normal path: N1 (above).
- `AT_BAR_CLOSE`, deferred path (S6): **unchanged by design** — a no-trade bar
  or `NoTradesInWindow` while deferred stays "not confirmed yet"; the
  S6/B4/B5/B6 rules decide (verified by a dedicated regression test). No skip
  is ever recorded on the deferred path.
- `PER_MINUTE`: a `NoTradesInWindow` whose `last_trade_at < window_start` is a
  skip — not counted, no failure reset; the forming bar without any candle is
  not a failure. An unproven one is re-raised and counted as before (S4
  classification, 3 consecutive minutes → ERROR).
- Nothing else changes: S1–S6, the B1–B6 rules, the failure threshold, the
  Deal / Risk / strategy semantics.

### Observability

- `_BotTicker.last_skip_reason` (per bot, in memory; reset with the rest of
  the ticker state on a bot state change, B3), `LiveCycleScheduler.
  last_skip_reason_for(bot_id)`, `BotResponse.last_skip_reason` and
  `GET /api/bots/{id}` (read-only; `None` when the scheduler has not recorded
  one or the live service is absent). Distinct from `last_error` — a skip is
  not an error.

## Tests

`backend/tests/test_mvp614_no_trade_bar.py` (13 tests, fake clock/broker/
snapshot harness shared with the MVP-6.13 scheduler tests):

- skip with a newer candle (incl. the forming **incomplete** next-bar candle;
  0 failures, no cycle, `last_skip_reason` set, boundary concluded);
- skip with a last trade before the bar start (no newer candle);
- unproven no-candle (last trade unknown, no newer candle) → one transient at
  `max_wait`, no skip;
- lagging feed (last trade inside the bar, no newer candle) → not proven, one
  transient at `max_wait`;
- **10 consecutive proven skips** after 2 failures: the bot stays RUNNING and
  the counter neither increments nor resets (peeked `failures == 2`), then one
  more unproven bar → 3rd failure → ERROR;
- proven-quiet empty window (`NoTradesInWindow`) skipped at `AT_BAR_CLOSE` and
  `PER_MINUTE` (at once, no `max_wait` wait);
- unproven empty window keeps the `MarketDataUnavailable` behaviour
  (`AT_BAR_CLOSE`: one transient at `max_wait`; `PER_MINUTE`: 3 transients →
  ERROR);
- deferred (S6) path: `NoTradesInWindow` (even proven) is "not confirmed yet" —
  no count, no skip; the B4 cycle runs once when the provider recovers;
- `get_snapshot`: empty window + usable last price → `NoTradesInWindow` (a
  subclass of `MarketDataUnavailable`) carrying `last_trade_at` / `window_start`;
  `last_trade_at` filled from `LastPrice.timestamp`; `None` keeps the existing
  `timestamp` fallback (newest candle).

## Validation

- `pytest` (backend, full suite): **499 passed, 1 skipped** (was 486 + 1 in
  MVP-6.13 round 5; +13 new tests; the single skip is the opt-in live
  sandbox integration test).
- `pytest tests/test_mvp614_no_trade_bar.py -q`: **13 passed**;
  `tests/test_mvp613_scheduler.py -q`: **36 passed** (no MVP-6.13 test changed
  or rewritten — S6/B4/B5/B6 semantics preserved).
- `ruff check app tests scripts`: **All checks passed!**
- `alembic heads`: single head `0005_deal_continuation` (no new migration).
- `npm run build` (frontend): **built successfully** (no frontend changes;
  built in 10.55 s).

## Known limitations (documented, not changed)

- The empty-window proof depends on the broker's last-trade time
  (`GetLastPrices.time`); T-Invest returns it for instruments with trades —
  for a never-traded instrument the field may be absent (`None`), and then an
  empty window is **not** proven and is counted as before (per contract).
- The same wall-clock snapshot window as MVP-6.13/B5 applies: right after a
  session reopen the window may lie inside the gap; with a proven-quiet
  window the tick now **skips** instead of counting (the intended NV-6.14
  effect), otherwise the B6.2 deferred bound decides. Fetching the snapshot by
  bar count across session gaps remains a separate follow-up (unchanged).
- `last_skip_reason` is per-bot in-memory state (like `last_error`): lost on
  restart; reset on a bot state change (B3).
- `PER_MINUTE`: only the `NoTradesInWindow` empty-window case is skipped; a
  formed snapshot whose currently forming minute has no candle still runs the
  cycle as before (S2 as written; the contract (N3) specifies only the
  `NoTradesInWindow` case).
- The N1 "newer candle" proof counts any candle with `start ≥ boundary`
  (including a forming/incomplete one), per the contract wording; it relies on
  T-Invest never emitting a candle without a trade (the documented "no empty
  candles" fact behind this MVP).
- WEEK_1/MONTH_1 bar-start assumption and the other MVP-6.13 limitations are
  unchanged (not re-verified here).

## Documentation & specification gaps

- `docs/architecture/TASK-09-LIVE-TRADING-MVP-6.md` §32 «No-trade bars are
  skipped, not failures — MVP-6.14» records N1/N2/N3, the source of
  `last_trade_at` (T-Invest `GetLastPrices.lastPrices[].time`) and the
  validation commands. No new project-level semantic contract was invented:
  the proof rules are exactly N1/N2; unproven cases keep the documented
  MVP-6.13 behaviour.
- Out of scope (unchanged): snapshot by bar count across session gaps;
  `HOUR_4`/`WEEK_1`/`MONTH_1` candle start-stamp rule; exit modes; recovery
  TP churn; `FILLED → UNKNOWN` cancel error.

## Constraints honoured

- Broker neutrality: no T-Invest types outside the adapter; `NoTradesInWindow`
  and `last_trade_at` are broker-neutral domain facts.
- `Decimal` / UTC semantics, the C7 snapshot trim and the lookback contract
  unchanged; S1–S6 and B1–B6 unchanged; Deal / Risk / strategy semantics
  unchanged (the skip changes only *whether a quiet tick is counted*).
- Plain push only (no `--force`, no rebase); REPORT committed and pushed to
  `agent/control` (fast-forwarded to `origin/agent/control` first); no
  `master` changes; no self-declared acceptance.

## Review request

Ready for the round-1 decision on `agent/review/mvp-6.14`
(`c1558bde659df94a42689a8f658650e7b254acd3` against `master @ bb52d36`). No
merge into `master` has been performed; publication requires acceptance first.
Issue #11 stays open.
